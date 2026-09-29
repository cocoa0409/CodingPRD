"""Project endpoints: formulation, review cycle, obligation, closeout."""
from flask import Blueprint

from db import db, new_row, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.calc import (
    closeout_reconciliation,
    federal_share_obligation,
    mitigation_cap_allocation,
    project_eligible_cost_final,
    project_eligible_cost_provisional,
    project_review_basis,
)
from services.constants import (
    CATEGORIES,
    MAX_RFI_ROUNDS,
    SINGLE_AUDIT_THRESHOLD_CENTS,
)
from services.ledger import (
    applicant_of_project,
    cascade_applicant,
    covering_policies,
    create_deobligation,
    create_progress_report,
    current_quarter_label,
    disaster_of_project,
    facility_of_project,
    lines_of_project,
    recompute_applicant_ledger,
    recompute_disaster_rollups,
    recompute_project_deobligations,
    reviewed_lines_of_project,
)
from validate import body, present, v_enum, v_id, v_int, v_str

bp = Blueprint("projects", __name__)


def _work_type(category):
    return "EMERGENCY" if category in ("A", "B") else "PERMANENT"


def _policies_for(project):
    disaster = disaster_of_project(project)
    if disaster is None:
        return []
    return covering_policies(project["facility_id"], disaster["incident_start_at"])


@bp.route(PREFIX + "/projects", methods=["POST"])
def create_project():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)
    raw_facility = payload.get("facility_id")
    if isinstance(raw_facility, str):
        facility = find("facilities", raw_facility)
        if facility is not None:
            check_scope(actor, facility["applicant_id"])

    applicant_id = v_id(payload, "applicant_id")
    facility_id = v_id(payload, "facility_id")
    category = v_enum(payload, "category", CATEGORIES)
    title = v_str(payload, "title")
    scope_of_work = v_str(payload, "scope_of_work")
    estimated_repair_cost_cents = v_int(payload, "estimated_repair_cost_cents",
                                        minimum=0)
    mitigation_requested_cents = v_int(payload, "mitigation_requested_cents",
                                       required=False, default=0, minimum=0)

    require("applicants", applicant_id)
    require("facilities", facility_id)

    if mitigation_requested_cents > estimated_repair_cost_cents:
        fail("ERR_MITIGATION_EXCEEDS_REPAIR",
             "mitigation_requested_cents exceeds estimated_repair_cost_cents")

    row = new_row("projects", {
        "applicant_id": applicant_id,
        "facility_id": facility_id,
        "category": category,
        "work_type": None,
        "title": title,
        "scope_of_work": scope_of_work,
        "estimated_repair_cost_cents": estimated_repair_cost_cents,
        "mitigation_requested_cents": mitigation_requested_cents,
        "status": "DRAFT",
        "size_class": None,
        "rfi_round_count": 0,
        "last_rfi_question": None,
        "repair_eligible_cents": 0,
        "anticipated_insurance_cents": 0,
        "settlement_allocated_cents": 0,
        "insurance_reduction_cents": 0,
        "mitigation_approved_cents": 0,
        "eligible_cost_provisional_cents": 0,
        "eligible_cost_final_cents": None,
        "federal_share_obligated_cents": 0,
        "federal_share_final_cents": None,
        "deobligated_cents": 0,
        "pending_deobligation_cents": 0,
        "closeout_variance_cents": None,
        "cost_reviewed_by_user_id": None,
        "obligated_by_user_id": None,
        "denial_reason": None,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/projects", methods=["GET"])
def list_projects():
    authenticate(ALL_ROLES)
    return render_list("projects", {
        "applicant_id": "applicant_id",
        "facility_id": "facility_id",
        "status": "status",
        "size_class": "size_class",
        "category": "category",
    })


@bp.route(PREFIX + "/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    actor = authenticate(ALL_ROLES)
    project = find("projects", project_id)
    if project is not None:
        check_scope(actor, project["applicant_id"])
    project = require("projects", project_id)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/submit", methods=["POST"])
def submit_project(project_id):
    actor = authenticate(("ApplicantAgent",))
    project = find("projects", project_id)
    if project is not None:
        check_scope(actor, project["applicant_id"])
    project = require("projects", project_id)

    if project["status"] != "DRAFT":
        fail("ERR_PROJECT_INVALID_STATE", "only a DRAFT project may be submitted")

    facility = facility_of_project(project)
    if facility is None or facility["eligibility_status"] != "ELIGIBLE":
        fail("ERR_FACILITY_INELIGIBLE", "the project's facility is not ELIGIBLE")

    applicant = applicant_of_project(project)
    if applicant is None or applicant["eligibility_status"] != "ELIGIBLE":
        fail("ERR_APPLICANT_NOT_ELIGIBLE", "the applicant is not ELIGIBLE")

    disaster = disaster_of_project(project)
    if disaster is None or disaster["status"] != "DECLARED":
        fail("ERR_DISASTER_NOT_OPEN", "the declaration is closed to submissions")

    setf(project, "work_type", _work_type(project["category"]))
    result = project_eligible_cost_provisional(project, disaster, _policies_for(project))
    for field, value in result.items():
        setf(project, field, value)
    setf(project, "status", "UNDER_REVIEW")
    touch(project)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/rfi", methods=["POST"])
def issue_rfi(project_id):
    authenticate(("ProgramSpecialist",))
    project = require("projects", project_id)
    payload = body()
    question = v_str(payload, "question", non_empty=False)

    if project["status"] != "UNDER_REVIEW":
        fail("ERR_PROJECT_INVALID_STATE",
             "an RFI may only be issued while UNDER_REVIEW")
    if project["rfi_round_count"] >= MAX_RFI_ROUNDS:
        fail("ERR_RFI_ROUNDS_EXHAUSTED", "the RFI round budget is exhausted")

    setf(project, "status", "RFI_ISSUED")
    setf(project, "rfi_round_count", project["rfi_round_count"] + 1)
    setf(project, "last_rfi_question", question)
    touch(project)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/rfi-response", methods=["POST"])
def respond_rfi(project_id):
    actor = authenticate(("ApplicantAgent",))
    project = find("projects", project_id)
    if project is not None:
        check_scope(actor, project["applicant_id"])
    project = require("projects", project_id)

    payload = body()
    v_str(payload, "response", non_empty=False)
    revised = v_int(payload, "revised_estimate_cents", required=False, default=None,
                    minimum=0)

    if project["status"] != "RFI_ISSUED":
        fail("ERR_PROJECT_INVALID_STATE",
             "there is no outstanding RFI on this project")

    if revised is not None:
        setf(project, "estimated_repair_cost_cents", revised)

    disaster = disaster_of_project(project)
    if disaster is not None:
        result = project_eligible_cost_provisional(project, disaster,
                                                   _policies_for(project))
        for field, value in result.items():
            setf(project, field, value)
    setf(project, "status", "UNDER_REVIEW")
    touch(project)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/cost-review", methods=["POST"])
def cost_review(project_id):
    actor = authenticate(("ProgramSpecialist",))
    project = require("projects", project_id)
    payload = body()

    decision = v_enum(payload, "decision", ("VALIDATE", "DENY"))
    denial_reason = None
    if decision == "DENY":
        denial_reason = v_str(payload, "denial_reason", non_empty=False)

    if project["status"] != "UNDER_REVIEW":
        fail("ERR_PROJECT_INVALID_STATE",
             "cost review is admissible only from UNDER_REVIEW")

    for line in lines_of_project(project["id"]):
        if line["review_status"] == "SUBMITTED":
            fail("ERR_UNREVIEWED_COST_LINE_ITEMS",
                 "every cost line item must be reviewed first")

    facility = facility_of_project(project)
    if facility is None or facility["eligibility_status"] != "ELIGIBLE":
        fail("ERR_FACILITY_INELIGIBLE", "the project's facility is not ELIGIBLE")

    if decision == "VALIDATE":
        disaster = disaster_of_project(project)
        basis = project_review_basis(
            project, disaster,
            reviewed_lines_of_project(project["id"]),
            _policies_for(project),
        )
        for field, value in basis.items():
            setf(project, field, value)
        setf(project, "mitigation_approved_cents", mitigation_cap_allocation(
            project["repair_eligible_cents"],
            project["mitigation_requested_cents"],
            project["size_class"],
        ))
        setf(project, "status", "VALIDATED")
    else:
        setf(project, "status", "DENIED")
        setf(project, "denial_reason", denial_reason)

    setf(project, "cost_reviewed_by_user_id", actor.user_id)
    touch(project)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/obligate", methods=["POST"])
def obligate_project(project_id):
    actor = authenticate(("GrantsOfficer",))
    project = require("projects", project_id)

    if project["status"] != "VALIDATED":
        fail("ERR_PROJECT_INVALID_STATE",
             "only a VALIDATED project may be obligated")

    facility = facility_of_project(project)
    if facility is not None and facility["flood_zone"] is True \
            and facility["prior_disaster_flood_damage"] is True:
        has_flood = any(p["policy_type"] == "FLOOD" for p in _policies_for(project))
        if not has_flood:
            fail("ERR_INSURANCE_REQUIREMENT_UNMET",
                 "a FLOOD policy covering the incident start is required")

    disaster = disaster_of_project(project)
    if disaster is None or disaster["status"] != "DECLARED":
        fail("ERR_DISASTER_NOT_OPEN", "the declaration is closed to obligations")

    share = federal_share_obligation(
        project["repair_eligible_cents"],
        project["insurance_reduction_cents"],
        project["mitigation_approved_cents"],
        disaster["federal_cost_share_pct"],
    )
    setf(project, "federal_share_obligated_cents", share)
    setf(project, "status", "OBLIGATED")
    setf(project, "obligated_by_user_id", actor.user_id)

    applicant = applicant_of_project(project)
    if applicant is not None:
        recompute_applicant_ledger(applicant)
        if applicant["total_obligated_cents"] >= SINGLE_AUDIT_THRESHOLD_CENTS \
                and applicant["monitoring_status"] == "STANDARD":
            setf(applicant, "audit_requirement", "SINGLE_AUDIT")
            setf(applicant, "monitoring_status", "ENHANCED")
            create_progress_report(applicant, current_quarter_label(), "DUE")
        touch(applicant)
    recompute_disaster_rollups(disaster)
    touch(project)
    touch(disaster)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/closeout-request", methods=["POST"])
def closeout_request(project_id):
    actor = authenticate(("ApplicantAgent",))
    project = find("projects", project_id)
    if project is not None:
        check_scope(actor, project["applicant_id"])
    project = require("projects", project_id)

    if project["status"] != "OBLIGATED":
        fail("ERR_PROJECT_INVALID_STATE",
             "closeout may only be requested on an OBLIGATED project")

    reviewed = reviewed_lines_of_project(project["id"])
    if not reviewed:
        fail("ERR_NO_DOCUMENTED_COSTS",
             "no ALLOWED or PARTIALLY_ALLOWED cost line item is documented")

    setf(project, "eligible_cost_final_cents",
         project_eligible_cost_final(project, reviewed))
    setf(project, "status", "CLOSEOUT_REQUESTED")
    touch(project)
    return respond(project)


@bp.route(PREFIX + "/projects/<project_id>/closeout-certify", methods=["POST"])
def closeout_certify(project_id):
    actor = authenticate(("StateAuditor",))
    project = require("projects", project_id)
    payload = body()
    v_str(payload, "audit_finding", non_empty=False)

    if project["status"] != "CLOSEOUT_REQUESTED":
        fail("ERR_PROJECT_INVALID_STATE",
             "closeout certification requires status CLOSEOUT_REQUESTED")

    disaster = disaster_of_project(project)
    final_share, variance = closeout_reconciliation(project, disaster)
    setf(project, "federal_share_final_cents", final_share)
    setf(project, "closeout_variance_cents", variance)
    setf(project, "status", "CLOSED")

    if project["size_class"] == "LARGE" and variance < 0:
        create_deobligation(project, "CLOSEOUT_UNDERRUN", -variance, actor.user_id)
        recompute_project_deobligations(project)

    applicant = applicant_of_project(project)
    cascade_applicant(applicant)
    touch(project)
    return respond(project)
