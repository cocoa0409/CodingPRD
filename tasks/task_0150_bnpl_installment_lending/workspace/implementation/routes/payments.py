"""Payment endpoints: create/get/list (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import (
    authenticate, require_role, require_borrower_owns, require_merchant_owns,
)
from response import success
from services import engine
from services.engine import stamp_new, touch, serialize_payment
from routes.common import (
    get_json_body, require_int, parse_pagination, paginate, sort_by_created,
    require_loan, require_payment,
)

bp = Blueprint("payments", __name__)

VALID_SOURCES = {"MANUAL", "AUTOPAY"}


def make_payment(loan, amount_cents, source):
    """Create a payment, run oldest-due-first allocation + cascade. Returns the
    payment record (already stored)."""
    allocation, unapplied = engine.allocate_payment(loan, amount_cents)
    payment = {
        "loan_id": loan["id"],
        "amount_cents": amount_cents,
        "source": source,
        "allocation": allocation,
        "unapplied_cents": unapplied,
    }
    stamp_new(payment)
    db.payments[payment["id"]] = payment

    # Recompute posture, bump loan, possibly bubble to PAID_OFF.
    touch(loan)
    engine.recompute_posture(loan)
    engine.maybe_payoff(loan)
    engine.reconcile_borrower(loan["borrower_id"])
    return payment


@bp.route("/payments", methods=["POST"])
def create_payment():
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    body = get_json_body()

    loan_id = body.get("loan_id")
    if not loan_id or not isinstance(loan_id, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'loan_id'.")
    loan = require_loan(loan_id)
    require_borrower_owns(role, uid, loan["borrower_id"])

    amount_cents = require_int(body, "amount_cents", gt=0)
    source = body.get("source", "MANUAL")
    if source is None:
        source = "MANUAL"
    if source not in VALID_SOURCES:
        raise err("ERR_INVALID_REQUEST", "source must be MANUAL or AUTOPAY.")

    payment = make_payment(loan, amount_cents, source)
    return success(serialize_payment(payment), status=201)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    p = require_payment(payment_id)
    loan = db.loans.get(p["loan_id"])
    if loan is not None:
        require_borrower_owns(role, uid, loan["borrower_id"])
        require_merchant_owns(role, uid, loan["merchant_id"])
    return success(serialize_payment(p), status=200)


@bp.route("/payments", methods=["GET"])
def list_payments():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    limit, offset = parse_pagination()
    loan_filter = request.args.get("loan_id")

    rows = list(db.payments.values())
    if loan_filter is not None:
        rows = [p for p in rows if p["loan_id"] == loan_filter]
    if role == "Borrower":
        rows = [p for p in rows
                if (db.loans.get(p["loan_id"]) or {}).get("borrower_id") == uid]
    elif role == "Merchant":
        rows = [p for p in rows
                if (db.loans.get(p["loan_id"]) or {}).get("merchant_id") == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_payment(p) for p in page],
                   status=200, pagination=meta)
