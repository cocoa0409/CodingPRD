"""Reference data endpoints: sites, employees, exposure limits, pumps."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE_LIMIT,
    ERR_DUPLICATE_PUMP_SERIAL,
    ERR_INVALID_REQUEST,
    raise_error,
)
from helpers import (
    reject_unknown,
    get_or_404, body, list_response, opt_int, opt_number, req_int, req_number,
    req_string, stamp_new,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from serializers import employee_out, exposure_limit_out, pump_out, site_out

bp = Blueprint("reference", __name__)

FIRM_ADMIN = ("FirmAdmin",)


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@bp.route("/ih/sites", methods=["POST"])
def create_site():
    require_auth(FIRM_ADMIN)
    data = body()
    reject_unknown(data, {"name", "industry_code", "retention_years"})
    name = req_string(data, "name")
    industry_code = req_string(data, "industry_code")
    retention_years = opt_int(data, "retention_years")
    if retention_years is None:
        retention_years = 30
    if retention_years < 1:
        raise_error(ERR_INVALID_REQUEST, "retention_years must be >= 1")
    site = {
        "name": name,
        "industry_code": industry_code,
        "retention_years": retention_years,
    }
    stamp_new(site)
    db.sites[site["id"]] = site
    return success_object(site_out(site), 201)


@bp.route("/ih/sites", methods=["GET"])
def list_sites():
    require_auth(ALL_ROLES)
    return list_response(list(db.sites.values()), site_out, {})


@bp.route("/ih/sites/<sid>", methods=["GET"])
def get_site(sid):
    require_auth(ALL_ROLES)
    return success_object(site_out(get_or_404(db.sites, sid, "Site")))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@bp.route("/ih/employees", methods=["POST"])
def create_employee():
    require_auth(FIRM_ADMIN)
    data = body()
    reject_unknown(data, {"site_id", "full_name", "external_ref", "job_title"})
    site_id = req_string(data, "site_id")
    full_name = req_string(data, "full_name")
    external_ref = req_string(data, "external_ref")
    job_title = req_string(data, "job_title")
    get_or_404(db.sites, site_id, "Site")
    emp = {
        "site_id": site_id,
        "full_name": full_name,
        "external_ref": external_ref,
        "job_title": job_title,
    }
    stamp_new(emp)
    db.employees[emp["id"]] = emp
    return success_object(employee_out(emp), 201)


@bp.route("/ih/employees", methods=["GET"])
def list_employees():
    require_auth(ALL_ROLES)
    return list_response(list(db.employees.values()), employee_out,
                         {"site_id": request.args.get("site_id")})


@bp.route("/ih/employees/<eid>", methods=["GET"])
def get_employee(eid):
    require_auth(ALL_ROLES)
    return success_object(employee_out(get_or_404(db.employees, eid, "Employee")))


# ---------------------------------------------------------------------------
# Exposure limits
# ---------------------------------------------------------------------------

@bp.route("/ih/exposure-limits", methods=["POST"])
def create_exposure_limit():
    require_auth(FIRM_ADMIN)
    data = body()
    reject_unknown(data, {"analyte_code", "basis", "limit_type", "limit_mg_m3", "action_fraction"})
    analyte_code = req_string(data, "analyte_code")
    basis = req_string(data, "basis")
    if basis not in ("OSHA_PEL", "ACGIH_TLV"):
        raise_error(ERR_INVALID_REQUEST, "basis must be OSHA_PEL or ACGIH_TLV")
    limit_type = req_string(data, "limit_type")
    if limit_type not in ("TWA8", "CEILING"):
        raise_error(ERR_INVALID_REQUEST, "limit_type must be TWA8 or CEILING")
    limit_mg_m3 = req_number(data, "limit_mg_m3")
    if limit_mg_m3 <= 0:
        raise_error(ERR_INVALID_REQUEST, "limit_mg_m3 must be > 0")
    action_fraction = opt_number(data, "action_fraction")
    if action_fraction is None:
        action_fraction = Decimal("0.1")
    if action_fraction <= 0 or action_fraction >= 1:
        raise_error(ERR_INVALID_REQUEST, "action_fraction must be > 0 and < 1")
    for existing in db.exposure_limits.values():
        if (existing["analyte_code"] == analyte_code
                and existing["basis"] == basis
                and existing["limit_type"] == limit_type):
            raise_error(ERR_DUPLICATE_LIMIT,
                        "ExposureLimit with same (analyte_code, basis, limit_type) exists")
    limit = {
        "analyte_code": analyte_code,
        "basis": basis,
        "limit_type": limit_type,
        "limit_mg_m3": limit_mg_m3,
        "action_fraction": action_fraction,
    }
    stamp_new(limit)
    db.exposure_limits[limit["id"]] = limit
    return success_object(exposure_limit_out(limit), 201)


@bp.route("/ih/exposure-limits", methods=["GET"])
def list_exposure_limits():
    require_auth(ALL_ROLES)
    return list_response(list(db.exposure_limits.values()), exposure_limit_out,
                         {"analyte_code": request.args.get("analyte_code")})


@bp.route("/ih/exposure-limits/<lid>", methods=["GET"])
def get_exposure_limit(lid):
    require_auth(ALL_ROLES)
    return success_object(exposure_limit_out(get_or_404(db.exposure_limits, lid, "ExposureLimit")))


# ---------------------------------------------------------------------------
# Pumps
# ---------------------------------------------------------------------------

@bp.route("/ih/pumps", methods=["POST"])
def create_pump():
    require_auth(FIRM_ADMIN)
    data = body()
    reject_unknown(data, {"site_id", "serial_number"})
    site_id = req_string(data, "site_id")
    serial_number = req_string(data, "serial_number")
    get_or_404(db.sites, site_id, "Site")
    for existing in db.pumps.values():
        if existing["site_id"] == site_id and existing["serial_number"] == serial_number:
            raise_error(ERR_DUPLICATE_PUMP_SERIAL,
                        "Pump serial_number already registered at the site")
    pump = {"site_id": site_id, "serial_number": serial_number}
    stamp_new(pump)
    db.pumps[pump["id"]] = pump
    return success_object(pump_out(pump), 201)


@bp.route("/ih/pumps", methods=["GET"])
def list_pumps():
    require_auth(ALL_ROLES)
    return list_response(list(db.pumps.values()), pump_out,
                         {"site_id": request.args.get("site_id")})


@bp.route("/ih/pumps/<pid>", methods=["GET"])
def get_pump(pid):
    require_auth(ALL_ROLES)
    return success_object(pump_out(get_or_404(db.pumps, pid, "Pump")))
