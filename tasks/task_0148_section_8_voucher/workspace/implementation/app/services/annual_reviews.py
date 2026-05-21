"""AnnualReview lifecycle: submit, mark-deficient, resubmit, approve, deny."""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from app import calculations, clock, store
from app.errors import APIError, invalid_state, not_found, validation
from app.services.common import occ_check, touch
from app.util import new_id, require_int, require_str


def _recompute(ar: dict) -> None:
    """Run calc_adjusted_income (recertification) + calc_ttp + calc_hap on `ar`."""
    tenancy = store.tenancies.get(ar["tenancy_id"])
    if tenancy is None:
        raise invalid_state("Tenancy missing for annual review")
    voucher = store.vouchers.get(tenancy["voucher_id"])
    if voucher is None:
        raise invalid_state("Voucher missing for tenancy")
    applicant = store.applicants.get(voucher["applicant_id"])
    if applicant is None:
        raise invalid_state("Applicant missing for voucher")

    declared_gross = ar["declared_gross_annual_income_cents"]
    declared_size = ar["declared_household_size"]
    dependents = max(0, declared_size - 1)

    new_adjusted = calculations.calc_adjusted_income(
        gross_cents=declared_gross,
        dependents_count=dependents,
        elderly_or_disabled_head=applicant["elderly_or_disabled_head"],
        medical_expense_cents=applicant["medical_expense_annual_cents"],
        childcare_expense_cents=applicant["childcare_expense_annual_cents"],
    )
    new_ttp = calculations.calc_ttp(
        adjusted_annual_income_cents=new_adjusted,
        gross_annual_income_cents=declared_gross,
    )
    new_hap = calculations.calc_hap(
        applicable_payment_standard_cents=tenancy["applicable_payment_standard_cents"],
        gross_rent_cents=tenancy["gross_rent_cents"],
        ttp_cents=new_ttp,
    )

    ar["new_adjusted_income_cents"] = new_adjusted
    ar["new_total_tenant_payment_cents"] = new_ttp
    ar["new_hap_cents"] = new_hap


def submit(ar_id: str, payload: dict) -> dict:
    payload = payload or {}
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    occ_check(ar, payload.get("version"))

    if ar["status"] != "DUE":
        raise invalid_state("AnnualReview is not DUE")

    try:
        declared_gross = require_int(payload.get("declared_gross_annual_income_cents"), field="declared_gross_annual_income_cents", min_value=0)
        declared_size = require_int(payload.get("declared_household_size"), field="declared_household_size", min_value=1, max_value=20)
    except ValueError as exc:
        raise validation(str(exc))

    now = clock.now()
    review_due = ar["review_due_date"]
    window = timedelta(days=30)
    if now < review_due - window or now > review_due + window:
        raise APIError("ERR_REVIEW_WINDOW_CLOSED", 409, "AnnualReview submission outside ±30 day window")

    ar["declared_gross_annual_income_cents"] = declared_gross
    ar["declared_household_size"] = declared_size
    ar["submitted_at"] = now
    ar["status"] = "SUBMITTED"
    _recompute(ar)
    touch(ar)
    return ar


def mark_deficient(ar_id: str, payload: dict) -> dict:
    payload = payload or {}
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    occ_check(ar, payload.get("version"))

    if ar["status"] != "SUBMITTED":
        raise invalid_state("AnnualReview is not SUBMITTED")

    codes = payload.get("deficiency_codes", [])
    if not isinstance(codes, list) or not all(isinstance(c, str) and c for c in codes):
        raise validation("deficiency_codes must be a non-empty list of strings")
    if len(codes) == 0:
        raise validation("deficiency_codes must be non-empty")

    ar["status"] = "DEFICIENT"
    ar["deficiency_codes"] = list(codes)
    ar["deficient_since"] = clock.now()
    touch(ar)
    return ar


def resubmit(ar_id: str, payload: dict) -> dict:
    payload = payload or {}
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    occ_check(ar, payload.get("version"))

    if ar["status"] != "DEFICIENT":
        raise invalid_state("AnnualReview is not DEFICIENT")
    # 14-day re-submit window from deficient_since.
    now = clock.now()
    if ar.get("deficient_since") and now > ar["deficient_since"] + timedelta(days=14):
        raise invalid_state("Re-submit window has elapsed")

    try:
        declared_gross = require_int(payload.get("declared_gross_annual_income_cents"), field="declared_gross_annual_income_cents", min_value=0)
        declared_size = require_int(payload.get("declared_household_size"), field="declared_household_size", min_value=1, max_value=20)
    except ValueError as exc:
        raise validation(str(exc))

    ar["declared_gross_annual_income_cents"] = declared_gross
    ar["declared_household_size"] = declared_size
    ar["submitted_at"] = now
    ar["deficiency_codes"] = []
    ar["status"] = "SUBMITTED"
    _recompute(ar)
    touch(ar)
    return ar


def approve(ar_id: str, payload: dict) -> dict:
    payload = payload or {}
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    occ_check(ar, payload.get("version"))

    if ar["status"] != "SUBMITTED":
        raise invalid_state("AnnualReview is not SUBMITTED")

    tenancy = store.tenancies.get(ar["tenancy_id"])
    if tenancy is None:
        raise invalid_state("Tenancy missing for review")

    tenancy["current_total_tenant_payment_cents"] = ar["new_total_tenant_payment_cents"]
    tenancy["current_hap_cents"] = ar["new_hap_cents"]
    touch(tenancy)

    ar["status"] = "APPROVED"
    touch(ar)

    # Schedule the next DUE row at this.review_due_date + 365 days.
    next_due = ar["review_due_date"] + timedelta(days=365)
    now = clock.now()
    next_id = new_id()
    store.annual_reviews[next_id] = {
        "id": next_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "tenancy_id": ar["tenancy_id"],
        "review_due_date": next_due,
        "submitted_at": None,
        "declared_gross_annual_income_cents": None,
        "declared_household_size": None,
        "new_adjusted_income_cents": None,
        "new_total_tenant_payment_cents": None,
        "new_hap_cents": None,
        "deficiency_codes": [],
        "status": "DUE",
        "deficient_since": None,
    }
    # Refresh tenancy's pointer to the now-current DUE AR.
    tenancy["current_annual_review_id"] = next_id
    return ar


def deny(ar_id: str, payload: dict) -> dict:
    payload = payload or {}
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    occ_check(ar, payload.get("version"))

    if ar["status"] not in ("SUBMITTED", "DEFICIENT"):
        raise invalid_state("AnnualReview is not SUBMITTED/DEFICIENT")

    ar["status"] = "DENIED"
    touch(ar)
    _cascade_denial(ar)
    return ar


def _cascade_denial(ar: dict) -> None:
    """Cascade tenancy → TERMINATED(ANNUAL_REVIEW_DENIED), voucher → TERMINATED."""
    tenancy = store.tenancies.get(ar["tenancy_id"])
    if tenancy is None:
        return
    if tenancy["status"] in ("ACTIVE", "ABATED", "PENDING_RENT_REASONABLE", "PENDING_INSPECTION"):
        tenancy["status"] = "TERMINATED"
        tenancy["termination_reason"] = "ANNUAL_REVIEW_DENIED"
        tenancy["terminated_at"] = clock.now()
        touch(tenancy)
        voucher = store.vouchers.get(tenancy["voucher_id"])
        if voucher is not None and voucher["status"] in ("LEASED", "SEARCHING", "SEARCHING_REISSUED"):
            voucher["status"] = "TERMINATED"
            touch(voucher)
