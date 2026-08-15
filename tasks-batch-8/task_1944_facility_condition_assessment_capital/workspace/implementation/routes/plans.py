"""CapitalPlan lifecycle, FundingScenario configuration and waterfall run,
PlanLineItem reads, and ProjectBundle grouping."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_BUDGET,
    ERR_INVALID_STATE,
    ERR_PRECONDITION_UNMET,
    ERR_REFERENCE_NOT_FOUND,
    ERR_REFERENTIAL_CONFLICT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    raise_error,
)
from middleware import auth
from response import ok_object
from services.core import (
    escalated_cost,
    get_or_404,
    list_response,
    new_record,
    pub,
    recompute_bundle,
    recompute_facility,
    recompute_plan_total,
    touch,
)
from util import body, is_int, v_int, v_num, v_str

bp = Blueprint("plans", __name__)


# ---------------------------------------------------------------------------
# CapitalPlan
# ---------------------------------------------------------------------------

@bp.post("/fca/capital-plans")
def create_capital_plan():
    auth("CapitalPlanner")
    data = body()
    # Priority 4: body FK existence
    facility_id = data.get("facility_id")
    if facility_id is not None and facility_id not in db.facilities:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"facility_id does not reference an existing facility: {facility_id}",
        )
    # Priority 6: OCC — expected_facility_version must match the facility's
    # current version (the field is mandatory on this endpoint)
    if facility_id is not None:
        fac = db.facilities[facility_id]
        expected = data.get("expected_facility_version")
        if not is_int(expected) or expected != fac["version"]:
            raise_error(
                ERR_STALE_VERSION,
                "expected_facility_version does not match the facility's current version",
            )
    # Priority 10: field shape
    title = v_str(data, "title")
    start_year = v_int(data, "start_year", minimum=2000, maximum=2200)
    horizon_years = v_int(data, "horizon_years", minimum=1, maximum=10)
    facility_id = v_str(data, "facility_id")
    fac = db.facilities[facility_id]
    rec = new_record()
    rec.update(
        {
            "facility_id": facility_id,
            "title": title,
            "start_year": start_year,
            "horizon_years": horizon_years,
            "status": "DRAFT",
            "total_programmed_cents": 0,
            "_submitted_by": None,
        }
    )
    db.capital_plans[rec["id"]] = rec
    # Plan creation mutates the facility aggregate.
    touch(fac)
    return ok_object(pub(rec), 201)


@bp.get("/fca/capital-plans")
def list_capital_plans():
    auth()
    records = list(db.capital_plans.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/fca/capital-plans/<plan_id>")
def get_capital_plan(plan_id):
    auth()
    return ok_object(pub(get_or_404(db.capital_plans, plan_id, "CapitalPlan")))


def _funded_items(plan_id):
    return [
        i
        for i in db.plan_line_items.values()
        if i["capital_plan_id"] == plan_id and i["funding_status"] == "FUNDED"
    ]


@bp.post("/fca/capital-plans/<plan_id>/submit")
def submit_capital_plan(plan_id):
    user_id, _ = auth("CapitalPlanner")
    plan = get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    # Priority 5: state legality
    if plan["status"] != "DRAFT":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit submit",
        )
    # Priority 13: submission requires a non-empty funded program
    if not _funded_items(plan_id):
        raise_error(
            ERR_PRECONDITION_UNMET,
            "Submission requires at least one FUNDED plan line item",
        )
    plan["status"] = "SUBMITTED"
    plan["_submitted_by"] = user_id
    touch(plan)
    # Portfolio side effect: a prior APPROVED plan for the same facility is
    # superseded.
    for other in db.capital_plans.values():
        if (
            other["id"] != plan_id
            and other["facility_id"] == plan["facility_id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    return ok_object(pub(plan))


@bp.post("/fca/capital-plans/<plan_id>/approve")
def approve_capital_plan(plan_id):
    user_id, _ = auth("Approver")
    plan = get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    # Priority 5: state legality
    if plan["status"] != "SUBMITTED":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit approve",
        )
    # Priority 7: segregation of duties — approver must differ from the
    # recorded submitter identity
    if plan.get("_submitted_by") is not None and user_id == plan["_submitted_by"]:
        raise_error(
            ERR_SEGREGATION_OF_DUTIES,
            "Approver must not be the operator who submitted the plan",
        )
    plan["status"] = "APPROVED"
    touch(plan)
    # Funded work enters IN_PROGRESS: OPEN advances; DEFERRED and
    # IN_PROGRESS are left exactly as they are.
    for item in _funded_items(plan_id):
        d = db.deficiencies.get(item["deficiency_id"])
        if d is not None and d["remediation_status"] == "OPEN":
            d["remediation_status"] = "IN_PROGRESS"
            touch(d)
    recompute_facility(db.facilities[plan["facility_id"]])
    return ok_object(pub(plan))


@bp.post("/fca/capital-plans/<plan_id>/reject")
def reject_capital_plan(plan_id):
    auth("Approver")
    plan = get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    if plan["status"] != "SUBMITTED":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit reject",
        )
    plan["status"] = "REJECTED"
    touch(plan)
    return ok_object(pub(plan))


@bp.post("/fca/capital-plans/<plan_id>/revise")
def revise_capital_plan(plan_id):
    auth("CapitalPlanner")
    plan = get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    if plan["status"] != "REJECTED":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit revise",
        )
    plan["status"] = "DRAFT"
    touch(plan)
    return ok_object(pub(plan))


@bp.post("/fca/capital-plans/<plan_id>/archive")
def archive_capital_plan(plan_id):
    auth("CapitalPlanner")
    plan = get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    if plan["status"] != "APPROVED":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit archive",
        )
    # Priority 13: every funded finding must be closed out
    for item in _funded_items(plan_id):
        d = db.deficiencies.get(item["deficiency_id"])
        if d is not None and d["remediation_status"] not in ("CORRECTED", "DEFERRED"):
            raise_error(
                ERR_PRECONDITION_UNMET,
                "Archive requires every funded deficiency to be CORRECTED or DEFERRED",
            )
    plan["status"] = "ARCHIVED"
    touch(plan)
    return ok_object(pub(plan))


@bp.get("/fca/capital-plans/<plan_id>/funding-scenarios")
def list_plan_scenarios(plan_id):
    auth()
    get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    records = [
        s for s in db.funding_scenarios.values() if s["capital_plan_id"] == plan_id
    ]
    return list_response(records)


@bp.get("/fca/capital-plans/<plan_id>/plan-line-items")
def list_plan_line_items(plan_id):
    auth()
    get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    records = [
        i for i in db.plan_line_items.values() if i["capital_plan_id"] == plan_id
    ]
    funding_status = request.args.get("funding_status")
    if funding_status is not None:
        records = [r for r in records if r["funding_status"] == funding_status]
    return list_response(records)


@bp.get("/fca/capital-plans/<plan_id>/project-bundles")
def list_plan_bundles(plan_id):
    auth()
    get_or_404(db.capital_plans, plan_id, "CapitalPlan")
    records = [
        b for b in db.project_bundles.values() if b["capital_plan_id"] == plan_id
    ]
    return list_response(records)


# ---------------------------------------------------------------------------
# FundingScenario
# ---------------------------------------------------------------------------

@bp.post("/fca/funding-scenarios")
def create_funding_scenario():
    auth("CapitalPlanner")
    data = body()
    # Priority 4: body FK existence
    capital_plan_id = data.get("capital_plan_id")
    if capital_plan_id is not None and capital_plan_id not in db.capital_plans:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"capital_plan_id does not reference an existing capital plan: {capital_plan_id}",
        )
    # Priority 5: scenarios are configured under a draft plan
    if capital_plan_id is not None:
        plan = db.capital_plans[capital_plan_id]
        if plan["status"] != "DRAFT":
            raise_error(
                ERR_INVALID_STATE,
                f"CapitalPlan status {plan['status']} does not permit scenario creation",
            )
    # Priority 10: field shape (types and presence)
    name = v_str(data, "name")
    annual_budget_cents = v_int(data, "annual_budget_cents")
    escalation_rate = v_num(data, "escalation_rate")
    capital_plan_id = v_str(data, "capital_plan_id")
    # Priority 14: fiscal shape
    if annual_budget_cents <= 0:
        raise_error(ERR_INVALID_BUDGET, "annual_budget_cents must be > 0")
    if not (0 <= escalation_rate <= 0.25):
        raise_error(
            ERR_INVALID_BUDGET, "escalation_rate must lie between 0 and 0.25"
        )
    rec = new_record()
    rec.update(
        {
            "capital_plan_id": capital_plan_id,
            "name": name,
            "annual_budget_cents": annual_budget_cents,
            "escalation_rate": escalation_rate,
            "status": "CONFIGURED",
        }
    )
    db.funding_scenarios[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/fca/funding-scenarios/<scenario_id>")
def get_funding_scenario(scenario_id):
    auth()
    return ok_object(
        pub(get_or_404(db.funding_scenarios, scenario_id, "FundingScenario"))
    )


@bp.post("/fca/funding-scenarios/<scenario_id>/run")
def run_funding_scenario(scenario_id):
    auth("CapitalPlanner")
    scenario = get_or_404(db.funding_scenarios, scenario_id, "FundingScenario")
    plan = db.capital_plans[scenario["capital_plan_id"]]
    # Priority 5: state legality — scenario CONFIGURED, plan DRAFT
    if scenario["status"] != "CONFIGURED":
        raise_error(
            ERR_INVALID_STATE,
            f"FundingScenario status {scenario['status']} does not permit run",
        )
    if plan["status"] != "DRAFT":
        raise_error(
            ERR_INVALID_STATE,
            f"CapitalPlan status {plan['status']} does not permit scenario run",
        )
    # Priority 6: OCC — expected_capital_plan_version must match (mandatory)
    data = body()
    expected = data.get("expected_capital_plan_version")
    if not is_int(expected) or expected != plan["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_capital_plan_version does not match the capital plan's current version",
        )
    # Supersession cascade: any other RUN scenario of this plan moves to
    # SUPERSEDED and its non-REMOVED line items move to REMOVED.
    affected_bundles = set()
    for other in db.funding_scenarios.values():
        if (
            other["capital_plan_id"] == plan["id"]
            and other["id"] != scenario_id
            and other["status"] == "RUN"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
            for item in db.plan_line_items.values():
                if (
                    item["funding_scenario_id"] == other["id"]
                    and item["funding_status"] != "REMOVED"
                ):
                    item["funding_status"] = "REMOVED"
                    touch(item)
                    if item.get("project_bundle_id"):
                        affected_bundles.add(item["project_bundle_id"])
    for bundle_id in affected_bundles:
        recompute_bundle(db.project_bundles[bundle_id])
    # Waterfall allocation
    facility_id = plan["facility_id"]
    start_year = plan["start_year"]
    final_year = start_year + plan["horizon_years"] - 1
    candidates = []
    for d in db.deficiencies.values():
        system = db.asset_systems.get(d["asset_system_id"])
        if system is None or system["facility_id"] != facility_id:
            continue
        if system["status"] == "RETIRED":
            continue
        if d["remediation_status"] not in ("OPEN", "DEFERRED"):
            continue
        if not (start_year <= d["recommended_year"] <= final_year):
            continue
        candidates.append(d)
    # Deterministic order: priority_score DESC, created_at ASC.
    candidates.sort(key=lambda d: (-d["priority_score"], d["created_at"]))
    by_year = {}
    for d in candidates:
        by_year.setdefault(d["recommended_year"], []).append(d)
    for plan_year in range(start_year, final_year + 1):
        budget_remaining = scenario["annual_budget_cents"]
        for d in by_year.get(plan_year, []):
            cost = escalated_cost(
                d["cost_estimate_cents"], scenario["escalation_rate"], plan_year
            )
            if cost <= budget_remaining:
                funding_status = "FUNDED"
                budget_remaining -= cost
            else:
                funding_status = "UNFUNDED"
            item = new_record()
            item.update(
                {
                    "capital_plan_id": plan["id"],
                    "deficiency_id": d["id"],
                    "funding_scenario_id": scenario_id,
                    "planned_year": plan_year,
                    "escalated_cost_cents": cost,
                    "funding_status": funding_status,
                    "project_bundle_id": None,
                }
            )
            db.plan_line_items[item["id"]] = item
    recompute_plan_total(plan)
    scenario["status"] = "RUN"
    touch(scenario)
    return ok_object(pub(scenario))


# ---------------------------------------------------------------------------
# PlanLineItem (read-only)
# ---------------------------------------------------------------------------

@bp.get("/fca/plan-line-items")
def list_line_items():
    auth()
    records = list(db.plan_line_items.values())
    for param in (
        "capital_plan_id",
        "funding_scenario_id",
        "deficiency_id",
        "funding_status",
        "project_bundle_id",
    ):
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r.get(param) == value]
    return list_response(records)


@bp.get("/fca/plan-line-items/<item_id>")
def get_line_item(item_id):
    auth()
    return ok_object(pub(get_or_404(db.plan_line_items, item_id, "PlanLineItem")))


# ---------------------------------------------------------------------------
# ProjectBundle
# ---------------------------------------------------------------------------

@bp.post("/fca/project-bundles")
def create_project_bundle():
    auth("CapitalPlanner")
    data = body()
    # Priority 4: body FK existence
    capital_plan_id = data.get("capital_plan_id")
    if capital_plan_id is not None and capital_plan_id not in db.capital_plans:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"capital_plan_id does not reference an existing capital plan: {capital_plan_id}",
        )
    # Priority 10: field shape
    name = v_str(data, "name")
    phase_number = v_int(data, "phase_number", minimum=1)
    capital_plan_id = v_str(data, "capital_plan_id")
    rec = new_record()
    rec.update(
        {
            "capital_plan_id": capital_plan_id,
            "name": name,
            "phase_number": phase_number,
            "bundled_cost_cents": 0,
        }
    )
    db.project_bundles[rec["id"]] = rec
    return ok_object(pub(rec), 201)


@bp.get("/fca/project-bundles/<bundle_id>")
def get_project_bundle(bundle_id):
    auth()
    return ok_object(pub(get_or_404(db.project_bundles, bundle_id, "ProjectBundle")))


@bp.post("/fca/project-bundles/<bundle_id>/attach")
def attach_line_item(bundle_id):
    auth("CapitalPlanner")
    bundle = get_or_404(db.project_bundles, bundle_id, "ProjectBundle")
    data = body()
    # Priority 4: body FK existence
    plan_line_item_id = data.get("plan_line_item_id")
    if plan_line_item_id is not None and plan_line_item_id not in db.plan_line_items:
        raise_error(
            ERR_REFERENCE_NOT_FOUND,
            f"plan_line_item_id does not reference an existing plan line item: {plan_line_item_id}",
        )
    # Priority 5: no bundles may attach to a SUPERSEDED plan
    plan = db.capital_plans[bundle["capital_plan_id"]]
    if plan["status"] == "SUPERSEDED":
        raise_error(
            ERR_INVALID_STATE,
            "No further bundles may attach to a SUPERSEDED plan",
        )
    # Priority 10: field shape
    plan_line_item_id = v_str(data, "plan_line_item_id")
    item = db.plan_line_items[plan_line_item_id]
    # Priority 12: the attached item must belong to the same capital plan
    if item["capital_plan_id"] != bundle["capital_plan_id"]:
        raise_error(
            ERR_REFERENTIAL_CONFLICT,
            "Plan line item belongs to a different capital plan than the bundle",
        )
    old_bundle_id = item.get("project_bundle_id")
    item["project_bundle_id"] = bundle_id
    touch(item)
    if old_bundle_id and old_bundle_id != bundle_id and old_bundle_id in db.project_bundles:
        recompute_bundle(db.project_bundles[old_bundle_id])
    recompute_bundle(bundle)
    return ok_object(pub(bundle))
