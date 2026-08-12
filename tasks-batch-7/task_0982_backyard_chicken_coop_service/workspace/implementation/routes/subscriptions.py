"""Subscription endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import new_id, now, serialize, stamp_new, store, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_owner, require_role
from response import list_response, ok
from services.cascade import cancel_covered_visits, pause_subscription
from util import add_months, is_int, midnight, req_dt, req_str

bp = Blueprint("subscriptions", __name__)

CUSTOMER_OR_ADMIN = {"Customer", "PlatformAdmin"}


def get_subscription(sid):
    s = store.subscriptions.get(sid)
    if s is None:
        fail("ERR_SUBSCRIPTION_NOT_FOUND", f"Subscription {sid} does not exist")
    return s


@bp.route("/coopcare/subscriptions", methods=["POST"])
def create_subscription():
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    data = body()
    household_id = data.get("household_id")
    plan_id = data.get("plan_id")
    # Priority 3 (ownership) before priority 4 (existence) for body ids.
    require_owner(uid, role, household_id if isinstance(household_id, str) else None)
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    if not isinstance(plan_id, str) or not plan_id.strip():
        fail("ERR_INVALID_REQUEST", "plan_id is required")
    h = store.households.get(household_id)
    if h is None:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    if plan_id not in store.plans:
        fail("ERR_PLAN_NOT_FOUND", f"Subscription plan {plan_id} does not exist")
    period_start = midnight(req_dt(data, "current_period_start"))
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "subscription creation requires household status ACTIVE")
    for s in store.subscriptions.values():
        if s["household_id"] == household_id and s["status"] in ("ACTIVE", "PAUSED"):
            fail("ERR_SUBSCRIPTION_ALREADY_EXISTS", "household already has a non-CANCELLED subscription")
    rec = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "plan_id": plan_id,
        "pending_plan_id": None,
        "status": "ACTIVE",
        "current_period_start": period_start,
        "current_period_end": add_months(period_start, 1),
        "used_cleanings": 0,
        "used_health_checks": 0,
    })
    store.subscriptions[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/subscriptions", methods=["GET"])
def list_subscriptions():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "plan_id", "pending_plan_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.subscriptions.values(), filters)


@bp.route("/coopcare/subscriptions/<sid>", methods=["GET"])
def read_subscription(sid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_subscription(sid)), 200)


@bp.route("/coopcare/subscriptions/<sid>/pause", methods=["POST"])
def pause(sid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    s = get_subscription(sid)
    require_owner(uid, role, s["household_id"])
    if s["status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE", "pause requires subscription status ACTIVE")
    pause_subscription(s)
    return ok(serialize(s), 200)


@bp.route("/coopcare/subscriptions/<sid>/resume", methods=["POST"])
def resume(sid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    s = get_subscription(sid)
    require_owner(uid, role, s["household_id"])
    if s["status"] != "PAUSED":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE", "resume requires subscription status PAUSED")
    h = store.households[s["household_id"]]
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "resume requires household status ACTIVE")
    s["status"] = "ACTIVE"
    touch(s)
    return ok(serialize(s), 200)


@bp.route("/coopcare/subscriptions/<sid>/cancel", methods=["POST"])
def cancel(sid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    s = get_subscription(sid)
    require_owner(uid, role, s["household_id"])
    if s["status"] not in ("ACTIVE", "PAUSED"):
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE", "cancel requires subscription status ACTIVE or PAUSED")
    cancel_covered_visits(s)  # same covered-visit cascade as pause
    s["status"] = "CANCELLED"
    s["pending_plan_id"] = None
    touch(s)
    return ok(serialize(s), 200)


@bp.route("/coopcare/subscriptions/<sid>/plan-changes", methods=["POST"])
def plan_change(sid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    s = get_subscription(sid)
    require_owner(uid, role, s["household_id"])
    data = body()
    new_plan_id = data.get("new_plan_id")
    if not isinstance(new_plan_id, str) or not new_plan_id.strip():
        fail("ERR_INVALID_REQUEST", "new_plan_id is required")
    if new_plan_id not in store.plans:
        fail("ERR_PLAN_NOT_FOUND", f"Subscription plan {new_plan_id} does not exist")
    expected = data.get("expected_subscription_version")
    if not is_int(expected):
        fail("ERR_INVALID_REQUEST", "expected_subscription_version is required and must be an integer")
    if s["status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE", "plan change requires subscription status ACTIVE")
    if expected != s["version"]:
        fail("ERR_STALE_VERSION", "expected_subscription_version does not match the current version")
    s["pending_plan_id"] = new_plan_id
    touch(s)
    return ok(serialize(s), 200)


@bp.route("/coopcare/subscriptions/<sid>/renew-period", methods=["POST"])
def renew_period(sid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    s = get_subscription(sid)
    if s["status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE", "renew-period requires subscription status ACTIVE")
    if now().date() < s["current_period_end"].date():
        fail("ERR_PERIOD_NOT_ENDED", "logical clock has not reached the current period end")
    if s["pending_plan_id"] is not None:
        s["plan_id"] = s["pending_plan_id"]
        s["pending_plan_id"] = None
    s["used_cleanings"] = 0
    s["used_health_checks"] = 0
    s["current_period_start"] = s["current_period_end"]
    s["current_period_end"] = add_months(s["current_period_start"], 1)
    touch(s)
    return ok(serialize(s), 200)
