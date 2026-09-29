"""RemediationPlan endpoints (PRD 3.9).

Creating, recording a milestone on, and completing a remediation plan are three
of the five operations permitted while the plan year is frozen.
"""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("remediation", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")
DEFICIENCY_TYPES = (
    "MRF_REFRESH",
    "TOOL_SLA",
    "RXDC_LATE",
    "GAG_CLAUSE",
    "ATTESTATION_LATE",
)


@bp.route("/compliance/remediation-plans", methods=["POST"])
def create_plan():
    guards.authorize("ComplianceOfficer")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    target = guards.field(
        body, "target_deficiency_type", "enum", enum=DEFICIENCY_TYPES
    )
    milestone_count = guards.field(body, "milestone_count", "integer")
    plan_summary = guards.field(body, "plan_summary", "string")
    guards.require(
        milestone_count >= 1,
        "ERR_INVALID_REQUEST",
        "milestone_count must be at least 1.",
    )
    guards.fetch("plan_year", plan_year_id)
    # Exempt from the frozen lockdown (PRD 2.8).
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "target_deficiency_type": target,
        "milestone_count": milestone_count,
        "plan_summary": plan_summary,
        "completed_milestone_count": 0,
        "last_milestone_label": None,
        "status": "ACTIVE",
        "abatement_posted_cents": None,
        "completed_at": None,
    })
    db.remediation_plans[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/remediation-plans/<row_id>", methods=["GET"])
def get_plan(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(
        response.public(guards.fetch("remediation_plan", row_id))
    )


@bp.route("/compliance/remediation-plans", methods=["GET"])
def list_plans():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.remediation_plans), [
        ("plan_year_id", "plan_year_id", None),
        ("status", "status", None),
        ("target_deficiency_type", "target_deficiency_type", None),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route(
    "/compliance/remediation-plans/<row_id>/milestone-completions", methods=["POST"]
)
def record_milestone(row_id):
    guards.authorize("ComplianceOfficer")
    plan = guards.fetch("remediation_plan", row_id)
    body = guards.read_body()
    label = guards.field(body, "milestone_label", "string")
    # Exempt from the frozen lockdown (PRD 2.8).
    guards.state_is(plan["status"], "ACTIVE")
    # Ladder step 37 — no completion beyond milestone_count.
    guards.require(
        plan["completed_milestone_count"] + 1 <= plan["milestone_count"],
        "ERR_MILESTONES_INCOMPLETE",
        "All %d milestones are already recorded." % plan["milestone_count"],
    )
    with db.txn(plan):
        plan["completed_milestone_count"] = plan["completed_milestone_count"] + 1
        plan["last_milestone_label"] = label
    return response.object_response(response.public(plan))


@bp.route("/compliance/remediation-plans/<row_id>/complete", methods=["POST"])
def complete_plan(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer")
    plan = guards.fetch("remediation_plan", row_id)
    body = guards.read_body()
    note = guards.field(body, "completion_note", "string", required=False)
    plan_year = db.plan_years.get(plan["plan_year_id"])
    # Exempt from the frozen lockdown (PRD 2.8).
    guards.state_is(plan["status"], "ACTIVE")
    # Ladder step 36 — there must be money to abate.
    accruals = domain.unreversed_accruals(
        plan["plan_year_id"], plan["target_deficiency_type"]
    )
    guards.require(
        bool(accruals),
        "ERR_NO_ACCRUAL_TO_REMEDIATE",
        "No unreversed %s accrual exists on the plan year."
        % plan["target_deficiency_type"],
    )
    # Ladder step 37 — every milestone recorded.
    guards.require(
        plan["completed_milestone_count"] == plan["milestone_count"],
        "ERR_MILESTONES_INCOMPLETE",
        "%d of %d milestones are recorded."
        % (plan["completed_milestone_count"], plan["milestone_count"]),
    )
    base = sum(entry["signed_amount_cents"] for entry in accruals)
    abatement = calc.abatement_amount(base)
    with db.txn(plan):
        plan["status"] = "COMPLETED"
        plan["abatement_posted_cents"] = abatement
        plan["completed_at"] = clock.now_iso()
    reason = note or (
        "Remediation plan %s completed for %s."
        % (plan["id"], plan["target_deficiency_type"])
    )
    domain.append_entry(
        plan_year,
        "ABATEMENT",
        plan["target_deficiency_type"],
        -abatement,
        0,
        0,
        1.0,
        None,
        reason,
        posted_by_user_id=user_id,
        remediation_plan_id=plan["id"],
    )
    if plan_year is not None:
        with db.txn(plan_year):
            # Exposure moves; deficiency_points deliberately do NOT.
            domain.recompute_exposure(plan_year)
    return response.object_response(response.public(plan))
