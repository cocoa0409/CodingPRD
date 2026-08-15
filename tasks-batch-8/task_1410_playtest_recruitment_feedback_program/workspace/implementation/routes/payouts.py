"""Incentive payout endpoints with segregation of duties and budget control."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import get_payload, require_string, stamp_new, touch
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_PARTICIPANT_NOT_ACTIVE, ERR_BUDGET_EXCEEDED, ERR_NO_COMPENSABLE_ACTIVITY,
    ERR_DUPLICATE_PAYOUT,
)
from services.serializers import public
from services.calculations import (
    incentive_amount_provisional, incentive_amount_final, incentive_amounts,
)

bp = make_blueprint("payouts")

_NON_VOID_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "ISSUED")


def _get_payout(pid):
    p = db.payouts.get(pid)
    if p is None:
        raise_error(ERR_NOT_FOUND, "Incentive payout not found")
    return p


@bp.route("/playtests/incentive-payouts", methods=["POST"])
def create_payout():
    user_id, _role = require_roles("IncentiveOfficer")
    body = get_payload()
    study_id = require_string(body, "study_id")
    participant_id = require_string(body, "participant_id")

    study = db.studies.get(study_id)
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    participant = db.participants.get(participant_id)
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")

    # Referential/capacity: at least one ATTENDED booking in the study
    session_ids = {s["id"] for s in db.sessions.values() if s["study_id"] == study_id}
    has_attended = any(
        b for b in db.bookings.values()
        if b["participant_id"] == participant_id
        and b["session_id"] in session_ids
        and b["status"] == "ATTENDED"
    )
    if not has_attended:
        raise_error(ERR_NO_COMPENSABLE_ACTIVITY,
                    "Payout requires at least one ATTENDED booking in the study")

    # Uniqueness: at most one non-VOID payout per (study, participant)
    for p in db.payouts.values():
        if (p["study_id"] == study_id and p["participant_id"] == participant_id
                and p["status"] in _NON_VOID_STATUSES):
            raise_error(ERR_DUPLICATE_PAYOUT,
                        "A non-VOID payout already exists for this study and participant")

    provisional = incentive_amount_provisional(study_id, participant_id)
    rec = {
        "study_id": study_id,
        "participant_id": participant_id,
        "amount_provisional_cents": provisional,
        "amount_final_cents": None,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "issued_by_user_id": None,
        "rejection_reason": None,
    }
    stamp_new(rec)
    db.payouts[rec["id"]] = rec
    return success(public(rec, "payout"), status=201)


@bp.route("/playtests/incentive-payouts", methods=["GET"])
def list_payouts():
    require_roles("ResearchOpsAdmin", "IncentiveOfficer")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.payouts.values())
    for param in ("study_id", "participant_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if str(p.get(param)) == v]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(p, "payout") for p in page], status=200, pagination=pagination)


@bp.route("/playtests/incentive-payouts/<pid>", methods=["GET"])
def get_payout(pid):
    require_roles("ResearchOpsAdmin", "IncentiveOfficer")
    p = _get_payout(pid)
    return success(public(p, "payout"), status=200)


@bp.route("/playtests/incentive-payouts/<pid>/submit", methods=["POST"])
def submit_payout(pid):
    require_roles("IncentiveOfficer")
    p = _get_payout(pid)
    if p["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Payout must be DRAFT to submit")
    p["status"] = "PENDING_APPROVAL"
    touch(p)
    return success(public(p, "payout"), status=200)


@bp.route("/playtests/incentive-payouts/<pid>/resubmit", methods=["POST"])
def resubmit_payout(pid):
    require_roles("IncentiveOfficer")
    p = _get_payout(pid)
    if p["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE, "Payout must be REJECTED to resubmit")
    p["status"] = "PENDING_APPROVAL"
    touch(p)
    return success(public(p, "payout"), status=200)


@bp.route("/playtests/incentive-payouts/<pid>/approve", methods=["POST"])
def approve_payout(pid):
    user_id, _role = require_roles("IncentiveOfficer")
    p = _get_payout(pid)
    # State check outranks the budget check
    if p["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Payout must be PENDING_APPROVAL to approve")
    # Segregation of duties
    if user_id == p["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "The payout creator cannot approve it")
    participant = db.participants.get(p["participant_id"])
    if participant is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")
    if participant["status"] == "BANNED":
        raise_error(ERR_PARTICIPANT_NOT_ACTIVE, "Participant is BANNED")
    study = db.studies.get(p["study_id"])
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")

    # Fiscal gate evaluated LAST, pinned evaluation order:
    final = incentive_amount_final(p["study_id"], p["participant_id"])
    if study.get("budget_committed_cents", 0) + final > study["incentive_budget_cents"]:
        raise_error(ERR_BUDGET_EXCEEDED, "Budget would be exceeded by this approval")
    p["amount_final_cents"] = final
    study["budget_committed_cents"] = study.get("budget_committed_cents", 0) + final
    touch(study)
    p["approved_by_user_id"] = user_id
    p["status"] = "APPROVED"
    touch(p)
    return success(public(p, "payout"), status=200)


@bp.route("/playtests/incentive-payouts/<pid>/reject", methods=["POST"])
def reject_payout(pid):
    require_roles("IncentiveOfficer")
    p = _get_payout(pid)
    body = get_payload()
    reason = require_string(body, "rejection_reason")
    if p["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Payout must be PENDING_APPROVAL to reject")
    p["status"] = "REJECTED"
    p["rejection_reason"] = reason
    touch(p)
    return success(public(p, "payout"), status=200)


@bp.route("/playtests/incentive-payouts/<pid>/issue", methods=["POST"])
def issue_payout(pid):
    user_id, _role = require_roles("IncentiveOfficer")
    p = _get_payout(pid)
    if p["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Payout must be APPROVED to issue")
    if user_id == p["approved_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "The payout approver cannot issue it")
    study = db.studies.get(p["study_id"])
    if study is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    final = p.get("amount_final_cents") or 0
    study["budget_spent_cents"] = study.get("budget_spent_cents", 0) + final
    touch(study)
    p["issued_by_user_id"] = user_id
    p["status"] = "ISSUED"
    touch(p)
    return success(public(p, "payout"), status=200)
