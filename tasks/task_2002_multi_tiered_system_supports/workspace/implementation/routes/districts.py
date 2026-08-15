"""District and School endpoints (incl. flat read/list aliases)."""

from flask import Blueprint

from db import DB
from errors import err, ERR_DISTRICT_NOT_FOUND, ERR_SCHOOL_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, opt_int, base_fields, paginate, sort_created,
)
from response import success_object, success_list
from services import (
    serialize_district, serialize_school, resolve_district, resolve_school,
)

bp = Blueprint("districts", __name__)


# ---------- Districts ----------

@bp.post("/districts")
def create_district():
    require_role("PlatformAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"name", "academic_year", "sped_referral_min_weeks", "fidelity_threshold_pct"})
    require_fields(body, ["name", "academic_year"])
    name = req_string(body, "name")
    academic_year = req_string(body, "academic_year")
    min_weeks = opt_int(body, "sped_referral_min_weeks")
    if min_weeks is None:
        min_weeks = 12
    fidelity_threshold = opt_int(body, "fidelity_threshold_pct")
    if fidelity_threshold is None:
        fidelity_threshold = 80
    d = base_fields()
    d.update({
        "name": name,
        "academic_year": academic_year,
        "sped_referral_min_weeks": min_weeks,
        "fidelity_threshold_pct": fidelity_threshold,
    })
    DB.districts[d["id"]] = d
    return success_object(serialize_district(d), status=201)


@bp.get("/districts")
def list_districts():
    require_role(*ALL_ROLES)
    items = sort_created(DB.districts.values())
    page, limit, offset, total = paginate(items)
    return success_list([serialize_district(d) for d in page], limit, offset, total)


@bp.get("/districts/<districtId>")
def get_district(districtId):
    require_role(*ALL_ROLES)
    d = resolve_district(districtId)
    return success_object(serialize_district(d))


# ---------- Schools ----------

@bp.post("/districts/<districtId>/schools")
def create_school(districtId):
    require_role("PlatformAdmin")
    body = get_json_body()
    check_unknown_fields(body, {"name", "grade_span_low", "grade_span_high"})
    require_fields(body, ["name", "grade_span_low", "grade_span_high"])
    name = req_string(body, "name")
    low = req_int(body, "grade_span_low")
    high = req_int(body, "grade_span_high")
    resolve_district(districtId)
    s = base_fields()
    s.update({
        "district_id": districtId,
        "name": name,
        "grade_span_low": low,
        "grade_span_high": high,
    })
    DB.schools[s["id"]] = s
    return success_object(serialize_school(s), status=201)


@bp.get("/districts/<districtId>/schools")
def list_schools(districtId):
    require_role(*ALL_ROLES)
    resolve_district(districtId)
    items = sort_created(s for s in DB.schools.values() if s["district_id"] == districtId)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_school(s) for s in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>")
def get_school(districtId, schoolId):
    require_role(*ALL_ROLES)
    s = resolve_school(districtId, schoolId)
    return success_object(serialize_school(s))


@bp.get("/schools/<schoolId>")
def get_school_flat(schoolId):
    """Flat read alias for School (PRD §2.4)."""
    require_role(*ALL_ROLES)
    s = DB.schools.get(schoolId)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "schoolId does not exist")
    return success_object(serialize_school(s))
