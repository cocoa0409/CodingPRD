"""Facility endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request, err_invalid_enum
from middleware import get_auth, require_roles
from response import success_object, success_list, paginate
from services import cascades
from services.records import new_record, touch, public
from constants import FACILITY_TYPES, SPECIES
from util import today, parse_date
from validate import get_body, validate_body

bp = Blueprint("facilities", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_facility(facility_id):
    f = store.facilities.get(facility_id)
    if f is None:
        raise err_not_found("facility")
    return f


def _validate_allowed_species(value):
    if not isinstance(value, list) or not value:
        raise err_invalid_request("allowed_species must be a non-empty array")
    for item in value:
        if item not in SPECIES:
            raise err_invalid_enum("allowed_species", item)
    return value


def _validate_positive_int(field, value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise err_invalid_request("%s must be a non-negative integer" % field)
    return value


@bp.post("/v1/facilities")
def create_facility():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {
        "name": ("string", True, None),
        "facility_type": ("string", True, FACILITY_TYPES),
        "region_code": ("string", True, None),
        "address": ("string", False, None),
        "max_visit_minutes": ("integer", True, None),
        "allowed_species": ("array", True, None),
        "min_liability_coverage_cents": ("integer", True, None),
        "max_overlapping_teams": ("integer", True, None),
        "visits_per_week_cap": ("integer", True, None),
        "required_waiver_version": ("string", False, None),
    })
    _validate_allowed_species(body["allowed_species"])
    for f in ("max_visit_minutes", "min_liability_coverage_cents",
              "max_overlapping_teams", "visits_per_week_cap"):
        _validate_positive_int(f, body[f])
    rec = new_record(store.facilities, {
        "name": body["name"],
        "facility_type": body["facility_type"],
        "region_code": body["region_code"],
        "address": body.get("address"),
        "max_visit_minutes": body["max_visit_minutes"],
        "allowed_species": body["allowed_species"],
        "min_liability_coverage_cents": body["min_liability_coverage_cents"],
        "max_overlapping_teams": body["max_overlapping_teams"],
        "visits_per_week_cap": body["visits_per_week_cap"],
        "required_waiver_version": body.get("required_waiver_version", "v1"),
        "status": "PROSPECT",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/facilities/<facility_id>")
def get_facility(facility_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_facility(facility_id)), 200)


@bp.get("/v1/facilities")
def list_facilities():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.facilities.values())
    status = request.args.get("status")
    facility_type = request.args.get("facility_type")
    region_code = request.args.get("region_code")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if facility_type is not None:
        records = [r for r in records if r["facility_type"] == facility_type]
    if region_code is not None:
        records = [r for r in records if r["region_code"] == region_code]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.patch("/v1/facilities/<facility_id>")
def patch_facility(facility_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    f = _get_facility(facility_id)
    body = validate_body(get_body(), {
        "name": ("string", False, None),
        "max_visit_minutes": ("integer", False, None),
        "allowed_species": ("array", False, None),
        "min_liability_coverage_cents": ("integer", False, None),
        "max_overlapping_teams": ("integer", False, None),
        "visits_per_week_cap": ("integer", False, None),
        "required_waiver_version": ("string", False, None),
    }, partial=True)
    changed = False
    if "allowed_species" in body:
        body["allowed_species"] = _validate_allowed_species(body["allowed_species"])
    for f_ in ("max_visit_minutes", "min_liability_coverage_cents",
               "max_overlapping_teams", "visits_per_week_cap"):
        if f_ in body:
            _validate_positive_int(f_, body[f_])
    for key, val in body.items():
        if f.get(key) != val:
            f[key] = val
            changed = True
    if changed:
        touch(f)
    return success_object(public(f), 200)


@bp.post("/v1/facilities/<facility_id>/suspend")
def suspend_facility(facility_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    f = _get_facility(facility_id)
    validate_body(get_body(), {"reason": ("string", True, None)})
    if f["status"] != "ACTIVE":
        raise err("ERR_FACILITY_NOT_ACTIVE", 409, "Facility is not ACTIVE")
    # Manual suspension: existing SCHEDULED visits are kept.
    f["status"] = "SUSPENDED"
    touch(f)
    return success_object(public(f), 200)


@bp.post("/v1/facilities/<facility_id>/reinstate")
def reinstate_facility(facility_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    f = _get_facility(facility_id)
    if f["status"] != "SUSPENDED":
        raise err("ERR_FACILITY_NOT_SUSPENDED", 409, "Facility is not SUSPENDED")
    has_active = any(
        a["facility_id"] == f["id"] and a["status"] == "ACTIVE"
        for a in store.agreements.values()
    )
    if not has_active:
        raise err("ERR_NO_ACTIVE_AGREEMENT", 409,
                  "No ACTIVE agreement exists for this facility")
    f["status"] = "ACTIVE"
    touch(f)
    return success_object(public(f), 200)


@bp.post("/v1/facilities/<facility_id>/terminate")
def terminate_facility(facility_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    f = _get_facility(facility_id)
    body = validate_body(get_body(), {"reason": ("string", True, None)})
    if f["status"] not in ("ACTIVE", "SUSPENDED", "ONBOARDING", "PROSPECT"):
        raise err("ERR_FACILITY_ALREADY_TERMINAL", 409, "Facility is already TERMINATED")
    was_live = f["status"] in ("ACTIVE", "SUSPENDED")
    f["status"] = "TERMINATED"
    touch(f)
    if was_live:
        # Agreement in ACTIVE -> TERMINATED plus the agreement-loss cascade.
        for ag in list(store.agreements.values()):
            if ag["facility_id"] == f["id"] and ag["status"] == "ACTIVE":
                ag["status"] = "TERMINATED"
                ag["terminated_reason"] = body["reason"]
                touch(ag)
        cascades.cancel_scheduled_visits_of_facility(f["id"], "AGREEMENT_ENDED")
        for req in list(store.visit_requests.values()):
            if req["facility_id"] == f["id"] and req["status"] in ("OPEN", "OFFERED"):
                req["status"] = "WITHDRAWN"
                touch(req)
    return success_object(public(f), 200)


@bp.get("/v1/facilities/<facility_id>/demand-summary")
def demand_summary(facility_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    f = _get_facility(facility_id)
    today_d = today()
    window_start = today_d - timedelta(days=90)
    open_count = 0
    expired_90 = 0
    fulfilled_90 = 0
    for req in store.visit_requests.values():
        if req["facility_id"] != f["id"]:
            continue
        if req["status"] in ("OPEN", "OFFERED"):
            open_count += 1
        elif req["status"] == "EXPIRED" and req.get("expired_on"):
            if parse_date(req["expired_on"]) >= window_start:
                expired_90 += 1
        elif req["status"] == "FULFILLED" and req.get("fulfilled_on"):
            if parse_date(req["fulfilled_on"]) >= window_start:
                fulfilled_90 += 1
    return success_object({
        "facility_id": f["id"],
        "open_request_count": open_count,
        "expired_last_90d": expired_90,
        "fulfilled_last_90d": fulfilled_90,
        "unmet_demand_index": open_count + expired_90,
    }, 200)
