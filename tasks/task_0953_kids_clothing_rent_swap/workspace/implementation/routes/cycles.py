"""The cycle calendar, its charges and its invoice (PRD 3.2)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("cycles", __name__)

TERMINAL_ITEM_FULFILLMENT = ("RECEIVED", "CANCELLED", "LOST")


def invoice_of(cycle):
    """The pinned four-step order: proration -> discount -> credit -> surcharge."""
    damage = derive.cycle_damage_fee(cycle["id"])
    credit_applied = derive.cycle_credit_applied(cycle["id"])
    post_credit = (cycle["plan_charge_cents"] + cycle["protection_fee_cents"]
                   + cycle["late_fee_cents"] + damage - credit_applied)
    base = max(0, post_credit)
    surcharge = calc.surcharge_amount(base)
    return {
        "plan_charge_cents": cycle["plan_charge_cents"],
        "proration_credit_cents": cycle["proration_credit_cents"],
        "discount_cents": cycle["discount_cents"],
        "protection_fee_cents": cycle["protection_fee_cents"],
        "late_fee_cents": cycle["late_fee_cents"],
        "damage_fee_cents": damage,
        "credit_applied_cents": credit_applied,
        "surcharge_cents": surcharge,
        "invoice_total_cents": base + surcharge,
    }


@bp.post("/kidswear/cycles")
def create_cycle():
    auth.gate("PlatformAdmin", "BillingAgent")
    body = shape.body_json()
    member_id = shape.id_string(body, "member_id")
    start_at = shape.instant(body, "start_at")
    member = lookup.member(member_id)
    lookup.standing(member, block_pending=True)
    highest = 0
    for cycle in store.db["cycles"].values():
        if cycle["member_id"] == member_id and cycle["cycle_index"] > highest:
            highest = cycle["cycle_index"]
    index = highest + 1
    if index > K.CYCLE_MAX_INDEX:
        raise ApiError("ERR_VALIDATION", "cycle_index would exceed CYCLE_MAX_INDEX.")
    swap_by_at, return_due_at, grace_ends_at = calc.cycle_windows(start_at)
    row = store.insert("cycles", {
        "member_id": member_id,
        "cycle_index": index,
        "start_at": start_at,
        "swap_by_at": swap_by_at,
        "return_due_at": return_due_at,
        "grace_ends_at": grace_ends_at,
        "status": "SCHEDULED",
        "plan_charge_cents": 0,
        "proration_credit_cents": 0,
        "discount_cents": 0,
        "protection_fee_cents": 0,
        "protection_waiver_used_cents": 0,
        "late_fee_cents": 0,
        "surcharge_cents": 0,
        "invoice_total_cents": 0,
    })
    return envelope.created(serialize.cycle(row))


@bp.get("/kidswear/cycles")
def list_cycles():
    caller = auth.gate("PlatformAdmin", "Member", "BillingAgent", "WarehouseOperator")
    rows = store.all_rows("cycles")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.CYCLE_STATUSES))
    return envelope.listing(rows, serialize.cycle)


@bp.get("/kidswear/cycles/<cycle_id>")
def read_cycle(cycle_id):
    caller = auth.gate("PlatformAdmin", "Member", "BillingAgent", "WarehouseOperator")
    row = lookup.cycle(cycle_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.cycle(row))


@bp.post("/kidswear/cycles/<cycle_id>/open")
def open_cycle(cycle_id):
    auth.gate("PlatformAdmin")
    cycle = lookup.cycle(cycle_id)
    member = lookup.member(cycle["member_id"])
    lookup.standing(member, block_pending=True)
    if cycle["status"] != "SCHEDULED":
        raise ApiError("ERR_CYCLE_INVALID_STATE")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The owning member is not ACTIVE.")
    if timeutil.now() < cycle["start_at"]:
        raise ApiError("ERR_CYCLE_NOT_STARTED")

    plan = lookup.plan(member["plan_id"])
    fraction = calc.effective_discount_pct(plan, member["protection_enrolled"])
    prorated = plan["monthly_fee_cents"] - cycle["proration_credit_cents"]
    plan_charge = calc.plan_charge(plan, cycle["proration_credit_cents"], fraction)
    discount = prorated - plan_charge
    if member["protection_enrolled"]:
        protection_fee = calc.protection_fee(fraction)
        discount += K.PROTECTION_FEE_CENTS_PER_CYCLE - protection_fee
    else:
        protection_fee = 0
    cycle["plan_charge_cents"] = plan_charge
    cycle["protection_fee_cents"] = protection_fee
    cycle["discount_cents"] = discount
    cycle["status"] = "OPEN"
    store.touch(cycle)
    ledger.new_charge(member, "PLAN_CHARGE", plan_charge, cycle["id"])
    if member["protection_enrolled"]:
        ledger.new_charge(member, "PROTECTION_FEE", protection_fee, cycle["id"])
    return envelope.ok(serialize.cycle(cycle))


@bp.post("/kidswear/cycles/<cycle_id>/close-swap-window")
def close_swap_window(cycle_id):
    auth.gate("PlatformAdmin")
    cycle = lookup.cycle(cycle_id)
    member = lookup.member(cycle["member_id"])
    lookup.standing(member, block_pending=True)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE")
    if timeutil.now() <= cycle["swap_by_at"]:
        raise ApiError("ERR_SWAP_WINDOW_STILL_OPEN")
    for request in derive.cycle_swap_requests(cycle_id):
        if request["status"] == "DRAFT":
            # DRAFT is cancelled outright on its own machine (PRD 3.4) and still
            # records MEMBER_STANDING as the reason the window closed on it.
            request["status"] = "CANCELLED"
            request["rejection_reason"] = "MEMBER_STANDING"
            store.touch(request)
        elif request["status"] == "SUBMITTED":
            request["status"] = "REJECTED"
            request["rejection_reason"] = "MEMBER_STANDING"
            store.touch(request)
    cycle["status"] = "SWAP_CLOSED"
    store.touch(cycle)
    return envelope.ok(serialize.cycle(cycle))


@bp.post("/kidswear/cycles/<cycle_id>/assess-late")
def assess_late(cycle_id):
    auth.gate("BillingAgent")
    cycle = lookup.cycle(cycle_id)
    member = lookup.member(cycle["member_id"])
    lookup.standing(member, block_pending=True)
    if cycle["status"] not in ("SWAP_CLOSED", "RETURN_DUE"):
        raise ApiError("ERR_CYCLE_INVALID_STATE")
    clock = timeutil.now()
    if clock > cycle["grace_ends_at"]:
        target = "GRACE"
    elif cycle["status"] == "SWAP_CLOSED" and clock > cycle["return_due_at"]:
        target = "RETURN_DUE"
    else:
        raise ApiError("ERR_GRACE_NOT_EXPIRED")

    if target == "GRACE":
        plan = lookup.plan(member["plan_id"])
        mode = plan["late_fee_mode"]
        total = 0
        for item in derive.cycle_box_items(cycle_id):
            if item["fulfillment_status"] not in (
                    "SHIPPED", "WITH_MEMBER", "RETURNING", "RECEIVED", "LOST"):
                continue
            changed = False
            if item["fulfillment_status"] in ("SHIPPED", "WITH_MEMBER"):
                days = calc.days_late_for(clock, cycle["grace_ends_at"])
                if days != item["days_late"]:
                    item["days_late"] = days
                    changed = True
            fee = calc.late_fee_for_days(item["days_late"], mode)
            if fee != item["late_fee_cents"]:
                item["late_fee_cents"] = fee
                changed = True
            if changed:
                store.touch(item)
            total += fee
        cycle["late_fee_cents"] = total
        cycle["status"] = "GRACE"
        store.touch(cycle)
        if total > 0:
            ledger.new_charge(member, "LATE_FEE", total, cycle["id"])
    else:
        cycle["status"] = "RETURN_DUE"
        store.touch(cycle)
    return envelope.ok(serialize.cycle(cycle))


@bp.post("/kidswear/cycles/<cycle_id>/close")
def close_cycle(cycle_id):
    auth.gate("BillingAgent", "PlatformAdmin")
    cycle = lookup.cycle(cycle_id)
    member = lookup.member(cycle["member_id"])
    lookup.standing(member, block_pending=True)
    if cycle["status"] not in ("GRACE", "RETURN_DUE", "HELD"):
        raise ApiError("ERR_CYCLE_INVALID_STATE")

    if cycle["status"] == "HELD":
        if member["status"] != "DELINQUENT":
            raise ApiError("ERR_CYCLE_INVALID_STATE")
        cycle["status"] = "DELINQUENT_CLOSED"
        store.touch(cycle)
        return envelope.ok(serialize.cycle(cycle))

    for item in derive.cycle_box_items(cycle_id):
        if item["settlement_status"] == "BOUGHT_OUT":
            continue
        if item["fulfillment_status"] not in TERMINAL_ITEM_FULFILLMENT:
            raise ApiError("ERR_CYCLE_INVALID_STATE",
                           "Every box item must be received, cancelled, lost or bought out.")
    if member["status"] == "DELINQUENT":
        raise ApiError("ERR_CYCLE_CLOSE_BLOCKED_BY_DELINQUENCY")

    invoice = invoice_of(cycle)
    cycle["surcharge_cents"] = invoice["surcharge_cents"]
    cycle["invoice_total_cents"] = invoice["invoice_total_cents"]
    cycle["status"] = "CLOSED"
    store.touch(cycle)
    ledger.new_charge(member, "SURCHARGE", invoice["surcharge_cents"], cycle["id"])
    return envelope.ok(serialize.cycle(cycle))


@bp.get("/kidswear/cycles/<cycle_id>/invoice")
def read_invoice(cycle_id):
    caller = auth.gate("PlatformAdmin", "Member", "BillingAgent")
    cycle = lookup.cycle(cycle_id)
    auth.own(caller, cycle["member_id"])
    return envelope.ok(invoice_of(cycle))
