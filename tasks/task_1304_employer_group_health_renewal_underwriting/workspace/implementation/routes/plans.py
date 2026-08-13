"""Benefit plan design endpoints (PRD 3.4)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError, not_found,
    ERR_PLAN_NOT_DRAFT, ERR_PLAN_HAS_ACTIVE_QUOTES,
    ERR_CASE_NOT_READY_FOR_MODELING, ERR_INVALID_STATE_TRANSITION,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import plan_json
from services import calcs
from validators import body, req_str, req_int, req_num, req_enum, opt_bool

bp = Blueprint("plans", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]
STRATEGIES = ["FLAT_DOLLAR", "PERCENTAGE", "TIERED"]
# "CENSUS_RECEIVED or any later state" in the case lifecycle
MODELABLE_CASE_STATES = [
    "CENSUS_RECEIVED", "CLAIMS_PENDING", "RATING_IN_PROGRESS",
    "QUOTED", "NEGOTIATING", "APPROVED",
]


def get_plan_or_404(plan_id):
    plan = store.plans.get(plan_id)
    if plan is None:
        raise not_found("Plan design does not exist")
    return plan


@bp.post("/underwriting-cases/<caseId>/plan-designs")
def create_plan(caseId):
    auth(["Underwriter"])
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    data = body()
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "plan_name": req_str(data, "plan_name"),
        "deductible_individual": req_int(data, "deductible_individual"),
        "deductible_family": req_int(data, "deductible_family"),
        "oop_max_individual": req_int(data, "oop_max_individual"),
        "oop_max_family": req_int(data, "oop_max_family"),
        "coinsurance_pct": req_num(data, "coinsurance_pct"),
        "copay_primary": req_int(data, "copay_primary"),
        "copay_specialist": req_int(data, "copay_specialist"),
        "actuarial_value": None,
        "relativity_factor": None,
        "employer_contribution_pct": req_num(data, "employer_contribution_pct"),
        "contribution_strategy": req_enum(data, "contribution_strategy", STRATEGIES),
        "is_reference_plan": opt_bool(data, "is_reference_plan", False),
        "status": "DRAFT",
    })
    store.plans[rec["id"]] = rec
    return created(plan_json(rec))


@bp.get("/underwriting-cases/<caseId>/plan-designs")
def list_plans(caseId):
    auth(READ_ROLES)
    if caseId not in store.cases:
        raise not_found("Underwriting case does not exist")
    items = [p for p in store.plans.values() if p["case_id"] == caseId]
    return paginated([plan_json(p) for p in sorted_items(items)])


@bp.get("/plan-designs/<planId>")
def get_plan(planId):
    auth(READ_ROLES)
    return ok(plan_json(get_plan_or_404(planId)))


@bp.post("/plan-designs/<planId>/model")
def model_plan(planId):
    auth(["Underwriter"])
    plan = get_plan_or_404(planId)
    case = store.cases.get(plan["case_id"])
    if case is None:
        raise not_found("Underwriting case does not exist")
    if case["status"] not in MODELABLE_CASE_STATES:
        raise ApiError(ERR_CASE_NOT_READY_FOR_MODELING,
                       "Case must be in CENSUS_RECEIVED or later for plan modeling", 409)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_PLAN_NOT_DRAFT,
                       "Plan design must be in DRAFT status to model", 409)
    plan["actuarial_value"] = calcs.actuarial_value(
        plan["deductible_individual"], plan["coinsurance_pct"],
        plan["oop_max_individual"], plan["copay_primary"], plan["copay_specialist"],
    )
    # Relativity vs. the case's reference plan (PRD 3.4)
    ref_av = None
    if not plan["is_reference_plan"]:
        refs = [p for p in store.plans.values()
                if p["case_id"] == plan["case_id"] and p["id"] != plan["id"]
                and p["is_reference_plan"]]
        # Prefer a modeled reference plan (its AV has been computed)
        refs.sort(key=lambda p: (p["actuarial_value"] is None, p["_seq"]))
        for ref in refs:
            if ref.get("actuarial_value") is not None:
                ref_av = ref["actuarial_value"]
                break
    plan["relativity_factor"] = calcs.relativity_factor(
        plan["is_reference_plan"], plan["actuarial_value"], ref_av
    )
    plan["status"] = "MODELED"
    touch(plan)
    return ok(plan_json(plan))


@bp.post("/plan-designs/<planId>/reject")
def reject_plan(planId):
    auth(["Underwriter"])
    plan = get_plan_or_404(planId)
    if plan["status"] == "MODELED":
        live = [q for q in store.quotes.values()
                if q["plan_design_id"] == plan["id"]
                and q["status"] in ("PROPOSED", "COUNTERED")]
        if live:
            raise ApiError(ERR_PLAN_HAS_ACTIVE_QUOTES,
                           "Cannot reject plan with active (PROPOSED/COUNTERED) quotes", 409)
    elif plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "The requested state transition is not valid from the current state", 409)
    plan["status"] = "REJECTED"
    touch(plan)
    return ok(plan_json(plan))
