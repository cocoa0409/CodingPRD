"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the PRD
contract. They are intentionally generous about server-minted fields
(e.g., computed counters): a test that wants to pin a specific computed
value asserts it directly in test code.
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
    """PRD §2.4 four common properties: id, created_at, updated_at,
    version. Asserted for entities that carry version (i.e., NOT
    Contribution, EducationExpense, or TaxReport)."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Donor
# ---------------------------------------------------------------------------
def assert_donor(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "full_name must be a non-empty string"
    )
    soa = data.get("state_of_residence")
    assert isinstance(soa, str) and len(soa) == 2 and soa.isupper(), (
        f"state_of_residence must be exactly two uppercase letters, got {soa!r}"
    )
    ssn = data.get("ssn_last_four")
    assert isinstance(ssn, str) and len(ssn) == 4 and ssn.isdigit(), (
        f"ssn_last_four must be exactly 4 digits, got {ssn!r}"
    )
    assert isinstance(data.get("ytd_contribution_total_cents"), int)
    assert data["ytd_contribution_total_cents"] >= 0
    assert isinstance(data.get("ytd_state_deduction_used_cents"), int)
    assert data["ytd_state_deduction_used_cents"] >= 0


# ---------------------------------------------------------------------------
# Beneficiary
# ---------------------------------------------------------------------------
def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    ssn = data.get("ssn_last_four")
    assert isinstance(ssn, str) and len(ssn) == 4 and ssn.isdigit()
    assert data.get("relationship_family_code") in {
        "SELF", "CHILD", "SIBLING", "NIECE_NEPHEW", "PARENT", "COUSIN",
        "SPOUSE", "IN_LAW", "FIRST_COUSIN_ONCE_REMOVED",
    }
    assert isinstance(data.get("k12_ytd_qualified_cents"), int)
    assert data["k12_ytd_qualified_cents"] >= 0


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
def assert_account(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("primary_donor_id", ""))
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    spc = data.get("state_plan_code")
    assert isinstance(spc, str) and len(spc) == 2 and spc.isupper()
    assert data.get("status") in {"OPEN", "RESTRICTED", "CLOSED"}
    for f in (
        "basis_balance_cents", "earnings_balance_cents",
        "total_balance_cents", "lifetime_contribution_cap_cents",
        "state_rule_version_at_open",
    ):
        assert isinstance(data.get(f), int), f"{f} must be int"
        assert data[f] >= 0, f"{f} must be >= 0"
    assert_account_balance_invariant(data)


def assert_account_balance_invariant(data: Dict[str, Any]) -> None:
    """PRD §2.9: balance_invariant —
    basis_balance_cents + earnings_balance_cents = total_balance_cents."""
    assert (
        data["basis_balance_cents"] + data["earnings_balance_cents"]
        == data["total_balance_cents"]
    ), (
        f"balance invariant violated: basis={data['basis_balance_cents']}, "
        f"earnings={data['earnings_balance_cents']}, "
        f"total={data['total_balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Contribution — append-only, ONLY id + created_at per PRD §2.4
# ---------------------------------------------------------------------------
def assert_contribution(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: Contribution does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("donor_id", ""))
    assert (
        isinstance(data.get("amount_cents"), int)
        and data["amount_cents"] > 0
    )
    assert data.get("contribution_kind") in {"LUMP_SUM", "RECURRING"}
    assert data.get("status") in {"PENDING", "SETTLED", "REVERSED"}
    if data["contribution_kind"] == "RECURRING":
        assert data.get("recurring_plan_id") is not None
        assert is_valid_uuid(data["recurring_plan_id"])
    else:
        # PRD §3.3: recurring_plan_id is null when LUMP_SUM.
        assert data.get("recurring_plan_id") in (None, "")
    if data["status"] == "SETTLED":
        assert data.get("settled_at") is not None
        assert is_iso8601_timestamp(data["settled_at"])
    else:
        assert data.get("settled_at") in (None, "")


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------
def assert_withdrawal(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert (
        isinstance(data.get("requested_amount_cents"), int)
        and data["requested_amount_cents"] > 0
    )
    assert data.get("expense_category") in {
        "POST_SECONDARY_TUITION", "ROOM_AND_BOARD", "BOOKS_SUPPLIES",
        "K_12", "NON_QUALIFIED",
    }
    assert data.get("status") in {
        "REQUESTED", "REJECTED", "DISBURSED", "CLASSIFIED", "REPORTED",
    }


# ---------------------------------------------------------------------------
# RecurringPlan
# ---------------------------------------------------------------------------
def assert_recurring_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("donor_id", ""))
    assert (
        isinstance(data.get("amount_cents"), int)
        and data["amount_cents"] > 0
    )
    assert data.get("cadence_days") in {7, 14, 30, 90, 365}
    assert isinstance(data.get("next_run_at"), str)
    assert is_iso8601_timestamp(data["next_run_at"])
    assert data.get("status") in {"ACTIVE", "PAUSED", "CANCELLED"}


# ---------------------------------------------------------------------------
# BeneficiaryChangeRequest
# ---------------------------------------------------------------------------
def assert_beneficiary_change_request(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("current_beneficiary_id", ""))
    assert is_valid_uuid(data.get("proposed_beneficiary_id", ""))
    assert data.get("status") in {"SUBMITTED", "APPROVED", "REJECTED"}


# ---------------------------------------------------------------------------
# EducationExpense — append-only, ONLY id + created_at per PRD §2.4
# ---------------------------------------------------------------------------
def assert_education_expense(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: EducationExpense does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("withdrawal_id", ""))
    assert (
        isinstance(data.get("institution_name"), str)
        and 0 < len(data["institution_name"]) <= 200
    )
    assert data.get("category") in {
        "POST_SECONDARY_TUITION", "ROOM_AND_BOARD", "BOOKS_SUPPLIES",
        "K_12", "NON_QUALIFIED",
    }
    assert (
        isinstance(data.get("amount_cents"), int)
        and data["amount_cents"] > 0
    )
    assert isinstance(data.get("incurred_on"), str)


# ---------------------------------------------------------------------------
# TaxReport — frozen-or-live, ONLY id + created_at per PRD §2.4
# ---------------------------------------------------------------------------
def assert_tax_report(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: TaxReport does NOT carry updated_at or version; its
    # mutability is governed by `locked` instead.
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data.get("tax_year"), int) and data["tax_year"] >= 2000
    for f in (
        "gross_distribution_cents", "earnings_cents", "basis_cents",
        "total_penalty_cents",
    ):
        assert isinstance(data.get(f), int), f"{f} must be int"
        assert data[f] >= 0, f"{f} must be >= 0"
    assert isinstance(data.get("locked"), bool)
    # PRD §3.7: basis_cents = gross_distribution_cents - earnings_cents.
    assert (
        data["basis_cents"]
        == data["gross_distribution_cents"] - data["earnings_cents"]
    ), (
        f"tax-report basis identity violated: "
        f"gross={data['gross_distribution_cents']}, "
        f"earnings={data['earnings_cents']}, basis={data['basis_cents']}"
    )


# ---------------------------------------------------------------------------
# StateRule
# ---------------------------------------------------------------------------
def assert_state_rule(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    sc = data.get("state_code")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isupper()
    assert (
        isinstance(data.get("deduction_cap_cents"), int)
        and data["deduction_cap_cents"] >= 0
    )
    assert data.get("parity") in {"IN_STATE_ONLY", "PARITY"}
    assert (
        isinstance(data.get("lifetime_aggregate_cap_cents"), int)
        and data["lifetime_aggregate_cap_cents"] > 0
    )
    assert isinstance(data.get("k12_qualified"), bool)


# ---------------------------------------------------------------------------
# Withdrawal post-disburse: basis/earnings split invariant — PRD §3.5
# ---------------------------------------------------------------------------
def assert_withdrawal_split_sums_to_requested(data: Dict[str, Any]) -> None:
    """PRD §3.5: `basis_portion_cents` as the residual ... so the two
    portions sum to `requested_amount_cents`."""
    assert data["basis_portion_cents"] is not None
    assert data["earnings_portion_cents"] is not None
    total = data["basis_portion_cents"] + data["earnings_portion_cents"]
    assert total == data["requested_amount_cents"], (
        f"basis_portion ({data['basis_portion_cents']}) + earnings_portion "
        f"({data['earnings_portion_cents']}) != requested "
        f"({data['requested_amount_cents']})"
    )


# ---------------------------------------------------------------------------
# Withdrawal post-classify: qualified + non-qualified = requested — PRD §3.5
# ---------------------------------------------------------------------------
def assert_withdrawal_classification_sums_to_requested(
    data: Dict[str, Any],
) -> None:
    """PRD §3.5: `non_qualified_amount_cents` is `requested_amount_cents`
    minus `qualified_amount_cents`."""
    assert data["qualified_amount_cents"] is not None
    assert data["non_qualified_amount_cents"] is not None
    total = (
        data["qualified_amount_cents"]
        + data["non_qualified_amount_cents"]
    )
    assert total == data["requested_amount_cents"], (
        f"qualified ({data['qualified_amount_cents']}) + non_qualified "
        f"({data['non_qualified_amount_cents']}) != requested "
        f"({data['requested_amount_cents']})"
    )


# ---------------------------------------------------------------------------
# Version bump invariant
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: version starts at 1 and increments by 1 on every
    successful mutation of the row."""
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


__all__ = [
    "assert_donor",
    "assert_beneficiary",
    "assert_account",
    "assert_account_balance_invariant",
    "assert_contribution",
    "assert_withdrawal",
    "assert_recurring_plan",
    "assert_beneficiary_change_request",
    "assert_education_expense",
    "assert_tax_report",
    "assert_state_rule",
    "assert_withdrawal_split_sums_to_requested",
    "assert_withdrawal_classification_sums_to_requested",
    "assert_version_incremented_by_one",
]
