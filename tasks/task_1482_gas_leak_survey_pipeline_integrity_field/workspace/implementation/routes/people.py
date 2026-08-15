"""Personnel endpoints (PRD §3.3): FieldTechnician, ComplianceOfficer,
CalibrationTech, DispatchCoordinator, IntegrityAnalyst."""
from flask import request

from db import STORE, make_entity, serialize
from errors import bad_request
from middleware import (body, parse_pagination, req_enum, req_list, req_str,
                        require_roles)
from response import list_response, success
from services import FIELDS, get_or_404, sorted_all
from . import bp

SURVEY_METHODS = ["WALKING", "MOBILE", "AERIAL", "PATROL"]
REGULATORS = ["PHMSA", "STATE_PUC", "LOCAL_FIRE_MARSHAL"]


def _check_unique_employee(collection, code):
    if any(e["employee_code"] == code for e in STORE[collection].values()):
        raise bad_request("employee_code must be unique")


def _ser(collection):
    return lambda e: serialize(e, FIELDS[collection])


def _list_personnel(collection):
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = sorted_all(collection)
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(items, _ser(collection), limit, offset)


def _get_personnel(collection, eid):
    return success(serialize(get_or_404(collection, eid), FIELDS[collection]))


# --- FieldTechnician ---------------------------------------------------------
@bp.post("/field-technicians")
@require_roles("IntegrityAnalyst")
def create_field_technician():
    d = body()
    code = req_str(d, "employee_code")
    name = req_str(d, "full_name")
    methods = req_list(d, "qualified_methods")
    for m in methods:
        if m not in SURVEY_METHODS:
            raise bad_request(
                f"qualified_methods entries must be one of {SURVEY_METHODS}")
    region = req_str(d, "home_region")
    _check_unique_employee("field_technicians", code)
    ent = make_entity()
    ent.update({"employee_code": code, "full_name": name,
                "qualified_methods": methods, "home_region": region,
                "status": "ACTIVE"})
    STORE["field_technicians"][ent["id"]] = ent
    return success(serialize(ent, FIELDS["field_technicians"]), code=201)


@bp.get("/field-technicians")
@require_roles("IntegrityAnalyst", "DispatchCoordinator")
def list_field_technicians():
    return _list_personnel("field_technicians")


@bp.get("/field-technicians/<eid>")
@require_roles("IntegrityAnalyst", "DispatchCoordinator")
def get_field_technician(eid):
    return _get_personnel("field_technicians", eid)


# --- ComplianceOfficer ---------------------------------------------------------
@bp.post("/compliance-officers")
@require_roles("IntegrityAnalyst")
def create_compliance_officer():
    d = body()
    code = req_str(d, "employee_code")
    name = req_str(d, "full_name")
    scope = req_list(d, "jurisdiction_scope")
    for r in scope:
        if r not in REGULATORS:
            raise bad_request(
                f"jurisdiction_scope entries must be one of {REGULATORS}")
    _check_unique_employee("compliance_officers", code)
    ent = make_entity()
    ent.update({"employee_code": code, "full_name": name,
                "jurisdiction_scope": scope, "status": "ACTIVE"})
    STORE["compliance_officers"][ent["id"]] = ent
    return success(serialize(ent, FIELDS["compliance_officers"]), code=201)


@bp.get("/compliance-officers")
@require_roles("IntegrityAnalyst")
def list_compliance_officers():
    return _list_personnel("compliance_officers")


@bp.get("/compliance-officers/<eid>")
@require_roles("IntegrityAnalyst")
def get_compliance_officer(eid):
    return _get_personnel("compliance_officers", eid)


# --- simple personnel types -----------------------------------------------------
def _create_simple(collection):
    d = body()
    code = req_str(d, "employee_code")
    name = req_str(d, "full_name")
    _check_unique_employee(collection, code)
    ent = make_entity()
    ent.update({"employee_code": code, "full_name": name, "status": "ACTIVE"})
    STORE[collection][ent["id"]] = ent
    return success(serialize(ent, FIELDS[collection]), code=201)


@bp.post("/calibration-techs")
@require_roles("IntegrityAnalyst")
def create_calibration_tech():
    return _create_simple("calibration_techs")


@bp.get("/calibration-techs")
@require_roles("IntegrityAnalyst")
def list_calibration_techs():
    return _list_personnel("calibration_techs")


@bp.post("/dispatch-coordinators")
@require_roles("IntegrityAnalyst")
def create_dispatch_coordinator():
    return _create_simple("dispatch_coordinators")


@bp.get("/dispatch-coordinators")
@require_roles("IntegrityAnalyst")
def list_dispatch_coordinators():
    return _list_personnel("dispatch_coordinators")


@bp.post("/integrity-analysts")
@require_roles("IntegrityAnalyst")
def create_integrity_analyst():
    return _create_simple("integrity_analysts")


@bp.get("/integrity-analysts")
@require_roles("IntegrityAnalyst")
def list_integrity_analysts():
    return _list_personnel("integrity_analysts")
