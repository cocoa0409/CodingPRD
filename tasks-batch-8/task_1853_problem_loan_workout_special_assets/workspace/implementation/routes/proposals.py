"""Restructure proposal routes (PRD §3.3-§3.4)."""
from flask import Blueprint

import db
from auth import (
    ROLE_CREDIT_COMMITTEE, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_CASE_NOT_NEGOTIABLE, ERR_CASE_NOT_NEGOTIATION,
    ERR_COUNTER_NOT_MATERIAL, ERR_FORGIVENESS_CAP_EXCEEDED, ERR_NOT_FOUND,
    ERR_PROPOSAL_NOT_APPROVED, ERR_PROPOSAL_NOT_COMMITTEE_REVIEW,
    ERR_PROPOSAL_NOT_COUNTERED, ERR_PROPOSAL_NOT_DRAFT,
    ERR_PROPOSAL_NOT_UNDER_REVIEW, ERR_PROPOSAL_NOT_WITHDRAWABLE,
    ERR_STALE_VERSION,
)
from response import ok, paginate
from services import (
    book_charge_off, compute_tdr_flag, forgiveness_cap_exceeded, get_loan,
    get_proposal, proposal_out, proposals_of_case, sorted_rows,
)
from validate import as_enum, as_int, field, get_body, no_unknown

bp = Blueprint("proposals", __name__)

PROPOSAL_KINDS = ("FORBEARANCE", "MODIFICATION", "RESTRUCTURE")
TERM_FIELDS = (
    "concession_rate_bps", "term_extension_months",
    "principal_forgiveness_cents", "borrower_concession_cents",
)
PROPOSAL_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)
WITHDRAWABLE = ("DRAFT", "SUBMITTED", "UNDER_BORROWER_REVIEW", "COUNTERED")


def resolve(loanId, caseId, proposalId=None):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    proposal = None
    if proposalId is not None:
        proposal = get_proposal(proposalId)
        if proposal is None or proposal["case_id"] != caseId:
            raise ApiError(ERR_NOT_FOUND, 404, "Proposal not found")
    return loan, case, proposal


@bp.route("/loans/<loanId>/workout-cases/<caseId>/proposals", methods=["POST"])
def create_proposal(loanId, caseId):
    require_roles(ROLE_WORKOUT_OFFICER)
    loan, case, _ = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, set(TERM_FIELDS) | {"proposal_kind", "expected_case_version"})
    kind = as_enum(field(data, "proposal_kind"), "proposal_kind", PROPOSAL_KINDS)
    terms = {name: as_int(field(data, name), name, 0) for name in TERM_FIELDS}
    expected = as_int(field(data, "expected_case_version"), "expected_case_version")

    # state (priority 4): drafting only from NEGOTIATION or IMPAIRMENT_REVIEW
    if case["status"] not in ("NEGOTIATION", "IMPAIRMENT_REVIEW"):
        raise ApiError(
            ERR_CASE_NOT_NEGOTIABLE, 409,
            "Proposals may be drafted only from NEGOTIATION or IMPAIRMENT_REVIEW",
        )
    # OCC (priority 5)
    if expected != case["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale case version")

    proposal = db.stamp({
        "id": db.new_id(),
        "case_id": caseId,
        "proposal_kind": kind,
        "concession_rate_bps": terms["concession_rate_bps"],
        "term_extension_months": terms["term_extension_months"],
        "principal_forgiveness_cents": terms["principal_forgiveness_cents"],
        "borrower_concession_cents": terms["borrower_concession_cents"],
        "tdr_flag": False,
        "negotiation_round": 1,
        "status": "DRAFT",
    })
    STORE["proposals"][proposal["id"]] = proposal
    # drafting during IMPAIRMENT_REVIEW swings the case back to NEGOTIATION
    if case["status"] == "IMPAIRMENT_REVIEW":
        case["status"] = "NEGOTIATION"
    db.touch(case)
    return ok(proposal_out(proposal), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/proposals", methods=["GET"])
def list_proposals(loanId, caseId):
    require_roles(*PROPOSAL_READERS)
    resolve(loanId, caseId)
    rows = [proposal_out(p) for p in sorted_rows(proposals_of_case(caseId))]
    return paginate(rows)


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/submit",
    methods=["POST"],
)
def submit_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "DRAFT":
        raise ApiError(ERR_PROPOSAL_NOT_DRAFT, 409, "Proposal is not DRAFT")
    # DRAFT -> SUBMITTED -> UNDER_BORROWER_REVIEW (automatic on submit)
    proposal["status"] = "UNDER_BORROWER_REVIEW"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/counter",
    methods=["POST"],
)
def counter_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    data = get_body()
    no_unknown(data, set(TERM_FIELDS))
    terms = {name: as_int(field(data, name), name, 0) for name in TERM_FIELDS}
    if proposal["status"] != "UNDER_BORROWER_REVIEW":
        raise ApiError(
            ERR_PROPOSAL_NOT_UNDER_REVIEW, 409,
            "Counter requires UNDER_BORROWER_REVIEW",
        )
    if all(terms[name] == proposal[name] for name in TERM_FIELDS):
        raise ApiError(
            ERR_COUNTER_NOT_MATERIAL, 422,
            "Counter terms must differ in at least one term field",
        )
    for name in TERM_FIELDS:
        proposal[name] = terms[name]
    proposal["status"] = "COUNTERED"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/resubmit",
    methods=["POST"],
)
def resubmit_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "COUNTERED":
        raise ApiError(ERR_PROPOSAL_NOT_COUNTERED, 409, "Proposal is not COUNTERED")
    # COUNTERED -> RESUBMITTED -> UNDER_BORROWER_REVIEW; round increments
    proposal["negotiation_round"] += 1
    proposal["status"] = "UNDER_BORROWER_REVIEW"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/escalate-to-committee",
    methods=["POST"],
)
def escalate_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "UNDER_BORROWER_REVIEW":
        raise ApiError(
            ERR_PROPOSAL_NOT_UNDER_REVIEW, 409,
            "Escalation requires UNDER_BORROWER_REVIEW",
        )
    proposal["status"] = "COMMITTEE_REVIEW"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/committee-approve",
    methods=["POST"],
)
def committee_approve(loanId, caseId, proposalId):
    require_roles(ROLE_CREDIT_COMMITTEE)
    loan, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "COMMITTEE_REVIEW":
        raise ApiError(
            ERR_PROPOSAL_NOT_COMMITTEE_REVIEW, 409,
            "Committee approval requires COMMITTEE_REVIEW",
        )
    # fiscal cap (priority 9): cumulative forgiveness <= 25% of original, inclusive
    if forgiveness_cap_exceeded(
        loan["original_principal_cents"],
        loan["charged_off_principal_cents"],
        proposal["principal_forgiveness_cents"],
    ):
        raise ApiError(
            ERR_FORGIVENESS_CAP_EXCEEDED, 422,
            "Cumulative forgiveness would exceed 25% of original principal",
        )
    proposal["status"] = "APPROVED"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/committee-reject",
    methods=["POST"],
)
def committee_reject(loanId, caseId, proposalId):
    require_roles(ROLE_CREDIT_COMMITTEE)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "COMMITTEE_REVIEW":
        raise ApiError(
            ERR_PROPOSAL_NOT_COMMITTEE_REVIEW, 409,
            "Committee rejection requires COMMITTEE_REVIEW",
        )
    proposal["status"] = "REJECTED"
    db.touch(proposal)
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/consummate",
    methods=["POST"],
)
def consummate_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    loan, case, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] != "APPROVED":
        raise ApiError(ERR_PROPOSAL_NOT_APPROVED, 409, "Proposal is not APPROVED")
    if case["status"] != "NEGOTIATION":
        raise ApiError(ERR_CASE_NOT_NEGOTIATION, 409, "Case is not NEGOTIATION")

    # TDR determination (PRD §3.4): concession granted AND borrower in difficulty
    tdr_flag = compute_tdr_flag(loan, case, proposal)
    proposal["tdr_flag"] = tdr_flag
    proposal["status"] = "CONSUMMATED"
    db.touch(proposal)

    case["status"] = "IMPAIRMENT_REVIEW"
    case["tdr_status"] = "TDR_CONFIRMED" if tdr_flag else "TDR_REJECTED"
    db.touch(case)

    if tdr_flag and not loan["is_tdr"]:
        loan["is_tdr"] = True
        db.touch(loan)

    # forgiveness books a system charge-off through the same machinery
    if proposal["principal_forgiveness_cents"] > 0:
        book_charge_off(
            loan, case, proposal["principal_forgiveness_cents"], "PARTIAL_IMPAIRMENT"
        )
    return ok(proposal_out(proposal))


@bp.route(
    "/loans/<loanId>/workout-cases/<caseId>/proposals/<proposalId>/withdraw",
    methods=["POST"],
)
def withdraw_proposal(loanId, caseId, proposalId):
    require_roles(ROLE_WORKOUT_OFFICER)
    _, _, proposal = resolve(loanId, caseId, proposalId)
    if proposal["status"] not in WITHDRAWABLE:
        raise ApiError(
            ERR_PROPOSAL_NOT_WITHDRAWABLE, 409,
            "Proposal cannot be withdrawn from its current state",
        )
    proposal["status"] = "WITHDRAWN"
    db.touch(proposal)
    return ok(proposal_out(proposal))
