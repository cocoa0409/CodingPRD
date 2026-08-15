"""Disbursement CRUD + state machine + QSF ledger."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CLAIM_INVALID_STATE,
    ERR_DISBURSEMENT_INVALID_STATE,
    ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_NEGATIVE_NET_AWARD,
    ERR_QSF_INSUFFICIENT_FUNDS,
)
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    bump,
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_claim,
    resolve_disbursement,
    sort_by_created_at,
    utc_now_iso,
)
from services.calculations import disbursement_allocation, qsf_reconciliation

bp = Blueprint("disbursements", __name__)

DISB_READ_ROLES = (
    "ProgramAdministrator",
    "DisbursementApprover",
    "ClaimantRole",
)


@bp.route("/settlement-programs/<pid>/claims/<cid>/prepare-disbursement", methods=["POST"])
def prepare_disbursement(pid, cid):
    user_id, role = require_role("DisbursementApprover")
    prog, claim = resolve_claim(pid, cid)

    if claim["status"] != "LIENS_RESOLVED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, "Claim must be LIENS_RESOLVED to prepare disbursement", 409)

    # Fund sufficiency check BEFORE net-award non-negativity (per PRD section 2.9)
    if prog["qsf_remaining_cents"] < claim["net_award_cents"]:
        raise ApiError(ERR_QSF_INSUFFICIENT_FUNDS, "QSF has insufficient funds for net award", 402)

    if claim["net_award_cents"] < 0:
        raise ApiError(ERR_NEGATIVE_NET_AWARD, "net_award_cents < 0", 422)

    # Reserve from QSF
    claim["qsf_reservation_cents"] = claim["net_award_cents"]
    claim["status"] = "READY_FOR_DISBURSEMENT"
    claim["prepare_disbursement_user_id"] = user_id

    # Run allocation waterfall
    claimant = db.claimants[claim["claimant_id"]]
    disbursement_allocation(claim, claimant)

    # Recompute QSF
    qsf_reconciliation(prog)
    bump(prog)

    bump(claim)
    return success_envelope(claim, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/disbursements", methods=["GET"])
def list_disbursements(pid, cid):
    user_id, role = require_role(*DISB_READ_ROLES)
    prog, claim = resolve_claim(pid, cid)
    limit, offset = get_pagination()

    items = [d for d in db.disbursements.values() if d["claim_id"] == cid]

    state_filter = request.args.get("state")
    if state_filter:
        items = [d for d in items if d["state"] == state_filter]

    claim_filter = request.args.get("claim_id")
    if claim_filter:
        items = [d for d in items if d["claim_id"] == claim_filter]

    items = sort_by_created_at(items)
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>/claims/<cid>/disbursements/<did>", methods=["GET"])
def get_disbursement(pid, cid, did):
    user_id, role = require_role(*DISB_READ_ROLES)
    prog, claim, disb = resolve_disbursement(pid, cid, did)
    return success_envelope(disb, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/disbursements/<did>/approve", methods=["POST"])
def approve_disbursement(pid, cid, did):
    user_id, role = require_role("DisbursementApprover")
    prog, claim, disb = resolve_disbursement(pid, cid, did)

    if disb["state"] != "PENDING":
        raise ApiError(ERR_DISBURSEMENT_INVALID_STATE, "Disbursement must be PENDING to approve", 409)

    # Segregation of duties: approver != prepare-disbursement caller
    if user_id == claim.get("prepare_disbursement_user_id"):
        raise ApiError(ERR_SELF_APPROVAL_FORBIDDEN, "Approver must differ from the user who called prepare-disbursement", 403)

    disb["state"] = "APPROVED"
    bump(disb)
    return success_envelope(disb, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/disbursements/<did>/release", methods=["POST"])
def release_disbursement(pid, cid, did):
    user_id, role = require_role("DisbursementApprover")
    prog, claim, disb = resolve_disbursement(pid, cid, did)

    if disb["state"] != "APPROVED":
        raise ApiError(ERR_DISBURSEMENT_INVALID_STATE, "Disbursement must be APPROVED to release", 409)

    disb["state"] = "RELEASED"
    disb["released_at"] = prog["current_utc"]
    bump(disb)

    # Recompute QSF
    qsf_reconciliation(prog)
    bump(prog)

    # Check if all siblings are RELEASED or VOIDED -> claim becomes DISBURSED
    siblings = [d for d in db.disbursements.values() if d["claim_id"] == cid]
    all_done = all(d["state"] in ("RELEASED", "VOIDED") for d in siblings)
    if all_done and claim["status"] == "READY_FOR_DISBURSEMENT":
        claim["status"] = "DISBURSED"
        bump(claim)

    return success_envelope(disb, 200, "object")


@bp.route("/settlement-programs/<pid>/claims/<cid>/disbursements/<did>/void", methods=["POST"])
def void_disbursement(pid, cid, did):
    user_id, role = require_role("DisbursementApprover")
    prog, claim, disb = resolve_disbursement(pid, cid, did)

    if disb["state"] != "PENDING":
        raise ApiError(ERR_DISBURSEMENT_INVALID_STATE, "Disbursement must be PENDING to void", 409)

    disb["state"] = "VOIDED"
    bump(disb)

    # PRD §3.8: the claim crosses to DISBURSED automatically when every
    # sibling disbursement is RELEASED or VOIDED — voiding the last pending
    # sibling triggers the same cascade as releasing it. Once the claim
    # leaves READY_FOR_DISBURSEMENT, its qsf_reservation_cents no longer
    # counts against the fund, which is how the void refunds the balance.
    siblings = [d for d in db.disbursements.values() if d["claim_id"] == cid]
    all_done = all(d["state"] in ("RELEASED", "VOIDED") for d in siblings)
    if all_done and claim["status"] == "READY_FOR_DISBURSEMENT":
        claim["status"] = "DISBURSED"
        bump(claim)

    # Recompute QSF (refund happens automatically via reconciliation)
    qsf_reconciliation(prog)
    bump(prog)

    return success_envelope(disb, 200, "object")
