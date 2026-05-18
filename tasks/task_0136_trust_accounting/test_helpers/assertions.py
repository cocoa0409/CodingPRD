"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4: 'Most resources expose four common fields: id, created_at,
updated_at, and version. ... One entity is an exception: the
Transaction resource is an append-only event-log record that carries
only id and created_at; it has no updated_at and no version'.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that starts at 1 on creation
    and increments by exactly 1 on every successful mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Monetary precision — PRD §2.7
# ---------------------------------------------------------------------------
def assert_money_2dp(value: Any, field: str = "monetary field") -> None:
    """PRD §2.7: 'All monetary fields are denominated in United States
    dollars and carry exactly 2 decimal places.'"""
    assert isinstance(value, (int, float)), (
        f"{field} must be numeric, got {type(value).__name__}: {value!r}"
    )
    # 2dp tolerance: float ↔ representation imprecision must not exceed 0.5e-2.
    rounded = round(float(value) + 1e-9, 2)
    assert abs(float(value) - rounded) < 1e-6, (
        f"{field} carries more than 2 decimal places: {value!r}"
    )


# ---------------------------------------------------------------------------
# Trust — PRD §3.1
# ---------------------------------------------------------------------------
def assert_trust(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("trust_type") in {"REVOCABLE", "IRREVOCABLE"}, (
        f"trust_type {data.get('trust_type')!r} not in PRD enum"
    )
    assert data.get("grantor_tax_status") in {"GRANTOR", "NON_GRANTOR"}
    assert isinstance(data.get("has_grantor_powers"), bool)
    assert isinstance(data.get("grantor_user_id"), str) and (
        data["grantor_user_id"]
    )
    assert isinstance(data.get("situs_state"), str) and (
        len(data["situs_state"]) == 2
    )
    assert isinstance(data.get("inception_date"), str)
    assert data.get("status") in {
        "DRAFT", "ACTIVE", "TERMINATED", "REVOKED",
    }
    assert_money_2dp(data.get("principal_balance"), "principal_balance")
    assert_money_2dp(data.get("income_balance"), "income_balance")
    assert_money_2dp(data.get("gst_exemption_used"),
                     "gst_exemption_used")


def assert_trust_invariants(data: Dict[str, Any]) -> None:
    """Cross-field invariants implied by PRD §3.1 / §3.9: balances are
    non-negative; gst_exemption_used cannot exceed the limit."""
    assert data["principal_balance"] >= 0, (
        f"principal_balance must be >= 0, got {data['principal_balance']}"
    )
    assert data["income_balance"] >= 0, (
        f"income_balance must be >= 0, got {data['income_balance']}"
    )
    assert data["gst_exemption_used"] >= 0
    # PRD §3.6: cap is 13,610,000.00.
    assert data["gst_exemption_used"] <= 13_610_000.00 + 1e-6


# ---------------------------------------------------------------------------
# Trustee — PRD §3.2
# ---------------------------------------------------------------------------
def assert_trustee(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("user_id"), str) and data["user_id"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("is_primary"), bool)
    assert data.get("status") in {"ACTIVE", "RESIGNED", "REMOVED"}


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.2
# ---------------------------------------------------------------------------
def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("relation_class") in {
        "SPOUSE", "CHILD", "GRANDCHILD", "OTHER_LINEAL", "NON_LINEAL",
    }
    assert isinstance(data.get("is_skip_person"), bool)
    assert data.get("beneficiary_class") in {
        "INCOME", "REMAINDER", "INCOME_AND_REMAINDER",
    }
    assert data.get("distribution_tier") in {"TIER_1", "TIER_2"}
    assert data.get("status") in {"ACTIVE", "TERMINATED"}
    assert isinstance(data.get("birth_date"), str)


# ---------------------------------------------------------------------------
# Asset — PRD §3.2
# ---------------------------------------------------------------------------
def assert_asset(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("description"), str)
    assert data.get("asset_class") in {
        "CASH", "EQUITY", "BOND", "REAL_ESTATE", "OTHER",
    }
    assert_money_2dp(data.get("book_value"), "book_value")
    assert data.get("classification") in {"PRINCIPAL", "INCOME"}
    assert data.get("status") in {"FUNDED", "DISTRIBUTED", "SOLD"}


# ---------------------------------------------------------------------------
# Transaction — PRD §2.4, §3.3 (append-only)
# ---------------------------------------------------------------------------
def assert_transaction(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4 carves Transaction out: "no updated_at and no version".
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "Transaction must NOT carry updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "Transaction must NOT carry version per PRD §2.4"
    )
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("tax_year_id"), str)
    assert data.get("txn_type") in {
        "INCOME_ORDINARY", "INCOME_INTEREST", "INCOME_DIVIDEND",
        "INCOME_CAPITAL_GAIN", "EXPENSE_ADMINISTRATIVE",
        "EXPENSE_INVESTMENT",
    }
    assert_money_2dp(data.get("amount"), "amount")
    assert data["amount"] >= 0, "Transaction.amount is always positive"
    assert isinstance(data.get("transaction_date"), str)
    assert data.get("principal_or_income") in {"PRINCIPAL", "INCOME"}
    assert isinstance(data.get("description"), str)


# ---------------------------------------------------------------------------
# Distribution — PRD §3.4
# ---------------------------------------------------------------------------
def assert_distribution(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    assert isinstance(data.get("tax_year_id"), str)
    assert isinstance(data.get("scheduled_date"), str)
    assert_money_2dp(data.get("amount_principal"), "amount_principal")
    assert_money_2dp(data.get("amount_income"), "amount_income")
    assert data["amount_principal"] >= 0
    assert data["amount_income"] >= 0
    assert data.get("distribution_type") in {
        "MANDATORY", "DISCRETIONARY", "TERMINATING",
    }
    assert data.get("status") in {
        "PROPOSED", "APPROVED", "EXECUTED", "REJECTED",
    }
    assert isinstance(data.get("proposed_by_user_id"), str) and (
        data["proposed_by_user_id"]
    )
    # approved_by_user_id is null until APPROVED.
    approved_by = data.get("approved_by_user_id")
    assert approved_by is None or (isinstance(approved_by, str)
                                   and approved_by)
    assert isinstance(data.get("gst_taxable"), bool)
    assert_money_2dp(data.get("gst_tax_amount"), "gst_tax_amount")
    assert data["gst_tax_amount"] >= 0


# ---------------------------------------------------------------------------
# TaxYear — PRD §3.5
# ---------------------------------------------------------------------------
def assert_tax_year(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("trust_id"), str)
    cy = data.get("calendar_year")
    assert isinstance(cy, int) and 1900 <= cy <= 3000, (
        f"calendar_year must be a 4-digit year, got {cy!r}"
    )
    assert isinstance(data.get("start_date"), str)
    assert isinstance(data.get("end_date"), str)
    assert data.get("status") in {
        "OPEN", "CLOSING", "CLOSED", "AMENDED",
    }
    assert_money_2dp(data.get("dni"), "dni")
    assert_money_2dp(data.get("trust_taxable_income"),
                     "trust_taxable_income")
    assert_money_2dp(data.get("trust_income_tax"), "trust_income_tax")
    closed_at = data.get("closed_at")
    assert closed_at is None or is_iso8601_timestamp(closed_at)


# ---------------------------------------------------------------------------
# K1 — PRD §3.7
# ---------------------------------------------------------------------------
def assert_k1(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_year_id"), str)
    assert isinstance(data.get("trust_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    assert_money_2dp(data.get("ordinary_income_share"),
                     "ordinary_income_share")
    assert_money_2dp(data.get("interest_income_share"),
                     "interest_income_share")
    assert_money_2dp(data.get("dividend_income_share"),
                     "dividend_income_share")
    assert_money_2dp(data.get("capital_gain_share"),
                     "capital_gain_share")
    assert_money_2dp(data.get("total_distributed"), "total_distributed")
    assert data.get("status") in {"DRAFT", "ISSUED", "SUPERSEDED"}
    sdvs = data.get("snapshot_distribution_version_sum")
    assert sdvs is None or isinstance(sdvs, int)
    issued_at = data.get("issued_at")
    assert issued_at is None or is_iso8601_timestamp(issued_at)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.4: 'version ... increments by exactly 1 on every
    successful mutation of the resource'."""
    assert new_version == old_version + 1, (
        f"version must increment by exactly 1: was {old_version}, "
        f"got {new_version}"
    )


__all__ = [
    "assert_money_2dp",
    "assert_trust",
    "assert_trust_invariants",
    "assert_trustee",
    "assert_beneficiary",
    "assert_asset",
    "assert_transaction",
    "assert_distribution",
    "assert_tax_year",
    "assert_k1",
    "assert_version_incremented_by_one",
]
