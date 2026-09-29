"""Assessment and eligible-measure endpoints (PRD section 3.4)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (APPLICANT, CONTRACTOR, PROGRAM_ADMIN, PROGRAM_REVIEWER,
                    authorize)

bp = Blueprint("assessments", __name__)


def _measure_entries(payload):
    raw = fields.req_list(payload, "measures")
    entries = []
    for index, item in enumerate(raw):
        entry = fields.entry_object(item, "measures")
        entries.append({
            "measure_code": fields.req_str(entry, "measure_code", allow_empty=False),
            "proposed_quantity": fields.req_int(entry, "proposed_quantity", minimum=1),
            "estimated_cost_cents": fields.req_int(entry, "estimated_cost_cents", minimum=0),
            "index": index,
        })
    return entries


def _qualify(program, household, assessed_panel_amps, entries):
    """The five stages of eligible_measure_qualification, executed exactly once."""
    rows = []
    for entry in entries:
        item = domain.catalog_item(program["id"], entry["measure_code"])
        rows.append({"entry": entry, "item": item, "reason": None})

    rows.sort(key=lambda r: (
        r["item"]["sort_order"] if r["item"] is not None else 0,
        r["entry"]["index"],
    ))

    # Stage A -- catalog currency and tier eligibility only.
    for row in rows:
        item = row["item"]
        if item is None or not item["active"]:
            row["reason"] = "RETIRED_CATALOG_ITEM"
            continue
        if household["income_tier"] == "STANDARD" and not item["standard_tier_eligible"]:
            row["reason"] = "TIER_INELIGIBLE"

    # Stage B -- the panel-upgrade anchor, against tentatively qualified lines.
    has_anchor = any(
        row["reason"] is None and row["item"] is not None
        and row["item"]["qualifies_as_appliance_anchor"]
        for row in rows
    )
    for row in rows:
        if row["reason"] is not None:
            continue
        if row["item"]["requires_qualifying_appliance"] and not has_anchor:
            row["reason"] = "ANCHOR_MISSING"

    # Stage C -- capacity propagation from surviving panel-upgrade lines.
    effective = assessed_panel_amps
    for row in rows:
        if row["reason"] is not None:
            continue
        if row["item"]["is_panel_upgrade"]:
            effective = max(effective, row["item"]["upgraded_capacity_amps"])

    # Stage D -- the capacity gate; panel-upgrade lines are exempt.
    for row in rows:
        if row["reason"] is not None:
            continue
        item = row["item"]
        if not item["is_panel_upgrade"] and item["required_panel_capacity_amps"] > effective:
            row["reason"] = "PANEL_CAPACITY_INSUFFICIENT"

    # Stage E -- prerequisites, read against the settled post-Stage-D state.
    survived_d = {
        row["entry"]["measure_code"] for row in rows if row["reason"] is None
    }
    for row in rows:
        if row["reason"] is not None:
            continue
        prerequisite = row["item"]["prerequisite_measure_code"]
        if prerequisite is not None and prerequisite not in survived_d:
            row["reason"] = "PREREQUISITE_MISSING"

    return rows, effective


def _write_eligible_measures(assessment, program, household, rows):
    created = []
    for position, row in enumerate(rows, start=1):
        record = store.new_record({
            "assessment_id": assessment["id"],
            "measure_code": row["entry"]["measure_code"],
            "proposed_quantity": row["entry"]["proposed_quantity"],
            "estimated_cost_cents": row["entry"]["estimated_cost_cents"],
            "qualified": row["reason"] is None,
            "disqualification_reason": row["reason"],
            "estimated_incentive_cents": 0,
            "evaluation_order": position,
        }, versioned=False)
        store.eligible_measures[record["id"]] = record
        row["record"] = record
        created.append(record)

    share = calc.tier_cost_share(program, household["income_tier"])
    inputs = []
    for row in rows:
        if row["reason"] is not None:
            continue
        item = row["item"]
        inputs.append({
            "ref": row["record"],
            "measure_code": row["entry"]["measure_code"],
            "group": item["combined_cap_group"],
            "is_panel": item["is_panel_upgrade"],
            "unit": item["unit_incentive_cents"],
            "maxq": item["max_quantity"],
            "mcap": item["measure_cap_cents"],
            "qty": row["entry"]["proposed_quantity"],
            "cost": row["entry"]["estimated_cost_cents"],
        })
    result = calc.allocate(
        inputs, program, share, household["lifetime_cap_remaining_cents"])
    for detail in result["lines"]:
        detail["ref"]["estimated_incentive_cents"] = detail["allocated_cents"]

    assessment["qualified_measure_count"] = len(inputs)
    assessment["estimated_total_incentive_cents"] = result["total_incentive_cents"]
    return created


@bp.post("/assessments")
@authorize(CONTRACTOR, PROGRAM_ADMIN)
def create_assessment():
    payload = guards.body()
    household_id = fields.req_str(payload, "household_id", allow_empty=False)
    contractor_id = fields.req_str(payload, "contractor_id", allow_empty=False)
    assessed_panel_amps = fields.req_int(payload, "assessed_panel_amps", minimum=0)
    entries = _measure_entries(payload)
    expected_version = fields.req_int(payload, "expected_household_version")
    notes = fields.opt_str(payload, "assessment_notes")

    household = domain.get_household(household_id)
    contractor = domain.get_contractor(contractor_id)
    program = domain.get_program(household["program_id"])
    if contractor["program_id"] != program["id"]:
        raise ApiError(errors.ERR_CONTRACTOR_NOT_FOUND)
    for entry in entries:
        if domain.catalog_item(program["id"], entry["measure_code"]) is None:
            raise ApiError(errors.ERR_MEASURE_CODE_NOT_IN_CATALOG)

    superseded = []
    for prior in store.ordered(store.assessments):
        if prior["household_id"] != household["id"]:
            continue
        if prior["status"] not in ("PENDING_REVIEW", "APPROVED"):
            continue
        if prior["status"] == "APPROVED":
            for project in store.projects.values():
                if (project["assessment_id"] == prior["id"]
                        and project["status"] in domain.BLOCKING_ASSESSMENT_PROJECT_STATES):
                    raise ApiError(
                        errors.ERR_INVALID_STATE_TRANSITION,
                        message="A live rebate project still references the prior assessment.",
                    )
        superseded.append(prior)

    if expected_version != household["version"]:
        raise ApiError(errors.ERR_STALE_HOUSEHOLD_VERSION)

    domain.require_contractor_fitness(contractor)

    assessment = store.new_record({
        "household_id": household["id"],
        "contractor_id": contractor["id"],
        "assessed_panel_amps": assessed_panel_amps,
        "effective_panel_amps": assessed_panel_amps,
        "status": "PENDING_REVIEW",
        "qualified_measure_count": 0,
        "estimated_total_incentive_cents": 0,
        "assessment_notes": notes,
        "approved_by_user_id": None,
    })
    store.assessments[assessment["id"]] = assessment

    rows, effective = _qualify(program, household, assessed_panel_amps, entries)
    assessment["effective_panel_amps"] = effective
    _write_eligible_measures(assessment, program, household, rows)

    for prior in superseded:
        prior["status"] = "SUPERSEDED"
        store.touch(prior)
    store.touch(household)

    return envelope.object_response(store.public(assessment), 201)


@bp.get("/assessments/<assessment_id>")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_assessment(assessment_id):
    assessment = domain.get_assessment(assessment_id)
    return envelope.object_response(store.public(assessment))


@bp.get("/assessments")
@authorize(CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_assessments():
    limit, offset = guards.pagination()
    household_id = request.args.get("household_id")
    contractor_id = request.args.get("contractor_id")
    status = request.args.get("status")
    records = store.ordered(
        store.assessments,
        lambda a: (household_id is None or a["household_id"] == household_id)
        and (contractor_id is None or a["contractor_id"] == contractor_id)
        and (status is None or a["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.get("/assessments/<assessment_id>/eligible-measures")
@authorize(APPLICANT, CONTRACTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_eligible_measures(assessment_id):
    limit, offset = guards.pagination()
    qualified = guards.bool_arg("qualified")
    assessment = domain.get_assessment(assessment_id)
    records = [
        row for row in domain.eligible_measures(assessment["id"])
        if qualified is None or row["qualified"] == qualified
    ]
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/assessments/<assessment_id>/approve")
@authorize(PROGRAM_REVIEWER)
def approve_assessment(assessment_id):
    payload = guards.body()
    decision = fields.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    fields.opt_str(payload, "review_notes")
    assessment = domain.get_assessment(assessment_id)

    if assessment["status"] != "PENDING_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)

    if decision == "APPROVE":
        contractor = store.contractors.get(assessment["contractor_id"])
        if contractor is None or contractor["status"] != "ENROLLED_ACTIVE":
            raise ApiError(errors.ERR_CONTRACTOR_NOT_ACTIVE)
        if assessment["qualified_measure_count"] < 1:
            raise ApiError(errors.ERR_NO_ELIGIBLE_MEASURES)
        assessment["status"] = "APPROVED"
    else:
        assessment["status"] = "REJECTED"

    assessment["approved_by_user_id"] = guards.actor_id()
    store.touch(assessment)
    return envelope.object_response(store.public(assessment))
