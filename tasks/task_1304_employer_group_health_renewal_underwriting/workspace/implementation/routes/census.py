"""Census snapshot endpoints (PRD 3.2)."""
from flask import Blueprint

from db import store, new_record, touch, now_iso
from errors import (
    ApiError, not_found,
    ERR_CENSUS_NOT_PENDING, ERR_CENSUS_COUNT_MISMATCH,
    ERR_EMPTY_ENROLLMENT, ERR_TIER_SUM_MISMATCH,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import census_json
from services.workflow import on_census_validated
from validators import body, req_int, req_dict, opt_num

bp = Blueprint("census", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
TIER_KEYS = ("EE", "ES", "EC", "EF")


def get_census_or_404(census_id):
    census = store.censuses.get(census_id)
    if census is None:
        raise not_found("Census snapshot does not exist")
    return census


@bp.post("/underwriting-cases/<caseId>/census-snapshots")
def create_census(caseId):
    auth(["Underwriter"])
    case = store.cases.get(caseId)
    if case is None:
        raise not_found("Underwriting case does not exist")
    data = body()
    total_employees = req_int(data, "total_employees")
    enrolled_employees = req_int(data, "enrolled_employees")
    dependent_count = req_int(data, "dependent_count")
    tier_distribution = req_dict(data, "tier_distribution")
    # Demographic measures are supplied with the census file contents.
    average_age = opt_num(data, "average_age")
    gender_ratio = opt_num(data, "gender_ratio")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "submitted_at": now_iso(),
        "total_employees": total_employees,
        "enrolled_employees": enrolled_employees,
        "dependent_count": dependent_count,
        "average_age": average_age,
        "gender_ratio": gender_ratio,
        "tier_distribution": tier_distribution,
        "status": "PENDING",
    })
    store.censuses[rec["id"]] = rec
    return created(census_json(rec))


@bp.get("/underwriting-cases/<caseId>/census-snapshots")
def list_census(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [c for c in store.censuses.values() if c["case_id"] == caseId]
    return paginated([census_json(c) for c in sorted_items(items)])


@bp.get("/census-snapshots/<censusId>")
def get_census(censusId):
    auth(READ_ROLES)
    return ok(census_json(get_census_or_404(censusId)))


@bp.post("/census-snapshots/<censusId>/validate")
def validate_census(censusId):
    auth(["Underwriter"])
    census = get_census_or_404(censusId)
    if census["status"] != "PENDING":
        raise ApiError(ERR_CENSUS_NOT_PENDING,
                       "Census snapshot must be in PENDING status", 409)
    case = store.cases.get(census["case_id"])
    if case is None:
        raise not_found("Underwriting case does not exist")
    # PRD 3.2 validation order: count match -> non-empty enrollment -> tier sum
    if census["total_employees"] != case["group_size"]:
        raise ApiError(ERR_CENSUS_COUNT_MISMATCH,
                       "Census total_employees does not match case group_size", 409)
    if census["enrolled_employees"] <= 0:
        raise ApiError(ERR_EMPTY_ENROLLMENT,
                       "Enrolled employees must be greater than zero", 409)
    tier_sum = sum(
        census["tier_distribution"].get(k, 0) for k in TIER_KEYS
        if isinstance(census["tier_distribution"].get(k, 0), int)
    )
    if tier_sum != census["enrolled_employees"]:
        raise ApiError(ERR_TIER_SUM_MISMATCH,
                       "Tier distribution values must sum to enrolled_employees", 409)
    census["status"] = "VALIDATED"
    touch(census)
    on_census_validated(census)
    return ok(census_json(census))


@bp.post("/census-snapshots/<censusId>/reject")
def reject_census(censusId):
    auth(["Underwriter"])
    census = get_census_or_404(censusId)
    if census["status"] != "PENDING":
        raise ApiError(ERR_CENSUS_NOT_PENDING,
                       "Census snapshot must be in PENDING status", 409)
    census["status"] = "REJECTED"
    touch(census)
    return ok(census_json(census))
