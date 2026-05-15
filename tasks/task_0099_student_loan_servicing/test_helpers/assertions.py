"""Entity assertion helpers and domain invariant checks.

PRD §2.4 sets the canonical envelope rules:
  - Mutable entities (Borrower, Loan, RepaymentPlan, HardshipRequest,
    DischargeApplication, EmploymentCertification) carry id +
    created_at + updated_at + version.
  - Immutable entities (Payment, CollectionsAction, ClockState) carry
    only id + created_at; updated_at and version MUST NOT appear.

PRD §2.5 pins integer-cent precision everywhere. Helpers in this file
encode each rule verbatim from the PRD.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import THRESHOLDS


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: Dict[str, Any], entity_label: str) -> None:
    """PRD §2.4 rule for mutable entities — id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601 UTC, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be integer >= 1, got "
        f"{data.get('version')!r}"
    )


def _assert_common_immutable(data: Dict[str, Any], entity_label: str) -> None:
    """PRD §2.4 rule for immutable entities — id + created_at only.

    Asserts updated_at and version are absent (or None), since PRD says
    "neither updated_at nor version is present on those records."
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601 UTC, got "
        f"{data.get('created_at')!r}"
    )
    # Allow either missing keys or explicit None; reject any non-None
    # value on the forbidden fields.
    if "updated_at" in data:
        assert data["updated_at"] is None, (
            f"{entity_label} is an immutable entity per PRD §2.4 and "
            f"must not carry updated_at; got {data['updated_at']!r}"
        )
    if "version" in data:
        assert data["version"] is None, (
            f"{entity_label} is an immutable entity per PRD §2.4 and "
            f"must not carry version; got {data['version']!r}"
        )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_borrower(data: Dict[str, Any]) -> None:
    """Validate Borrower response shape against PRD §3.1 + §2.4."""
    _assert_common_mutable(data, "Borrower")
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    ssn = data.get("ssn_last4")
    assert isinstance(ssn, str) and len(ssn) == 4 and ssn.isdigit(), (
        f"PRD §3.1: ssn_last4 must be exactly 4 numeric characters, "
        f"got {ssn!r}"
    )
    assert isinstance(data.get("family_size"), int) and data["family_size"] >= 1
    assert isinstance(data.get("state_code"), str)
    assert isinstance(data.get("adjusted_gross_income_cents"), int)
    assert data["adjusted_gross_income_cents"] >= 0
    assert data.get("veteran_status") in {"NONE", "VETERAN", "TPD_VETERAN"}
    # Aggregate fields are computed (PRD §2.11) and must be integer cents.
    assert isinstance(data.get("aggregate_principal_balance_cents"), int)
    assert isinstance(data.get("aggregate_interest_balance_cents"), int)
    assert data["aggregate_principal_balance_cents"] >= 0
    assert data["aggregate_interest_balance_cents"] >= 0


VALID_LOAN_STATUSES = {
    "IN_SCHOOL", "GRACE", "REPAYMENT", "DEFERMENT", "FORBEARANCE",
    "DELINQUENT", "DEFAULT", "REHABILITATION", "PAID_OFF", "DISCHARGED",
}
VALID_LOAN_TYPES = {"DIRECT_SUBSIDIZED", "DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"}


def assert_loan(data: Dict[str, Any]) -> None:
    """Validate Loan response shape against PRD §3.2 + §2.4."""
    _assert_common_mutable(data, "Loan")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert data.get("loan_type") in VALID_LOAN_TYPES
    assert data.get("status") in VALID_LOAN_STATUSES
    assert isinstance(data.get("original_principal_cents"), int)
    assert data["original_principal_cents"] > 0
    assert isinstance(data.get("principal_balance_cents"), int)
    assert data["principal_balance_cents"] >= 0
    assert isinstance(data.get("accrued_interest_cents"), int)
    assert data["accrued_interest_cents"] >= 0
    assert isinstance(data.get("capitalized_interest_cents"), int)
    assert data["capitalized_interest_cents"] >= 0
    assert isinstance(data.get("interest_rate_bps"), int)
    assert 0 < data["interest_rate_bps"] <= 2000, (
        "PRD §3.2: interest_rate_bps capped at 2000 basis points"
    )
    assert isinstance(data.get("days_past_due"), int)
    assert data["days_past_due"] >= 0
    assert isinstance(data.get("qualifying_pslf_payment_count"), int)
    assert data["qualifying_pslf_payment_count"] >= 0


VALID_PLAN_STATUSES = {"PENDING", "ACTIVE", "SUPERSEDED", "TERMINATED"}
VALID_PLAN_TYPES = {"STANDARD_10", "IBR", "PAYE", "SAVE"}


def assert_repayment_plan(data: Dict[str, Any]) -> None:
    """Validate RepaymentPlan response shape against PRD §3.7 + §2.4."""
    _assert_common_mutable(data, "RepaymentPlan")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert data.get("plan_type") in VALID_PLAN_TYPES
    assert data.get("status") in VALID_PLAN_STATUSES
    assert isinstance(data.get("monthly_payment_cents"), int)
    assert data["monthly_payment_cents"] >= 0
    assert isinstance(data.get("included_loan_ids"), list)
    assert isinstance(data.get("certified_agi_cents"), int)
    assert data["certified_agi_cents"] >= 0
    assert isinstance(data.get("certified_family_size"), int)
    assert data["certified_family_size"] >= 0


VALID_HARDSHIP_KINDS = {
    "DEFERMENT_IN_SCHOOL", "DEFERMENT_UNEMPLOYMENT",
    "DEFERMENT_ECONOMIC_HARDSHIP", "DEFERMENT_MILITARY",
    "FORBEARANCE_GENERAL", "FORBEARANCE_MANDATORY",
}
VALID_HARDSHIP_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED", "CANCELLED"}


def assert_hardship_request(data: Dict[str, Any]) -> None:
    """Validate HardshipRequest response shape against PRD §3.5 + §2.4."""
    _assert_common_mutable(data, "HardshipRequest")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert data.get("kind") in VALID_HARDSHIP_KINDS
    assert data.get("status") in VALID_HARDSHIP_STATUSES
    assert isinstance(data.get("applied_loan_ids"), list)
    assert is_iso8601_timestamp(data.get("requested_from", ""))
    assert is_iso8601_timestamp(data.get("requested_to", ""))
    assert isinstance(data.get("cumulative_forbearance_days_at_request"), int)
    assert data["cumulative_forbearance_days_at_request"] >= 0


VALID_DISCHARGE_PROGRAMS = {"PSLF", "VETERAN_TPD"}
VALID_DISCHARGE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED"}


def assert_discharge_application(data: Dict[str, Any]) -> None:
    """Validate DischargeApplication response shape against PRD §3.9 + §2.4."""
    _assert_common_mutable(data, "DischargeApplication")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert data.get("program") in VALID_DISCHARGE_PROGRAMS
    assert data.get("status") in VALID_DISCHARGE_STATUSES
    assert isinstance(data.get("approved_loan_ids", []), list)
    assert isinstance(data.get("discharged_principal_cents", 0), int)
    assert isinstance(data.get("discharged_interest_cents", 0), int)


VALID_EMPLOYER_TYPES = {
    "GOVERNMENT", "NONPROFIT_501C3",
    "OTHER_NONPROFIT_QUALIFYING", "PRIVATE_NON_QUALIFYING",
}
VALID_CERT_STATUSES = {"SUBMITTED", "APPROVED", "REJECTED"}


def assert_employment_certification(data: Dict[str, Any]) -> None:
    """Validate EmploymentCertification response shape against PRD §3.8 + §2.4."""
    _assert_common_mutable(data, "EmploymentCertification")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data.get("employer_name"), str) and data["employer_name"]
    assert data.get("employer_type") in VALID_EMPLOYER_TYPES
    assert data.get("status") in VALID_CERT_STATUSES
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))


VALID_PAYMENT_SOURCES = {
    "BORROWER", "EMPLOYER",
    "ADMINISTRATIVE_WAGE_GARNISHMENT", "TREASURY_OFFSET",
}


def assert_payment(data: Dict[str, Any]) -> None:
    """Validate Payment response shape against PRD §3.4 + §2.4.

    Payment is immutable per §2.4 — must not carry updated_at or version.
    """
    _assert_common_immutable(data, "Payment")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0, (
        "PRD §3.4: Payment.amount_cents must be positive"
    )
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert data.get("source") in VALID_PAYMENT_SOURCES
    assert isinstance(data.get("pslf_qualifying"), bool)
    assert isinstance(data.get("allocations"), list)
    for alloc in data["allocations"]:
        assert is_valid_uuid(alloc.get("loan_id", ""))
        # PRD §3.4: fees_cents always 0 in this system.
        assert alloc.get("fees_cents", 0) == 0
        assert isinstance(alloc.get("interest_cents", 0), int)
        assert isinstance(alloc.get("principal_cents", 0), int)
        assert alloc.get("interest_cents", 0) >= 0
        assert alloc.get("principal_cents", 0) >= 0


VALID_COLLECTIONS_KINDS = {
    "DEFAULT_DECLARATION", "REHAB_AGREEMENT_OPEN", "REHAB_PAYMENT_RECORDED",
    "REHAB_COMPLETED", "WAGE_GARNISHMENT_ORDER", "TREASURY_OFFSET_APPLIED",
}


def assert_collections_action(data: Dict[str, Any]) -> None:
    """Validate CollectionsAction response shape against PRD §3.6 + §2.4.

    CollectionsAction is immutable per §2.4.
    """
    _assert_common_immutable(data, "CollectionsAction")
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert is_valid_uuid(data.get("loan_id", ""))
    assert data.get("kind") in VALID_COLLECTIONS_KINDS
    assert isinstance(data.get("amount_cents", 0), int)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert isinstance(data.get("recorded_by"), str) and data["recorded_by"]


# ---------------------------------------------------------------------------
# Domain invariant checks
# ---------------------------------------------------------------------------
def assert_loan_invariants(loan: Dict[str, Any]) -> None:
    """Cross-field invariants on a single Loan record per PRD §2.5 + §3.3."""
    assert loan["principal_balance_cents"] >= 0
    assert loan["accrued_interest_cents"] >= 0
    assert loan["capitalized_interest_cents"] >= 0
    # Interest cap: PRD §3.2 — bps in (0, 2000].
    assert 0 < loan["interest_rate_bps"] <= 2000


def assert_borrower_aggregates_match(borrower: Dict[str, Any],
                                     loans: Iterable[Dict[str, Any]]) -> None:
    """PRD §2.11: aggregate fields are the live sum across non-terminal loans.

    PRD §2.11: "the borrower's aggregate_principal_balance_cents and
    aggregate_interest_balance_cents are recomputed as the sums of
    principal_balance_cents and accrued_interest_cents across that
    borrower's non-terminal loans. A loan that has reached either of
    the two terminal statuses (PAID_OFF or DISCHARGED) drops out of
    the aggregate."
    """
    expected_principal = 0
    expected_interest = 0
    for loan in loans:
        if loan["status"] in ("PAID_OFF", "DISCHARGED"):
            continue
        expected_principal += loan["principal_balance_cents"]
        expected_interest += loan["accrued_interest_cents"]
    assert borrower["aggregate_principal_balance_cents"] == expected_principal, (
        f"PRD §2.11 aggregate_principal_balance_cents mismatch: "
        f"got {borrower['aggregate_principal_balance_cents']}, "
        f"expected {expected_principal}"
    )
    assert borrower["aggregate_interest_balance_cents"] == expected_interest, (
        f"PRD §2.11 aggregate_interest_balance_cents mismatch: "
        f"got {borrower['aggregate_interest_balance_cents']}, "
        f"expected {expected_interest}"
    )


def assert_version_bumped(new_resource: Dict[str, Any],
                          old_version: int) -> None:
    """PRD §2.4: every successful mutation increments version by 1."""
    assert new_resource["version"] == old_version + 1, (
        f"PRD §2.4: version must increment by 1 on every successful "
        f"mutation. Was {old_version}, now {new_resource['version']}"
    )


def assert_integer_cents(value: Any, field_label: str = "value") -> None:
    """PRD §2.5: monetary fields are integer cents with no fractional cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"PRD §2.5: {field_label} must be integer cents, got "
        f"{type(value).__name__}({value!r})"
    )


__all__ = [
    "assert_borrower",
    "assert_loan",
    "assert_repayment_plan",
    "assert_hardship_request",
    "assert_discharge_application",
    "assert_employment_certification",
    "assert_payment",
    "assert_collections_action",
    "assert_loan_invariants",
    "assert_borrower_aggregates_match",
    "assert_version_bumped",
    "assert_integer_cents",
    "VALID_LOAN_STATUSES",
    "VALID_LOAN_TYPES",
    "VALID_PLAN_STATUSES",
    "VALID_PLAN_TYPES",
    "VALID_HARDSHIP_KINDS",
    "VALID_HARDSHIP_STATUSES",
    "VALID_DISCHARGE_PROGRAMS",
    "VALID_DISCHARGE_STATUSES",
    "VALID_EMPLOYER_TYPES",
    "VALID_CERT_STATUSES",
    "VALID_PAYMENT_SOURCES",
    "VALID_COLLECTIONS_KINDS",
]
