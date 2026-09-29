"""Capital budgets, replacement planning and synthetic disposal (PRD 3.9)."""

from decimal import Decimal as D

import calc
import derive
import errors
import middleware
import response
import validate
from db import bump, by_creation, common_fields, db, new_id, now
from errors import ApiError
from routes.blueprint import bp
from routes.common import listing

PLAN_FILTERS = {
    "field_id": "field_id",
    "capital_budget_id": "capital_budget_id",
    "submitted_by_staff_member_id": "submitted_by_staff_member_id",
    "decided_by_staff_member_id": "decided_by_staff_member_id",
    "funding_status": "funding_status",
    "disposal_status": "disposal_status",
}


# ----------------------------------------------------------------- budgets
@bp.post("/capital-budgets")
def create_budget():
    middleware.authenticate(["FacilitiesDirector"])
    body = validate.Body(required=["fiscal_year", "total_authorized_amount_cents"])
    fiscal_year = body.integer("fiscal_year", 2020, 2040)
    total = body.integer("total_authorized_amount_cents", 1, 99999999999)

    # priority 23 - only one budget may exist per fiscal year
    for other in db.capital_budgets.values():
        if other["fiscal_year"] == fiscal_year:
            raise ApiError("ERR_FISCAL_YEAR_DUPLICATE", 409,
                           "A capital budget already exists for that fiscal year.")

    budget = {
        "id": new_id(),
        "fiscal_year": fiscal_year,
        "total_authorized_amount_cents": total,
        "committed_amount_cents": 0,
        "available_amount_cents": total,
        "lock_threshold_amount_cents": calc.rcents(
            D(total) * calc.BUDGET_LOCK_TRIGGER_RATIO),
        "status": "OPEN",
    }
    budget.update(common_fields())
    db.capital_budgets[budget["id"]] = budget
    derive.recompute_budget(budget)
    return response.created(budget)


@bp.get("/capital-budgets/<budget_id>")
def read_budget(budget_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.budget_or_404(budget_id))


# ----------------------------------------------------------------- plans
def _mandatory_order_count(field):
    """PRD 3.9: MANDATORY orders opened within the 365-day lookback, any status."""
    cutoff = now().minus_days(calc.PRIORITY_LOOKBACK_DAYS)
    return sum(1 for o in derive.field_rows(db.remediation_orders, field["id"])
               if o["severity"] == "MANDATORY"
               and o["opened_at_utc"].dt >= cutoff.dt)


@bp.post("/replacement-plans")
def create_plan():
    middleware.authenticate(["FacilitiesDirector"])
    body = validate.Body(required=["field_id", "capital_budget_id",
                                   "target_surface_type", "area_sq_ft",
                                   "priority_basis", "planned_install_year",
                                   "expected_field_version"])
    field_id = body.string("field_id")
    budget_id = body.string("capital_budget_id")
    target_surface = body.enum("target_surface_type", calc.SURFACE_TYPES)
    area = body.integer("area_sq_ft", 1, 400000)
    basis = body.enum("priority_basis", calc.PRIORITY_BASES)
    install_year = body.integer("planned_install_year", 2026, 2040)
    expected_version = body.integer("expected_field_version")

    field = middleware.body_field(field_id)          # priority 18
    middleware.body_budget(budget_id)                # priority 21

    # priority 33 - optimistic concurrency on Field.version
    if expected_version != field["version"]:
        raise ApiError("ERR_STALE_FIELD_VERSION", 412,
                       "expected_field_version does not match the current "
                       "Field.version.")

    # priority 34 - a retired field takes no new plans
    if field["retired_at"] is not None:
        raise ApiError("ERR_FIELD_RETIRED", 409,
                       "A retired field takes no new replacement plans.")

    derive.recompute_field(field)
    pricing = calc.plan_pricing(area, target_surface, field["surface_type"])
    score = calc.replacement_priority_score(basis, field,
                                            _mandatory_order_count(field))

    plan = {
        "id": new_id(),
        "field_id": field_id,
        "capital_budget_id": budget_id,
        "submitted_by_staff_member_id": None,
        "decided_by_staff_member_id": None,
        "target_surface_type": target_surface,
        "area_sq_ft": area,
        "priority_basis": basis,
        "planned_install_year": install_year,
        "base_construction_cents": pricing["base_construction_cents"],
        "disposal_cents": pricing["disposal_cents"],
        "pre_contingency_subtotal_cents": pricing["pre_contingency_subtotal_cents"],
        "contingency_rate": pricing["contingency_rate"],
        "contingency_cents": pricing["contingency_cents"],
        "plan_funding_amount_cents": pricing["plan_funding_amount_cents"],
        "replacement_priority_score": score,
        "funding_status": "DRAFT",
        "disposal_status": ("PENDING" if field["surface_type"] == "SYNTHETIC_TURF"
                            else "NOT_APPLICABLE"),
        "manifest_reference": None,
        "disposal_facility_name": None,
        "diverted_tonnage": None,
        "total_tonnage": None,
        "diversion_ratio": None,
        "submitted_at_utc": None,
        "decided_at_utc": None,
        "completed_at_utc": None,
        "decision_notes": None,
    }
    plan.update(common_fields())
    db.replacement_plans[plan["id"]] = plan
    derive.touch_field(field)
    return response.created(plan)


@bp.get("/replacement-plans")
def list_plans():
    middleware.authenticate(middleware.ALL_ROLES)
    return listing(db.replacement_plans, PLAN_FILTERS)


@bp.get("/replacement-plans/<plan_id>")
def read_plan(plan_id):
    middleware.authenticate(middleware.ALL_ROLES)
    return response.ok(middleware.plan_or_404(plan_id))


@bp.post("/replacement-plans/<plan_id>/submit")
def submit_plan(plan_id):
    middleware.authenticate(["FacilitiesDirector"])
    plan = middleware.plan_or_404(plan_id)
    body = validate.Body(required=["submitted_by_staff_member_id"])
    submitted_by = body.string("submitted_by_staff_member_id")
    middleware.body_staff(submitted_by)                      # priority 19

    # priority 43 - the plan must be in DRAFT
    if plan["funding_status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_DRAFT", 409,
                       "Only a DRAFT plan may be submitted.")

    # priority 50 - a deferred plan waits for its budget to reopen
    budget = db.capital_budgets[plan["capital_budget_id"]]
    if budget["status"] != "OPEN":
        raise ApiError("ERR_BUDGET_LOCKED", 409, "The capital budget is LOCKED.")

    plan["funding_status"] = "SUBMITTED"
    plan["submitted_by_staff_member_id"] = submitted_by
    plan["submitted_at_utc"] = now()
    bump(plan)
    # PRD 3.9: the disposal axis is untouched by submission.
    return response.ok(plan)


@bp.post("/replacement-plans/<plan_id>/decide")
def decide_plan(plan_id):
    user_id, _role = middleware.authenticate(["FacilitiesDirector"])
    plan = middleware.plan_or_404(plan_id)

    # priority 15 - the decider may never be the submitter
    middleware.deny_self(user_id, plan["submitted_by_staff_member_id"])

    body = validate.Body(required=["decision", "decided_by_staff_member_id"],
                         optional=["decision_notes"])
    decision = body.enum("decision", ["APPROVE", "REJECT", "RESCIND"])
    decided_by = body.string("decided_by_staff_member_id")
    notes = body.string("decision_notes", 1, 2000)
    middleware.body_staff(decided_by)                        # priority 19

    if decision in ("APPROVE", "REJECT"):
        # priority 44
        if plan["funding_status"] != "SUBMITTED":
            raise ApiError("ERR_PLAN_NOT_SUBMITTED", 409,
                           "Only a SUBMITTED plan may be approved or rejected.")
    else:
        # priority 45
        if (plan["funding_status"] != "APPROVED"
                or plan["disposal_status"] == "COMPLETED"):
            raise ApiError("ERR_PLAN_NOT_APPROVED", 409,
                           "Only an APPROVED plan whose disposal has not completed "
                           "may be rescinded.")

    budget = db.capital_budgets[plan["capital_budget_id"]]
    field = db.fields[plan["field_id"]]
    current = now()

    if decision == "APPROVE":
        # priority 50, then 68, then 69
        if budget["status"] != "OPEN":
            raise ApiError("ERR_BUDGET_LOCKED", 409, "The capital budget is LOCKED.")
        if plan["replacement_priority_score"] < calc.MIN_APPROVAL_PRIORITY_SCORE:
            raise ApiError("ERR_PLAN_PRIORITY_BELOW_THRESHOLD", 422,
                           "replacement_priority_score is below 20.00.")
        if plan["plan_funding_amount_cents"] > budget["available_amount_cents"]:
            raise ApiError("ERR_BUDGET_INSUFFICIENT", 422,
                           "The budget has insufficient available capital.")

        # hop one
        plan["funding_status"] = "APPROVED"
        plan["decided_by_staff_member_id"] = decided_by
        plan["decided_at_utc"] = current
        plan["decision_notes"] = notes
        bump(plan)

        # hops two and three
        was_open = budget["status"] == "OPEN"
        derive.recompute_budget(budget)
        bump(budget)

        # hop four is the consequence of that lock
        if was_open and budget["status"] == "LOCKED":
            siblings = [p for p in db.replacement_plans.values()
                        if p["capital_budget_id"] == budget["id"]
                        and p["id"] != plan["id"]
                        and p["funding_status"] == "DRAFT"]
            siblings = by_creation(siblings)
            siblings.sort(key=lambda p: -p["replacement_priority_score"])
            for sibling in siblings:
                sibling["funding_status"] = "DEFERRED"
                bump(sibling)
        return response.ok(plan)

    if decision == "REJECT":
        plan["funding_status"] = "REJECTED"
        plan["decided_by_staff_member_id"] = decided_by
        plan["decided_at_utc"] = current
        plan["decision_notes"] = notes
        bump(plan)
        # PRD 3.9: no capital movement at all, the budget is left untouched.
        derive.touch_field(field)
        return response.ok(plan)

    # RESCIND - the compensating action
    plan["funding_status"] = "RESCINDED"
    plan["decided_by_staff_member_id"] = decided_by
    plan["decided_at_utc"] = current
    plan["decision_notes"] = notes
    if plan["disposal_status"] in ("PENDING", "MANIFESTED"):
        # the manifest values are retained for audit while the obligation lapses
        plan["disposal_status"] = "NOT_APPLICABLE"
    bump(plan)

    was_locked = budget["status"] == "LOCKED"
    derive.recompute_budget(budget)
    bump(budget)
    if was_locked and budget["status"] == "OPEN":
        for sibling in by_creation([p for p in db.replacement_plans.values()
                                    if p["capital_budget_id"] == budget["id"]
                                    and p["funding_status"] == "DEFERRED"]):
            sibling["funding_status"] = "DRAFT"
            bump(sibling)

    derive.touch_field(field)
    return response.ok(plan)


@bp.post("/replacement-plans/<plan_id>/disposal-manifest")
def record_manifest(plan_id):
    middleware.authenticate(["FacilitiesDirector"])
    plan = middleware.plan_or_404(plan_id)
    body = validate.Body(required=["manifest_reference", "disposal_facility_name",
                                   "diverted_tonnage", "total_tonnage"])
    reference = body.string("manifest_reference", 1, 60)
    facility = body.string("disposal_facility_name", 1, 120)
    diverted = body.number("diverted_tonnage", calc.ZERO)
    total = body.number("total_tonnage", calc.ZERO)

    # priority 46 - the disposal axis never reads the funding axis here
    if plan["disposal_status"] != "PENDING":
        raise ApiError("ERR_DISPOSAL_NOT_PENDING", 409,
                       "The plan's disposal_status is not PENDING.")

    # priority 65 - the tonnage must make sense and clear the diversion policy
    if total <= calc.ZERO or diverted > total:
        raise ApiError("ERR_DISPOSAL_DIVERSION_BELOW_MINIMUM", 422,
                       "total_tonnage must exceed 0.00 and diverted_tonnage may "
                       "not exceed it.")
    ratio = calc.r2(diverted / total)
    if ratio < calc.MIN_DIVERSION_RATIO:
        raise ApiError("ERR_DISPOSAL_DIVERSION_BELOW_MINIMUM", 422,
                       "The diversion ratio is below 0.75.")

    plan["disposal_status"] = "MANIFESTED"
    plan["manifest_reference"] = reference
    plan["disposal_facility_name"] = facility
    plan["diverted_tonnage"] = calc.r2(diverted)
    plan["total_tonnage"] = calc.r2(total)
    plan["diversion_ratio"] = ratio
    bump(plan)
    return response.ok(plan)


@bp.post("/replacement-plans/<plan_id>/complete")
def complete_disposal(plan_id):
    middleware.authenticate(["FacilitiesDirector"])
    plan = middleware.plan_or_404(plan_id)
    body = validate.Body(required=["completed_at_utc"])
    completed_at = body.instant("completed_at_utc")

    current = now()
    if completed_at.dt > current.dt:
        raise errors.invalid_request(
            "completed_at_utc may not be later than the current instant.")

    # priority 47 - the single cross-axis guard in the whole specification
    if (plan["disposal_status"] != "MANIFESTED"
            or plan["funding_status"] != "APPROVED"):
        raise ApiError("ERR_DISPOSAL_COMPLETION_NOT_PERMITTED", 409,
                       "Completion requires disposal_status MANIFESTED and "
                       "funding_status APPROVED.")

    plan["disposal_status"] = "COMPLETED"
    plan["completed_at_utc"] = completed_at
    bump(plan)

    field = db.fields[plan["field_id"]]
    derive.cascade_retire(field, completed_at, "FIELD_RETIRED_BY_REPLACEMENT_PLAN")
    derive.touch_field(field)
    return response.ok(plan)
