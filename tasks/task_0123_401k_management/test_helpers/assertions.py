"""Entity assertions and domain invariant checkers.

Validates the structural shape of each entity response against the
field set PRD §2.4 and §3 specify, including the common-fields
distinction: Plan / Participant / Loan / HardshipWithdrawal /
RMDSchedule carry id + created_at + updated_at + version; ledger-style
entities (ContributionRecord / VestingSnapshot / LoanRepayment /
PlanClock) carry ONLY id + created_at and MUST NOT expose
updated_at or version.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 — id + created_at + updated_at + version."""
    assert is_valid_uuid(str(data.get("id", ""))), (
        f"{label}.id must be a UUID (got {data.get('id')!r})"
    )
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{label}.created_at must be ISO 8601 "
        f"(got {data.get('created_at')!r})"
    )
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), (
        f"{label}.updated_at must be ISO 8601 "
        f"(got {data.get('updated_at')!r})"
    )
    assert isinstance(data.get("version"), int), (
        f"{label}.version must be int (got {type(data.get('version'))})"
    )


def _assert_ledger_fields(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 — ledger entities expose ONLY id + created_at; they
    MUST NOT expose updated_at or version.
    """
    assert is_valid_uuid(str(data.get("id", ""))), (
        f"{label}.id must be a UUID"
    )
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), (
        f"{label}.created_at must be ISO 8601"
    )
    # PRD §2.4: "Implementations must not emit updated_at or version on
    # these entities".
    assert "updated_at" not in data, (
        f"{label} is a ledger entity — must not expose updated_at"
    )
    assert "version" not in data, (
        f"{label} is a ledger entity — must not expose version"
    )


# ---------------------------------------------------------------------------
# Plan — PRD §2.4 / §3.1
# ---------------------------------------------------------------------------
def assert_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Plan")
    assert isinstance(data.get("plan_name"), str) and data["plan_name"]
    assert isinstance(data.get("plan_year"), int)
    assert data.get("match_formula_type") in (
        "SAFE_HARBOR_BASIC", "TIERED",
    )
    assert data.get("vesting_schedule_type") in ("CLIFF", "GRADED")
    assert isinstance(data.get("rmd_age"), int)
    assert isinstance(data.get("current_vesting_epoch"), int)
    assert data.get("status") in ("DRAFT", "ACTIVE", "FROZEN")


# ---------------------------------------------------------------------------
# Participant — PRD §2.4 / §3.2
# ---------------------------------------------------------------------------
def assert_participant(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Participant")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("employee_external_id"), str)
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("hire_date"), str)
    assert isinstance(data.get("annual_compensation_cents"), int)
    assert isinstance(data.get("elected_deferral_pct"), (int, float))
    assert 0 <= data["elected_deferral_pct"] <= 100
    assert isinstance(data.get("cumulative_employee_contribution_cents"), int)
    assert isinstance(data.get("cumulative_employer_match_cents"), int)
    assert isinstance(data.get("total_account_balance_cents"), int)
    assert data.get("status") in (
        "ENROLLED", "ACTIVE", "SUSPENDED", "TERMINATED",
    )


# ---------------------------------------------------------------------------
# ContributionRecord — PRD §2.4 / §3.3 (LEDGER)
# ---------------------------------------------------------------------------
def assert_contribution_record(data: Dict[str, Any]) -> None:
    _assert_ledger_fields(data, "ContributionRecord")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("pay_period_end"), str)
    assert isinstance(data.get("gross_pay_cents"), int)
    assert isinstance(data.get("employee_amount_cents"), int)
    assert isinstance(data.get("employer_match_cents"), int)
    assert data.get("status") == "POSTED"


# ---------------------------------------------------------------------------
# VestingSnapshot — PRD §2.4 / §3.4 (LEDGER / append-only audit)
# ---------------------------------------------------------------------------
def assert_vesting_snapshot(data: Dict[str, Any]) -> None:
    _assert_ledger_fields(data, "VestingSnapshot")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("vesting_epoch"), int)
    assert isinstance(data.get("service_years_completed"), int)
    assert data["service_years_completed"] >= 0
    assert isinstance(data.get("vested_pct"), (int, float))
    assert 0 <= data["vested_pct"] <= 100
    assert isinstance(data.get("vested_balance_cents"), int)
    assert data["vested_balance_cents"] >= 0


# ---------------------------------------------------------------------------
# Loan — PRD §2.4 / §3.5
# ---------------------------------------------------------------------------
def assert_loan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Loan")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("requested_amount_cents"), int)
    assert isinstance(data.get("term_months"), int)
    assert 1 <= data["term_months"] <= 60
    assert isinstance(data.get("outstanding_principal_cents"), int)
    assert isinstance(data.get("payments_made"), int)
    assert data.get("status") in (
        "REQUESTED", "ACTIVE", "SATISFIED", "DEFAULTED", "REJECTED",
    )


# ---------------------------------------------------------------------------
# LoanRepayment — PRD §2.4 / §3.5 (LEDGER)
# ---------------------------------------------------------------------------
def assert_loan_repayment(data: Dict[str, Any]) -> None:
    _assert_ledger_fields(data, "LoanRepayment")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("loan_id"), str)
    assert isinstance(data.get("payment_amount_cents"), int)
    assert isinstance(data.get("principal_cents"), int)
    # PRD §3.5: "principal_cents equals payment_amount_cents".
    assert data["principal_cents"] == data["payment_amount_cents"]
    assert isinstance(data.get("posted_on"), str)
    assert data.get("status") == "POSTED"


# ---------------------------------------------------------------------------
# HardshipWithdrawal — PRD §2.4 / §3.6
# ---------------------------------------------------------------------------
def assert_hardship_withdrawal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "HardshipWithdrawal")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("requested_amount_cents"), int)
    assert data.get("hardship_reason_code") in (
        "MEDICAL", "EDUCATION", "PRIMARY_RESIDENCE",
        "FUNERAL", "EVICTION",
    )
    assert data.get("status") in ("REQUESTED", "APPROVED", "DENIED")


# ---------------------------------------------------------------------------
# RMDSchedule — PRD §2.4 / §3.7
# ---------------------------------------------------------------------------
def assert_rmd_schedule(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RMDSchedule")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("participant_id"), str)
    assert isinstance(data.get("rmd_year"), int)
    assert isinstance(data.get("required_amount_cents"), int)
    assert isinstance(data.get("due_date"), str)
    assert isinstance(data.get("distributed_amount_cents"), int)
    assert data["distributed_amount_cents"] >= 0
    assert data.get("status") in ("SCHEDULED", "FULFILLED", "MISSED")


# ---------------------------------------------------------------------------
# PlanClock — PRD §2.4 / §2.7 (LEDGER singleton)
# ---------------------------------------------------------------------------
def assert_plan_clock(data: Dict[str, Any]) -> None:
    _assert_ledger_fields(data, "PlanClock")
    assert isinstance(data.get("plan_id"), str)
    assert isinstance(data.get("current_date"), str)


# ---------------------------------------------------------------------------
# Domain invariants — PRD §3.3, §3.5
# ---------------------------------------------------------------------------
def assert_participant_balance_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.3: balance reflects cumulative employee + employer minus
    debits. The non-negative property is the safe cross-implementation
    invariant.
    """
    assert data["cumulative_employee_contribution_cents"] >= 0
    assert data["cumulative_employer_match_cents"] >= 0
    assert data["total_account_balance_cents"] >= 0


def assert_version_incremented_by_one(new: int, old: int) -> None:
    """PRD §2.4: 'incremented by exactly one on every mutation'."""
    assert new == old + 1, (
        f"version must increment by exactly one: {old} -> {new}"
    )


__all__ = [
    "assert_plan",
    "assert_participant",
    "assert_contribution_record",
    "assert_vesting_snapshot",
    "assert_loan",
    "assert_loan_repayment",
    "assert_hardship_withdrawal",
    "assert_rmd_schedule",
    "assert_plan_clock",
    "assert_participant_balance_invariant",
    "assert_version_incremented_by_one",
]
