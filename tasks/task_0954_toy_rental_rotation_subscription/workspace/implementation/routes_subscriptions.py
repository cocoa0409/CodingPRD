"""Subscription routes: read, plan change, pause, resume, cancel, box create,
box list, fee list."""
from datetime import datetime, time, timedelta, timezone

from flask import Blueprint

from domain import (
    MAX_PAUSE_DAYS_PER_365,
    OPEN_BOX_STATES,
    base_fields,
    by_seq,
    cancel_member_wishlist,
    cancel_planned_box,
    touch,
)
from envelope import ok_list, ok_object
from errors import domain as derr, invalid_state, not_found, stale_version
from serializers import serialize_box, serialize_fee, serialize_subscription
from store import DB, clock, clock_date
from timestamps import iso3, parse_date
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
    query_filter,
    require_ownership,
)

bp = Blueprint("subscriptions", __name__)


def _get_subscription(sid):
    s = DB.subscriptions.get(sid)
    if s is None:
        raise not_found("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription id does not exist.")
    return s


def _member(member_id):
    return DB.members.get(member_id)


def _check_overlap(sub, start, end):
    """Half-open [start, end) windows; pure adjacency is allowed."""
    for w in sub["pause_windows"]:
        if start < w["end_date"] and end > w["start_date"]:
            raise derr("ERR_PAUSE_WINDOW_OVERLAP", 409,
                       "Pause window overlaps an existing window.")


def _allowance_used(sub):
    from serializers import paused_days_used
    return paused_days_used(sub)


@bp.get("/toy-rental/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager", "CustomerService"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    return ok_object(serialize_subscription(s))


@bp.patch("/toy-rental/subscriptions/<sid>/plan")
def change_plan(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    s = _get_subscription(sid)
    data = body()
    shape = parse_fields(data, [
        F("plan_id", True, "str"),
        F("expected_subscription_version", True, "int"),
    ])
    plan_id = shape.values.get("plan_id")
    if isinstance(plan_id, str) and plan_id not in DB.plans:
        raise not_found("ERR_PLAN_NOT_FOUND", "SubscriptionPlan id does not exist.")
    require_ownership(role, uid, s["member_id"])
    expected = shape.values.get("expected_subscription_version")
    if isinstance(expected, int) and expected != s["version"]:
        raise stale_version()
    finalize_shape(shape)
    s["plan_id"] = plan_id
    touch(s)
    return ok_object(serialize_subscription(s))


@bp.post("/toy-rental/subscriptions/<sid>/pause")
def pause_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    m = _member(s["member_id"])
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    if s["status"] != "ACTIVE":
        raise derr("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                   "Subscription is not ACTIVE.")
    data = body()
    shape = parse_fields(data, [
        F("start_date", True, "date"),
        F("duration_days", True, "int", min=1),
    ])
    start_raw = shape.values.get("start_date")
    duration = shape.values.get("duration_days")
    if start_raw is not None and duration is not None:
        start = parse_date(start_raw)
        end = start + timedelta(days=duration)
        _check_overlap(s, start, end)
        if _allowance_used(s) + duration > MAX_PAUSE_DAYS_PER_365:
            raise derr("ERR_PAUSE_ALLOWANCE_EXCEEDED", 422,
                       "Pause allowance of 60 days per 365 days exceeded.")
    finalize_shape(shape)
    start = parse_date(start_raw)
    end = start + timedelta(days=duration)
    window = {"start_date": start, "end_date": end, "consumed_days": None, "closed": False}
    s["pause_windows"].append(window)
    if start <= clock_date():
        # Immediate pause.
        s["status"] = "PAUSED"
        s["current_pause_end"] = datetime.combine(end, time.min, tzinfo=timezone.utc)
        for b in by_seq([b for b in DB.boxes.values() if b["subscription_id"] == sid]):
            if b["status"] == "PLANNED":
                cancel_planned_box(b, released=None)
    touch(s)
    return ok_object(serialize_subscription(s))


@bp.post("/toy-rental/subscriptions/<sid>/resume")
def resume_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    m = _member(s["member_id"])
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    if s["status"] != "PAUSED":
        raise derr("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                   "Subscription is not PAUSED.")
    data = body()
    shape = parse_fields(data, [])
    finalize_shape(shape)
    _close_active_window(s)
    touch(s)
    return ok_object(serialize_subscription(s))


def _close_active_window(s):
    """Close the currently open pause window and shift the cadence anchor."""
    today = clock_date()
    for w in s["pause_windows"]:
        if not w["closed"] and w["start_date"] <= today:
            consumed = max(0, (min(today, w["end_date"]) - w["start_date"]).days)
            w["consumed_days"] = consumed
            w["closed"] = True
            s["next_cycle_due_at"] = s["next_cycle_due_at"] + timedelta(days=consumed)
            break
    s["current_pause_end"] = None
    s["status"] = "ACTIVE"


@bp.post("/toy-rental/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    if s["status"] not in ("ACTIVE", "PAUSED"):
        raise invalid_state("Subscription cannot be cancelled from its current state.")
    data = body()
    shape = parse_fields(data, [F("reason", False, "str")])
    finalize_shape(shape)
    cancel_member_wishlist(s["member_id"], released=None)
    for b in by_seq([b for b in DB.boxes.values() if b["subscription_id"] == sid]):
        if b["status"] == "PLANNED":
            cancel_planned_box(b, released=None)
    s["pause_windows"] = [w for w in s["pause_windows"] if w["closed"]]
    s["current_pause_end"] = None
    s["status"] = "CANCELLED"
    s["cancel_reason"] = shape.values.get("reason")
    touch(s)
    return ok_object(serialize_subscription(s))


@bp.post("/toy-rental/subscriptions/<sid>/rotation-boxes")
def create_rotation_box(sid):
    uid, role = authenticate()
    authorize(role, {"Member"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    m = _member(s["member_id"])
    if m is not None and m["status"] == "SUSPENDED":
        raise derr("ERR_MEMBER_SUSPENDED", 409, "Member is SUSPENDED.")
    if s["status"] != "ACTIVE":
        raise derr("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                   "Subscription is not ACTIVE.")
    data = body()
    shape = parse_fields(data, [F("expected_subscription_version", True, "int")])
    expected = shape.values.get("expected_subscription_version")
    if isinstance(expected, int) and expected != s["version"]:
        raise stale_version()
    if clock() < s["next_cycle_due_at"]:
        raise derr("ERR_BOX_CYCLE_NOT_DUE", 422,
                   "The next rotation cycle is not yet due.")
    for b in DB.boxes.values():
        if b["subscription_id"] == sid and b["status"] in OPEN_BOX_STATES:
            raise derr("ERR_PREVIOUS_BOX_OPEN", 409,
                       "A sibling rotation box is still open.")
    finalize_shape(shape)
    plan = DB.plans.get(s["plan_id"])
    b = base_fields()
    cycle = sum(1 for x in DB.boxes.values() if x["subscription_id"] == sid) + 1
    b.update({
        "subscription_id": sid,
        "cycle_number": cycle,
        "status": "PLANNED",
        "swap_count": 0,
        "delivered_at": None,
        "delivered_at_dt": None,
        "due_date": None,
        "received_at": None,
        "received_at_dt": None,
        "plan_snapshot": {
            "plan_id": plan["id"] if plan else None,
            "toys_per_box": plan["toys_per_box"] if plan else 1,
            "swap_allowance_per_cycle": plan["swap_allowance_per_cycle"] if plan else 0,
            "max_holds": plan["max_holds"] if plan else 0,
            "rotation_cadence_days": plan["rotation_cadence_days"] if plan else 1,
            "rental_period_days": plan["rental_period_days"] if plan else 1,
            "buyout_discount_pct": plan["buyout_discount_pct"] if plan else 0,
        },
    })
    DB.boxes[b["id"]] = b
    touch(s)
    return ok_object(serialize_box(b), status=201)


@bp.get("/toy-rental/subscriptions/<sid>/rotation-boxes")
def list_subscription_boxes(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "OperationsManager"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    boxes = by_seq([b for b in DB.boxes.values() if b["subscription_id"] == sid])
    page, meta = paginate(boxes)
    return ok_list([serialize_box(b) for b in page], meta)


@bp.get("/toy-rental/subscriptions/<sid>/fees")
def list_subscription_fees(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService"})
    s = _get_subscription(sid)
    require_ownership(role, uid, s["member_id"])
    status = query_filter("status")
    fees = [f for f in DB.fees.values() if f["subscription_id"] == sid]
    if status is not None:
        fees = [f for f in fees if f["status"] == status]
    fees = by_seq(fees)
    page, meta = paginate(fees)
    return ok_list([serialize_fee(f) for f in page], meta)
