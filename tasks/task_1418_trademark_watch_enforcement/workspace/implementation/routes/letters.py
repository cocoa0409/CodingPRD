"""CeaseDesistLetter endpoints (PRD 3.6)."""

from flask import Blueprint

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES, ERR_ENFORCEMENT_BARRED, ERR_MATTER_NOT_ACTIVE,
    ERR_RESPONSE_WINDOW_OPEN, ERR_BUDGET_EXCEEDED,
)
from middleware import require_roles, enforce_client_scope
from response import success
from services import domain
from services.domain import (
    ser_letter, settlement_installments, auto_docket_response_deadline,
    client_budget_spent, LIVE_AGREEMENT_STATES, ISSUE_FEE_CENTS, REISSUE_FEE_CENTS,
)
from util import (
    get_payload, reject_unknown_fields, require_enum, optional_int,
    touch, fmt_business, business_day_count, parse_dt,
)
from routes.common import do_list

bp = Blueprint("cease_desist_letters", __name__)

READ_ROLES = ("Paralegal", "AssociateAttorney", "PartnerAttorney", "ClientContact")
DECISIONS = ("APPROVED", "SENT_BACK")
RESPONSE_OUTCOMES = ("COMPLIED", "REFUSED", "NEGOTIATION_STARTED")


def _get_letter(letter_id):
    letter = db.cease_desist_letters.get(letter_id)
    if letter is None:
        raise_error(ERR_NOT_FOUND, "CeaseDesistLetter not found")
    return letter


def _scope(user_id, role, letter):
    enforce_client_scope(user_id, role,
                         domain.client_id_for_resource("cease_desist_letter", letter))


def _budget_remaining(client_id):
    client = db.clients[client_id]
    return client["enforcement_budget_cents"] - client_budget_spent(client_id)


@bp.route("/brand/cease-desist-letters", methods=["GET"])
def list_letters():
    user_id, role = require_roles(*READ_ROLES)
    return do_list(db.cease_desist_letters.values(), ser_letter,
                   [("enforcement_matter_id", "enforcement_matter_id", None),
                    ("status", "status", None)],
                   user_id, role, "cease_desist_letter")


@bp.route("/brand/cease-desist-letters/<letter_id>", methods=["GET"])
def get_letter(letter_id):
    user_id, role = require_roles(*READ_ROLES)
    letter = _get_letter(letter_id)
    _scope(user_id, role, letter)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/submit-review", methods=["POST"])
def submit_review(letter_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    letter = _get_letter(letter_id)
    if letter["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "submit-review is declared only from DRAFT")
    letter["status"] = "PENDING_REVIEW"
    touch(letter)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/approve", methods=["POST"])
def approve_letter(letter_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"decision"})
    decision = require_enum(body, "decision", DECISIONS)
    letter = _get_letter(letter_id)
    if letter["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "approve is declared only from PENDING_REVIEW")
    # Segregation of duties: the approver / sender-back must differ from the drafter.
    if user_id == letter["drafted_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "Letter approver must differ from drafted_by_user_id")
    if decision == "APPROVED":
        letter["approved_by_user_id"] = user_id
        letter["status"] = "APPROVED"
    else:  # SENT_BACK returns the letter to DRAFT with no approval stamp.
        letter["status"] = "DRAFT"
    touch(letter)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/issue", methods=["POST"])
def issue_letter(letter_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    letter = _get_letter(letter_id)
    if letter["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "issue is declared only from APPROVED")
    matter = db.enforcement_matters.get(letter["enforcement_matter_id"])
    # Enforcement bar (priority 8): a live coexistence agreement on the
    # matter's record bars cease-and-desist issuance.
    barred = any(
        a["trademark_record_id"] == matter["trademark_record_id"]
        and a["status"] in LIVE_AGREEMENT_STATES
        for a in db.coexistence_agreements.values()
    )
    if barred:
        raise_error(ERR_ENFORCEMENT_BARRED,
                    "A live CoexistenceAgreement on the record bars issuance")
    # The matter must still be ACTIVE (priority 18).
    if matter["status"] != "ACTIVE":
        raise_error(ERR_MATTER_NOT_ACTIVE, "The letter's matter is not ACTIVE")
    # Fiscal (priority 23): the remaining budget must cover the issue fee.
    if _budget_remaining(matter["client_id"]) < ISSUE_FEE_CENTS:
        raise_error(ERR_BUDGET_EXCEEDED, "budget_remaining_cents does not cover the issue fee")
    now = db.clock.now()
    letter["status"] = "ISSUED"
    letter["_ever_issued"] = True
    letter["issued_at"] = fmt_business(now)
    letter["response_due_at"] = fmt_business(
        business_day_count(now, letter["response_due_days"]))
    touch(letter)
    touch(matter)  # accrued_fees_cents derivation changed for this matter
    # Auto-docket the RESPONSE_DUE deadline anchored at issuance.
    auto_docket_response_deadline(matter, letter, now)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/record-response", methods=["POST"])
def record_response(letter_id):
    user_id, role = require_roles("Paralegal")
    body = get_payload()
    reject_unknown_fields(body, {"response_outcome"})
    outcome = require_enum(body, "response_outcome", RESPONSE_OUTCOMES)
    letter = _get_letter(letter_id)
    if letter["status"] == "ISSUED":
        if outcome == "COMPLIED":
            letter["status"] = "COMPLIED"
        elif outcome == "REFUSED":
            letter["status"] = "REFUSED"
        else:  # NEGOTIATION_STARTED
            letter["status"] = "NEGOTIATING"
    elif letter["status"] == "NEGOTIATING":
        if outcome == "COMPLIED":
            letter["status"] = "COMPLIED"
        elif outcome == "REFUSED":
            letter["status"] = "REFUSED"
        else:
            raise_error(ERR_INVALID_STATE,
                        "NEGOTIATION_STARTED is not declared from NEGOTIATING")
    else:
        raise_error(ERR_INVALID_STATE,
                    "record-response is declared only from ISSUED / NEGOTIATING")
    # Compliance with an agreed settlement triggers installment computation:
    # floor division; the remainder lands on the FINAL installment.
    if letter["status"] == "COMPLIED" and letter["settlement_amount_cents"] is not None:
        letter["installment_schedule"] = settlement_installments(
            letter["settlement_amount_cents"], letter["installment_count"])
    touch(letter)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/reissue", methods=["POST"])
def reissue_letter(letter_id):
    user_id, role = require_roles("AssociateAttorney")
    body = get_payload()
    reject_unknown_fields(body, {"response_due_days"})
    response_due_days = optional_int(body, "response_due_days", default=None, minimum=1)
    letter = _get_letter(letter_id)
    if letter["status"] != "NEGOTIATING":
        raise_error(ERR_INVALID_STATE, "reissue is declared only from NEGOTIATING")
    matter = db.enforcement_matters.get(letter["enforcement_matter_id"])
    # Manual reissues are subject to the affordability check (PRD 3.6).
    if _budget_remaining(matter["client_id"]) < REISSUE_FEE_CENTS:
        raise_error(ERR_BUDGET_EXCEEDED, "budget_remaining_cents does not cover the reissue fee")
    now = db.clock.now()
    letter["status"] = "ISSUED"
    letter["reissue_count"] += 1
    if response_due_days is not None:
        letter["response_due_days"] = response_due_days
    letter["issued_at"] = fmt_business(now)
    letter["response_due_at"] = fmt_business(
        business_day_count(now, letter["response_due_days"]))
    touch(letter)
    touch(matter)  # accrued fee derivation changed
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/escalate-litigation", methods=["POST"])
def escalate_litigation(letter_id):
    user_id, role = require_roles("PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    letter = _get_letter(letter_id)
    if letter["status"] == "ISSUED":
        # From ISSUED this requires the response window to have fully passed.
        if not (db.clock.now() > parse_dt(letter["response_due_at"])):
            raise_error(ERR_RESPONSE_WINDOW_OPEN,
                        "escalate-litigation from ISSUED requires current_utc > response_due_at")
        letter["status"] = "ESCALATED_LITIGATION"
    elif letter["status"] == "REFUSED":
        letter["status"] = "ESCALATED_LITIGATION"
    else:
        raise_error(ERR_INVALID_STATE,
                    "escalate-litigation is declared only from ISSUED / REFUSED")
    touch(letter)
    return success(ser_letter(letter), 200)


@bp.route("/brand/cease-desist-letters/<letter_id>/void", methods=["POST"])
def void_letter(letter_id):
    user_id, role = require_roles("AssociateAttorney", "PartnerAttorney")
    body = get_payload()
    reject_unknown_fields(body, set())
    letter = _get_letter(letter_id)
    if letter["status"] in ("DRAFT", "PENDING_REVIEW", "APPROVED"):
        letter["status"] = "VOID"
    elif letter["status"] == "ISSUED":
        # Voiding an ISSUED letter is a rescission reserved to a PartnerAttorney.
        if role != "PartnerAttorney":
            raise_error(ERR_FORBIDDEN, "rescinding an ISSUED letter requires PartnerAttorney")
        letter["status"] = "VOID"
        # Fee reversal happens by construction: VOID letters contribute nothing
        # to the budget ledger or the matter's accrued fees (PRD 2.6).
        matter = db.enforcement_matters.get(letter["enforcement_matter_id"])
        if matter is not None:
            touch(matter)
    else:
        raise_error(ERR_INVALID_STATE,
                    "void is declared only from DRAFT / PENDING_REVIEW / APPROVED / ISSUED")
    touch(letter)
    return success(ser_letter(letter), 200)
