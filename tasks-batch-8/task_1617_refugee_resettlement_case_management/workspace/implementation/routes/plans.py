"""EmploymentPlan endpoints (OCC-guarded create, patch, certify)."""

from flask import Blueprint

from db import store, clock_date, new_id, stamp_new, touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_CASE_TRANSFER_PENDING,
)
from helpers import body_dict, req_string, req_int, opt_int, opt_date, req_enum
from middleware import authenticate, authorize, EMPLOYMENT_SPECIALIST
from response import success_object, success_list
from serializers import ser_plan
from services import plans_of_case, sorted_records, determine_self_sufficient
from routes.cases import get_case_or_404

bp = Blueprint("plans", __name__)

VARIANTS = {"MONTHLY", "ANNUALIZED"}


def get_plan_or_404(plan_id):
    plan = store.employment_plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Employment plan not found.")
    return plan


@bp.post("/employment-plans")
def create_plan():
    _uid, role = authenticate()
    authorize(role, {EMPLOYMENT_SPECIALIST})
    d = body_dict()
    # Priority 3: body FK existence
    case_id = req_string(d, "case_id")
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError(ERR_NOT_FOUND, 404, "case_id does not identify an existing case.")
    # Priority 4: schema — expected_case_version is a non-optional integer
    expected = req_int(d, "expected_case_version")
    # Priority 5: optimistic concurrency on Case.version
    if expected != case["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_case_version does not match the case's current version.",
        )
    # Priority 6: state — the case must be ARRIVED
    if case["status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be ARRIVED to create an employment plan.")
    # Priority 9: transfer freeze
    if case["open_transfer_id"] is not None:
        raise ApiError(ERR_CASE_TRANSFER_PENDING, 409, "Case has an open transfer.")
    # Supersede any existing ACTIVE plan of the case.
    for p in plans_of_case(case["id"]):
        if p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            touch(p)
    plan = {
        "id": new_id(),
        "case_id": case["id"],
        "monthly_income_cents": 0,
        "trailing_3m_income_cents": 0,
        "job_start_date": None,
        "employed_members_count": 0,
        "status": "ACTIVE",
        "self_sufficient": None,
        "determination_variant": None,
        "certified_on": None,
    }
    stamp_new(plan)
    store.employment_plans[plan["id"]] = plan
    # Plan creation mutates the case: version += 1.
    touch(case)
    return success_object(ser_plan(plan), 201)


@bp.get("/cases/<case_id>/employment-plans")
def list_plans_of_case(case_id):
    authenticate()
    case = get_case_or_404(case_id)
    return success_list(sorted_records(plans_of_case(case["id"])), ser_plan)


@bp.patch("/employment-plans/<plan_id>")
def patch_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, {EMPLOYMENT_SPECIALIST})
    plan = get_plan_or_404(plan_id)
    d = body_dict()
    # Priority 4: schema on provided fields
    monthly = opt_int(d, "monthly_income_cents", minimum=0)
    trailing = opt_int(d, "trailing_3m_income_cents", minimum=0)
    employed = opt_int(d, "employed_members_count", minimum=0)
    job_start = opt_date(d, "job_start_date")  # explicit null allowed
    job_start_provided = "job_start_date" in d
    # Priority 6: state — only ACTIVE plans may be patched
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE plan can be updated.")
    if monthly is not None:
        plan["monthly_income_cents"] = monthly
    if trailing is not None:
        plan["trailing_3m_income_cents"] = trailing
    if employed is not None:
        plan["employed_members_count"] = employed
    if job_start_provided:
        plan["job_start_date"] = job_start
    touch(plan)
    return success_object(ser_plan(plan), 200)


@bp.post("/employment-plans/<plan_id>/certify")
def certify_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, {EMPLOYMENT_SPECIALIST})
    plan = get_plan_or_404(plan_id)
    d = body_dict()
    # Priority 4: schema
    variant = req_enum(d, "variant", VARIANTS)
    # Priority 6: state — only ACTIVE plans can be certified
    if plan["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE plan can be certified.")
    case = store.cases[plan["case_id"]]
    passed = determine_self_sufficient(plan, case["household_size"], variant)
    plan["self_sufficient"] = passed
    plan["determination_variant"] = variant
    if passed:
        plan["status"] = "CERTIFIED"
        plan["certified_on"] = clock_date()
    touch(plan)
    return success_object(ser_plan(plan), 200)
