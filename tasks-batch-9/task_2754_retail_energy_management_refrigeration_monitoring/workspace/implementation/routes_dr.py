"""Demand-response participation and settlement (PRD 3.8)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from db import db, new_row
from errors import ApiError
from security import ENERGY_ANALYST, ENERGY_MANAGER, roles
from util import rhu

bp = Blueprint("dr_events", __name__)

RECOVERY_GAP = timedelta(minutes=calc.DR_RECOVERY_GAP_MINUTES)


def _conflicts(new_start, new_end, other_start, other_end):
    """Closed windows plus a mandatory 240-minute recovery separation."""
    return (new_start < other_end + RECOVERY_GAP
            and other_start < new_end + RECOVERY_GAP)


@bp.route("/utility-accounts/<account_id>/demand-response-events", methods=["POST"])
@roles(ENERGY_MANAGER)
def enroll_event(account_id):
    body = v.body()
    program_code = v.get_str(body, "program_code", min_len=1)
    start = v.get_dt(body, "curtailment_start_iso")
    end = v.get_dt(body, "curtailment_end_iso")
    target_reduction_kw = v.get_num(body, "target_reduction_kw", 1, gt=0)
    v.window(start, end, "curtailment_start_iso", "curtailment_end_iso")
    account = common.get_account(account_id)
    if account["dr_enrollment_state"] == "SUSPENDED":
        raise ApiError("ERR_DR_ENROLLMENT_SUSPENDED")
    for other in derive.account_events(account_id):
        if other["event_state"] not in ("SCHEDULED", "NOTIFIED", "ACTIVE"):
            continue
        if _conflicts(start, end, other["curtailment_start_iso"],
                      other["curtailment_end_iso"]):
            raise ApiError("ERR_DR_WINDOW_CONFLICT")
    event = new_row(db.dr_events, {
        "utility_account_id": account_id,
        "program_code": program_code,
        "curtailment_start_iso": start,
        "curtailment_end_iso": end,
        "target_reduction_kw": target_reduction_kw,
        "baseline_kw": None,
        "total_reduction_kwh": None,
        "performance_pct": None,
        "incentive_usd": rhu(0, 2),
        "penalty_usd": rhu(0, 2),
        "event_state": "SCHEDULED",
        "settlement_state": "PENDING",
        "notified_at_iso": None,
        "opt_out_reason": None,
        "reversal_reason": None,
    })
    return envelope.created(serial.dr_event(event))


@bp.route("/demand-response-events/<event_id>/notify", methods=["POST"])
@roles(ENERGY_MANAGER)
def notify_event(event_id):
    event = common.get_event(event_id)
    if event["event_state"] != "SCHEDULED":
        raise ApiError("ERR_DR_EVENT_STATE_INVALID")
    account = derive.account_of_event(event)
    if account["dr_enrollment_state"] != "ENROLLED":
        raise ApiError("ERR_DR_ENROLLMENT_SUSPENDED")
    baseline = calc.dr_baseline_kw(account["id"], event["curtailment_start_iso"])
    if baseline is None:
        raise ApiError("ERR_BASELINE_DATA_INSUFFICIENT")
    event["event_state"] = "NOTIFIED"
    event["baseline_kw"] = baseline
    event["notified_at_iso"] = db.clock
    cascade.touch(event)
    return envelope.ok(serial.dr_event(event))


@bp.route("/demand-response-events/<event_id>/activate", methods=["POST"])
@roles(ENERGY_MANAGER)
def activate_event(event_id):
    event = common.get_event(event_id)
    if event["event_state"] != "NOTIFIED":
        raise ApiError("ERR_DR_EVENT_STATE_INVALID")
    account = derive.account_of_event(event)
    store = derive.store_of_account(account)
    if store is not None and store["energy_posture"] in ("CURTAILED", "LOCKED"):
        raise ApiError("ERR_FOOD_SAFETY_HOLD")
    if db.clock < event["curtailment_start_iso"]:
        raise ApiError("ERR_CURTAILMENT_NOT_ELAPSED")
    event["event_state"] = "ACTIVE"
    cascade.touch(event)
    if store is not None:
        cascade.recompute_posture(store)
    return envelope.ok(serial.dr_event(event))


@bp.route("/demand-response-events/<event_id>/settle", methods=["POST"])
@roles(ENERGY_ANALYST)
def settle_event(event_id):
    event = common.get_event(event_id)
    if event["settlement_state"] != "PENDING" or event["event_state"] != "COMPLETED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    if db.clock < event["curtailment_end_iso"]:
        raise ApiError("ERR_CURTAILMENT_NOT_ELAPSED")
    account = derive.account_of_event(event)
    total, target, performance, incentive, penalty = calc.dr_settlement(
        account["id"], event)
    event["total_reduction_kwh"] = total
    event["performance_pct"] = performance
    event["incentive_usd"] = incentive
    event["penalty_usd"] = penalty
    event["settlement_state"] = "SETTLED"
    cascade.touch(event)
    cascade.touch(account)
    return envelope.ok(serial.dr_event(event))


@bp.route("/demand-response-events/<event_id>/reverse-settlement", methods=["POST"])
@roles(ENERGY_MANAGER)
def reverse_settlement(event_id):
    body = v.body()
    reversal_reason = v.get_str(body, "reversal_reason", min_len=1)
    event = common.get_event(event_id)
    if event["settlement_state"] != "SETTLED":
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID")
    account = derive.account_of_event(event)
    event["settlement_state"] = "REVERSED"
    event["reversal_reason"] = reversal_reason
    cascade.touch(event)
    cascade.touch(account)
    return envelope.ok(serial.dr_event(event))
