"""Payload factories — one per entity, INPUT fields only.

The PRD-required input fields and their shapes are pinned in §3 of the
PRD. Computed fields (status, balances, version, created_at, etc.) are
never accepted from input and never live here.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Borrower (PRD §3.1)
# ---------------------------------------------------------------------------
def create_borrower_payload(**overrides) -> Dict[str, Any]:
    """Default payload for POST /borrowers.

    PRD §3.1 required: full_name, ssn_last4, state_code.
    family_size defaults to 1; adjusted_gross_income_cents defaults to
    0; agi_certified_at and veteran_status default to absent/NONE.
    """
    defaults: Dict[str, Any] = {
        "full_name": "Test Borrower",
        "ssn_last4": "1234",
        "family_size": TEST_DEFAULTS["DEFAULT_FAMILY_SIZE"],
        "state_code": TEST_DEFAULTS["DEFAULT_STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def update_borrower_payload(**overrides) -> Dict[str, Any]:
    """PATCH /borrowers/{id} accepts any subset of demographic fields."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Loan (PRD §3.2)
# ---------------------------------------------------------------------------
def create_loan_payload(**overrides) -> Dict[str, Any]:
    """Default payload for POST /borrowers/{bid}/loans.

    PRD §3.2 required: loan_type, original_principal_cents,
    interest_rate_bps, disbursement_date.
    """
    defaults: Dict[str, Any] = {
        "loan_type": "DIRECT_UNSUBSIDIZED",
        "original_principal_cents": TEST_DEFAULTS["DEFAULT_PRINCIPAL_CENTS"],
        "interest_rate_bps": TEST_DEFAULTS["DEFAULT_INTEREST_RATE_BPS"],
        "disbursement_date": TEST_DEFAULTS["DEFAULT_DISBURSEMENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def separate_loan_payload(**overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/loans/{lid}/separate — optional skip_grace."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Payment (PRD §3.4)
# ---------------------------------------------------------------------------
def create_payment_payload(amount_cents: int = 10_000,
                           **overrides) -> Dict[str, Any]:
    """Default payload for POST /borrowers/{bid}/payments.

    PRD §3.4 required: amount_cents (positive integer).
    source defaults to BORROWER, received_at defaults to current clock.
    """
    defaults: Dict[str, Any] = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Repayment plan (PRD §3.7)
# ---------------------------------------------------------------------------
def create_plan_payload(plan_type: str,
                        included_loan_ids: List[str],
                        **overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/plans — required plan_type + included_loan_ids."""
    defaults: Dict[str, Any] = {
        "plan_type": plan_type,
        "included_loan_ids": list(included_loan_ids),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Hardship request (PRD §3.5)
# ---------------------------------------------------------------------------
def create_hardship_request_payload(kind: str,
                                    requested_from: str,
                                    requested_to: str,
                                    applied_loan_ids: List[str],
                                    **overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/hardship-requests.

    PRD §3.5 required: kind, requested_from, requested_to,
    applied_loan_ids.
    """
    defaults: Dict[str, Any] = {
        "kind": kind,
        "requested_from": requested_from,
        "requested_to": requested_to,
        "applied_loan_ids": list(applied_loan_ids),
    }
    defaults.update(overrides)
    return defaults


def update_hardship_request_payload(status: str,
                                    **overrides) -> Dict[str, Any]:
    """PATCH /borrowers/{bid}/hardship-requests/{rid}."""
    defaults: Dict[str, Any] = {"status": status}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Discharge application (PRD §3.9)
# ---------------------------------------------------------------------------
def create_discharge_application_payload(program: str,
                                         **overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/discharge-applications.

    PRD §3.9 required: program (PSLF or VETERAN_TPD).
    """
    defaults: Dict[str, Any] = {"program": program}
    defaults.update(overrides)
    return defaults


def update_discharge_application_payload(status: str,
                                         approved_loan_ids: Optional[List[str]] = None,
                                         **overrides) -> Dict[str, Any]:
    """PATCH /borrowers/{bid}/discharge-applications/{aid}."""
    defaults: Dict[str, Any] = {"status": status}
    if approved_loan_ids is not None:
        defaults["approved_loan_ids"] = list(approved_loan_ids)
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Employment certification (PRD §3.8)
# ---------------------------------------------------------------------------
def create_employment_certification_payload(employer_name: str = "Test Public Agency",
                                            employer_type: str = "GOVERNMENT",
                                            period_start: str = "2025-01-01T00:00:00.000Z",
                                            period_end: str = "2026-12-31T23:59:59.999Z",
                                            **overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/employment-certifications.

    PRD §3.8 required: employer_name, employer_type, period_start,
    period_end.
    """
    defaults: Dict[str, Any] = {
        "employer_name": employer_name,
        "employer_type": employer_type,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def update_employment_certification_payload(status: str,
                                            **overrides) -> Dict[str, Any]:
    """PATCH /borrowers/{bid}/employment-certifications/{cid}."""
    defaults: Dict[str, Any] = {"status": status}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Collections action (PRD §3.6)
# ---------------------------------------------------------------------------
def create_collections_action_payload(kind: str,
                                      amount_cents: int = 0,
                                      occurred_at: Optional[str] = None,
                                      **overrides) -> Dict[str, Any]:
    """POST /borrowers/{bid}/loans/{lid}/collections.

    PRD §3.6 required: kind. amount_cents defaults to 0 for non-
    financial kinds; occurred_at defaults to the current clock.
    """
    defaults: Dict[str, Any] = {
        "kind": kind,
        "amount_cents": amount_cents,
    }
    if occurred_at is not None:
        defaults["occurred_at"] = occurred_at
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Helpers for unique values in parametrized tests.
# ---------------------------------------------------------------------------
def unique_borrower_name(prefix: str = "Borrower") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


__all__ = [
    "create_borrower_payload",
    "update_borrower_payload",
    "create_loan_payload",
    "separate_loan_payload",
    "create_payment_payload",
    "create_plan_payload",
    "create_hardship_request_payload",
    "update_hardship_request_payload",
    "create_discharge_application_payload",
    "update_discharge_application_payload",
    "create_employment_certification_payload",
    "update_employment_certification_payload",
    "create_collections_action_payload",
    "unique_borrower_name",
]
