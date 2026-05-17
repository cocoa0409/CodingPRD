"""Foreclosure case routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from config import (
    AUCTION_NOTICE_DAYS,
    FILING_TO_AUCTION_DAYS,
    NOI_WINDOW_DAYS,
    REINSTATEMENT_CUTOFF_DAYS,
)
from db import store
from errors import (
    err_auction_notice,
    err_forbidden,
    err_foreclosure_case_exists,
    err_invalid_state,
    err_noi_window_not_elapsed,
    err_reinstatement_cutoff,
    err_reinstatement_insufficient,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from services.calculations import reinstatement_quote_cents
from services.loan_engine import bump, loan_open_foreclosure
from services.serializers import foreclosure_view
from utils import floor_days_between, midnight_utc, new_uuid, parse_iso

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
    get_loan_or_404,
    paginate,
    parse_pagination,
    sort_by_created_at,
)

bp = Blueprint("foreclosure", __name__)


@bp.post("/foreclosure-cases")
@require_auth(["ForeclosureAttorney"])
def open_case():
    body = get_json()
    loan_id = body.get("loan_id")
    if not isinstance(loan_id, str) or not loan_id:
        raise err_invalid_state("loan_id required")
    loan = get_loan_or_404(loan_id)
    foreclosure_costs = get_int(body, "foreclosure_costs_cents", 0) or 0
    if foreclosure_costs < 0:
        raise err_invalid_state("foreclosure_costs_cents must be >= 0")
    with store.lock:
        # PRD §3.6 textual order: "at most one open case per loan" is the
        # named exclusivity rule; a second open attempt fires the specific
        # ERR_FORECLOSURE_CASE_EXISTS. When a case is already open the
        # loan necessarily sits in FORECLOSURE posture, so checking
        # exclusivity first yields the more useful named error.
        if loan_open_foreclosure(loan_id):
            raise err_foreclosure_case_exists()
        if loan["posture"] != "DEFAULT":
            raise err_invalid_state("Loan posture must be DEFAULT to open foreclosure.")
        now = store.now()
        cid = new_uuid()
        case = {
            "id": cid,
            "loan_id": loan_id,
            "opened_at": now,
            "status": "NOI_ISSUED",
            "noi_sent_at": now,
            "filed_at": None,
            "auction_date": None,
            "reinstatement_quote_cents": 0,
            "foreclosure_costs_cents": foreclosure_costs,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        case["reinstatement_quote_cents"] = reinstatement_quote_cents(loan, case, now)
        store.foreclosure_cases[cid] = case
        loan["posture"] = "FORECLOSURE"
        bump(loan, now)
    return success(foreclosure_view(case), 201)


def _get_case(cid):
    c = store.foreclosure_cases.get(cid)
    if c is None:
        raise err_resource_not_found("ForeclosureCase not found.")
    return c


@bp.get("/foreclosure-cases/<cid>/quote")
@require_auth(["Servicer", "Borrower", "ForeclosureAttorney"])
def get_quote(cid):
    case = _get_case(cid)
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    enforce_borrower_owns_loan(loan)
    now = store.now()
    case["reinstatement_quote_cents"] = reinstatement_quote_cents(loan, case, now)
    return success(foreclosure_view(case), 200)


@bp.post("/foreclosure-cases/<cid>/file")
@require_auth(["ForeclosureAttorney"])
def file_case(cid):
    case = _get_case(cid)
    if case["status"] != "NOI_ISSUED":
        raise err_invalid_state("Only NOI_ISSUED cases can be filed.")
    # Reject if there's a non-terminal MediationCase.
    for m in store.mediation_cases.values():
        if m["foreclosure_case_id"] == cid and m["status"] not in (
            "FAILED",
            "OFFER_REJECTED",
            "COMPLETED",
        ):
            raise err_invalid_state("An active MediationCase exists on this case.")
    now = store.now()
    days_since_noi = floor_days_between(midnight_utc(now), midnight_utc(case["noi_sent_at"]))
    if days_since_noi < NOI_WINDOW_DAYS:
        raise err_noi_window_not_elapsed()
    case["status"] = "FILED"
    case["filed_at"] = now
    bump(case, now)
    return success(foreclosure_view(case), 200)


@bp.post("/foreclosure-cases/<cid>/schedule-auction")
@require_auth(["ForeclosureAttorney"])
def schedule_auction(cid):
    case = _get_case(cid)
    if case["status"] != "FILED":
        raise err_invalid_state("Only FILED cases can have an auction scheduled.")
    body = get_json()
    ad_raw = body.get("auction_date")
    if ad_raw is None:
        raise err_auction_notice("auction_date required")
    try:
        auction_date = parse_iso(ad_raw)
    except Exception:
        raise err_auction_notice("Invalid auction_date")
    now = store.now()
    days_since_file = floor_days_between(midnight_utc(now), midnight_utc(case["filed_at"]))
    if days_since_file < FILING_TO_AUCTION_DAYS:
        raise err_auction_notice("Case has not been on file for 60+ days.")
    days_until_auction = floor_days_between(midnight_utc(auction_date), midnight_utc(now))
    if days_until_auction < AUCTION_NOTICE_DAYS:
        raise err_auction_notice("auction_date must be ≥ now + 30 days.")
    case["status"] = "AUCTION_SCHEDULED"
    case["auction_date"] = auction_date
    bump(case, now)
    return success(foreclosure_view(case), 200)


@bp.post("/foreclosure-cases/<cid>/reinstate")
@require_auth(["Servicer", "Borrower"])
def reinstate_case(cid):
    case = _get_case(cid)
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    enforce_borrower_owns_loan(loan)
    if case["status"] not in ("NOI_ISSUED", "MEDIATION_OPEN", "FILED", "AUCTION_SCHEDULED"):
        raise err_invalid_state("Case is not open for reinstatement.")
    body = get_json()
    amount = get_int(body, "payment_amount_cents")
    if amount is None or amount <= 0:
        raise err_reinstatement_insufficient("payment_amount_cents must be > 0")
    now = store.now()
    # Cutoff: 5 days before auction.
    if case["status"] == "AUCTION_SCHEDULED":
        days_to_auction = floor_days_between(midnight_utc(case["auction_date"]), midnight_utc(now))
        if days_to_auction <= REINSTATEMENT_CUTOFF_DAYS:
            raise err_reinstatement_cutoff()
    # Re-check quote at commit time.
    quote = reinstatement_quote_cents(loan, case, now)
    case["reinstatement_quote_cents"] = quote
    if amount < quote:
        raise err_reinstatement_insufficient()
    # Delegate to payment posting (it'll detect reinstatement path).
    from routes.payments import _post_payment_internal

    _post_payment_internal(loan, now, amount, None)
    # _post_payment_internal will have closed the case + bumped versions.
    return success(foreclosure_view(case), 200)


@bp.get("/foreclosure-cases")
@require_auth(["ForeclosureAttorney", "Servicer", "PlatformAdmin"])
def list_cases():
    limit, offset = parse_pagination()
    items = list(store.foreclosure_cases.values())
    status = request.args.get("status")
    loan_id = request.args.get("loan_id")
    if status:
        items = [c for c in items if c["status"] == status]
    if loan_id:
        items = [c for c in items if c["loan_id"] == loan_id]
    items = sort_by_created_at(items)
    page = paginate(items, limit, offset)
    return list_success([foreclosure_view(c) for c in page], limit, offset, len(items), 200)
