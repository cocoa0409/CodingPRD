"""Households: registration, lifecycle, size ladder, entitlements, money adjustments."""

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

bp = Blueprint("members", __name__)


@bp.post("/kidswear/members")
def register_member():
    auth.gate("PlatformAdmin")
    body = shape.body_json()
    plan_id = shape.id_string(body, "plan_id")
    email = shape.string(body, "email")
    display_name = shape.string(body, "display_name")
    child_size_code = shape.enum_in(body, "child_size_code", K.SIZE_LADDER)
    protection_enrolled = shape.boolean(body, "protection_enrolled", required=False, default=False)
    auto_apply_credit = shape.boolean(body, "auto_apply_credit", required=False, default=True)

    plan = lookup.plan(plan_id)
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED")
    for existing in store.db["members"].values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL")

    row = store.insert("members", {
        "plan_id": plan_id,
        "email": email,
        "display_name": display_name,
        "child_size_code": child_size_code,
        "size_effective_at": timeutil.now(),
        "status": "PENDING",
        "protection_enrolled": protection_enrolled,
        "auto_apply_credit": auto_apply_credit,
        "permanent_slots_consumed": 0,
    })
    return envelope.created(serialize.member(row))


@bp.get("/kidswear/members")
def list_members():
    auth.gate("PlatformAdmin", "BillingAgent", "WarehouseOperator",
              "LogisticsCoordinator", "MerchandisePlanner")
    rows = store.all_rows("members")
    rows = listing.eq(rows, "plan_id", shape.query_str("plan_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.MEMBER_STATUSES))
    return envelope.listing(rows, serialize.member)


@bp.get("/kidswear/members/<member_id>")
def read_member(member_id):
    caller = auth.gate("PlatformAdmin", "Member", "BillingAgent", "WarehouseOperator",
                       "LogisticsCoordinator", "MerchandisePlanner")
    auth.own(caller, member_id)
    row = lookup.member(member_id)
    return envelope.ok(serialize.member(row))


@bp.post("/kidswear/members/<member_id>/activate")
def activate_member(member_id):
    auth.gate("PlatformAdmin")
    member = lookup.member(member_id)
    lookup.standing(member)
    if member["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    plan = lookup.plan(member["plan_id"])
    if plan["status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED")
    member["status"] = "ACTIVE"
    member["size_effective_at"] = timeutil.now()
    store.touch(member)
    return envelope.ok(serialize.member(member))


@bp.post("/kidswear/members/<member_id>/size-up")
def size_up(member_id):
    caller = auth.gate("Member", "PlatformAdmin")
    auth.own(caller, member_id)
    body = shape.body_json()
    new_size_code = shape.member_in(body, "new_size_code", K.SIZE_LADDER)
    member = lookup.member(member_id)
    lookup.standing(member)
    steps = calc.size_ordinal(new_size_code) - calc.size_ordinal(member["child_size_code"])
    if steps < 1 or steps > K.SIZE_UP_MAX_STEPS_PER_EVENT:
        raise ApiError("ERR_SIZE_UP_INVALID_STEP")
    elapsed = timeutil.now() - member["size_effective_at"]
    if elapsed.total_seconds() < K.SIZE_UP_MIN_DAYS_BETWEEN_EVENTS * 86400:
        raise ApiError("ERR_SIZE_UP_TOO_SOON")
    member["child_size_code"] = new_size_code
    member["size_effective_at"] = timeutil.now()
    store.touch(member)
    return envelope.ok(serialize.member(member))


@bp.post("/kidswear/members/<member_id>/protection")
def toggle_protection(member_id):
    caller = auth.gate("Member", "BillingAgent")
    auth.own(caller, member_id)
    body = shape.body_json()
    enrolled = shape.boolean(body, "enrolled")
    member = lookup.member(member_id)
    lookup.standing(member)
    member["protection_enrolled"] = enrolled
    store.touch(member)
    return envelope.ok(serialize.member(member))


@bp.post("/kidswear/members/<member_id>/cancel")
def cancel_member(member_id):
    caller = auth.gate("Member", "PlatformAdmin")
    auth.own(caller, member_id)
    member = lookup.member(member_id)
    lookup.standing(member)
    if member["status"] not in ("ACTIVE", "PAUSED"):
        raise ApiError("ERR_INVALID_STATE")
    for item in derive.member_box_items(member_id):
        if item["fulfillment_status"] in ("SHIPPED", "WITH_MEMBER", "RETURNING"):
            raise ApiError("ERR_INVALID_STATE",
                           "Garments still with the household must be returned first.")
    from_paused = member["status"] == "PAUSED"
    if from_paused:
        for req in store.all_rows("pause_requests"):
            if req["member_id"] == member_id and req["status"] == "ACTIVE":
                req["status"] = "ENDED"
                store.touch(req)
    for entry in derive.member_credits(member_id):
        if entry["status"] in ("AVAILABLE", "PARTIALLY_APPLIED"):
            entry["status"] = "REVOKED"
            entry["revoke_reason"] = "MEMBER_CANCELLED"
            store.touch(entry)
    if not from_paused:
        for cycle in store.all_rows("cycles"):
            if cycle["member_id"] == member_id and cycle["status"] == "SCHEDULED":
                cycle["status"] = "CLOSED"
                store.touch(cycle)
    member["status"] = "CANCELLED"
    store.touch(member)
    return envelope.ok(serialize.member(member))


@bp.get("/kidswear/members/<member_id>/entitlements")
def read_entitlements(member_id):
    caller = auth.gate("PlatformAdmin", "Member", "BillingAgent")
    auth.own(caller, member_id)
    member = lookup.member(member_id)
    plan = store.get("plans", member["plan_id"])
    slots_occupied = 0
    for box in store.all_rows("boxes"):
        if box["member_id"] == member_id and box["status"] != "CLOSED":
            slots_occupied += derive.box_occupied(box["id"])
    swaps_remaining = 0
    for cycle in store.all_rows("cycles"):
        if cycle["member_id"] == member_id and cycle["status"] == "OPEN":
            swaps_remaining = derive.swap_entitlement_remaining(cycle, plan)
            break
    data = {
        "slots_total": plan["slots_per_box"],
        "slots_occupied": slots_occupied,
        "slots_permanently_consumed": member["permanent_slots_consumed"],
        "swaps_remaining": swaps_remaining,
        "pause_days_remaining_period":
            K.PAUSE_MAX_DAYS_PER_PERIOD - derive.pause_days_used_period(member_id),
        "pause_days_remaining_lifetime":
            K.PAUSE_MAX_DAYS_LIFETIME - derive.pause_days_used_lifetime(member_id),
        "credit_balance_cents": derive.member_credit_balance(member_id),
        "outstanding_balance_cents": derive.member_outstanding_balance(member_id),
    }
    return envelope.ok(data)


@bp.post("/kidswear/members/<member_id>/charge-adjustments")
def charge_adjustment(member_id):
    auth.gate("BillingAgent")
    body = shape.body_json()
    charge_type = shape.member_in(body, "charge_type", K.CHARGE_TYPES)
    amount_cents = shape.integer(body, "amount_cents")
    cycle_id = shape.id_string(body, "cycle_id", required=False)
    member = lookup.member(member_id)
    if cycle_id is not None:
        lookup.cycle(cycle_id)
    lookup.standing(member)
    charge = ledger.new_charge(member, charge_type, amount_cents, cycle_id)
    return envelope.created(serialize.charge_entry(charge))


@bp.post("/kidswear/members/<member_id>/credit-adjustments")
def credit_adjustment(member_id):
    auth.gate("BillingAgent")
    body = shape.body_json()
    amount_cents = shape.integer(body, "amount_cents", minimum=1)
    shape.string(body, "reason", required=False, default=None)
    member = lookup.member(member_id)
    lookup.standing(member)
    entry = ledger.new_credit(member, amount_cents)
    # Auto-apply deliberately does NOT fire for operator grants (PRD 3.11).
    return envelope.created(serialize.credit_entry(entry))


@bp.post("/kidswear/members/<member_id>/credit-applications")
def apply_credit(member_id):
    caller = auth.gate("BillingAgent", "Member")
    auth.own(caller, member_id)
    body = shape.body_json()
    charge_entry_id = shape.id_string(body, "charge_entry_id")
    expected_member_version = shape.integer(body, "expected_member_version")
    member = lookup.member(member_id)
    charge = lookup.charge_entry(charge_entry_id)
    lookup.standing(member)
    # rung 21
    if expected_member_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    clock = timeutil.now()
    entries = derive.member_credits(member_id)
    usable = [e for e in entries
              if e["status"] in ("AVAILABLE", "PARTIALLY_APPLIED") and clock < e["expires_at"]]
    # rung 58
    if entries and not usable:
        raise ApiError("ERR_CREDIT_EXPIRED")
    # rung 59
    if derive.member_credit_balance(member_id) <= 0:
        raise ApiError("ERR_INSUFFICIENT_CREDIT")
    # rung 60
    if charge["status"] not in ("ASSESSED", "PARTIALLY_SETTLED"):
        raise ApiError("ERR_CHARGE_NOT_OPEN")
    ledger.apply_credit_waterfall(member, only_charge=charge)
    store.touch(member)
    return envelope.ok(serialize.charge_entry(charge))
