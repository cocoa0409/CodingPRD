"""Annual plans: create, submit, return, revise, approve, publish (with airport OCC)."""
from datetime import date
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles
from constants import PLAN_STATUSES
from db import store
from services import hazard_is_critical
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, now, parse_date)

bp = Blueprint("plans", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "RegulatorAgent")
ACTIVE_STATES = ("SUBMITTED_FOR_REVIEW", "APPROVED", "PUBLISHED")


def _get_plan(rid):
    return get_or_404(store.annual_plans, rid, "annual plan")


def _duplicate_exists(airport_id, plan_year, exclude_id=None):
    for p in store.annual_plans.values():
        if p["id"] == exclude_id:
            continue
        if p["airport_id"] == airport_id and p["plan_year"] == plan_year and p["status"] in ACTIVE_STATES:
            return True
    return False


@bp.post("/annual-plans")
def create_plan():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("plan_year", "int", True, {"min": 2000, "max": 2100}),
        ("version_note", "str", False),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    # ERR_PLAN_DUPLICATE_YEAR enforced at creation and at submission (PRD §3.6)
    if _duplicate_exists(data["airport_id"], data["plan_year"]):
        raise E.ApiError(E.ERR_PLAN_DUPLICATE_YEAR,
                         "an annual plan for this airport and plan year is already in review/approval/publish", 409)
    rec = new_entity(store.annual_plans, {
        "airport_id": data["airport_id"],
        "plan_year": data["plan_year"],
        "status": "DRAFT",
        "submitted_at": None,
        "approved_by_regulator_id": None,
        "published_at": None,
        "version_note": data.get("version_note"),
    })
    return ok_object(serialize(rec), 201)


@bp.get("/annual-plans")
def list_plans():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    if status is not None and status not in PLAN_STATUSES:
        raise E.invalid_enum("status", status)
    year_raw = args.get("plan_year")
    year = None
    if year_raw is not None:
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            raise E.invalid_request("plan_year must be an integer")
    rows = [p for p in store.annual_plans.values()
            if (args.get("airport_id") is None or p["airport_id"] == args.get("airport_id"))
            and (year is None or p["plan_year"] == year)
            and (status is None or p["status"] == status)
            and (args.get("approved_by_regulator_id") is None or p.get("approved_by_regulator_id") == args.get("approved_by_regulator_id"))]
    return list_response(rows)


@bp.get("/annual-plans/<rid>")
def get_plan(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_plan(rid)))


@bp.post("/annual-plans/<rid>/submit")
def submit_plan(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    p = _get_plan(rid)
    if p["status"] != "DRAFT":
        raise E.invalid_state("annual plan must be in DRAFT to submit")
    if _duplicate_exists(p["airport_id"], p["plan_year"], exclude_id=p["id"]):
        raise E.ApiError(E.ERR_PLAN_DUPLICATE_YEAR,
                         "an annual plan for this airport and plan year is already in review/approval/publish", 409)
    p["status"] = "SUBMITTED_FOR_REVIEW"
    p["submitted_at"] = now()
    touch(p)
    # non-blocking training-currency warning: records expiring before plan year end
    cutoff = date(p["plan_year"], 12, 31)
    warnings = []
    for b in store.biologists.values():
        if b["airport_id"] != p["airport_id"]:
            continue
        for tr in store.training_records.values():
            if tr["biologist_id"] == b["id"] and parse_date(tr["expires_at"]) < cutoff:
                warnings.append({
                    "training_record_id": tr["id"],
                    "biologist_id": b["id"],
                    "expires_at": tr["expires_at"],
                })
    return ok_object(serialize(p), 200, meta_extra={"warnings": warnings})


@bp.post("/annual-plans/<rid>/return-for-revision")
def return_plan(rid):
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    p = _get_plan(rid)
    if p["status"] != "SUBMITTED_FOR_REVIEW":
        raise E.invalid_state("annual plan must be in SUBMITTED_FOR_REVIEW to return")
    p["status"] = "RETURNED"
    touch(p)
    return ok_object(serialize(p))


@bp.post("/annual-plans/<rid>/revise")
def revise_plan(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    p = _get_plan(rid)
    if p["status"] != "RETURNED":
        raise E.invalid_state("annual plan must be in RETURNED to revise")
    p["status"] = "DRAFT"
    touch(p)
    return ok_object(serialize(p))


@bp.post("/annual-plans/<rid>/approve")
def approve_plan(rid):
    uid, role = authenticate()
    require_roles(role, ("RegulatorAgent",))
    p = _get_plan(rid)
    if p["status"] != "SUBMITTED_FOR_REVIEW":
        raise E.invalid_state("annual plan must be in SUBMITTED_FOR_REVIEW to approve")
    p["status"] = "APPROVED"
    p["approved_by_regulator_id"] = uid
    touch(p)
    return ok_object(serialize(p))


@bp.post("/annual-plans/<rid>/publish")
def publish_plan(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    p = _get_plan(rid)
    data = body()
    if "expected_airport_version" not in data or data["expected_airport_version"] is None:
        raise E.invalid_request("missing required field: 'expected_airport_version'")
    expected = data["expected_airport_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.invalid_request("expected_airport_version must be an integer")
    if p["status"] != "APPROVED":
        raise E.invalid_state("annual plan must be in APPROVED to publish")
    if hazard_is_critical(p["airport_id"]):
        raise E.ApiError(E.ERR_HAZARD_CRITICAL_BLOCK,
                         "airport is at CRITICAL hazard level; publishing the annual plan is blocked", 409)
    ap = store.airports.get(p["airport_id"])
    # OCC (priority 20)
    if ap is not None and expected != ap["version"]:
        raise E.ApiError(E.ERR_STALE_VERSION,
                         "expected_airport_version does not match the airport's current version", 412)
    p["status"] = "PUBLISHED"
    p["published_at"] = now()
    touch(p)
    # supersede any prior PUBLISHED plan for the same airport
    for other in store.annual_plans.values():
        if (other["id"] != p["id"] and other["airport_id"] == p["airport_id"]
                and other["status"] == "PUBLISHED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    if ap is not None:
        touch(ap)  # publishing mutates the parent airport aggregate
    return ok_object(serialize(p))
