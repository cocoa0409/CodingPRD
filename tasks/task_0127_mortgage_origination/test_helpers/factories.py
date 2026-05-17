"""Payload factories — one per input-bearing endpoint.

Every factory emits the exact field names PRD §3 specifies. Optional
fields are omitted by default unless the caller passes them. Computed
fields (status, dti_ratio, ltv_ratio, version, etc.) are never emitted
— they are set by the server.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS
from .test_users import LOAN_OFFICER_ID


# ---------------------------------------------------------------------------
# Borrower — PRD §3.1
# ---------------------------------------------------------------------------
def create_borrower_payload(
    *,
    full_name: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    annual_income_cents: Optional[int] = None,
    credit_score: Optional[int] = None,
    state_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /borrowers — PRD §3.1.

    All five fields are required per PRD §3.1: full_name, ssn_last4
    (exactly 4 numeric chars), annual_income_cents (non-negative),
    credit_score (300..850), state_code (2 letters).
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name
            if full_name is not None
            else f"{TEST_DEFAULTS['BORROWER_FULL_NAME']} "
                 f"{_uuid.uuid4().hex[:6]}"
        ),
        "ssn_last4": (
            ssn_last4 if ssn_last4 is not None
            else TEST_DEFAULTS["BORROWER_SSN_LAST4"]
        ),
        "annual_income_cents": (
            annual_income_cents
            if annual_income_cents is not None
            else TEST_DEFAULTS["BORROWER_ANNUAL_INCOME_CENTS"]
        ),
        "credit_score": (
            credit_score if credit_score is not None
            else TEST_DEFAULTS["BORROWER_CREDIT_SCORE"]
        ),
        "state_code": (
            state_code if state_code is not None
            else TEST_DEFAULTS["BORROWER_STATE_CODE"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LoanApplication — PRD §3.1
# ---------------------------------------------------------------------------
def create_loan_application_payload(
    *,
    borrower_id: str,
    property_address: Optional[str] = None,
    sale_price_cents: Optional[int] = None,
    requested_loan_amount_cents: Optional[int] = None,
    loan_term_months: Optional[int] = None,
    loan_purpose: Optional[str] = None,
    assigned_loan_officer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /loan-applications — PRD §3.1.

    Inputs per PRD §3.1: borrower_id, property_address, sale_price_cents
    (> 0), requested_loan_amount_cents (> 0 and <= sale_price_cents),
    loan_term_months (one of 120/180/240/360), loan_purpose
    (PURCHASE/REFINANCE), assigned_loan_officer_id.
    """
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "property_address": (
            property_address if property_address is not None
            else TEST_DEFAULTS["PROPERTY_ADDRESS"]
        ),
        "sale_price_cents": (
            sale_price_cents if sale_price_cents is not None
            else TEST_DEFAULTS["SALE_PRICE_CENTS"]
        ),
        "requested_loan_amount_cents": (
            requested_loan_amount_cents
            if requested_loan_amount_cents is not None
            else TEST_DEFAULTS["REQUESTED_LOAN_AMOUNT_CENTS"]
        ),
        "loan_term_months": (
            loan_term_months if loan_term_months is not None
            else TEST_DEFAULTS["LOAN_TERM_MONTHS"]
        ),
        "loan_purpose": (
            loan_purpose if loan_purpose is not None
            else TEST_DEFAULTS["LOAN_PURPOSE"]
        ),
        "assigned_loan_officer_id": (
            assigned_loan_officer_id
            if assigned_loan_officer_id is not None
            else LOAN_OFFICER_ID
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Income verification — PRD §3.3
# ---------------------------------------------------------------------------
def create_income_verification_payload(
    *,
    source_type: str = "W2",
    documented_annual_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../income-verifications — PRD §3.3.

    PRD §3.3: source_type in {W2, SELF_EMPLOYED, OTHER};
    documented_annual_cents non-negative integer cents.
    """
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "documented_annual_cents": (
            documented_annual_cents
            if documented_annual_cents is not None
            else TEST_DEFAULTS["INCOME_DOCUMENTED_ANNUAL_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Asset verification — PRD §3.3
# ---------------------------------------------------------------------------
def create_asset_verification_payload(
    *,
    asset_type: str = "SAVINGS",
    balance_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../asset-verifications — PRD §3.3.

    PRD §3.3: asset_type in {CHECKING, SAVINGS, INVESTMENT, GIFT};
    balance_cents non-negative integer.
    """
    payload: Dict[str, Any] = {
        "asset_type": asset_type,
        "balance_cents": (
            balance_cents if balance_cents is not None
            else TEST_DEFAULTS["ASSET_BALANCE_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appraisal — PRD §3.4
# ---------------------------------------------------------------------------
def order_appraisal_payload(
    *,
    report_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../appraisal — PRD §3.4 input is report_date only."""
    payload: Dict[str, Any] = {
        "report_date": (
            report_date if report_date is not None
            else TEST_DEFAULTS["APPRAISAL_REPORT_DATE"]
        ),
    }
    payload.update(overrides)
    return payload


def complete_appraisal_payload(
    *,
    appraised_value_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../appraisal/complete — PRD §3.4 input is
    appraised_value_cents only.
    """
    payload: Dict[str, Any] = {
        "appraised_value_cents": (
            appraised_value_cents
            if appraised_value_cents is not None
            else TEST_DEFAULTS["APPRAISED_VALUE_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Title search — PRD §3.4
# ---------------------------------------------------------------------------
def complete_title_search_payload(
    *,
    defects_found: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../title-search/complete — PRD §3.4: defects_found array;
    empty -> CLEAR, non-empty -> ISSUES_FOUND.
    """
    payload: Dict[str, Any] = {
        "defects_found": defects_found if defects_found is not None else [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Rate lock — PRD §3.5
# ---------------------------------------------------------------------------
def place_rate_lock_payload(
    *,
    locked_rate_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../rate-lock — PRD §3.5: locked_rate_bps strictly positive
    and not exceeding 2,000.
    """
    payload: Dict[str, Any] = {
        "locked_rate_bps": (
            locked_rate_bps if locked_rate_bps is not None
            else TEST_DEFAULTS["LOCKED_RATE_BPS"]
        ),
    }
    payload.update(overrides)
    return payload


def extend_rate_lock_payload(
    *,
    extra_days: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../rate-lock/extend — PRD §3.5: extra_days in {7, 15, 30}."""
    payload: Dict[str, Any] = {"extra_days": extra_days}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disclosures — PRD §3.6
# ---------------------------------------------------------------------------
def issue_disclosure_payload(
    *,
    kind: str,
    apr_bps: Optional[int] = None,
    total_loan_costs_cents: Optional[int] = None,
    total_other_costs_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../disclosures — PRD §3.6.

    Inputs: kind (LOAN_ESTIMATE / CLOSING_DISCLOSURE), apr_bps (strictly
    positive, no greater than 2,500), total_loan_costs_cents,
    total_other_costs_cents.

    PRD §2.4: "Clients may not supply a version in the disclosure-
    issuance body; the server mints the next number atomically."
    Tests that want to exercise the version-conflict path pass a
    version via **overrides explicitly.
    """
    payload: Dict[str, Any] = {
        "kind": kind,
        "apr_bps": (
            apr_bps if apr_bps is not None
            else TEST_DEFAULTS["LE_APR_BPS"]
        ),
        "total_loan_costs_cents": (
            total_loan_costs_cents
            if total_loan_costs_cents is not None
            else TEST_DEFAULTS["TOTAL_LOAN_COSTS_CENTS"]
        ),
        "total_other_costs_cents": (
            total_other_costs_cents
            if total_other_costs_cents is not None
            else TEST_DEFAULTS["TOTAL_OTHER_COSTS_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# UDAAP review — PRD §3.9
# ---------------------------------------------------------------------------
def submit_udaap_review_payload(
    *,
    outcome: str = "PASS",
    notes: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../udaap-reviews — PRD §3.9.

    outcome in {PASS, FLAG, BLOCK}; notes required when outcome is
    FLAG or BLOCK.
    """
    payload: Dict[str, Any] = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Submit underwriting — PRD §3.7
# ---------------------------------------------------------------------------
def submit_underwriting_payload(
    *,
    compliance_reviewer_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../submit-underwriting — PRD §3.7: payload carries
    compliance_reviewer_id, the opaque identifier of the
    ComplianceOfficer who will own the UDAAP review.
    """
    payload: Dict[str, Any] = {
        "compliance_reviewer_id": compliance_reviewer_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Underwrite decision — PRD §3.8
# ---------------------------------------------------------------------------
def underwrite_decision_payload(
    *,
    decision: str,
    counter_offered_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../underwrite-decision — PRD §3.8.

    decision in {APPROVE, COUNTER_OFFER, DENY};
    counter_offered_amount_cents required when decision=COUNTER_OFFER.
    """
    payload: Dict[str, Any] = {"decision": decision}
    if counter_offered_amount_cents is not None:
        payload["counter_offered_amount_cents"] = (
            counter_offered_amount_cents
        )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock — PRD §2.9
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — PRD §2.9: "to a supplied to instant in
    ISO 8601 UTC".
    """
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OCC version envelope — PRD §2.7
# ---------------------------------------------------------------------------
def version_body(version: int) -> Dict[str, Any]:
    """PRD §2.7: "Endpoints that mutate an existing resource accept an
    optional version integer in the request body."
    """
    return {"version": version}


__all__ = [
    "create_borrower_payload",
    "create_loan_application_payload",
    "create_income_verification_payload",
    "create_asset_verification_payload",
    "order_appraisal_payload",
    "complete_appraisal_payload",
    "complete_title_search_payload",
    "place_rate_lock_payload",
    "extend_rate_lock_payload",
    "issue_disclosure_payload",
    "submit_udaap_review_payload",
    "submit_underwriting_payload",
    "underwrite_decision_payload",
    "clock_advance_payload",
    "version_body",
]
