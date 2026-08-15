"""Incident endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CROSS_DISTRICT_REFERENCE,
    ERR_DISCIPLINE_CONTEXT_REQUIRED,
    ERR_FUTURE_INCIDENT,
    ERR_INVALID_STATE,
    raise_err,
)
from middleware import (
    authenticate,
    district_ownership,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.pricing import sla_window_hours
from validation import (
    get_body,
    opt_bool,
    opt_str,
    paginate,
    pagination_params,
    req_datetime,
    req_enum,
    req_str,
)

bp = Blueprint("incidents", __name__)

LIST_ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "HRRecruiter", "Driver"}
WRITE_ROLES = {"Driver", "ContractorOps"}


def check_incident_transition(inc, allowed_from):
    if inc["status"] == "CLOSED":
        raise_err(ERR_ALREADY_TERMINAL, "Incident is CLOSED (terminal)")
    if inc["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Incident in state %s cannot perform this transition" % inc["status"],
        )


def _stamp_submission(inc):
    now = db.clock_now()
    due = now + timedelta(hours=sla_window_hours(inc["severity"]))
    inc["_submitted_at_dt"] = now
    inc["_district_due_by_dt"] = due
    inc["submitted_at"] = db.fmt_clock(now)
    inc["district_due_by"] = db.fmt_clock(due)


@bp.route("/busops/incidents", methods=["POST"])
def create_incident():
    body = get_body()
    district_id = req_str(body, "district_id")
    category = req_enum(body, "category", ("ACCIDENT", "BEHAVIOR", "MECHANICAL", "MEDICAL"))
    severity = req_enum(body, "severity", ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
    description = req_str(body, "description")
    occurred = req_datetime(body, "occurred_at")
    route_id = opt_str(body, "route_id")
    driver_id = opt_str(body, "driver_id")
    service_day_id = opt_str(body, "service_day_id")
    flag = opt_bool(body, "student_discipline_flag", default=False)
    actor = authenticate()
    require_roles(actor, WRITE_ROLES)
    # existence, left to right
    get_or_404("districts", district_id, "District")
    route = get_or_404("routes", route_id, "Route") if route_id is not None else None
    if driver_id is not None:
        get_or_404("drivers", driver_id, "Driver")
    day = (
        get_or_404("service_days", service_day_id, "ServiceDay")
        if service_day_id is not None
        else None
    )
    # temporal: occurred_at must not lie in the future
    if occurred > db.clock_now():
        raise_err(ERR_FUTURE_INCIDENT, "occurred_at is after the logical clock")
    # referential: route/service day must belong to the incident's district
    if route is not None:
        r_contract = db.find("contracts", route["contract_id"])
        if r_contract is None or r_contract["district_id"] != district_id:
            raise_err(
                ERR_CROSS_DISTRICT_REFERENCE,
                "route_id resolves to a different district",
            )
    if day is not None:
        d_contract = db.find("contracts", day["contract_id"])
        if d_contract is None or d_contract["district_id"] != district_id:
            raise_err(
                ERR_CROSS_DISTRICT_REFERENCE,
                "service_day_id resolves to a different district",
            )

    rec = {
        "id": db.new_id(),
        "district_id": district_id,
        "route_id": route_id,
        "driver_id": driver_id,
        "service_day_id": service_day_id,
        "category": category,
        "severity": severity,
        "description": description,
        "occurred_at": db.fmt_clock(occurred),
        "student_discipline_flag": flag,
        "status": "DRAFT",
        "submitted_at": None,
        "district_due_by": None,
        "acknowledged_at": None,
        "sla_breached": False,
        "_submitted_at_dt": None,
        "_district_due_by_dt": None,
        "_acknowledged_at_dt": None,
        "_district_ref": district_id,
    }
    db.stamp_new(rec)
    db.STORES["incidents"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/incidents", methods=["GET"])
def list_incidents():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, LIST_ROLES)
    items = list(db.all_of("incidents"))
    for param in ("district_id", "route_id", "driver_id", "service_day_id", "status", "severity"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if i.get(param) == v]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/incidents/<rid>", methods=["GET"])
def get_incident(rid):
    actor = authenticate()
    require_roles(actor, LIST_ROLES)
    rec = get_or_404("incidents", rid, "Incident")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(db.public(rec))


@bp.route("/busops/incidents/<rid>/submit", methods=["POST"])
def submit_incident(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, WRITE_ROLES)
    inc = get_or_404("incidents", rid, "Incident")
    check_incident_transition(inc, ("DRAFT", "RETURNED_FOR_INFO"))
    if inc["student_discipline_flag"] and (
        inc.get("route_id") is None or inc.get("service_day_id") is None
    ):
        raise_err(
            ERR_DISCIPLINE_CONTEXT_REQUIRED,
            "student_discipline_flag=true requires route_id and service_day_id",
        )
    inc["status"] = "SUBMITTED"
    _stamp_submission(inc)
    db.touch(inc)
    return success_object(db.public(inc))


@bp.route("/busops/incidents/<rid>/acknowledge", methods=["POST"])
def acknowledge_incident(rid):
    get_body()
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    inc = get_or_404("incidents", rid, "Incident")
    district_ownership(actor, inc["district_id"])
    check_incident_transition(inc, ("SUBMITTED",))
    now = db.clock_now()
    inc["status"] = "ACKNOWLEDGED"
    inc["_acknowledged_at_dt"] = now
    inc["acknowledged_at"] = db.fmt_clock(now)
    due = inc.get("_district_due_by_dt")
    inc["sla_breached"] = bool(due is not None and now > due)
    db.touch(inc)
    return success_object(db.public(inc))


@bp.route("/busops/incidents/<rid>/return", methods=["POST"])
def return_incident(rid):
    body = get_body()
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin"})
    inc = get_or_404("incidents", rid, "Incident")
    district_ownership(actor, inc["district_id"])
    check_incident_transition(inc, ("SUBMITTED",))
    inc["status"] = "RETURNED_FOR_INFO"
    db.touch(inc)
    return success_object(db.public(inc))


@bp.route("/busops/incidents/<rid>/close", methods=["POST"])
def close_incident(rid):
    body = get_body()
    opt_str(body, "resolution_note")
    actor = authenticate()
    require_roles(actor, {"DistrictAdmin", "ContractorOps"})
    inc = get_or_404("incidents", rid, "Incident")
    if actor["role"] == "DistrictAdmin":
        district_ownership(actor, inc["district_id"])
    check_incident_transition(inc, ("ACKNOWLEDGED",))
    inc["status"] = "CLOSED"
    db.touch(inc)
    return success_object(db.public(inc))
