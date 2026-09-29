"""PlanYear endpoints (PRD 3.1, 3.9)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("plan_years", __name__)

READ_ROLES = (
    "PlanSponsorAdmin",
    "ComplianceOfficer",
    "ExternalAuditor",
    "PlatformOperator",
)


@bp.route("/compliance/plan-years", methods=["POST"])
def create_plan_year():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    sponsor_name = guards.field(body, "sponsor_name", "string")
    label = guards.field(body, "plan_year_label", "string")
    start_date = guards.field(body, "start_date", "date")
    end_date = guards.field(body, "end_date", "date")
    covered_lives = guards.field(body, "covered_lives", "integer")
    attestation_deadline = guards.field(body, "attestation_deadline_date", "date")
    rxdc_deadline = guards.field(body, "rxdc_deadline_date", "date")
    guards.require(
        covered_lives >= 1, "ERR_INVALID_REQUEST", "covered_lives must be at least 1."
    )
    # Ladder step 19 — interval shape.
    guards.require(
        clock.parse_date(end_date) > clock.parse_date(start_date),
        "ERR_INVALID_INTERVAL",
        "end_date must be strictly after start_date.",
    )
    # Ladder step 41 — label uniqueness.
    guards.require(
        all(p["plan_year_label"] != label for p in db.plan_years.values()),
        "ERR_DUPLICATE_PLAN_YEAR_LABEL",
        "plan_year_label '%s' is already in use." % label,
    )
    record = db.common_fields()
    record.update({
        "sponsor_name": sponsor_name,
        "plan_year_label": label,
        "start_date": start_date,
        "end_date": end_date,
        "covered_lives": covered_lives,
        "attestation_deadline_date": attestation_deadline,
        "rxdc_deadline_date": rxdc_deadline,
        "lifecycle_status": "SETUP",
        "compliance_posture": "COMPLIANT",
        "deficiency_points": 0,
        "penalty_exposure_cents": 0,
        "tool_sla_breach_count": 0,
        "attestation_status": "NOT_STARTED",
        "freeze_flag": False,
        "freeze_reason": None,
        "last_compliance_run_at": None,
    })
    db.plan_years[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/plan-years/<row_id>", methods=["GET"])
def get_plan_year(row_id):
    guards.authorize(*READ_ROLES)
    plan_year = guards.fetch("plan_year", row_id)
    return response.object_response(response.public(plan_year))


@bp.route("/compliance/plan-years", methods=["GET"])
def list_plan_years():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    rows = guards.apply_filters(db.ordered(db.plan_years), [
        ("plan_year_label", "plan_year_label", None),
        ("lifecycle_status", "lifecycle_status", None),
        ("compliance_posture", "compliance_posture", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/plan-years/<row_id>/activate", methods=["POST"])
def activate_plan_year(row_id):
    guards.authorize("PlanSponsorAdmin")
    plan_year = guards.fetch("plan_year", row_id)
    guards.read_body()
    guards.not_frozen(plan_year)
    guards.state_is(plan_year["lifecycle_status"], "SETUP")
    # Ladder step 18 — a TPA contract must be on the roster.
    guards.require(
        any(
            c["contract_type"] == "TPA"
            for c in db.contracts_of_plan_year(plan_year["id"])
        ),
        "ERR_TPA_CONTRACT_REQUIRED",
        "At least one TPA service provider contract is required.",
    )
    with db.txn(plan_year):
        plan_year["lifecycle_status"] = "ACTIVE"
    return response.object_response(response.public(plan_year))


@bp.route("/compliance/plan-years/<row_id>/close-reporting", methods=["POST"])
def close_reporting(row_id):
    guards.authorize("PlanSponsorAdmin")
    plan_year = guards.fetch("plan_year", row_id)
    guards.read_body()
    guards.not_frozen(plan_year)
    guards.state_is(plan_year["lifecycle_status"], "ACTIVE")
    # Ladder step 24 — the reporting period must have ended.
    guards.require(
        clock.today_iso() > plan_year["end_date"],
        "ERR_REPORTING_PERIOD_NOT_ENDED",
        "The clock date must be strictly after end_date.",
    )
    with db.txn(plan_year):
        plan_year["lifecycle_status"] = "REPORTING_CLOSED"
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(plan_year))


@bp.route("/compliance/plan-years/<row_id>/freeze", methods=["POST"])
def freeze_plan_year(row_id):
    guards.authorize("ExternalAuditor")
    plan_year = guards.fetch("plan_year", row_id)
    body = guards.read_body()
    reason = guards.field(body, "reason", "string")
    guards.not_frozen(plan_year)
    guards.state_is(plan_year["freeze_flag"], False)
    with db.txn(plan_year):
        plan_year["freeze_flag"] = True
        plan_year["freeze_reason"] = reason
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(plan_year))


@bp.route("/compliance/plan-years/<row_id>/unfreeze", methods=["POST"])
def unfreeze_plan_year(row_id):
    guards.authorize("ExternalAuditor")
    plan_year = guards.fetch("plan_year", row_id)
    body = guards.read_body()
    guards.field(body, "note", "string", required=False)
    # Exempt from the frozen lockdown (PRD 2.8).
    guards.state_is(plan_year["freeze_flag"], True)
    with db.txn(plan_year):
        plan_year["freeze_flag"] = False
        plan_year["freeze_reason"] = None
        domain.recompute_posture(plan_year)
    return response.object_response(response.public(plan_year))


@bp.route("/compliance/plan-years/<row_id>/compliance-runs", methods=["POST"])
def compliance_run(row_id):
    guards.authorize("ComplianceOfficer", "PlatformOperator")
    plan_year = guards.fetch("plan_year", row_id)
    guards.read_body()
    guards.not_frozen(plan_year)
    summary = domain.compliance_run(plan_year)
    return response.object_response(summary)


@bp.route("/compliance/plan-years/<row_id>/penalty-projection", methods=["GET"])
def penalty_projection(row_id):
    guards.authorize("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")
    plan_year = guards.fetch("plan_year", row_id)
    as_of_date = guards.query_date("as_of_date")
    if as_of_date is None:
        as_of_date = clock.today_iso()
    else:
        # Ladder step 38 — projection date in range.
        guards.require(
            plan_year["start_date"] <= as_of_date <= plan_year["end_date"],
            "ERR_PROJECTION_DATE_OUT_OF_RANGE",
            "as_of_date must fall inside the plan year.",
        )
    return response.object_response(domain.projection(plan_year, as_of_date))
