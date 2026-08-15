"""AssumptionSet endpoints including the review/revision loop."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination, list_page
from errors import (
    invalid_state, plan_terminated, validation, ApiError,
    ERR_PLAN_YEAR_MISMATCH, ERR_ASSUMPTION_MISMATCH, ERR_ASSUMPTION_YEAR_CONFLICT,
    ERR_UNIQUENESS_VIOLATION, ERR_SEGREGATION_OF_DUTIES, ERR_ACTUARY_NOT_ENROLLED,
)
from validate import body_of, req_str, req_int, req_num
from services.core import base_record, touch, public, get_plan, get_aset

bp = Blueprint("assumptions", __name__)

READ_ROLES = ["PlanAdmin", "Actuary", "SeniorActuary", "Auditor"]
ACTUARY_ROLES = ["Actuary", "SeniorActuary"]


def _plan_active_gate(plan):
    if plan["status"] != "ACTIVE":
        raise plan_terminated()


def _enrollment_gate(user_id):
    """Acting actuary must exist and be ENROLLED (priority 7)."""
    act = store.actuaries.get(user_id)
    if act is None or act.get("enrollment_status") != "ENROLLED":
        raise ApiError(ERR_ACTUARY_NOT_ENROLLED, 422, "Acting actuary is not ENROLLED")


# ---------------------------------------------------------------------------
# AssumptionSet CRUD
# ---------------------------------------------------------------------------

@bp.route("/v1/plans/<plan_id>/assumption-sets", methods=["POST"])
def create_assumption_set(plan_id):
    role, user_id = require_roles(ACTUARY_ROLES)
    plan = get_plan(plan_id)
    _plan_active_gate(plan)
    body = body_of(request)

    # priority 11: plan-year match
    py = body.get("plan_year")
    if isinstance(py, int) and not isinstance(py, bool) and py != plan["plan_year"]:
        raise ApiError(ERR_PLAN_YEAR_MISMATCH, 422, "plan_year differs from the plan's plan_year")

    # priority 12: mortality table + retirement age consistency
    mt = body.get("mortality_table")
    if isinstance(mt, str) and mt != "TEST_TABLE_4AGE":
        raise ApiError(ERR_ASSUMPTION_MISMATCH, 422, "mortality_table must be TEST_TABLE_4AGE")
    ra = body.get("retirement_age")
    if isinstance(ra, int) and not isinstance(ra, bool) and ra != plan["normal_retirement_age"]:
        raise ApiError(ERR_ASSUMPTION_MISMATCH, 422, "retirement_age must equal the plan's normal_retirement_age")

    # priority 22: body well-formedness
    plan_year = req_int(body, "plan_year")
    label = req_str(body, "label")
    mortality_table = req_str(body, "mortality_table")
    if mortality_table != "TEST_TABLE_4AGE":
        raise ApiError(ERR_ASSUMPTION_MISMATCH, 422, "mortality_table must be TEST_TABLE_4AGE")
    funding_discount_rate = req_num(body, "funding_discount_rate")
    if not (0 < funding_discount_rate <= 0.20):
        raise validation("funding_discount_rate must be in (0, 0.20]")
    disclosure_discount_rate = req_num(body, "disclosure_discount_rate")
    if not (0 < disclosure_discount_rate <= 0.20):
        raise validation("disclosure_discount_rate must be in (0, 0.20]")
    retirement_age = req_int(body, "retirement_age")
    if retirement_age != plan["normal_retirement_age"]:
        raise ApiError(ERR_ASSUMPTION_MISMATCH, 422, "retirement_age must equal the plan's normal_retirement_age")

    rec = base_record()
    rec.update({
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "label": label,
        "mortality_table": mortality_table,
        "funding_discount_rate": funding_discount_rate,
        "disclosure_discount_rate": disclosure_discount_rate,
        "retirement_age": retirement_age,
        "prepared_by_actuary_id": user_id,
        "approved_by_actuary_id": None,
        "status": "DRAFT",
    })
    store.assumption_sets[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/v1/plans/<plan_id>/assumption-sets", methods=["GET"])
def list_assumption_sets(plan_id):
    require_roles(READ_ROLES)
    plan = get_plan(plan_id)
    limit, offset = parse_pagination(request.args)
    items = [s for s in store.assumption_sets.values() if s["plan_id"] == plan["id"]]
    page, total = list_page(items, limit, offset)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/v1/assumption-sets/<set_id>", methods=["GET"])
def fetch_assumption_set(set_id):
    require_roles(READ_ROLES)
    rec = get_aset(set_id)
    return success_object(public(rec))


def _set_plan_gate(aset):
    plan = store.plans.get(aset["plan_id"])
    if plan is not None and plan["status"] != "ACTIVE":
        raise plan_terminated()
    return plan


@bp.route("/v1/assumption-sets/<set_id>/submit", methods=["POST"])
def submit_assumption_set(set_id):
    require_roles(ACTUARY_ROLES)
    aset = get_aset(set_id)
    if aset["status"] != "DRAFT":
        raise invalid_state("AssumptionSet is not DRAFT")
    _set_plan_gate(aset)
    aset["status"] = "IN_REVIEW"
    touch(aset)
    return success_object(public(aset))


@bp.route("/v1/assumption-sets/<set_id>/approve", methods=["POST"])
def approve_assumption_set(set_id):
    role, user_id = require_roles(["SeniorActuary"])
    aset = get_aset(set_id)
    if aset["status"] != "IN_REVIEW":
        raise invalid_state("AssumptionSet is not IN_REVIEW")
    _set_plan_gate(aset)
    # priority 6: segregation of duties before enrollment (priority 7)
    if user_id == aset["prepared_by_actuary_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422, "Approver must differ from the preparer")
    _enrollment_gate(user_id)
    aset["status"] = "APPROVED"
    aset["approved_by_actuary_id"] = user_id
    touch(aset)
    return success_object(public(aset))


@bp.route("/v1/assumption-sets/<set_id>/reject", methods=["POST"])
def reject_assumption_set(set_id):
    require_roles(["SeniorActuary"])
    aset = get_aset(set_id)
    if aset["status"] != "IN_REVIEW":
        raise invalid_state("AssumptionSet is not IN_REVIEW")
    _set_plan_gate(aset)
    aset["status"] = "DRAFT"
    touch(aset)
    return success_object(public(aset))


@bp.route("/v1/assumption-sets/<set_id>/lock", methods=["POST"])
def lock_assumption_set(set_id):
    role, user_id = require_roles(["SeniorActuary"])
    aset = get_aset(set_id)
    if aset["status"] != "APPROVED":
        raise invalid_state("AssumptionSet is not APPROVED")
    _set_plan_gate(aset)
    # priority 7: enrollment gate applies to lock as well
    _enrollment_gate(user_id)
    # priority 16: one LOCKED set per (plan, plan_year)
    for other in store.assumption_sets.values():
        if (
            other["id"] != aset["id"]
            and other["plan_id"] == aset["plan_id"]
            and other["plan_year"] == aset["plan_year"]
            and other["status"] == "LOCKED"
        ):
            raise ApiError(ERR_ASSUMPTION_YEAR_CONFLICT, 409, "Another assumption set is already LOCKED for this plan_year")
    aset["status"] = "LOCKED"
    touch(aset)
    return success_object(public(aset))


@bp.route("/v1/assumption-sets/<set_id>/reopen", methods=["POST"])
def reopen_assumption_set(set_id):
    require_roles(["SeniorActuary"])
    aset = get_aset(set_id)
    if aset["status"] != "APPROVED":
        raise invalid_state("AssumptionSet is not APPROVED")
    _set_plan_gate(aset)
    # priority 17: forbidden while referenced by a live valuation run
    for run in store.valuation_runs.values():
        if run["assumption_set_id"] == aset["id"] and run["status"] in ("INITIATED", "COMPUTED", "CERTIFIED"):
            raise ApiError(ERR_UNIQUENESS_VIOLATION, 409, "Assumption set is referenced by a live valuation run")
    aset["status"] = "DRAFT"
    aset["approved_by_actuary_id"] = None
    touch(aset)
    return success_object(public(aset))


@bp.route("/v1/assumption-sets/<set_id>/retire", methods=["POST"])
def retire_assumption_set(set_id):
    require_roles(ACTUARY_ROLES)
    aset = get_aset(set_id)
    if aset["status"] != "DRAFT":
        raise invalid_state("AssumptionSet is not DRAFT")
    _set_plan_gate(aset)
    aset["status"] = "RETIRED"
    touch(aset)
    return success_object(public(aset))
