"""No-further-action letters: drafting, signing and rescission."""

from flask import Blueprint

from db import assign, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, pagination,
                        req_datetime, req_str, require_project_owner, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("nfa_letters", __name__)

READ_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer")
SINGLE_READ_ROLES = READ_ROLES + ("Homeowner",)


@bp.post("/nfa-letters")
def create_letter():
    user_id, role = authenticate(("LicensedSiteProfessional",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    closing_date = req_datetime(payload, "closing_date")

    letter = create("nfa_letters", {
        "tank_project_id": project["id"],
        "closing_date": closing_date,
        "drafted_by_user_id": user_id,
        "issued_by_user_id": None,
        "issued_at": None,
        "rescinded_at": None,
        "rescission_reason": None,
        "status": "DRAFT",
    })
    return entity_response(letter, 201)


@bp.get("/nfa-letters")
def list_letters():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    status = filter_arg("status")
    rows = list(db.nfa_letters.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/nfa-letters/<letter_id>")
def read_letter(letter_id):
    user_id, role = authenticate(SINGLE_READ_ROLES)
    letter = resolve("nfa_letters", letter_id)
    project = db.tank_projects.get(letter["tank_project_id"])
    if project is not None:
        require_project_owner(project, user_id, role)
    return entity_response(letter)


@bp.post("/nfa-letters/<letter_id>/issue")
def issue_letter(letter_id):
    user_id, role = authenticate(("LicensedSiteProfessional",))
    letter = resolve("nfa_letters", letter_id)
    project = db.tank_projects.get(letter["tank_project_id"])

    if letter["status"] != "DRAFT":
        raise ApiError("ERR_NFA_STATE_INVALID")
    if project is None or project["status"] != "CLEARED":
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    # rule 10 — segregation of duties precedes the substantive closure checks.
    if user_id == letter["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    svc.recompute_blockers(project)
    if project["nfa_blockers"]:
        raise ApiError("ERR_NFA_BLOCKED")
    now = db.now()
    if letter["closing_date"] < now:
        raise ApiError("ERR_CLOSING_DATE_IN_PAST")

    assign(letter, "status", "ISSUED")
    assign(letter, "issued_at", now)
    assign(letter, "issued_by_user_id", user_id)
    assign(project, "status", "CLOSED_NFA")
    svc.recompute_blockers(project)
    return entity_response(letter)


@bp.post("/nfa-letters/<letter_id>/rescind")
def rescind_letter(letter_id):
    authenticate(("ComplianceOfficer",))
    letter = resolve("nfa_letters", letter_id)
    payload = body()
    reason = req_str(payload, "rescission_reason")
    project = db.tank_projects.get(letter["tank_project_id"])

    if letter["status"] != "ISSUED":
        raise ApiError("ERR_NFA_STATE_INVALID")
    if project is None or project["status"] != "CLOSED_NFA":
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    assign(letter, "status", "RESCINDED")
    assign(letter, "rescinded_at", db.now())
    assign(letter, "rescission_reason", reason)

    # Level 2 — the project reopens.
    assign(project, "status", "REMEDIATION_ACTIVE")
    assign(project, "contamination_class", "UNCLASSIFIED")
    assign(project, "remediation_volume_cubic_yards", None)
    assign(project, "remediation_volume_basis", None)
    assign(project, "remediation_started", True)

    # Level 3 — approved claims walk back to review.
    for claim in svc.children("trust_fund_claims", project["id"]):
        if claim["status"] != "APPROVED":
            continue
        assign(claim, "status", "UNDER_REVIEW")
        assign(claim, "reimbursed_amount_cents", 0)
        assign(claim, "decided_at", None)
        assign(claim, "unreimbursed_balance_cents", int(claim["eligible_amount_cents"]))
        findings = sorted(set(list(claim["eligibility_findings"])
                              + ["NFA_RESCINDED_REVALIDATION_REQUIRED"]))
        assign(claim, "eligibility_findings", findings)

    # Level 4 — cost recomputation re-runs the insurance waterfall.
    svc.recompute_cost(project)
    svc.recompute_blockers(project)
    return entity_response(letter)
