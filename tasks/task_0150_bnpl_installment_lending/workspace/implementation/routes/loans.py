"""Loan endpoints: activation, default, cancel, get/list (PRD §3.4, §3.10)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from middleware import (
    authenticate, require_role, require_borrower_owns, require_merchant_owns,
)
from response import success
from services import engine
from services import calculations as calc
from services.engine import (
    stamp_new, touch, serialize_loan, _parse_iso,
)
from routes.common import (
    get_json_body, require_int, parse_pagination, paginate, sort_by_created,
    require_application, require_loan,
)

bp = Blueprint("loans", __name__)


@bp.route("/loans", methods=["POST"])
def activate_loan():
    uid, role = authenticate()
    require_role(role, {"Borrower"})
    body = get_json_body()

    application_id = body.get("application_id")
    if not application_id or not isinstance(application_id, str):
        raise err("ERR_INVALID_REQUEST", "Missing required field 'application_id'.")
    app = require_application(application_id)
    require_borrower_owns(role, uid, app["borrower_id"])

    # State: application must be APPROVED.
    if app["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE",
                  "Application must be APPROVED to activate.")

    # Reg Z gate (priority 7): an accepted disclosure must exist (ERR_DISCLOSURE_NOT_ACCEPTED).
    accepted_disclosures = [
        d for d in db.disclosure_acceptances.values()
        if d["application_id"] == application_id and d["accepted"] is True
    ]
    if not accepted_disclosures:
        raise err("ERR_DISCLOSURE_NOT_ACCEPTED",
                  "An accepted Reg Z disclosure is required to activate.")

    borrower = db.borrowers[app["borrower_id"]]
    merchant = db.merchants[app["merchant_id"]]

    # Fiscal re-check (priority 11): available credit >= financed principal.
    outstanding = engine.compute_borrower_outstanding(borrower["id"])
    avail = max(0, borrower["eligible_credit_limit_cents"] - outstanding)
    if avail < app["financed_principal_cents"]:
        raise err("ERR_INSUFFICIENT_CREDIT",
                  "Available credit is insufficient to activate the loan.")

    # Activation: drive Application -> ACTIVATED, create the Loan.
    app["status"] = "ACTIVATED"
    touch(app)

    loan = {
        "application_id": app["id"],
        "borrower_id": app["borrower_id"],
        "merchant_id": app["merchant_id"],
        "financed_principal_cents": app["financed_principal_cents"],
        "apr_bps": app["apr_bps"],
        "finance_charge_cents": app["finance_charge_cents"],
        "remaining_principal_cents": app["financed_principal_cents"],
        "status": "ACTIVE",
        "delinquency_status": "CURRENT",
    }
    stamp_new(loan)
    db.loans[loan["id"]] = loan

    # Installment schedule (activation date = loan.created_at as UTC date).
    activation_dt = _parse_iso(loan["created_at"])
    schedule = calc.build_schedule(
        loan["financed_principal_cents"], app["plan_type"], app.get("term_months"))
    for row in schedule:
        due_dt = activation_dt + timedelta(days=row["offset_days"])
        inst = {
            "loan_id": loan["id"],
            "sequence_no": row["sequence_no"],
            "due_date": db.iso_millis(due_dt),
            "amount_due_cents": row["amount_due_cents"],
            "principal_portion_cents": row["principal_portion_cents"],
            "amount_paid_cents": 0,
            "late_fee_cents": 0,
            "status": "SCHEDULED",
        }
        stamp_new(inst)
        db.installments[inst["id"]] = inst

    # MerchantSettlement PENDING (calculations.merchant_settlement_net).
    gross = loan["financed_principal_cents"]
    fee = calc.mdr_fee(gross, merchant["mdr_bps"])
    settlement = {
        "merchant_id": merchant["id"],
        "loan_id": loan["id"],
        "gross_financed_cents": gross,
        "mdr_fee_cents": fee,
        "net_settlement_cents": gross - fee,
        "clawed_back_cents": 0,
        "status": "PENDING",
    }
    stamp_new(settlement)
    db.merchant_settlements[settlement["id"]] = settlement

    # Recompute aggregates.
    engine.reconcile_borrower(borrower["id"])
    engine.reconcile_merchant(merchant["id"])

    return success(serialize_loan(loan), status=201)


@bp.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    loan = require_loan(loan_id)
    require_borrower_owns(role, uid, loan["borrower_id"])
    require_merchant_owns(role, uid, loan["merchant_id"])
    return success(serialize_loan(loan), status=200)


@bp.route("/loans", methods=["GET"])
def list_loans():
    uid, role = authenticate()
    require_role(role, {"Servicer", "Borrower", "Merchant"})
    limit, offset = parse_pagination()
    borrower_filter = request.args.get("borrower_id")
    merchant_filter = request.args.get("merchant_id")
    application_filter = request.args.get("application_id")

    rows = list(db.loans.values())
    if borrower_filter is not None:
        rows = [l for l in rows if l["borrower_id"] == borrower_filter]
    if merchant_filter is not None:
        rows = [l for l in rows if l["merchant_id"] == merchant_filter]
    if application_filter is not None:
        rows = [l for l in rows if l["application_id"] == application_filter]
    if role == "Borrower":
        rows = [l for l in rows if l["borrower_id"] == uid]
    elif role == "Merchant":
        rows = [l for l in rows if l["merchant_id"] == uid]

    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([serialize_loan(l) for l in page], status=200, pagination=meta)


def _check_occ(loan, body):
    expected = body.get("expected_loan_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST",
                  "expected_loan_version is required and must be an integer.")
    if expected != loan["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_loan_version does not match the loan's current version.")


@bp.route("/loans/<loan_id>/default", methods=["POST"])
def default_loan(loan_id):
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    loan = require_loan(loan_id)
    body = get_json_body()

    # State: must be ACTIVE.
    if loan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Loan must be ACTIVE to default.")
    # Delinquency precondition (priority 9).
    if loan["delinquency_status"] != "DELINQUENT":
        raise err("ERR_NOT_DELINQUENT",
                  "Loan must be DELINQUENT to be declared defaulted.")
    # OCC (priority 12).
    _check_occ(loan, body)

    loan["status"] = "DEFAULTED"
    touch(loan)  # increments version by 1

    # All SCHEDULED/LATE installments -> WRITTEN_OFF.
    for inst in engine.loan_installments(loan["id"]):
        if inst["status"] in ("SCHEDULED", "LATE"):
            inst["status"] = "WRITTEN_OFF"
            touch(inst)

    # AutopayMandate (if ENABLED) -> DISABLED.
    _disable_autopay(loan["id"])

    # Settlement: if still PENDING -> CLAWED_BACK in full; if RELEASED, no change.
    settlement = engine.settlement_for_loan(loan["id"])
    if settlement is not None and settlement["status"] == "PENDING":
        engine.claw_back_full(settlement)

    engine.reconcile_borrower(loan["borrower_id"])
    engine.reconcile_merchant(loan["merchant_id"])
    return success(serialize_loan(loan), status=200)


@bp.route("/loans/<loan_id>/cancel", methods=["POST"])
def cancel_loan(loan_id):
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    loan = require_loan(loan_id)
    body = get_json_body()

    # State: must be ACTIVE.
    if loan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Loan must be ACTIVE to cancel.")
    # No payment yet (priority 10).
    if engine.compute_loan_total_paid(loan["id"]) != 0:
        raise err("ERR_LOAN_HAS_PAYMENTS",
                  "Loan cannot be cancelled after a payment was made.")
    # OCC (priority 12).
    _check_occ(loan, body)

    loan["status"] = "CANCELLED"
    touch(loan)  # increments version by 1

    # All installments -> CANCELLED (SCHEDULED amount_due reduced to amount_paid).
    for inst in engine.loan_installments(loan["id"]):
        if inst["status"] == "SCHEDULED":
            inst["amount_due_cents"] = inst["amount_paid_cents"]
        inst["status"] = "CANCELLED"
        touch(inst)

    # Settlement -> CLAWED_BACK in full.
    settlement = engine.settlement_for_loan(loan["id"])
    if settlement is not None and settlement["status"] != "CLAWED_BACK":
        engine.claw_back_full(settlement)

    _disable_autopay(loan["id"])

    engine.reconcile_borrower(loan["borrower_id"])
    engine.reconcile_merchant(loan["merchant_id"])
    return success(serialize_loan(loan), status=200)


def _disable_autopay(loan_id):
    for mnd in db.autopay_mandates.values():
        if mnd["loan_id"] == loan_id and mnd["status"] == "ENABLED":
            mnd["status"] = "DISABLED"
            touch(mnd)
