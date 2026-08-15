"""Club treasury transactions (PRD 3.1).

treasury_balance_cents always equals the sum of POSTED dues payments minus the
sum of APPROVED reimbursements for the club. Treasury transactions are audit
lines (PRD 2.4): no version, no updated_at. Both approvals and voids increment
the club's version.
"""

from flask import Blueprint

import db
import response
from middleware import (authenticate, resolve_caller, must_find,
                        new_audit_fields, touch)
from validation import get_body, as_enum, as_int_range, present
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INSUFFICIENT_TREASURY)
from services.serialize import treasury_transaction_view

bp = Blueprint("treasury_transactions", __name__)

TXN_KINDS = ("DUES_PAYMENT", "EXPENSE_REIMBURSEMENT")


@bp.post("/treasury-transactions")
def create_treasury_transaction():
    role, user_id = authenticate(["Volunteer"])
    body = get_body()
    # Priority 3: referenced identifiers exist (club_id).
    club = None
    if isinstance(body.get("club_id"), str):
        club = must_find("clubs", body["club_id"], "Club")
    resolve_caller(role, user_id)
    # Priority 14: request shape.
    club_id = present(body, "club_id")
    if not isinstance(club_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'club_id': must be a string")
    if club is None:
        club = must_find("clubs", club_id, "Club")
    txn_kind = as_enum(body, "txn_kind", TXN_KINDS)
    amount_cents = as_int_range(body, "amount_cents", lo=0)
    rec = new_audit_fields()
    rec.update({
        "club_id": club["id"],
        "txn_kind": txn_kind,
        "amount_cents": amount_cents,
        "txn_status": "POSTED",
    })
    db.table("treasury_transactions")[rec["id"]] = rec
    # A dues payment is POSTED on entry and credits the treasury immediately;
    # an expense reimbursement does not touch the balance until approved.
    if txn_kind == "DUES_PAYMENT":
        club["treasury_balance_cents"] += amount_cents
        touch(club)
    return response.success(treasury_transaction_view(rec), status=201)


@bp.get("/treasury-transactions/<tid>")
def get_treasury_transaction(tid):
    role, user_id = authenticate(["ProgramAdmin", "Volunteer"])
    rec = must_find("treasury_transactions", tid, "TreasuryTransaction")
    resolve_caller(role, user_id)
    return response.success(treasury_transaction_view(rec))


@bp.post("/treasury-transactions/<tid>/approve")
def approve_treasury_transaction(tid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("treasury_transactions", tid, "TreasuryTransaction")
    resolve_caller(role, user_id)
    # Priority 5: only a POSTED expense reimbursement is approvable; a dues
    # payment credits on entry and never passes through approval.
    if rec["txn_status"] != "POSTED" or rec["txn_kind"] != "EXPENSE_REIMBURSEMENT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a POSTED expense reimbursement can be approved")
    club = db.table("clubs").get(rec["club_id"])
    # Priority 12: treasury solvency -- approval must not drive the club's
    # treasury_balance_cents negative.
    if club is not None and club["treasury_balance_cents"] - rec["amount_cents"] < 0:
        raise ApiError(ERR_INSUFFICIENT_TREASURY, 422,
                       "Approving this reimbursement would drive the club treasury negative")
    rec["txn_status"] = "APPROVED"
    if club is not None:
        club["treasury_balance_cents"] -= rec["amount_cents"]
        touch(club)
    return response.success(treasury_transaction_view(rec))


@bp.post("/treasury-transactions/<tid>/void")
def void_treasury_transaction(tid):
    role, user_id = authenticate(["Volunteer"])
    rec = must_find("treasury_transactions", tid, "TreasuryTransaction")
    resolve_caller(role, user_id)
    # Priority 5: a transaction still in POSTED status may be voided.
    if rec["txn_status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a POSTED treasury transaction can be voided")
    rec["txn_status"] = "VOIDED"
    club = db.table("clubs").get(rec["club_id"])
    # Voiding a dues payment reverses the credit it applied; both approvals
    # and voids increment the club's version (PRD 3.1).
    if club is not None:
        if rec["txn_kind"] == "DUES_PAYMENT":
            club["treasury_balance_cents"] -= rec["amount_cents"]
        touch(club)
    return response.success(treasury_transaction_view(rec))
