"""Mediation case routes."""
from __future__ import annotations

from flask import Blueprint, g

from config import (
    MEDIATION_AUTOFAIL_NOI_DAYS,
    NOI_WINDOW_DAYS,
)
from db import store
from errors import (
    err_forbidden,
    err_hamp_floor,
    err_hamp_not_a_reduction,
    err_hamp_stale,
    err_hardship_missing,
    err_invalid_state,
    err_mediation_already_open,
    err_mediation_window_closed,
    err_resource_not_found,
    err_segregation,
)
from middleware import require_auth
from response import success
from services.calculations import hamp_modified_payment
from services.loan_engine import bump
from services.serializers import mediation_view
from utils import floor_days_between, midnight_utc, new_uuid

from routes._helpers import (
    enforce_borrower_owns_loan,
    get_int,
    get_json,
)

bp = Blueprint("mediation", __name__)

_ALLOWED_REJECTION_REASONS = {"DTI_TOO_HIGH", "AFFORDABILITY_FLOOR", "BORROWER_REFUSED"}


def _get_med(mid):
    m = store.mediation_cases.get(mid)
    if m is None:
        raise err_resource_not_found("MediationCase not found.")
    return m


def _origination_to_now_months(loan, now) -> int:
    """Whole months elapsed since origination_date (floored)."""
    od = midnight_utc(loan["origination_date"])
    return max(0, (now.year - od.year) * 12 + (now.month - od.month))


@bp.post("/foreclosure-cases/<cid>/mediation-cases")
@require_auth(["Servicer", "Borrower"])
def request_mediation(cid):
    case = store.foreclosure_cases.get(cid)
    if case is None:
        raise err_resource_not_found("ForeclosureCase not found.")
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    enforce_borrower_owns_loan(loan)
    # Closed/terminal foreclosure-case statuses are invalid state; the
    # named regulatory + exclusivity errors PRD §3.6 catalogues
    # (ERR_MEDIATION_WINDOW_CLOSED, ERR_MEDIATION_ALREADY_OPEN) only
    # apply to open cases. NOI_ISSUED and MEDIATION_OPEN are both
    # "open" — MEDIATION_OPEN is caused exclusively by an existing
    # active mediation so it is handled by the exclusivity check below.
    if case["status"] in ("FILED", "AUCTION_SCHEDULED",
                          "CLOSED_REINSTATED", "CLOSED_MODIFIED",
                          "CLOSED_SOLD"):
        raise err_invalid_state(
            "Mediation can only be requested while case is in the NOI window."
        )
    # PRD §2.6: regulatory window (priority 12) fires before referential
    # exclusivity (priority 16). Check window first.
    now = store.now()
    days_since_noi = floor_days_between(midnight_utc(now), midnight_utc(case["noi_sent_at"]))
    if days_since_noi >= NOI_WINDOW_DAYS:
        raise err_mediation_window_closed()
    # Priority 13: hardship.
    borrower = store.borrowers.get(loan["borrower_id"])
    if borrower is None or borrower.get("hardship_attested_at") is None:
        raise err_hardship_missing()
    # Priority 16: no active mediation already.
    for m in store.mediation_cases.values():
        if m["foreclosure_case_id"] == cid and m["status"] not in (
            "FAILED",
            "OFFER_REJECTED",
            "COMPLETED",
        ):
            raise err_mediation_already_open()
    mid = new_uuid()
    record = {
        "id": mid,
        "foreclosure_case_id": cid,
        "opened_at": None,
        "status": "REQUESTED",
        "offered_new_rate_bps": None,
        "offered_term_extension_months": None,
        "offered_principal_forbearance_cents": 0,
        "target_payment_cents": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.mediation_cases[mid] = record
    case["status"] = "MEDIATION_OPEN"
    bump(case, now)
    return success(mediation_view(record), 201)


@bp.post("/mediation-cases/<mid>/open")
@require_auth(["LossMitigationUnderwriter"])
def open_mediation(mid):
    m = _get_med(mid)
    if m["status"] != "REQUESTED":
        raise err_invalid_state("Only REQUESTED mediation cases can be opened.")
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None or case["status"] != "MEDIATION_OPEN":
        raise err_invalid_state("Foreclosure case is not in MEDIATION_OPEN.")
    now = store.now()
    m["status"] = "OPEN"
    m["opened_at"] = now
    bump(m, now)
    return success(mediation_view(m), 200)


@bp.post("/mediation-cases/<mid>/extend-offer")
@require_auth(["LossMitigationUnderwriter"])
def extend_offer(mid):
    m = _get_med(mid)
    if m["status"] not in ("OPEN", "OFFER_REJECTED"):
        raise err_invalid_state("Can only extend offer from OPEN or OFFER_REJECTED.")
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None or case["status"] != "MEDIATION_OPEN":
        raise err_invalid_state("Parent ForeclosureCase is not in MEDIATION_OPEN.")
    if m["status"] == "OFFER_REJECTED" and m.get("rejection_reason") == "BORROWER_REFUSED":
        raise err_invalid_state("Cannot re-extend after BORROWER_REFUSED.")
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    body = get_json()
    new_rate = body.get("offered_new_rate_bps", None)
    if new_rate is not None:
        if not isinstance(new_rate, int) or isinstance(new_rate, bool) or new_rate <= 0:
            raise err_invalid_state("offered_new_rate_bps must be > 0 when supplied")
    term_ext = body.get("offered_term_extension_months", 0)
    if term_ext is None:
        term_ext = 0
    if not isinstance(term_ext, int) or isinstance(term_ext, bool) or term_ext < 0:
        raise err_invalid_state("offered_term_extension_months must be >= 0")
    principal_forb = body.get("offered_principal_forbearance_cents", 0)
    if principal_forb is None:
        principal_forb = 0
    if not isinstance(principal_forb, int) or isinstance(principal_forb, bool) or principal_forb < 0:
        raise err_invalid_state("offered_principal_forbearance_cents must be >= 0")

    now = store.now()
    months_elapsed = _origination_to_now_months(loan, now)
    calc = hamp_modified_payment(loan, months_elapsed, new_rate, term_ext, principal_forb)
    if calc["target_payment_cents"] < 0:
        raise err_hamp_floor()
    # Reduction guard first (priority 19), then affordability floor (priority 20).
    if calc["target_payment_cents"] >= loan["scheduled_payment_cents"]:
        raise err_hamp_not_a_reduction()
    if calc["target_payment_cents"] < calc["floor_payment_cents"]:
        raise err_hamp_floor()

    m["status"] = "OFFER_EXTENDED"
    m["offered_new_rate_bps"] = new_rate
    m["offered_term_extension_months"] = term_ext
    m["offered_principal_forbearance_cents"] = principal_forb
    m["target_payment_cents"] = calc["target_payment_cents"]
    m["rejection_reason"] = None
    bump(m, now)
    # Record who extended the offer for SoD on /complete.
    store.last_offer_extender[mid] = g.user_id
    return success(mediation_view(m), 200)


@bp.post("/mediation-cases/<mid>/accept-offer")
@require_auth(["Borrower", "Servicer"])
def accept_offer(mid):
    m = _get_med(mid)
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None:
        raise err_resource_not_found("Parent ForeclosureCase not found.")
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    enforce_borrower_owns_loan(loan)
    # PRD §2.1: "a single X-User-ID cannot both extend a mediation
    # offer and accept the same offer on the same MediationCase ... A
    # second-step attempt by the first-step operator is rejected with
    # ERR_SEGREGATION_OF_DUTIES and HTTP 403." Per PRD §2.6 priority 4
    # (segregation-of-duties), this fires before the source-state
    # precondition check at priority 8.
    extender = store.last_offer_extender.get(mid)
    if extender is not None and extender == g.user_id:
        raise err_segregation()
    if m["status"] != "OFFER_EXTENDED":
        raise err_invalid_state("Only OFFER_EXTENDED can be accepted.")
    now = store.now()
    m["status"] = "OFFER_ACCEPTED"
    # Record the accepter so /complete's SoD check can validate that
    # the completer is also distinct from the accepter (per PRD §3.7).
    store.last_offer_accepter = getattr(store, "last_offer_accepter", {})
    store.last_offer_accepter[mid] = g.user_id
    bump(m, now)
    return success(mediation_view(m), 200)


@bp.post("/mediation-cases/<mid>/reject-offer")
@require_auth(["Borrower", "Servicer", "LossMitigationUnderwriter"])
def reject_offer(mid):
    m = _get_med(mid)
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None:
        raise err_resource_not_found("Parent ForeclosureCase not found.")
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    if g.role == "Borrower":
        enforce_borrower_owns_loan(loan)
    if m["status"] != "OFFER_EXTENDED":
        raise err_invalid_state("Only OFFER_EXTENDED can be rejected.")
    body = get_json()
    reason = body.get("rejection_reason")
    if reason not in _ALLOWED_REJECTION_REASONS:
        raise err_invalid_state("Invalid rejection_reason.")
    now = store.now()
    m["status"] = "OFFER_REJECTED"
    m["rejection_reason"] = reason
    bump(m, now)
    return success(mediation_view(m), 200)


@bp.post("/mediation-cases/<mid>/complete")
@require_auth(["LossMitigationUnderwriter"])
def complete_mediation(mid):
    m = _get_med(mid)
    if m["status"] != "OFFER_ACCEPTED":
        raise err_invalid_state("Only OFFER_ACCEPTED can be completed.")
    # SoD: completing operator must not be the same as extender.
    extender = store.last_offer_extender.get(mid)
    if extender is not None and extender == g.user_id:
        raise err_segregation()
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None:
        raise err_resource_not_found("Parent ForeclosureCase not found.")
    loan = store.loans.get(case["loan_id"])
    if loan is None:
        raise err_resource_not_found("Loan for case not found.")
    now = store.now()
    months_elapsed = _origination_to_now_months(loan, now)
    calc = hamp_modified_payment(
        loan,
        months_elapsed,
        m["offered_new_rate_bps"],
        m["offered_term_extension_months"] or 0,
        m["offered_principal_forbearance_cents"] or 0,
    )
    if calc["target_payment_cents"] < 0:
        raise err_hamp_stale()
    # Compare to stored target within ±100 cents.
    if abs(calc["target_payment_cents"] - (m["target_payment_cents"] or 0)) > 100:
        raise err_hamp_stale()
    new_target = calc["target_payment_cents"]
    m["status"] = "COMPLETED"
    bump(m, now)
    case["status"] = "CLOSED_MODIFIED"
    bump(case, now)
    # Modify loan.
    loan["scheduled_payment_cents"] = new_target
    if m["offered_new_rate_bps"] is not None:
        loan["interest_rate_bps"] = m["offered_new_rate_bps"]
    loan["term_months"] = loan["term_months"] + (m["offered_term_extension_months"] or 0)
    loan["posture"] = "CURRENT"
    bump(loan, now)
    return success(mediation_view(m), 200)


@bp.post("/mediation-cases/<mid>/fail")
@require_auth(["LossMitigationUnderwriter"])
def fail_mediation(mid):
    m = _get_med(mid)
    if m["status"] != "OFFER_REJECTED":
        raise err_invalid_state("Only OFFER_REJECTED can be failed manually.")
    case = store.foreclosure_cases.get(m["foreclosure_case_id"])
    if case is None:
        raise err_resource_not_found("Parent ForeclosureCase not found.")
    now = store.now()
    days_since_noi = floor_days_between(midnight_utc(now), midnight_utc(case["noi_sent_at"]))
    if not (
        m.get("rejection_reason") == "BORROWER_REFUSED"
        or days_since_noi >= MEDIATION_AUTOFAIL_NOI_DAYS
    ):
        raise err_invalid_state(
            "Manual fail requires BORROWER_REFUSED rejection or 60+ days since NOI."
        )
    m["status"] = "FAILED"
    bump(m, now)
    # Cascade ForeclosureCase MEDIATION_OPEN → FILED if NOI window has expired.
    if case["status"] == "MEDIATION_OPEN":
        days_since_noi = floor_days_between(midnight_utc(now), midnight_utc(case["noi_sent_at"]))
        if days_since_noi >= NOI_WINDOW_DAYS:
            case["status"] = "FILED"
            case["filed_at"] = now
            bump(case, now)
    return success(mediation_view(m), 200)


@bp.get("/mediation-cases/<mid>")
@require_auth(["LossMitigationUnderwriter", "Servicer", "Borrower", "ForeclosureAttorney"])
def get_mediation(mid):
    m = _get_med(mid)
    if g.role == "Borrower":
        case = store.foreclosure_cases.get(m["foreclosure_case_id"])
        if case is None:
            raise err_resource_not_found("Parent ForeclosureCase not found.")
        loan = store.loans.get(case["loan_id"])
        if loan is None:
            raise err_resource_not_found("Loan for case not found.")
        enforce_borrower_owns_loan(loan)
    return success(mediation_view(m), 200)
