"""Entity assertions and domain invariant checkers.

These check response shape and domain invariants required by the PRD
contract.

PRD §2.4 — entities split into two shapes:

    common-fields (Taxpayer, TaxLiability, InstallmentAgreement,
    OfferInCompromise, FederalTaxLien, CNCStatus, ReconsiderationRequest):
        id, created_at, updated_at, version

    append-only (Payment, CSEDTollingEvent):
        id, created_at only — NO updated_at, NO version
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )


def _assert_created_at(data: Dict[str, Any]) -> None:
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'an integer version field that begins at 1 on creation
    and increments by 1 on every successful mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 common-fields entities."""
    _assert_id(data)
    _assert_created_at(data)
    _assert_updated_at_and_version(data)


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'The two append-only entities — Payment and
    CSEDTollingEvent — carry only id and created_at; neither updated_at
    nor version is present on them because they are never edited in
    place.'
    """
    _assert_id(data)
    _assert_created_at(data)


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.4: 'an integer version field that begins at 1 on creation
    and increments by 1 on every successful mutation.'"""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']}+{delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions — PRD §3
# ---------------------------------------------------------------------------
def assert_taxpayer(data: Dict[str, Any]) -> None:
    """PRD §3.1 Taxpayer fields."""
    assert_common_fields(data)
    assert isinstance(data["tin"], str) and len(data["tin"]) == 9, (
        f"tin must be 9 digits, got {data.get('tin')!r}"
    )
    assert data["filing_status"] in (
        "SINGLE", "MARRIED_JOINT", "MARRIED_SEPARATE", "HEAD_OF_HOUSEHOLD",
    )
    assert isinstance(data["monthly_disposable_income_cents"], int)
    assert isinstance(data["total_assessed_debt_cents"], int)
    assert data["total_assessed_debt_cents"] >= 0
    assert data["collection_status"] in (
        "ACTIVE", "IN_AGREEMENT", "IN_OIC_REVIEW",
        "IN_COMPROMISE", "CNC", "PAID_IN_FULL",
    )


def assert_tax_liability(data: Dict[str, Any]) -> None:
    """PRD §3.1 TaxLiability fields."""
    assert_common_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["tax_year"], int)
    assert is_iso8601_timestamp(data["assessment_date"])
    assert isinstance(data["original_assessed_amount_cents"], int)
    assert data["original_assessed_amount_cents"] > 0
    assert isinstance(data["accrued_interest_cents"], int)
    assert data["accrued_interest_cents"] >= 0
    assert isinstance(data["accrued_penalty_cents"], int)
    assert data["accrued_penalty_cents"] >= 0
    assert isinstance(data["payments_applied_cents"], int)
    assert data["payments_applied_cents"] >= 0
    assert isinstance(data["current_balance_cents"], int)
    assert data["current_balance_cents"] >= 0
    assert is_iso8601_timestamp(data["csed_base_date"])
    assert is_iso8601_timestamp(data["csed_effective_date"])
    assert data["status"] in (
        "OPEN", "IN_AGREEMENT", "IN_COMPROMISE", "CNC", "EXPIRED", "PAID",
    )


def assert_installment_agreement(data: Dict[str, Any]) -> None:
    """PRD §3.4 InstallmentAgreement fields."""
    assert_common_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["liability_ids"], list)
    assert len(data["liability_ids"]) >= 1
    assert data["agreement_type"] in ("SHORT_TERM", "LONG_TERM", "PPIA")
    assert isinstance(data["proposed_monthly_payment_cents"], int)
    assert data["proposed_monthly_payment_cents"] > 0
    assert data["payment_method"] in (
        "CHECK", "DDIA", "PAYROLL_DEDUCTION",
    )
    if data["payment_method"] == "DDIA":
        assert isinstance(data["ddia_bank_account_last4"], str)
        assert len(data["ddia_bank_account_last4"]) == 4
    assert isinstance(data["missed_payment_count"], int)
    assert data["missed_payment_count"] >= 0
    assert data["status"] in (
        "PENDING", "ACTIVE", "DEFAULTED", "TERMINATED", "COMPLETED",
    )


def assert_offer_in_compromise(data: Dict[str, Any]) -> None:
    """PRD §3.8 OfferInCompromise fields."""
    assert_common_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["liability_ids"], list)
    assert len(data["liability_ids"]) >= 1
    assert isinstance(data["offer_amount_cents"], int)
    assert data["offer_amount_cents"] > 0
    assert isinstance(data["deposit_paid_cents"], int)
    assert data["deposit_paid_cents"] >= 0
    assert isinstance(data["rcp_cents"], int)
    assert data["rcp_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW",
        "ACCEPTED", "REJECTED", "WITHDRAWN",
    )


def assert_federal_tax_lien(data: Dict[str, Any]) -> None:
    """PRD §3.7 FederalTaxLien fields."""
    assert_common_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["liability_ids"], list)
    assert len(data["liability_ids"]) >= 1
    assert is_iso8601_timestamp(data["filed_date"])
    assert data["status"] in ("FILED", "WITHDRAWN", "RELEASED")
    if data["status"] == "FILED":
        assert data.get("released_at") in (None, "")
        assert data.get("release_reason") in (None, "")
    else:
        assert is_iso8601_timestamp(data["released_at"])
        assert data["release_reason"] in (
            "PAID_IN_FULL", "OIC_ACCEPTED",
            "CSED_EXPIRED", "ADMIN_RELEASE",
        )


def assert_cnc_status(data: Dict[str, Any]) -> None:
    """PRD §3.11 CNCStatus fields."""
    assert_common_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["liability_ids"], list)
    assert len(data["liability_ids"]) >= 1
    assert data["hardship_reason"] in (
        "UNEMPLOYMENT", "MEDICAL",
        "NEGATIVE_DISPOSABLE_INCOME", "OTHER",
    )
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["review_due_date"])
    assert data["status"] in ("ACTIVE", "REVERSED", "EXPIRED")


def assert_reconsideration_request(data: Dict[str, Any]) -> None:
    """PRD §3.10 ReconsiderationRequest fields."""
    assert_common_fields(data)
    assert isinstance(data["agreement_id"], str)
    assert data["reason"] in (
        "HARDSHIP", "INCOME_CHANGE",
        "OIC_DENIED_REVERT", "MISSED_PAYMENT_CURE",
    )
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")


def assert_payment(data: Dict[str, Any]) -> None:
    """PRD §2.4 + §3.5 Payment — append-only entity."""
    assert_append_only_fields(data)
    assert isinstance(data["taxpayer_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["received_at"])
    assert data["payment_kind"] in (
        "INSTALLMENT", "OIC_DEPOSIT", "OIC_INSTALLMENT", "LUMP_SUM",
    )
    assert isinstance(data["allocation"], list)
    # PRD §3.5: "an array of { liability_id, applied_cents } rows whose
    # applied_cents values sum exactly to amount_cents."
    if data["allocation"]:
        for row in data["allocation"]:
            assert "liability_id" in row
            assert "applied_cents" in row
            assert isinstance(row["applied_cents"], int)
            assert row["applied_cents"] >= 0


# ---------------------------------------------------------------------------
# Cross-entity invariants — PRD §3.5 conservation laws
# ---------------------------------------------------------------------------
def assert_allocation_sums_to(payment: Dict[str, Any],
                              expected_total: int) -> None:
    """PRD §3.5: 'an array of { liability_id, applied_cents } rows whose
    applied_cents values sum exactly to amount_cents.'

    For a LUMP_SUM payment with surplus, expected_total is the portion
    actually allocated (amount_cents minus the unallocatable surplus).
    For INSTALLMENT / OIC_INSTALLMENT, the sum equals amount_cents.
    """
    total = sum(row["applied_cents"] for row in payment["allocation"])
    assert total == expected_total, (
        f"allocation sums to {total}, expected {expected_total}"
    )


def assert_current_balance_eq(liability: Dict[str, Any],
                              expected_cents: int) -> None:
    actual = liability["current_balance_cents"]
    assert actual == expected_cents, (
        f"current_balance_cents={actual}, expected {expected_cents}"
    )


def assert_status(entity: Dict[str, Any], expected_status: str) -> None:
    actual = entity.get("status")
    assert actual == expected_status, (
        f"status={actual!r}, expected {expected_status!r}"
    )


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_version_incremented_by",
    "assert_taxpayer",
    "assert_tax_liability",
    "assert_installment_agreement",
    "assert_offer_in_compromise",
    "assert_federal_tax_lien",
    "assert_cnc_status",
    "assert_reconsideration_request",
    "assert_payment",
    "assert_allocation_sums_to",
    "assert_current_balance_eq",
    "assert_status",
]
