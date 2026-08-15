"""DrawRequest and Repayment endpoints (the seasonal cycle, PRD 3.6)."""
from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_owner, require_role
from response import ok_list, ok_object
from routes.loans import get_loan_or_404
from serialize import list_response, ser_draw, ser_repayment
from services.core import (TERMINAL_LOAN_STATES, accrue_interest,
                           available_credit_cents, has_assigned_active_policy,
                           projected_accrued, standard_cascade, stamp_new,
                           touch)
from util import as_enum, as_pos_int, as_str, body, need, new_id

bp = Blueprint("draws", __name__)

DRAW_PURPOSES = ["SEED", "FERTILIZER", "FUEL", "LABOR", "EQUIPMENT_REPAIR",
                 "LIVING_EXPENSE"]
REPAYMENT_SOURCES = ["HARVEST_PROCEEDS", "INSURANCE_INDEMNITY", "OTHER"]


def get_draw_or_404(did):
    d = STORE.draws.get(did)
    if d is None:
        raise_err("ERR_NOT_FOUND", "Draw request not found")
    return d


def get_repayment_or_404(rid):
    r = STORE.repayments.get(rid)
    if r is None:
        raise_err("ERR_NOT_FOUND", "Repayment not found")
    return r


# ---------------------------------------------------------------------------
# Draw requests
# ---------------------------------------------------------------------------

@bp.route("/draw-requests", methods=["POST"])
def create_draw():
    uid, role = auth()
    require_role(role, ["Borrower", "LoanOfficer"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    amount = as_pos_int(need(b, "amount_cents"), "amount_cents")
    purpose = as_enum(need(b, "purpose"), "purpose", DRAW_PURPOSES)
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    if role == "Borrower":
        require_owner(loan["borrower_id"] == uid)
        borrower = STORE.borrowers.get(loan["borrower_id"])
        if borrower is not None and borrower["status"] == "SUSPENDED":
            raise_err("ERR_BORROWER_SUSPENDED",
                      "Suspended borrowers cannot create draw requests")
    draw = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "amount_cents": amount,
        "purpose": purpose,
        "disbursement_date": None,
        "status": "REQUESTED",
    })
    STORE.draws[draw["id"]] = draw
    return ok_object(ser_draw(draw), code=201)


@bp.route("/draw-requests/<did>", methods=["GET"])
def get_draw(did):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_draw(get_draw_or_404(did)))


@bp.route("/draw-requests", methods=["GET"])
def list_draws():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.draws.values(), ser_draw,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/draw-requests/<did>/approve", methods=["POST"])
def approve_draw(did):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    draw = get_draw_or_404(did)
    if draw["status"] != "REQUESTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED draw can be approved")
    loan = get_loan_or_404(draw["loan_account_id"])
    # Fixed gate order: loan ACTIVE, posture, insurance, availability.
    if loan["status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE", "Draw approval requires an ACTIVE loan")
    if loan["payment_posture"] in ("DELINQUENT", "DEFAULT"):
        raise_err("ERR_LOAN_POSTURE_BLOCKS_DRAWS",
                  "Payment posture blocks draw approval")
    if not has_assigned_active_policy(loan):
        raise_err("ERR_INSURANCE_NOT_ASSIGNED",
                  "No ACTIVE policy ASSIGNED to this loan")
    if draw["amount_cents"] > available_credit_cents(loan):
        raise_err("ERR_DRAW_EXCEEDS_AVAILABILITY",
                  "Draw amount exceeds available credit")
    draw["status"] = "APPROVED"
    touch(draw)
    return ok_object(ser_draw(draw))


@bp.route("/draw-requests/<did>/disburse", methods=["POST"])
def disburse_draw(did):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    draw = get_draw_or_404(did)
    if draw["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED draw can be disbursed")
    loan = get_loan_or_404(draw["loan_account_id"])
    if loan["status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE", "Draw disbursement requires an ACTIVE loan")
    accrue_interest(loan)
    loan["outstanding_principal_cents"] += draw["amount_cents"]
    draw["disbursement_date"] = get_clock()
    draw["status"] = "DISBURSED"
    touch(draw)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_draw(draw))


@bp.route("/draw-requests/<did>/deny", methods=["POST"])
def deny_draw(did):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    draw = get_draw_or_404(did)
    if draw["status"] != "REQUESTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a REQUESTED draw can be denied")
    draw["status"] = "DENIED"
    touch(draw)
    return ok_object(ser_draw(draw))


@bp.route("/draw-requests/<did>/cancel", methods=["POST"])
def cancel_draw(did):
    uid, role = auth()
    require_role(role, ["Borrower"])
    draw = get_draw_or_404(did)
    loan = get_loan_or_404(draw["loan_account_id"])
    require_owner(loan["borrower_id"] == uid)
    if draw["status"] not in ("REQUESTED", "APPROVED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a REQUESTED or APPROVED draw can be cancelled")
    draw["status"] = "CANCELLED"
    touch(draw)
    return ok_object(ser_draw(draw))


@bp.route("/draw-requests/<did>/rescind", methods=["POST"])
def rescind_draw(did):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    draw = get_draw_or_404(did)
    if draw["status"] != "DISBURSED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DISBURSED draw can be rescinded")
    loan = get_loan_or_404(draw["loan_account_id"])
    if loan["status"] != "ACTIVE":
        raise_err("ERR_LOAN_NOT_ACTIVE", "Draw rescission requires an ACTIVE loan")
    if draw["disbursement_date"] is None or \
            get_clock().date() != draw["disbursement_date"].date():
        raise_err("ERR_RESCIND_WINDOW_CLOSED",
                  "Rescission is only allowed on the disbursement UTC date")
    loan["outstanding_principal_cents"] -= draw["amount_cents"]
    draw["status"] = "RESCINDED"
    touch(draw)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_draw(draw))


# ---------------------------------------------------------------------------
# Repayments
# ---------------------------------------------------------------------------

@bp.route("/repayments", methods=["POST"])
def create_repayment():
    uid, role = auth()
    require_role(role, ["Borrower"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    amount = as_pos_int(need(b, "amount_cents"), "amount_cents")
    source = as_enum(need(b, "source"), "source", REPAYMENT_SOURCES)
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    require_owner(loan["borrower_id"] == uid)
    if loan["status"] not in ("ACTIVE", "RESTRUCTURING"):
        raise_err("ERR_LOAN_NOT_ACTIVE",
                  "Repayment requires loan status ACTIVE or RESTRUCTURING")
    # Project the accrual to the clock before the ceiling check; apply after.
    accrued_now = projected_accrued(loan)
    if amount > accrued_now + loan["outstanding_principal_cents"]:
        raise_err("ERR_PAYMENT_EXCEEDS_OUTSTANDING",
                  "Repayment exceeds accrued interest plus outstanding principal")
    accrue_interest(loan)
    applied_interest = min(amount, loan["accrued_interest_cents"])
    applied_principal = amount - applied_interest
    loan["accrued_interest_cents"] -= applied_interest
    loan["outstanding_principal_cents"] -= applied_principal
    rep = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "amount_cents": amount,
        "source": source,
        "applied_interest_cents": applied_interest,
        "applied_principal_cents": applied_principal,
        "status": "APPLIED",
    })
    STORE.repayments[rep["id"]] = rep
    if (loan["status"] == "ACTIVE" and loan["outstanding_principal_cents"] == 0
            and loan["accrued_interest_cents"] == 0):
        loan["status"] = "PAID_OFF"
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_repayment(rep), code=201)


@bp.route("/repayments/<rid>", methods=["GET"])
def get_repayment(rid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_repayment(get_repayment_or_404(rid)))


@bp.route("/repayments", methods=["GET"])
def list_repayments():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.repayments.values(), ser_repayment,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/repayments/<rid>/reverse", methods=["POST"])
def reverse_repayment(rid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    rep = get_repayment_or_404(rid)
    if rep["status"] != "APPLIED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPLIED repayment can be reversed")
    loan = get_loan_or_404(rep["loan_account_id"])
    if loan["status"] in TERMINAL_LOAN_STATES:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Repayment reversal is not allowed on a terminal loan")
    accrue_interest(loan)
    loan["accrued_interest_cents"] += rep["applied_interest_cents"]
    loan["outstanding_principal_cents"] += rep["applied_principal_cents"]
    rep["status"] = "REVERSED"
    touch(rep)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_repayment(rep))
