"""Fitting scheduling (OCC-guarded), milestone ladder, double-booking, and
record-outcome with the remake / readiness cascades (PRD §3.3, §3.5)."""
from datetime import datetime, timedelta

from flask import Blueprint, request

import errors
import serializers as S
import validation as V
from db import db, stamp_create, touch
from errors import fail
from lookups import get_order, get_fitting, get_tailor, get_room
from middleware import get_user_context, require_role, get_json_body
from response import success, list_response
from services import calculations as calc
from services import orders as osvc

bp = Blueprint("fittings", __name__)

MILESTONES = {"BASTED", "FORWARD", "FINAL"}
MILESTONE_ORDER = ["BASTED", "FORWARD", "FINAL"]


def _parse_dt(value):
    """Parse an ISO 8601 timestamp; return a tz-aware datetime or None on failure."""
    if not isinstance(value, str):
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _round_fittings(order_id, remake_round):
    """All fittings belonging to the given remake round of an order."""
    return [f for f in db.fittings.values()
            if f["order_id"] == order_id and f.get("remake_round") == remake_round]


def _next_milestone(order):
    """The lowest milestone rung not yet PASSED in the current remake round."""
    passed = {f["milestone"] for f in _round_fittings(order["id"], order["remake_round"])
              if f["outcome"] == "PASSED"}
    for m in MILESTONE_ORDER:
        if m not in passed:
            return m
    return None  # all passed (shouldn't happen — FINAL pass bubbles to READY)


# ---------------------------------------------------------------------------
# Schedule a fitting (OCC-guarded)
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/fittings")
def schedule_fitting(oid):
    _, role = get_user_context()
    require_role(role, {"FittingSpecialist", "ShopManager"})
    o = get_order(oid)
    body = get_json_body()

    tailor_id = V.req_str(body, "tailor_id")
    room_id = V.req_str(body, "room_id")
    milestone = V.req_enum(body, "milestone", MILESTONES)
    start_at = V.req_str(body, "start_at")
    end_at = V.req_str(body, "end_at")
    expected_version = V.req_int(body, "expected_order_version")

    # FK existence (priority 4)
    tailor = get_tailor(tailor_id)
    room = get_room(room_id)

    # state (priority 7): order must be CONFIRMED, IN_FITTING, or REMAKE
    if o["status"] not in ("CONFIRMED", "IN_FITTING", "REMAKE"):
        fail(errors.ERR_ORDER_INVALID_STATE, "Order is not in a fitting-schedulable state")

    # milestone ladder (priority 9): next rung is the lowest not-yet-passed in round
    expected_milestone = _next_milestone(o)
    if milestone != expected_milestone:
        fail(errors.ERR_MILESTONE_OUT_OF_ORDER, "Fitting milestone out of order")

    # tailor/room eligibility (priority 10)
    if milestone == "FINAL" and tailor["skill_tier"] != "MASTER":
        fail(errors.ERR_MASTER_TAILOR_REQUIRED, "FINAL fitting requires a MASTER tailor")
    if tailor["status"] != "ACTIVE":
        fail(errors.ERR_TAILOR_INACTIVE, "Assigned tailor is inactive")
    if room["status"] != "OPEN":
        fail(errors.ERR_ROOM_CLOSED, "Assigned room is closed")

    start_dt = _parse_dt(start_at)
    end_dt = _parse_dt(end_at)

    # room double-booking (priority 11): half-open interval + trailing room buffer
    buffer = timedelta(minutes=room["cleanup_buffer_minutes"])
    if start_dt is not None and end_dt is not None:
        new_room_end = end_dt + buffer
        for f in db.fittings.values():
            if f["room_id"] != room_id or f["outcome"] != "SCHEDULED":
                continue
            f_start = _parse_dt(f["start_at"])
            f_end = _parse_dt(f["end_at"])
            if f_start is None or f_end is None:
                continue
            f_room_end = f_end + timedelta(minutes=room["cleanup_buffer_minutes"])
            # overlap of [start, end+buffer) intervals
            if start_dt < f_room_end and f_start < new_room_end:
                fail(errors.ERR_ROOM_DOUBLE_BOOKED, "Room double-booked")

        # tailor double-booking (priority 12): strict half-open, no buffer
        for f in db.fittings.values():
            if f["tailor_id"] != tailor_id or f["outcome"] != "SCHEDULED":
                continue
            f_start = _parse_dt(f["start_at"])
            f_end = _parse_dt(f["end_at"])
            if f_start is None or f_end is None:
                continue
            if start_dt < f_end and f_start < end_dt:
                fail(errors.ERR_TAILOR_DOUBLE_BOOKED, "Tailor double-booked")

    # fitting window (priority 13): end_at strictly > start_at
    if start_dt is None or end_dt is None or not (end_dt > start_dt):
        fail(errors.ERR_INVALID_FITTING_WINDOW, "end_at must be strictly after start_at")

    # deposit gating for the first fitting of round 0 (PRD §3.3)
    if o["status"] == "CONFIRMED" and o["remake_round"] == 0:
        captured_deposit = sum(
            p["amount_cents"] for p in db.payments.values()
            if p["order_id"] == oid and p["kind"] == "DEPOSIT" and p["status"] == "CAPTURED"
        )
        if captured_deposit < o["deposit_due_cents"]:
            fail(errors.ERR_DEPOSIT_NOT_PAID, "Deposit not yet paid")

    # OCC (priority 17)
    if expected_version != o["version"]:
        fail(errors.ERR_STALE_VERSION, "Order version is stale")

    rec = stamp_create()
    rec.update({
        "order_id": oid,
        "tailor_id": tailor_id,
        "room_id": room_id,
        "milestone": milestone,
        "start_at": start_at,
        "end_at": end_at,
        "outcome": "SCHEDULED",
        "remake_round": o["remake_round"],  # internal: which round this belongs to
    })
    db.fittings[rec["id"]] = rec

    # first fitting moves CONFIRMED/REMAKE -> IN_FITTING
    if o["status"] in ("CONFIRMED", "REMAKE"):
        o["status"] = "IN_FITTING"
    touch(o)

    return success(S.fitting(rec), status=201)


@bp.get("/orders/<oid>/fittings")
def list_fittings(oid):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "SalesAssociate", "FittingSpecialist", "Customer"})
    get_order(oid)
    limit, offset = V.parse_pagination()
    milestone = request.args.get("milestone")
    outcome = request.args.get("outcome")

    def pred(f):
        if f["order_id"] != oid:
            return False
        if milestone is not None and f["milestone"] != milestone:
            return False
        if outcome is not None and f["outcome"] != outcome:
            return False
        return True

    items = [f for f in db.fittings.values() if pred(f)]
    items.sort(key=lambda f: f["created_at"])
    page = V.paginate(items, limit, offset)
    return list_response([S.fitting(f) for f in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Record outcome (PASS/FAIL) — bubble-up to READY / cascade to REMAKE
# ---------------------------------------------------------------------------

@bp.post("/orders/<oid>/fittings/<fid>/record-outcome")
def record_outcome(oid, fid):
    _, role = get_user_context()
    require_role(role, {"FittingSpecialist", "ShopManager"})
    o = get_order(oid)
    fitting = get_fitting(oid, fid)
    body = get_json_body()
    result = V.req_enum(body, "result", {"PASS", "FAIL"})

    # state (priority 7): parent order must be IN_FITTING
    if o["status"] != "IN_FITTING":
        fail(errors.ERR_ORDER_NOT_IN_FITTING, "Order is not IN_FITTING")

    if result == "PASS":
        # all earlier-milestone fittings of current round must already be PASSED
        idx = MILESTONE_ORDER.index(fitting["milestone"])
        passed = {f["milestone"] for f in _round_fittings(oid, o["remake_round"])
                  if f["outcome"] == "PASSED"}
        for earlier in MILESTONE_ORDER[:idx]:
            if earlier not in passed:
                fail(errors.ERR_MILESTONE_OUT_OF_ORDER, "Earlier milestone not yet passed")

        fitting["outcome"] = "PASSED"
        touch(fitting)

        # FINAL pass bubbles order up to READY
        if fitting["milestone"] == "FINAL":
            o["status"] = "READY"
        touch(o)
        return success(S.fitting(fitting))

    # result == FAIL
    if fitting["milestone"] == "FINAL":
        if o["remake_round"] >= calc.MAX_REMAKES:
            fail(errors.ERR_REMAKE_LIMIT_REACHED, "Remake limit reached")
        # cascade IN_FITTING -> REMAKE
        fitting["outcome"] = "FAILED"
        touch(fitting)
        _remake_cascade(o)
        return success(S.fitting(fitting))

    # non-FINAL fail: just mark the fitting failed (no order transition)
    fitting["outcome"] = "FAILED"
    touch(fitting)
    return success(S.fitting(fitting))


def _remake_cascade(order):
    """IN_FITTING -> REMAKE side effects (PRD §3.5)."""
    order["remake_round"] += 1
    order["status"] = "REMAKE"

    customer = db.customers.get(order["customer_id"])
    if customer is not None:
        customer["remake_count"] += 1
        customer["remake_risk_band"] = calc.customer_remake_risk(
            customer["remake_count"], customer["completed_order_count"]
        )
        # goodwill store credit
        comp = calc.remake_compensation(order["remake_round"], order["locked_total_cents"])
        customer["store_credit_cents"] += comp
        touch(customer)

    # reserve a fresh cut of fabric
    fabric = osvc._order_fabric(order)
    if fabric is not None:
        fabric["bolt_meters_remaining"] -= order["fabric_meters_required"]
        touch(fabric)

    # close the round: every still-SCHEDULED fitting -> FAILED
    for f in db.fittings.values():
        if f["order_id"] == order["id"] and f["outcome"] == "SCHEDULED":
            f["outcome"] = "FAILED"
            touch(f)

    osvc.recompute_balance(order)
    touch(order)
