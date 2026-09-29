"""Immediate-consistency cascades and the clock-driven transitions.

Every rollup is derived on read (see derive.py); what happens here is the
state-machine work plus the `updated_at`/`version` mutations that PRD 2.4
demands of every recomputation.
"""
import math
from datetime import datetime, timedelta

import calc
import derive
from common import (CLOCK, DB, UTC, add_days, add_hours, iso_ms, touch)

ZERO3 = derive.ZERO3
TERMINAL_LIFECYCLE = ("CLOSED", "TERMINATED", "WITHDRAWN")


def notice_hours(issued_at, target_pick_at):
    seconds = (target_pick_at - issued_at).total_seconds()
    return int(math.floor(seconds / 3600.0))


def set_renewal_window(contract):
    closes = datetime(int(contract["term_end_vintage"]), 11, 1, 0, 0, 0, tzinfo=UTC)
    contract["renewal_window_closes_at"] = closes
    contract["renewal_window_opens_at"] = closes - timedelta(
        days=int(contract["termination_notice_days"]))


def stamp_issuance(call, contract):
    call["issued_at"] = CLOCK.now
    call["notice_hours"] = notice_hours(CLOCK.now, call["target_pick_at"])
    call["ack_deadline_at"] = add_hours(CLOCK.now, contract["pick_call_ack_window_hours"])
    call["acknowledged_at"] = None


def touch_lane(lane_id):
    lane = DB["lanes"].get(lane_id)
    if lane is not None:
        touch(lane)


def cancel_scheduled_appointments(call):
    """Cancel the call's SCHEDULED appointments and recompute the lanes."""
    for appointment in derive.appointments_of_pick_call(call["id"]):
        if appointment["status"] != "SCHEDULED":
            continue
        appointment["status"] = "CANCELLED"
        touch(appointment)
        touch_lane(appointment["lane_id"])


def suspend_calls_on_cap(contract):
    for call in derive.pick_calls_of_contract(contract["id"]):
        if call["status"] not in ("ISSUED", "ACKNOWLEDGED"):
            continue
        was_acknowledged = call["status"] == "ACKNOWLEDGED"
        call["status"] = "SUSPENDED_CAP"
        touch(call)
        if was_acknowledged:
            cancel_scheduled_appointments(call)


def resume_calls_from_cap(contract):
    for call in derive.pick_calls_of_contract(contract["id"]):
        if call["status"] != "SUSPENDED_CAP":
            continue
        call["status"] = "ISSUED"
        stamp_issuance(call, contract)
        touch(call)


def withdraw_calls(contract, statuses):
    for call in derive.pick_calls_of_contract(contract["id"]):
        if call["status"] not in statuses:
            continue
        was_acknowledged = call["status"] == "ACKNOWLEDGED"
        call["status"] = "WITHDRAWN"
        touch(call)
        if was_acknowledged:
            cancel_scheduled_appointments(call)


def cancel_sampling_visits(contract):
    for visit in DB["visits"].values():
        if visit["contract_id"] != contract["id"]:
            continue
        if visit["status"] != "SCHEDULED":
            continue
        visit["status"] = "CANCELLED"
        touch(visit)
        crew = DB["crews"].get(visit["crew_id"])
        if crew is not None:
            touch(crew)


def close_appointment_if_settled(appointment):
    """ARRIVED -> CLOSED once every tag is NET_FINAL and decided."""
    if appointment["status"] != "ARRIVED":
        return
    tags = derive.tags_of_appointment(appointment["id"])
    if not tags:
        return
    for tag in tags:
        if tag["weigh_status"] != "NET_FINAL":
            return
        if tag["disposition"] in ("PENDING", "DISPUTED"):
            return
    appointment["status"] = "CLOSED"
    touch(appointment)
    touch_lane(appointment["lane_id"])


def touch_grower(grower_id):
    grower = DB["growers"].get(grower_id)
    if grower is not None:
        touch(grower)


# --------------------------------------------------------------------------
# grading cascade (PRD 3.7 step five)
# --------------------------------------------------------------------------
def grading_cascade(tag, contract):
    touch(contract)

    allocation = derive.allocation_for(contract["id"], tag["block_id"])
    if allocation is not None:
        touch(allocation)
    block = DB["blocks"].get(tag["block_id"])
    if block is not None:
        touch(block)

    appointment = DB["appointments"].get(tag["appointment_id"])
    call = DB["pick_calls"].get(appointment["pick_call_id"]) if appointment else None

    # the fulfilment check runs BEFORE the suspension check, so a call that has
    # just reached FULFILLED is never suspended
    if (call is not None and call["status"] == "ACKNOWLEDGED"
            and tag["disposition"] in derive.ACCEPTED_SET):
        delivered = derive.pick_call_delivered_net_tons(call["id"])
        if delivered >= derive.D(call["estimated_tons"]):
            call["status"] = "FULFILLED"
            touch(call)

    if derive.contract_tonnage_status(contract) != "OPEN":
        suspend_calls_on_cap(contract)

    if appointment is not None:
        close_appointment_if_settled(appointment)

    if tag["disposition"] in derive.REJECTED_SET:
        touch_grower(contract["grower_id"])


# --------------------------------------------------------------------------
# dispute cascade (PRD 3.8)
# --------------------------------------------------------------------------
def dispute_cascade(tag, contract, was_rejected):
    for line in derive.lines_of_tag(tag["id"]):
        if line["status"] != "PROVISIONAL":
            continue
        line["status"] = "VOID"
        line["voided_at"] = CLOCK.now
        touch(line)

    tag["contract_slice_tons"] = ZERO3
    tag["over_slice_tons"] = ZERO3
    tag["over_rejected_tons"] = ZERO3
    tag["excess_rejected_tons"] = ZERO3
    tag["disposition"] = "DISPUTED"
    touch(tag)

    touch(contract)
    allocation = derive.allocation_for(contract["id"], tag["block_id"])
    if allocation is not None:
        touch(allocation)
    block = DB["blocks"].get(tag["block_id"])
    if block is not None:
        touch(block)

    if derive.contract_tonnage_status(contract) == "OPEN":
        resume_calls_from_cap(contract)

    if was_rejected:
        touch_grower(contract["grower_id"])


# --------------------------------------------------------------------------
# the logical clock (PRD 2.6) -- five steps in a fixed order
# --------------------------------------------------------------------------
def advance_clock(target):
    CLOCK.now = target
    touched_growers = set()

    # 1. pick calls whose acknowledgement deadline has passed expire
    for call in derive.by_seq(DB["pick_calls"].values()):
        if call["status"] != "ISSUED":
            continue
        if call["ack_deadline_at"] is None or not CLOCK.now > call["ack_deadline_at"]:
            continue
        call["status"] = "EXPIRED"
        touch(call)
        contract = DB["contracts"].get(call["contract_id"])
        if contract is not None:
            touched_growers.add(contract["grower_id"])

    # 2. appointments whose window ended without a single weigh tag are no-shows
    for appointment in derive.by_seq(DB["appointments"].values()):
        if appointment["status"] != "SCHEDULED":
            continue
        if not CLOCK.now >= appointment["window_end"]:
            continue
        if derive.tags_of_appointment(appointment["id"]):
            continue
        appointment["status"] = "NO_SHOW"
        touch(appointment)
        touch_lane(appointment["lane_id"])
        call = DB["pick_calls"].get(appointment["pick_call_id"])
        if call is not None:
            touch(call)
            contract = DB["contracts"].get(call["contract_id"])
            if contract is not None:
                touched_growers.add(contract["grower_id"])

    # 3. installments past their due date with money still owing fall delinquent
    for installment in derive.by_seq(DB["installments"].values()):
        if installment["status"] not in ("SCHEDULED", "PARTIALLY_PAID"):
            continue
        if installment["due_at"] is None or not CLOCK.now > installment["due_at"]:
            continue
        if int(installment["paid_amount_cents"]) >= int(installment["planned_amount_cents"]):
            continue
        installment["status"] = "DELINQUENT"
        touch(installment)

    # 4. contracts whose termination notice has become effective terminate
    for contract in derive.by_seq(DB["contracts"].values()):
        if contract["lifecycle_status"] != "TERMINATION_PENDING":
            continue
        if contract["termination_effective_at"] is None:
            continue
        if not CLOCK.now >= contract["termination_effective_at"]:
            continue
        contract["lifecycle_status"] = "TERMINATED"
        touch(contract)

    # 5. the renewal dimension -- windows open first, then closing windows settle
    for contract in derive.by_seq(DB["contracts"].values()):
        if contract["lifecycle_status"] != "ACTIVE":
            continue
        if contract["renewal_status"] not in ("NOT_DUE", "RENEWED", "EVERGREEN_ROLLED"):
            continue
        opens = contract["renewal_window_opens_at"]
        closes = contract["renewal_window_closes_at"]
        if opens is None or closes is None:
            continue
        if CLOCK.now >= opens and CLOCK.now < closes:
            contract["renewal_status"] = "RENEWAL_WINDOW_OPEN"
            touch(contract)

    for contract in derive.by_seq(DB["contracts"].values()):
        if contract["lifecycle_status"] != "ACTIVE":
            continue
        if contract["renewal_status"] != "RENEWAL_WINDOW_OPEN":
            continue
        closes = contract["renewal_window_closes_at"]
        if closes is None or not CLOCK.now >= closes:
            continue
        if contract["evergreen_flag"]:
            contract["renewal_status"] = "EVERGREEN_ROLLED"
            contract["term_end_vintage"] = (int(contract["term_end_vintage"])
                                            + int(contract["evergreen_term_years"]))
            set_renewal_window(contract)
        else:
            contract["renewal_status"] = "NOT_RENEWING"
        touch(contract)

    for grower_id in touched_growers:
        touch_grower(grower_id)
