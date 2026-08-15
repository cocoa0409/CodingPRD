"""SecurityTransaction ingest, confirm, void."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_TRANSACTION_INVALID_STATE,
    ERR_PERSON_NOT_ACTIVE, ERR_SOD_INGESTER_CONFIRMER,
    ERR_PLAN_NOT_ACTIVE, ERR_BLACKOUT_PERIOD, ERR_FUTURE_TRANSACTION_DATE,
    ERR_PLAN_PERSON_MISMATCH, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    TRANSACTION_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate, parse_date, logical_clock_date,
)
from services.calculations import (
    DIRECTION_BY_CODE, recompute_balance_chain, compute_form4_deadline,
    recompute_open_obligation_count,
)

transactions_bp = Blueprint("transactions", __name__)


def _get_txn_or_404(tid):
    t = db.transactions.get(tid)
    if not t:
        raise ApiError(ERR_NOT_FOUND, f"SecurityTransaction {tid} not found.", 404)
    return t


@transactions_bp.route("/transactions", methods=["POST"])
def create_transaction():
    user_id, role = require_role("EquityPlanAdmin", "FilingCoordinator")
    body = request.get_json(force=True) or {}

    for f in ["reporting_person_id", "transaction_date", "transaction_code", "security_type", "shares"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["reporting_person_id"] not in db.reporting_persons:
        raise ApiError(ERR_INVALID_REQUEST, f"reporting_person_id {body['reporting_person_id']} not found.", 400)

    person = db.reporting_persons[body["reporting_person_id"]]

    if body["transaction_code"] not in DIRECTION_BY_CODE:
        raise ApiError(ERR_INVALID_REQUEST, f"Invalid transaction_code: {body['transaction_code']}", 400)

    if body["security_type"] not in ("COMMON_STOCK", "OPTION", "RSU", "DERIVATIVE_OTHER"):
        raise ApiError(ERR_INVALID_REQUEST, f"Invalid security_type: {body['security_type']}", 400)

    shares = body["shares"]
    if not isinstance(shares, int) or isinstance(shares, bool) or shares <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "shares must be a positive integer.", 400)

    if body["transaction_code"] in ("P", "S") and body.get("price_per_share") is None:
        raise ApiError(ERR_INVALID_REQUEST, "price_per_share is required for codes P and S.", 400)

    try:
        parse_date(body["transaction_date"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "transaction_date must be YYYY-MM-DD.", 400)

    plan_id = body.get("plan_id")
    if plan_id is not None and plan_id not in db.trading_plans:
        raise ApiError(ERR_INVALID_REQUEST, f"plan_id {plan_id} not found.", 400)

    txn = {
        "reporting_person_id": body["reporting_person_id"],
        "issuer_id": person["issuer_id"],
        "filing_id": None,
        "plan_id": plan_id,
        "transaction_date": body["transaction_date"],
        "transaction_code": body["transaction_code"],
        "security_type": body["security_type"],
        "shares": shares,
        "price_per_share": body.get("price_per_share"),
        "source": body.get("source", "MANUAL"),
        "direction": None,
        "shares_owned_after": None,
        "ingested_by_user_id": user_id,
        "status": "INGESTED",
    }
    stamp_created(txn)
    db.transactions[txn["id"]] = txn
    return success_object(serialize(txn, TRANSACTION_FIELDS), 201)


@transactions_bp.route("/transactions", methods=["GET"])
def list_transactions():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.transactions.values(), key=lambda x: x["created_at"])
    for param in ["reporting_person_id", "issuer_id", "filing_id", "plan_id", "status"]:
        val = request.args.get(param)
        if val:
            items = [t for t in items if str(t.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(t, TRANSACTION_FIELDS) for t in page], limit, offset, total)


@transactions_bp.route("/transactions/<transactionId>", methods=["GET"])
def get_transaction(transactionId):
    get_auth()
    t = _get_txn_or_404(transactionId)
    return success_object(serialize(t, TRANSACTION_FIELDS))


@transactions_bp.route("/transactions/<transactionId>/confirm", methods=["POST"])
def confirm_transaction(transactionId):
    user_id, role = require_role("ComplianceOfficer")
    txn = _get_txn_or_404(transactionId)

    if txn["status"] != "INGESTED":
        raise ApiError(ERR_TRANSACTION_INVALID_STATE, "Confirm requires INGESTED.", 409)

    person = db.reporting_persons[txn["reporting_person_id"]]
    if person["status"] != "ACTIVE":
        raise ApiError(ERR_PERSON_NOT_ACTIVE, "Reporting person must be ACTIVE.", 409)

    if user_id == txn["ingested_by_user_id"]:
        raise ApiError(ERR_SOD_INGESTER_CONFIRMER, "Confirmer must differ from ingester.", 403)

    if txn.get("plan_id"):
        plan = db.trading_plans.get(txn["plan_id"])
        if not plan or plan["status"] != "ACTIVE":
            raise ApiError(ERR_PLAN_NOT_ACTIVE, "Plan must be ACTIVE.", 422)
    else:
        # Blackout check (closed interval)
        issuer = db.issuers[txn["issuer_id"]]
        txn_date = parse_date(txn["transaction_date"])
        for w in db.blackout_windows.values():
            if w["issuer_id"] != issuer["id"]:
                continue
            if parse_date(w["start_date"]) <= txn_date <= parse_date(w["end_date"]):
                raise ApiError(ERR_BLACKOUT_PERIOD, "Transaction date inside blackout window.", 422)

    if parse_date(txn["transaction_date"]) > logical_clock_date():
        raise ApiError(ERR_FUTURE_TRANSACTION_DATE, "transaction_date is later than logical clock date.", 422)

    if txn.get("plan_id"):
        plan = db.trading_plans.get(txn["plan_id"])
        if plan and plan["reporting_person_id"] != txn["reporting_person_id"]:
            raise ApiError(ERR_PLAN_PERSON_MISMATCH, "Plan belongs to a different person.", 422)

    # --- Side effects ---
    txn["direction"] = DIRECTION_BY_CODE[txn["transaction_code"]]
    txn["status"] = "CONFIRMED"
    bump_version(txn)

    # Auto-create DRAFT FORM_4 for non-G codes
    if txn["transaction_code"] != "G":
        filing = {
            "issuer_id": txn["issuer_id"],
            "reporting_person_id": txn["reporting_person_id"],
            "form_type": "FORM_4",
            "amends_filing_id": None,
            "filing_deadline": compute_form4_deadline(
                txn["transaction_date"], db.issuers[txn["issuer_id"]]
            ),
            "is_late": False,
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "submitted_by_user_id": None,
            "submitted_at": None,
            "accepted_at": None,
            "accession_number": None,
            "rejection_reason": None,
        }
        stamp_created(filing)
        db.filings[filing["id"]] = filing
        txn["filing_id"] = filing["id"]
        recompute_open_obligation_count(txn["reporting_person_id"])

    recompute_balance_chain(txn["reporting_person_id"], txn["security_type"])
    return success_object(serialize(txn, TRANSACTION_FIELDS))


@transactions_bp.route("/transactions/<transactionId>/void", methods=["POST"])
def void_transaction(transactionId):
    user_id, role = require_role("ComplianceOfficer")
    txn = _get_txn_or_404(transactionId)

    if txn["status"] not in ("INGESTED", "CONFIRMED"):
        raise ApiError(ERR_TRANSACTION_INVALID_STATE, "Void requires INGESTED or CONFIRMED.", 409)

    if txn["status"] == "CONFIRMED" and txn.get("filing_id"):
        filing = db.filings.get(txn["filing_id"])
        if filing and filing["status"] in ("SUBMITTED", "ACCEPTED"):
            raise ApiError(ERR_TRANSACTION_INVALID_STATE, "Void blocked by SUBMITTED/ACCEPTED filing.", 409)

    # Discard linked DRAFT/READY filing
    if txn["status"] == "CONFIRMED" and txn.get("filing_id"):
        filing = db.filings.get(txn["filing_id"])
        if filing and filing["status"] in ("DRAFT", "READY"):
            filing["status"] = "DISCARDED"
            bump_version(filing)
            # Detach transactions
            for t in db.transactions.values():
                if t.get("filing_id") == filing["id"]:
                    t["filing_id"] = None
            recompute_open_obligation_count(txn["reporting_person_id"])

    txn["status"] = "VOID"
    txn["filing_id"] = None
    bump_version(txn)
    recompute_balance_chain(txn["reporting_person_id"], txn["security_type"])
    return success_object(serialize(txn, TRANSACTION_FIELDS))
