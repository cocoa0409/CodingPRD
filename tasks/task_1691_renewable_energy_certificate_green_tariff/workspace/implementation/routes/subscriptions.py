"""Subscription endpoints and the enrollment lifecycle."""

from flask import Blueprint, request

from errors import raise_err, ERR_STALE_VERSION, ERR_PROGRAM_NOT_OPEN, \
    ERR_SUBSCRIPTION_STATE_INVALID, ERR_DUPLICATE_UTILITY_ACCOUNT, \
    ERR_QUANTITY_INVALID, ERR_MARKET_CLASS_MISMATCH, ERR_ALLOCATION_EXCEEDS_CAP
from store import STORE, new_id, next_seq, now_ts, clock_now
from util import auth, require_role, ok_object, body_json, req_str, req_int, \
    get_or_404
from services import program_committed_capacity_kw, waitlist_promotion_scan, touch
from routes.generators import list_with_serializer

bp = Blueprint("subscriptions", __name__)


def serialize_subscription(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.post("/greenpower/subscriptions")
def create_subscription():
    uid, role = auth()
    require_role(role, "ProgramManager")
    body = body_json()
    program_id = req_str(body, "program_id")
    customer_name = req_str(body, "customer_name")
    utility_account_no = req_str(body, "utility_account_no")
    allocation_kw = req_int(body, "allocation_kw")
    estimated_usage_kwh = req_int(body, "estimated_usage_kwh")
    expected_program_version = req_int(body, "expected_program_version")

    program = get_or_404(STORE["programs"], program_id, "Program")
    if expected_program_version != program["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_program_version does not match the current program version")
    if program["status"] != "OPEN":
        raise_err(ERR_PROGRAM_NOT_OPEN, "Subscriptions require an OPEN program")
    for s in STORE["subscriptions"].values():
        if (s["program_id"] == program_id and s["status"] != "TERMINATED"
                and s["utility_account_no"] == utility_account_no):
            raise_err(ERR_DUPLICATE_UTILITY_ACCOUNT,
                      "utility_account_no is already enrolled in this program")
    if allocation_kw <= 0 or estimated_usage_kwh <= 0:
        raise_err(ERR_QUANTITY_INVALID,
                  "allocation_kw and estimated_usage_kwh must be positive integers")
    if program["market_class"] != "VOLUNTARY":
        raise_err(ERR_MARKET_CLASS_MISMATCH,
                  "Subscriptions are only permitted into VOLUNTARY programs")
    if allocation_kw > program["capacity_cap_kw"]:
        raise_err(ERR_ALLOCATION_EXCEEDS_CAP,
                  "allocation_kw exceeds the program capacity cap")

    now = now_ts()
    sub = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_id": program_id,
        "customer_name": customer_name,
        "utility_account_no": utility_account_no,
        "allocation_kw": allocation_kw,
        "estimated_usage_kwh": estimated_usage_kwh,
        "status": "PENDING",
        "activated_at": None,
        "waitlisted_at": None,
        "terminated_at": None,
        "_activated_dt": None,
        "_terminated_dt": None,
        "_seq": next_seq(),
    }
    STORE["subscriptions"][sub["id"]] = sub
    # Enrollment advances the program version (capacity view invalidation).
    touch(program)
    return ok_object(serialize_subscription(sub), 201)


@bp.get("/greenpower/subscriptions")
def list_subscriptions():
    auth()
    filters = {
        "program_id": request.args.get("program_id"),
        "status": request.args.get("status"),
    }
    return list_with_serializer(list(STORE["subscriptions"].values()), filters,
                                serialize_subscription)


@bp.get("/greenpower/subscriptions/<sid>")
def get_subscription(sid):
    auth()
    sub = get_or_404(STORE["subscriptions"], sid, "Subscription")
    return ok_object(serialize_subscription(sub))


@bp.post("/greenpower/subscriptions/<sid>/activate")
def activate_subscription(sid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    sub = get_or_404(STORE["subscriptions"], sid, "Subscription")
    program = get_or_404(STORE["programs"], sub["program_id"], "Program")
    if program["status"] != "OPEN":
        raise_err(ERR_PROGRAM_NOT_OPEN, "Activation requires an OPEN program")
    if sub["status"] != "PENDING":
        raise_err(ERR_SUBSCRIPTION_STATE_INVALID,
                  "Activation requires a PENDING subscription")
    committed = program_committed_capacity_kw(program["id"])
    if committed + sub["allocation_kw"] <= program["capacity_cap_kw"]:
        sub["status"] = "ACTIVE"
        sub["activated_at"] = now_ts()
        sub["_activated_dt"] = clock_now()
        touch(sub)
        touch(program)
    else:
        # Insufficient capacity is not an error: park in WAITLISTED.
        sub["status"] = "WAITLISTED"
        sub["waitlisted_at"] = now_ts()
        touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/greenpower/subscriptions/<sid>/suspend")
def suspend_subscription(sid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    sub = get_or_404(STORE["subscriptions"], sid, "Subscription")
    if sub["status"] != "ACTIVE":
        raise_err(ERR_SUBSCRIPTION_STATE_INVALID,
                  "Suspension requires an ACTIVE subscription")
    sub["status"] = "SUSPENDED"
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/greenpower/subscriptions/<sid>/reinstate")
def reinstate_subscription(sid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    sub = get_or_404(STORE["subscriptions"], sid, "Subscription")
    program = get_or_404(STORE["programs"], sub["program_id"], "Program")
    if program["status"] != "OPEN":
        raise_err(ERR_PROGRAM_NOT_OPEN, "Reinstatement requires an OPEN program")
    if sub["status"] != "SUSPENDED":
        raise_err(ERR_SUBSCRIPTION_STATE_INVALID,
                  "Reinstatement requires a SUSPENDED subscription")
    sub["status"] = "ACTIVE"
    touch(sub)
    return ok_object(serialize_subscription(sub))


@bp.post("/greenpower/subscriptions/<sid>/terminate")
def terminate_subscription(sid):
    uid, role = auth()
    require_role(role, "ProgramManager")
    sub = get_or_404(STORE["subscriptions"], sid, "Subscription")
    if sub["status"] not in ("PENDING", "WAITLISTED", "ACTIVE", "SUSPENDED"):
        raise_err(ERR_SUBSCRIPTION_STATE_INVALID,
                  "This subscription cannot be terminated from %s" % sub["status"])
    released = sub["status"] in ("ACTIVE", "SUSPENDED")
    if sub["status"] == "WAITLISTED":
        sub["waitlisted_at"] = None
    sub["status"] = "TERMINATED"
    sub["terminated_at"] = now_ts()
    sub["_terminated_dt"] = clock_now()
    touch(sub)
    if released:
        program = STORE["programs"].get(sub["program_id"])
        if program is not None:
            touch(program)
            # Capacity release triggers the waitlist promotion scan.
            waitlist_promotion_scan(program)
    return ok_object(serialize_subscription(sub))
