"""Construction permitting and backhaul crew coordination."""

from flask import Blueprint

import calc
import services
from db import (add_days, db, fmt_dt, get_dt, new_record, now, serialize,
                set_dt, sorted_records)
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, DATETIME, INTEGER, ROLE_CONSTRUCTION, STRING,
                        authenticate, f, pagination, require_conditional,
                        validate_body)

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ["BUILDING", "ELECTRICAL", "ROW"]
ORDER_TYPES = ["POWER", "FIBER"]
ORDER_ACTIONS = ["SCHEDULE", "CANCEL", "DELIVER"]


# ---------------------------------------------------------------------------
# construction permits
# ---------------------------------------------------------------------------

@bp.post("/construction-permits")
def create_permit():
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([
        f("candidate_id", STRING),
        f("permit_type", STRING, enum=PERMIT_TYPES),
        f("valid_days", INTEGER, required=False, ge=1, default=180),
    ])
    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)

    clock = now()
    permit = new_record({
        "candidate_id": candidate["id"],
        "permit_type": body["permit_type"],
        "valid_days": body["valid_days"],
        "status": "SUBMITTED",
        "submitted_date": fmt_dt(clock),
        "issued_date": None,
        "expiry_date": None,
        "revocation_reason": None,
    })
    set_dt(permit, "submitted_date", clock)
    set_dt(permit, "issued_date", None)
    set_dt(permit, "expiry_date", None)
    db.construction_permits[permit["id"]] = permit
    return created(serialize(permit))


@bp.get("/construction-permits")
def list_permits():
    authenticate(ALL_ROLES)
    pagination()  # ERR_INVALID_PAGINATION precedes the lazy-expiry sweep
    for permit in sorted_records(db.construction_permits):
        services.refresh_permit(permit)
    return listing("construction_permits", ["candidate_id", "status"])


@bp.get("/construction-permits/<permit_id>")
def read_permit(permit_id):
    authenticate(ALL_ROLES)
    permit = fetch("construction_permits", permit_id)
    services.refresh_permit(permit)
    return ok(serialize(permit))


@bp.post("/construction-permits/<permit_id>/issue")
def issue_permit(permit_id):
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([f("issued_date", DATETIME)])
    permit = fetch("construction_permits", permit_id)
    services.refresh_permit(permit)

    if permit["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", 409)

    candidate = db.candidates.get(permit["candidate_id"])
    if candidate is None or not candidate["environmental_cleared"]:
        raise ApiError("ERR_ENVIRONMENTAL_NOT_CLEARED", 409)
    if candidate["feasibility_status"] not in ("ENTITLED", "BUILD_READY"):
        raise ApiError("ERR_ZONING_NOT_APPROVED", 409)

    issued = body["issued_date"]
    if issued.dt > now():
        raise ApiError("ERR_DATE_IN_FUTURE", 422)

    expiry = add_days(issued.dt, permit["valid_days"])
    set_dt(permit, "issued_date", issued.dt, raw=issued.raw)
    set_dt(permit, "expiry_date", expiry)
    services.apply(permit, {
        "issued_date": issued.raw,
        "expiry_date": fmt_dt(expiry),
        "status": "ISSUED",
    })
    services.apply(candidate, {"permit_issued": True})
    return ok(serialize(permit))


@bp.post("/construction-permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([f("revocation_reason", STRING)])
    permit = fetch("construction_permits", permit_id)
    services.refresh_permit(permit)

    if permit["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_PERMIT_STATE", 409)

    services.apply(permit, {"revocation_reason": body["revocation_reason"],
                            "status": "REVOKED"})
    services.permit_left_issued(permit)
    return ok(serialize(permit))


# ---------------------------------------------------------------------------
# backhaul orders
# ---------------------------------------------------------------------------

def _capacity_exceeded(provider, window_start, window_end):
    capacity = int(provider["concurrent_crew_capacity"])
    existing = [o for o in services.orders_of_provider(provider["id"])
                if o["status"] in services.OPEN_ORDER_STATUSES]
    for day in calc.covered_days(window_start, window_end):
        count = 1
        for order in existing:
            start = get_dt(order, "window_start")
            end = get_dt(order, "window_end")
            if start is None or end is None:
                continue
            if start <= day < end:
                count += 1
        if count > capacity:
            return True
    return False


@bp.post("/backhaul-orders")
def create_order():
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([
        f("candidate_id", STRING),
        f("provider_id", STRING),
        f("order_type", STRING, enum=ORDER_TYPES),
        f("window_start", DATETIME),
        f("window_end", DATETIME),
    ])
    candidate = db.candidates.get(body["candidate_id"])
    if candidate is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404)
    provider = db.utility_providers.get(body["provider_id"])
    if provider is None:
        raise ApiError("ERR_UTILITY_PROVIDER_NOT_FOUND", 404)

    start = body["window_start"]
    end = body["window_end"]
    days = calc.crew_days(start.dt, end.dt)
    if days <= 0:
        raise ApiError("ERR_INVALID_WINDOW", 422)

    if _capacity_exceeded(provider, start.dt, end.dt):
        raise ApiError("ERR_PROVIDER_CAPACITY_EXCEEDED", 409)

    order = new_record({
        "candidate_id": candidate["id"],
        "provider_id": provider["id"],
        "order_type": body["order_type"],
        "window_start": start.raw,
        "window_end": end.raw,
        "crew_days": days,
        "delivered_date": None,
        "status": "REQUESTED",
    })
    set_dt(order, "window_start", start.dt, raw=start.raw)
    set_dt(order, "window_end", end.dt, raw=end.raw)
    set_dt(order, "delivered_date", None)
    db.backhaul_orders[order["id"]] = order
    services.refresh_provider_crew_days(provider)
    return created(serialize(order))


@bp.get("/backhaul-orders")
def list_orders():
    authenticate(ALL_ROLES)
    return listing("backhaul_orders",
                   ["candidate_id", "provider_id", "order_type", "status"])


@bp.get("/backhaul-orders/<order_id>")
def read_order(order_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("backhaul_orders", order_id)))


@bp.post("/backhaul-orders/<order_id>/status-actions")
def order_status_action(order_id):
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([
        f("action", STRING, enum=ORDER_ACTIONS),
        f("delivered_date", DATETIME, required=False),
    ])
    action = body["action"]
    if action == "DELIVER":
        require_conditional(body, "delivered_date")

    order = fetch("backhaul_orders", order_id)
    allowed = {
        "SCHEDULE": ("REQUESTED",),
        "CANCEL": ("REQUESTED", "SCHEDULED"),
        "DELIVER": ("SCHEDULED",),
    }[action]
    if order["status"] not in allowed:
        raise ApiError("ERR_INVALID_ORDER_STATE", 409)

    if action == "DELIVER":
        delivered = body["delivered_date"]
        if delivered.dt > now():
            raise ApiError("ERR_DATE_IN_FUTURE", 422)
        set_dt(order, "delivered_date", delivered.dt, raw=delivered.raw)
        services.apply(order, {"delivered_date": delivered.raw,
                               "status": "DELIVERED"})
    else:
        services.apply(order, {"status": {"SCHEDULE": "SCHEDULED",
                                          "CANCEL": "CANCELLED"}[action]})

    provider = db.utility_providers.get(order["provider_id"])
    if provider is not None:
        services.refresh_provider_crew_days(provider)
    return ok(serialize(order))
