"""FundType endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DUPLICATE,
    ERR_PREREQUISITE_MISSING,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, public, touch
from validate import (
    get_body, req_str, req_int, req_enum, req_bool, opt_bool,
    require_path_resource, deferred_body_ref,
)

bp = Blueprint("fund_types", __name__)

DIRECTOR = ["AidDirector"]
DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
CATEGORIES = ("FEDERAL_TITLE_IV", "INSTITUTIONAL", "STATE", "EXTERNAL")


@bp.post("/fund-types")
def create_fund_type():
    authorized(DIRECTOR)
    body = get_body()
    # Rung 4: body foreign key (absent key defers to the rung-9 shape check).
    ay = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 9: shape.
    req_str(body, "aid_year_id")
    fund_code = req_str(body, "fund_code")
    category = req_enum(body, "category", CATEGORIES)
    need_based = req_bool(body, "need_based")
    annual_cap = req_int(body, "annual_cap_cents")
    if annual_cap <= 0:
        raise_error(ERR_INVALID_REQUEST, "annual_cap_cents must be strictly positive")
    pool_budget = req_int(body, "pool_budget_cents")
    if pool_budget < 0:
        raise_error(ERR_INVALID_REQUEST, "pool_budget_cents must be zero or positive")
    packaging_rank = req_int(body, "packaging_rank")
    priority_cohort_only = opt_bool(body, "priority_cohort_only", False)
    requires_verification_complete = opt_bool(body, "requires_verification_complete", True)
    # Rung 11: uniqueness.
    for f in db.fund_types.values():
        if f["aid_year_id"] == ay["id"] and f["fund_code"] == fund_code:
            raise_error(ERR_DUPLICATE,
                        f"fund_code {fund_code} already exists in this aid year")
    for f in db.fund_types.values():
        if f["aid_year_id"] == ay["id"] and f["packaging_rank"] == packaging_rank:
            raise_error(ERR_DUPLICATE,
                        f"packaging_rank {packaging_rank} already exists in this aid year")
    rec = new_record("fund_types", {
        "aid_year_id": ay["id"],
        "fund_code": fund_code,
        "category": category,
        "need_based": need_based,
        "annual_cap_cents": annual_cap,
        "pool_budget_cents": pool_budget,
        "pool_reserved_cents": 0,
        "pool_disbursed_cents": 0,
        "priority_cohort_only": priority_cohort_only,
        "packaging_rank": packaging_rank,
        "requires_verification_complete": requires_verification_complete,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/fund-types")
def list_fund_types():
    authorized(DIRECTOR_OFFICER)
    return list_response("fund_types", {
        "aid_year_id": request.args.get("aid_year_id"),
        "status": request.args.get("status"),
    })


@bp.get("/fund-types/<rid>")
def get_fund_type(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("fund_types", rid)
    return success_object(public(rec))


@bp.post("/fund-types/<rid>/activate")
def activate_fund_type(rid):
    authorized(DIRECTOR)
    fund = require_path_resource("fund_types", rid)
    # Rung 5: state-machine legality.
    if fund["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"fund is {fund['status']}, expected DRAFT")
    # Rung 13: the parent aid year must be DRAFT or OPEN.
    ay = db.aid_years.get(fund["aid_year_id"])
    if ay is None or ay["status"] not in ("DRAFT", "OPEN"):
        raise_error(ERR_PREREQUISITE_MISSING,
                    "fund activation requires the aid year to be DRAFT or OPEN")
    fund["status"] = "ACTIVE"
    touch(fund)
    touch(ay)  # activation increments both the fund's and the aid year's version
    return success_object(public(fund))
