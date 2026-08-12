"""Assignment endpoints: confirm, execution, no-show, cancel."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BUS_DISTRICT_MISMATCH,
    ERR_CAPACITY_INSUFFICIENT,
    ERR_BUS_OVERLAP_CONFLICT,
    ERR_DRIVER_HOURS_CAP_EXCEEDED,
    ERR_DRIVER_OVERLAP_CONFLICT,
    ERR_DRIVER_REQUIRED,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    raise_err,
)
from middleware import (
    authenticate,
    driver_ownership,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.coverage import recompute_day_coverage
from services.pricing import (
    SOFT_CAP_MINUTES,
    bus_assignment_conflicts,
    driver_assignment_conflicts,
    driver_week_minutes,
)
from routes.service_days import check_bus_dispatchable, check_driver_dispatchable
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_int,
    req_minute,
)

bp = Blueprint("assignments", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk", "Driver"}
TERMINAL = ("COMPLETED", "NO_SHOW", "CANCELLED")


def check_assignment_transition(a, allowed_from):
    if a["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "Assignment is in a terminal state")
    if a["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Assignment in state %s cannot perform this transition" % a["status"],
        )


@bp.route("/busops/assignments", methods=["GET"])
def list_assignments():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("assignments"))
    for param in (
        "service_day_id",
        "route_id",
        "driver_id",
        "bus_id",
        "doubled_after_assignment_id",
        "status",
    ):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(param) == v]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/assignments/<rid>", methods=["GET"])
def get_assignment(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("assignments", rid, "Assignment")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(db.public(rec))


@bp.route("/busops/assignments/<rid>/confirm", methods=["POST"])
def confirm_assignment(rid):
    body = get_body()
    # Stage 1 schema: confirm requires driver_id and bus_id together.
    driver_id = body.get("driver_id")
    bus_id = body.get("bus_id")
    if driver_id is None or bus_id is None:
        raise_err(ERR_DRIVER_REQUIRED, "Confirm requires both driver_id and bus_id")
    if not isinstance(driver_id, str) or not isinstance(bus_id, str):
        raise_err(ERR_DRIVER_REQUIRED, "Confirm requires both driver_id and bus_id")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    # Stage 4 existence, left to right: path id, driver_id, bus_id.
    a = get_or_404("assignments", rid, "Assignment")
    driver = get_or_404("drivers", driver_id, "Driver")
    bus = get_or_404("buses", bus_id, "Bus")

    check_assignment_transition(a, ("PLANNED",))
    day = db.day_of_assignment(a)
    if day is None or day["status"] != "DISPATCH_OPEN":
        raise_err(ERR_INVALID_STATE, "Confirmation requires service day DISPATCH_OPEN")
    route = db.route_of_assignment(a)

    # 9. driver dispatchability
    check_driver_dispatchable(driver)
    # 10. bus dispatchability
    check_bus_dispatchable(bus, day["service_date"])
    if bus["capacity"] < route["student_count"]:
        raise_err(
            ERR_CAPACITY_INSUFFICIENT,
            "bus.capacity is below the route's student_count",
        )
    # 11. temporal overlap (half-open intervals; adjacency allowed)
    if driver_assignment_conflicts(
        driver_id, day["service_date"], a["planned_start_minute"], a["planned_end_minute"],
        exclude_ids=(a["id"],),
    ):
        raise_err(ERR_DRIVER_OVERLAP_CONFLICT, "Driver has an overlapping commitment")
    if bus_assignment_conflicts(
        bus_id, day["service_date"], a["planned_start_minute"], a["planned_end_minute"],
        exclude_ids=(a["id"],),
    ):
        raise_err(ERR_BUS_OVERLAP_CONFLICT, "Bus has an overlapping commitment")
    # 12. weekly soft cap
    monday, sunday = db.week_bounds(db.parse_date(day["service_date"]))
    candidate_minutes = a["planned_end_minute"] - a["planned_start_minute"]
    projected = driver_week_minutes(driver_id, monday, sunday, extra=candidate_minutes)
    if projected > SOFT_CAP_MINUTES:
        raise_err(
            ERR_DRIVER_HOURS_CAP_EXCEEDED,
            "Projected weekly minutes exceed the 2400-minute soft cap",
        )
    # 13. referential consistency
    contract = db.find("contracts", day["contract_id"])
    if contract is not None and bus["district_id"] != contract["district_id"]:
        raise_err(ERR_BUS_DISTRICT_MISMATCH, "Bus district does not match contract district")

    a["driver_id"] = driver_id
    a["bus_id"] = bus_id
    a["_driver_ref"] = driver_id
    a["status"] = "CONFIRMED"
    db.touch(a)
    recompute_day_coverage(day)
    return success_object(db.public(a))


@bp.route("/busops/assignments/<rid>/start", methods=["POST"])
def start_assignment(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"Driver"})
    a = get_or_404("assignments", rid, "Assignment")
    driver_ownership(actor, a.get("driver_id"))
    check_assignment_transition(a, ("CONFIRMED",))
    day = db.day_of_assignment(a)
    if day is None or day["status"] not in ("DISPATCH_OPEN", "LOCKED"):
        raise_err(
            ERR_INVALID_STATE,
            "Start requires the service day to be DISPATCH_OPEN or LOCKED",
        )
    a["status"] = "EN_ROUTE"
    db.touch(a)
    recompute_day_coverage(day)
    return success_object(db.public(a))


@bp.route("/busops/assignments/<rid>/complete", methods=["POST"])
def complete_assignment(rid):
    body = get_body()
    actual_start = req_minute(body, "actual_start_minute")
    actual_end = req_minute(body, "actual_end_minute")
    actual_miles = req_int(body, "actual_miles", minimum=0)
    actor = authenticate()
    require_roles(actor, {"Driver"})
    a = get_or_404("assignments", rid, "Assignment")
    driver_ownership(actor, a.get("driver_id"))
    check_assignment_transition(a, ("EN_ROUTE",))
    if actual_end <= actual_start:
        raise_err(
            ERR_INVALID_TIME_RANGE,
            "actual_end_minute must be strictly after actual_start_minute",
        )
    a["actual_start_minute"] = actual_start
    a["actual_end_minute"] = actual_end
    a["actual_miles"] = actual_miles
    a["status"] = "COMPLETED"
    db.touch(a)
    bus = db.find("buses", a.get("bus_id"))
    if bus is not None:
        bus["odometer_miles"] += actual_miles
        db.touch(bus)
    day = db.day_of_assignment(a)
    if day is not None:
        recompute_day_coverage(day)
    return success_object(db.public(a))


@bp.route("/busops/assignments/<rid>/no-show", methods=["POST"])
def no_show_assignment(rid):
    body = get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    a = get_or_404("assignments", rid, "Assignment")
    check_assignment_transition(a, ("CONFIRMED",))
    day = db.day_of_assignment(a)
    if day is None or day["status"] not in ("DISPATCH_OPEN", "LOCKED"):
        raise_err(
            ERR_INVALID_STATE,
            "No-show requires the service day to be DISPATCH_OPEN or LOCKED",
        )
    a["status"] = "NO_SHOW"
    db.touch(a)
    recompute_day_coverage(day)
    return success_object(db.public(a))


@bp.route("/busops/assignments/<rid>/cancel", methods=["POST"])
def cancel_assignment_endpoint(rid):
    body = get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    a = get_or_404("assignments", rid, "Assignment")
    check_assignment_transition(a, ("PLANNED", "CONFIRMED"))
    a["status"] = "CANCELLED"
    a["cancellation_reason"] = "OPS_CANCEL"
    db.touch(a)
    day = db.day_of_assignment(a)
    if day is not None:
        recompute_day_coverage(day)
    return success_object(db.public(a))
