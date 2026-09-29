"""Rebate project endpoints: creation, submission, review, quote (PRD 3.5, 3.6)."""
from flask import Blueprint, request

import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (APPLICANT, CONTRACTOR, FIELD_INSPECTOR, PROGRAM_ADMIN,
                    PROGRAM_REVIEWER, authorize)

bp = Blueprint("projects", __name__)


# ------------------------------------------------------------------ helpers ---
def measure_entries(payload, key="measures", required=True):
    raw = fields.req_list(payload, key) if required else fields.opt_list(payload, key)
    if raw is None:
        return None
    entries = []
    for item in raw:
        entry = fields.entry_object(item, key)
        entries.append({
            "measure_code": fields.req_str(entry, "measure_code", allow_empty=False),
            "planned_quantity": fields.req_int(entry, "planned_quantity", minimum=1),
            "estimated_cost_cents": fields.req_int(entry, "estimated_cost_cents", minimum=0),
        })
    return entries


def project_ownership(project):
    """Rung 7 for the seven project operations that carry an ownership check."""
    role = guards.actor_role()
    actor = guards.actor_id()
    if role == APPLICANT and actor != project["household_id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)
    if role == CONTRACTOR and actor != project["contractor_id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)


def validate_measure_set(program, assessment, effective_amps, entries):
    """Rungs 12, 13, 14 and 15 over a requested measure set, in ladder order."""
    items = [(entry, domain.catalog_item(program["id"], entry["measure_code"]))
             for entry in entries]

    # Rung 12 -- electrical safety.
    for entry, item in items:
        if item is None or item["is_panel_upgrade"]:
            continue
        if item["required_panel_capacity_amps"] > effective_amps:
            raise ApiError(errors.ERR_PANEL_CAPACITY_INSUFFICIENT)

    # Rung 13 -- measure-set coherence: the anchor rule, then prerequisites.
    has_anchor = any(
        item is not None and item["qualifies_as_appliance_anchor"] for _entry, item in items)
    for _entry, item in items:
        if item is None:
            continue
        if (item["is_panel_upgrade"] or item["requires_qualifying_appliance"]) and not has_anchor:
            raise ApiError(errors.ERR_PANEL_UPGRADE_ANCHOR_MISSING)

    present = {entry["measure_code"] for entry, _item in items}
    qualified_codes = {
        row["measure_code"] for row in domain.eligible_measures(assessment["id"])
        if row["qualified"]
    }
    for _entry, item in items:
        if item is None:
            continue
        prerequisite = item["prerequisite_measure_code"]
        if prerequisite is None:
            continue
        if prerequisite not in present or prerequisite not in qualified_codes:
            raise ApiError(errors.ERR_PREREQUISITE_MEASURE_MISSING)

    # Rung 14 -- non-empty measure set.
    if not entries or assessment["qualified_measure_count"] < 1:
        raise ApiError(errors.ERR_NO_ELIGIBLE_MEASURES)

    # Rung 15 -- per-line eligibility, then uniqueness.
    for entry, _item in items:
        if entry["measure_code"] not in qualified_codes:
            raise ApiError(errors.ERR_MEASURE_NOT_ELIGIBLE)
    seen = set()
    for entry, _item in items:
        if entry["measure_code"] in seen:
            raise ApiError(errors.ERR_DUPLICATE_MEASURE_LINE)
        seen.add(entry["measure_code"])

    return items


def create_lines(project, items):
    for entry, item in items:
        line = store.new_record({
            "project_id": project["id"],
            "measure_code": entry["measure_code"],
            "planned_quantity": entry["planned_quantity"],
            "pinned_unit_incentive_cents": item["unit_incentive_cents"],
            "pinned_measure_cap_cents": item["measure_cap_cents"],
            "pinned_max_quantity": item["max_quantity"],
            "pinned_sort_order": item["sort_order"],
            "pinned_combined_cap_group": item["combined_cap_group"],
            "pinned_is_panel_upgrade": item["is_panel_upgrade"],
            "estimated_cost_cents": entry["estimated_cost_cents"],
            "actual_cost_cents": None,
            "verified_quantity": None,
            "provisional_incentive_cents": 0,
            "final_incentive_cents": None,
            "install_status": "PLANNED",
            "verification_status": "PENDING",
            "rejection_reason": None,
        })
        store.project_measures[line["id"]] = line


# ------------------------------------------------------------------- routes ---
@bp.post("/rebate-projects")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_ADMIN)
def create_project():
    payload = guards.body()
    household_id = fields.req_str(payload, "household_id", allow_empty=False)
    assessment_id = fields.req_str(payload, "assessment_id", allow_empty=False)
    contractor_id = fields.req_str(payload, "contractor_id", allow_empty=False)
    verification_id = fields.req_str(payload, "income_verification_id", allow_empty=False)
    estimated_cost = fields.req_int(payload, "estimated_project_cost_cents", minimum=1)
    entries = measure_entries(payload)

    household = domain.get_household(household_id)
    program = domain.get_program(household["program_id"])
    assessment = domain.get_assessment(assessment_id)
    if assessment["household_id"] != household["id"]:
        raise ApiError(errors.ERR_ASSESSMENT_NOT_FOUND)
    contractor = domain.get_contractor(contractor_id)
    if contractor["program_id"] != program["id"]:
        raise ApiError(errors.ERR_CONTRACTOR_NOT_FOUND)
    verification = domain.get_income_verification(verification_id)
    if verification["household_id"] != household["id"]:
        raise ApiError(errors.ERR_INCOME_VERIFICATION_NOT_FOUND)
    for entry in entries:
        if domain.catalog_item(program["id"], entry["measure_code"]) is None:
            raise ApiError(errors.ERR_MEASURE_CODE_NOT_IN_CATALOG)

    role = guards.actor_role()
    if role == APPLICANT and guards.actor_id() != household["id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)
    if role == CONTRACTOR and guards.actor_id() != contractor["id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)

    if assessment["status"] != "APPROVED":
        raise ApiError(errors.ERR_ASSESSMENT_NOT_APPROVED)

    domain.require_contractor_fitness(contractor)

    items = validate_measure_set(
        program, assessment, assessment["effective_panel_amps"], entries)

    if household["income_tier"] is None or domain.verified_income_verification(
            household["id"]) is None:
        raise ApiError(errors.ERR_INCOME_TIER_NOT_VERIFIED)

    project = store.new_record({
        "household_id": household["id"],
        "assessment_id": assessment["id"],
        "contractor_id": contractor["id"],
        "income_verification_id": verification["id"],
        "status": "DRAFT",
        "estimated_project_cost_cents": estimated_cost,
        "actual_project_cost_cents": None,
        "provisional_total_incentive_cents": 0,
        "final_total_incentive_cents": None,
        "stacking_adjusted_state_incentive_cents": None,
        "disbursed_amount_cents": 0,
        "install_start_date": None,
        "install_end_date": None,
        "installed_panel_amps": None,
        "conditional_pass_flag": False,
        "remediation_count": 0,
        "submission_count": 0,
        "reviewed_by_user_id": None,
        "review_notes": None,
        "incomplete_reason": None,
    })
    store.projects[project["id"]] = project
    create_lines(project, items)
    result = domain.run_allocation(project, "provisional")
    domain.persist_allocation(project, "provisional", result, bump=False)
    return envelope.object_response(store.public(project), 201)


@bp.get("/rebate-projects/<project_id>")
@authorize(APPLICANT, CONTRACTOR, FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_project(project_id):
    project = domain.get_project(project_id)
    project_ownership(project)
    return envelope.object_response(store.public(project))


@bp.get("/rebate-projects")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_projects():
    limit, offset = guards.pagination()
    household_id = request.args.get("household_id")
    assessment_id = request.args.get("assessment_id")
    contractor_id = request.args.get("contractor_id")
    verification_id = request.args.get("income_verification_id")
    status = request.args.get("status")
    records = store.ordered(
        store.projects,
        lambda p: (household_id is None or p["household_id"] == household_id)
        and (assessment_id is None or p["assessment_id"] == assessment_id)
        and (contractor_id is None or p["contractor_id"] == contractor_id)
        and (verification_id is None or p["income_verification_id"] == verification_id)
        and (status is None or p["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.get("/rebate-projects/<project_id>/measures")
@authorize(APPLICANT, CONTRACTOR, FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_project_measures(project_id):
    limit, offset = guards.pagination()
    install_status = request.args.get("install_status")
    verification_status = request.args.get("verification_status")
    project = domain.get_project(project_id)
    records = [
        line for line in domain.project_measures(project["id"])
        if (install_status is None or line["install_status"] == install_status)
        and (verification_status is None or line["verification_status"] == verification_status)
    ]
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/rebate-projects/<project_id>/submit")
@authorize(APPLICANT, CONTRACTOR)
def submit_project(project_id):
    payload = guards.body()
    entries = measure_entries(payload, required=False)
    estimated_cost = fields.opt_int(payload, "estimated_project_cost_cents", minimum=1)
    project = domain.get_project(project_id)
    project_ownership(project)

    if project["status"] not in ("DRAFT", "INCOMPLETE"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)

    contractor = domain.contractor_of_project(project)
    domain.require_contractor_fitness(contractor)

    program = domain.program_of_project(project)
    assessment = store.assessments.get(project["assessment_id"])
    if assessment is None:
        raise ApiError(errors.ERR_ASSESSMENT_NOT_FOUND)

    if entries is None:
        entries = [{
            "measure_code": line["measure_code"],
            "planned_quantity": line["planned_quantity"],
            "estimated_cost_cents": line["estimated_cost_cents"],
        } for line in domain.project_measures(project["id"])
            if line["install_status"] != "VOID"]
        replace = False
    else:
        replace = True

    effective = project["installed_panel_amps"]
    if effective is None:
        effective = assessment["effective_panel_amps"]
    items = validate_measure_set(program, assessment, effective, entries)

    if replace:
        for line in domain.project_measures(project["id"]):
            del store.project_measures[line["id"]]
        create_lines(project, items)

    if estimated_cost is not None:
        project["estimated_project_cost_cents"] = estimated_cost
    project["submission_count"] += 1
    project["incomplete_reason"] = None
    project["status"] = "SUBMITTED"
    result = domain.run_allocation(project, "provisional")
    domain.persist_allocation(project, "provisional", result)
    store.touch(project)
    return envelope.object_response(store.public(project))


@bp.post("/rebate-projects/<project_id>/review")
@authorize(PROGRAM_REVIEWER)
def review_project(project_id):
    payload = guards.body()
    decision = fields.req_enum(
        payload, "decision", ("APPROVE", "RETURN_INCOMPLETE", "REJECT"))
    incomplete_reason = fields.opt_str(payload, "incomplete_reason", allow_empty=False)
    review_notes = fields.opt_str(payload, "review_notes")
    if decision == "RETURN_INCOMPLETE" and incomplete_reason is None:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            message="incomplete_reason is required when decision is RETURN_INCOMPLETE.",
        )
    project = domain.get_project(project_id)

    if project["status"] != "SUBMITTED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)

    if decision == "APPROVE":
        contractor = domain.contractor_of_project(project)
        if contractor is None or contractor["status"] != "ENROLLED_ACTIVE":
            raise ApiError(errors.ERR_CONTRACTOR_NOT_ACTIVE)
        household = domain.household_of_project(project)
        if household is None or household["income_tier"] is None:
            raise ApiError(errors.ERR_INCOME_TIER_NOT_VERIFIED)
        project["status"] = "APPROVED"
    elif decision == "RETURN_INCOMPLETE":
        project["status"] = "INCOMPLETE"
        project["incomplete_reason"] = incomplete_reason
    else:
        project["status"] = "REJECTED"

    project["reviewed_by_user_id"] = guards.actor_id()
    if review_notes is not None:
        project["review_notes"] = review_notes
    store.touch(project)
    if decision == "REJECT":
        domain.void_project_measures(project)
    return envelope.object_response(store.public(project))


@bp.get("/rebate-projects/<project_id>/incentive-quote")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def project_incentive_quote(project_id):
    variant = request.args.get("variant", "provisional")
    if variant not in ("provisional", "final"):
        raise ApiError(errors.ERR_INVALID_REQUEST, message="variant is invalid.")
    project = domain.get_project(project_id)
    result = domain.run_allocation(project, variant)
    lines = [{
        "measure_code": detail["measure_code"],
        "raw_incentive_cents": detail["raw_incentive_cents"],
        "cost_share_cap_cents": detail["cost_share_cap_cents"],
        "capped_line_cents": detail["capped_line_cents"],
        "allocated_cents": detail["allocated_cents"],
    } for detail in result["lines"]]
    return envelope.object_response({
        "project_id": project["id"],
        "variant": variant,
        "lines": lines,
        "group_capped_total_cents": result["group_capped_total_cents"],
        "household_cap_limit_cents": result["household_cap_limit_cents"],
        "total_incentive_cents": result["total_incentive_cents"],
        "group_cap_applied": result["group_cap_applied"],
        "household_cap_applied": result["household_cap_applied"],
        "residual_cents_assigned_to_measure_code": result[
            "residual_cents_assigned_to_measure_code"],
    })
