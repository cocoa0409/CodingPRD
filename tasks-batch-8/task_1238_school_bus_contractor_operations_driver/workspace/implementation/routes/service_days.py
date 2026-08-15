"""ServiceDay endpoints: lifecycle, reconcile, doubling, district report."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_ASSIGNMENTS_IN_FLIGHT,
    ERR_BUS_DISTRICT_MISMATCH,
    ERR_BUS_NOT_IN_SERVICE,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CREDENTIAL_EXPIRED,
    ERR_DOUBLING_INFEASIBLE,
    ERR_DRIVER_HOURS_CAP_EXCEEDED,
    ERR_DRIVER_NOT_ACTIVE,
    ERR_DRIVER_OVERLAP_CONFLICT,
    ERR_BUS_OVERLAP_CONFLICT,
    ERR_ENDORSEMENT_MISSING,
    ERR_INSPECTION_OVERDUE,
    ERR_INVALID_STATE,
    ERR_LICENSE_CLASS_INSUFFICIENT,
    ERR_OUTSIDE_CONTRACT_TERM,
    ERR_SERVICE_DAY_DATE_CONFLICT,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import (
    authenticate,
    district_ownership,
    get_or_404,
    require_roles,
)
from services.coverage import recompute_day_coverage
from services.pricing import (
    HARD_CAP_MINUTES,
    MAX_DOUBLING_DELAY_MINUTES,
    driver_week_minutes,
    shortage_credit,
    bus_assignment_conflicts,
    driver_assignment_conflicts,
)
from validation import (
    get_body,
    paginate,
    pagination_params,
    req_date,
    req_enum,
    req_int,
    req_str,
)
from routes.drivers import active_credential

bp = Blueprint("service_days", __name__)

READ_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FinanceClerk", "Driver"}
TERMINAL = ("INVOICED", "CANCELLED")


def check_day_transition(day, allowed_from):
    if day["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, "ServiceDay is in a terminal state")
    if day["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "ServiceDay in state %s cannot perform this transition" % day["status"],
        )


def check_driver_dispatchable(driver):
    if driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_NOT_ACTIVE, "Driver status is not ACTIVE")
    if active_credential(driver["id"], "CDL_B") is None:
        raise_err(ERR_CREDENTIAL_EXPIRED, "Driver lacks an ACTIVE CDL_B credential")
    if active_credential(driver["id"], "S_ENDORSEMENT") is None:
        raise_err(ERR_ENDORSEMENT_MISSING, "Driver lacks an ACTIVE S_ENDORSEMENT")
    if driver["license_class"] != "B":
        raise_err(
            ERR_LICENSE_CLASS_INSUFFICIENT, "School bus dispatch requires license_class B"
        )


def check_bus_dispatchable(bus, date_str):
    if bus["status"] != "IN_SERVICE":
        raise_err(ERR_BUS_NOT_IN_SERVICE, "Bus status is not IN_SERVICE")
    due = db.parse_date(bus["next_inspection_due"])
    service_date = db.parse_date(date_str)
    if due is None or service_date is None or due < service_date:
        raise_err(
            ERR_INSPECTION_OVERDUE,
            "bus.next_inspection_due must be on or after the service date",
        )


@bp.route("/busops/service-days", methods=["POST"])
def create_service_day():
    body = get_body()
    contract_id = req_str(body, "contract_id")
    service_date = req_date(body, "service_date")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    contract = get_or_404("contracts", contract_id, "Contract")
    # temporal: within contract term inclusive
    if service_date < contract["start_date"] or service_date > contract["end_date"]:
        raise_err(
            ERR_OUTSIDE_CONTRACT_TERM,
            "service_date outside contract [%s, %s]"
            % (contract["start_date"], contract["end_date"]),
        )
    # constraint: one day per contract+date
    for d in db.all_of("service_days"):
        if d["contract_id"] == contract_id and d["service_date"] == service_date:
            raise_err(
                ERR_SERVICE_DAY_DATE_CONFLICT,
                "A service day already exists for this contract and date",
            )
    # fiscal: contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Service-day creation requires contract ACTIVE")

    active_routes = [
        r
        for r in db.all_of("routes")
        if r["contract_id"] == contract_id and r["status"] == "ACTIVE"
    ]
    rec = {
        "id": db.new_id(),
        "contract_id": contract_id,
        "service_date": service_date,
        "status": "SCHEDULED",
        "required_routes": len(active_routes),
        "covered_routes": 0,
        "uncovered_routes": len(active_routes),
        "shortage_flag": len(active_routes) > 0,
        "shortage_credit_cents": 0,
        "cancellation_reason": None,
    }
    db.stamp_new(rec)
    db.STORES["service_days"][rec["id"]] = rec

    for route in active_routes:
        a = {
            "id": db.new_id(),
            "service_day_id": rec["id"],
            "route_id": route["id"],
            "driver_id": None,
            "bus_id": None,
            "status": "PLANNED",
            "cancellation_reason": None,
            "is_doubled": False,
            "doubled_after_assignment_id": None,
            "planned_start_minute": route["am_start_minute"],
            "planned_end_minute": route["am_end_minute"],
            "actual_start_minute": None,
            "actual_end_minute": None,
            "actual_miles": None,
            "billable": False,
            "_driver_ref": None,
        }
        db.stamp_new(a)
        db.STORES["assignments"][a["id"]] = a
    return success_object(db.public(rec), status=201)


@bp.route("/busops/service-days", methods=["GET"])
def list_service_days():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    items = list(db.all_of("service_days"))
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    service_date = request.args.get("service_date")
    if contract_id is not None:
        items = [d for d in items if d["contract_id"] == contract_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if service_date is not None:
        items = [d for d in items if d["service_date"] == service_date]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/service-days/<rid>", methods=["GET"])
def get_service_day(rid):
    actor = authenticate()
    require_roles(actor, READ_ROLES)
    rec = get_or_404("service_days", rid, "ServiceDay")
    return success_object(db.public(rec))


@bp.route("/busops/service-days/<rid>/open-dispatch", methods=["POST"])
def open_dispatch(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("service_days", rid, "ServiceDay")
    check_day_transition(rec, ("SCHEDULED",))
    contract = db.find("contracts", rec["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Open dispatch requires contract ACTIVE")
    rec["status"] = "DISPATCH_OPEN"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/service-days/<rid>/lock", methods=["POST"])
def lock_day(rid):
    body = get_body()
    expected = req_int(body, "expected_service_day_version")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("service_days", rid, "ServiceDay")
    if expected != rec["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_service_day_version does not match the day's current version",
        )
    check_day_transition(rec, ("DISPATCH_OPEN",))
    rec["status"] = "LOCKED"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/service-days/<rid>/reconcile", methods=["POST"])
def reconcile_day(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("service_days", rid, "ServiceDay")
    check_day_transition(rec, ("LOCKED",))
    assignments = db.assignments_of_day(rec["id"])
    for a in assignments:
        if a["status"] == "EN_ROUTE":
            raise_err(
                ERR_ASSIGNMENTS_IN_FLIGHT,
                "Reconcile blocked: assignments still EN_ROUTE on this service day",
            )
    for a in assignments:
        billable = a["status"] == "COMPLETED"
        if a["billable"] != billable:
            a["billable"] = billable
            db.touch(a)
    covered = sum(1 for a in assignments if a["billable"])
    rec["covered_routes"] = covered
    rec["uncovered_routes"] = rec["required_routes"] - covered
    rec["shortage_flag"] = rec["uncovered_routes"] > 0
    contract = db.find("contracts", rec["contract_id"])
    rec["shortage_credit_cents"] = shortage_credit(contract, rec)
    rec["status"] = "RECONCILED"
    db.touch(rec)
    return success_object(db.public(rec))


@bp.route("/busops/service-days/<rid>/cancel", methods=["POST"])
def cancel_day(rid):
    body = get_body()
    reason = req_enum(body, "cancellation_reason", ("WEATHER", "DISTRICT_CLOSURE"))
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    rec = get_or_404("service_days", rid, "ServiceDay")
    check_day_transition(rec, ("SCHEDULED", "DISPATCH_OPEN", "LOCKED"))
    rec["status"] = "CANCELLED"
    rec["cancellation_reason"] = reason
    db.touch(rec)
    for a in db.assignments_of_day(rec["id"]):
        if a["status"] in ("PLANNED", "CONFIRMED"):
            a["status"] = "CANCELLED"
            a["cancellation_reason"] = "WEATHER"
            db.touch(a)
    return success_object(db.public(rec))


@bp.route("/busops/service-days/<rid>/doubling-decisions", methods=["POST"])
def doubling_decision(rid):
    body = get_body()
    uncovered_id = req_str(body, "uncovered_assignment_id")
    absorbing_id = req_str(body, "absorbing_assignment_id")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    day = get_or_404("service_days", rid, "ServiceDay")
    uncovered = get_or_404("assignments", uncovered_id, "Assignment")
    absorbing = get_or_404("assignments", absorbing_id, "Assignment")

    # state checks on the transition target (uncovered) and the day
    if uncovered["status"] in ("COMPLETED", "NO_SHOW", "CANCELLED"):
        raise_err(ERR_ALREADY_TERMINAL, "Assignment is in a terminal state")
    if uncovered["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "Only a PLANNED assignment can be covered by doubling")
    check_day_transition(day, ("LOCKED",))

    # priority 9: driver dispatchability of the absorbing driver
    driver = db.find("drivers", absorbing.get("driver_id"))
    if driver is None:
        raise_err(ERR_DOUBLING_INFEASIBLE, "Absorbing assignment has no driver")
    check_driver_dispatchable(driver)
    # priority 10: bus dispatchability
    bus = db.find("buses", absorbing.get("bus_id"))
    if bus is None:
        raise_err(ERR_DOUBLING_INFEASIBLE, "Absorbing assignment has no bus")
    check_bus_dispatchable(bus, day["service_date"])

    route = db.route_of_assignment(uncovered)
    duration = uncovered["planned_end_minute"] - uncovered["planned_start_minute"]
    new_start = absorbing["planned_end_minute"]
    new_end = new_start + duration

    # priority 11: overlap checks with the shifted window
    if driver_assignment_conflicts(
        driver["id"], day["service_date"], new_start, new_end,
        exclude_ids=(uncovered["id"], absorbing["id"]),
    ):
        raise_err(ERR_DRIVER_OVERLAP_CONFLICT, "Driver has an overlapping commitment")
    if bus_assignment_conflicts(
        bus["id"], day["service_date"], new_start, new_end,
        exclude_ids=(uncovered["id"], absorbing["id"]),
    ):
        raise_err(ERR_BUS_OVERLAP_CONFLICT, "Bus has an overlapping commitment")

    # priority 12: doubling feasibility
    if absorbing["status"] != "CONFIRMED" or absorbing["service_day_id"] != day["id"]:
        raise_err(
            ERR_DOUBLING_INFEASIBLE,
            "Absorbing assignment must be CONFIRMED on the same service day",
        )
    if uncovered["service_day_id"] != day["id"]:
        raise_err(ERR_DOUBLING_INFEASIBLE, "Assignment is not on this service day")
    if bus["capacity"] < route["student_count"]:
        raise_err(
            ERR_DOUBLING_INFEASIBLE,
            "Absorbing bus capacity is below the uncovered route's student_count",
        )
    if absorbing["planned_end_minute"] > route["am_start_minute"] + MAX_DOUBLING_DELAY_MINUTES:
        raise_err(
            ERR_DOUBLING_INFEASIBLE,
            "Absorbing assignment ends too late for the 45-minute doubling window",
        )
    monday, sunday = db.week_bounds(db.parse_date(day["service_date"]))
    projected = driver_week_minutes(driver["id"], monday, sunday, extra=duration)
    if projected > HARD_CAP_MINUTES:
        raise_err(
            ERR_DRIVER_HOURS_CAP_EXCEEDED,
            "Doubling would exceed the 2700-minute hard cap",
        )

    # priority 13: referential consistency
    contract = db.find("contracts", day["contract_id"])
    if contract is not None and bus["district_id"] != contract["district_id"]:
        raise_err(ERR_BUS_DISTRICT_MISMATCH, "Bus district does not match contract district")

    uncovered["driver_id"] = absorbing["driver_id"]
    uncovered["bus_id"] = absorbing["bus_id"]
    uncovered["_driver_ref"] = absorbing["driver_id"]
    uncovered["status"] = "CONFIRMED"
    uncovered["is_doubled"] = True
    uncovered["doubled_after_assignment_id"] = absorbing["id"]
    uncovered["planned_start_minute"] = new_start
    uncovered["planned_end_minute"] = new_end
    db.touch(uncovered)
    recompute_day_coverage(day)
    return success_object(db.public(uncovered))


@bp.route("/busops/service-days/<rid>/district-report", methods=["GET"])
def district_report(rid):
    actor = authenticate()
    require_roles(actor, {"SystemAdmin", "DistrictAdmin", "ContractorOps"})
    day = get_or_404("service_days", rid, "ServiceDay")
    contract = db.find("contracts", day["contract_id"])
    if actor["role"] == "DistrictAdmin":
        district_ownership(actor, contract["district_id"] if contract else None)

    completed = [
        a
        for a in db.assignments_of_day(day["id"])
        if a["status"] == "COMPLETED"
    ]
    reports = []
    for a in completed:
        for r in db.all_of("ridership_reports"):
            if r["assignment_id"] == a["id"]:
                reports.append(r)
                break
    total_boardings = sum(r["boardings"] for r in reports)
    total_student_minutes_late = sum(r["student_minutes_late"] for r in reports)
    if reports:
        on_time_count = sum(1 for r in reports if r["on_time"])
        on_time_pct_x100 = (10000 * on_time_count) // len(reports)
        if on_time_pct_x100 >= 9500:
            tier = "EXCELLENT"
        elif on_time_pct_x100 >= 9000:
            tier = "SATISFACTORY"
        else:
            tier = "DEFICIENT"
    else:
        on_time_pct_x100 = None
        tier = None
    sla_breached = sum(
        1
        for i in db.all_of("incidents")
        if i.get("service_day_id") == day["id"] and i.get("sla_breached")
    )
    out = {
        "service_day_id": day["id"],
        "required_routes": day["required_routes"],
        "covered_routes": day["covered_routes"],
        "uncovered_routes": day["uncovered_routes"],
        "total_boardings": total_boardings,
        "total_student_minutes_late": total_student_minutes_late,
        "on_time_pct_x100": on_time_pct_x100,
        "on_time_tier": tier,
        "sla_breached_incidents": sla_breached,
        "shortage_credit_cents": day["shortage_credit_cents"],
    }
    return success_object(out)
