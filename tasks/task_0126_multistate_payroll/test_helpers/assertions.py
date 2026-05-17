"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4 common-fields split:
- Top-level mutable resources (Employee, W4Profile, PayPeriod,
  PayrollItem, Paycheck, GarnishmentOrder, RemittancePeriod) carry
  id + created_at + updated_at + version.
- Append-only / immutable records (YTDLedgerEntry, TaxBracketTable)
  carry ONLY id + created_at.
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
    """Every resource carries id + created_at — PRD §2.4."""
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601 with three fractional digits, "
        f"got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: top-level mutable resources carry updated_at +
    version. Version starts at 1 on creation and increments by exactly
    1 per mutation.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601 with three fractional digits, "
        f"got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


# ===========================================================================
# Top-level resources — PRD §3
# ===========================================================================
def assert_employee(data: Dict[str, Any]) -> None:
    """PRD §3.1 Employee shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("hire_date"), str)
    assert data.get("work_state") in {"CA", "NY", "TX", "IL", "PA"}, (
        f"unexpected work_state: {data.get('work_state')!r}"
    )
    assert data.get("work_locality") in {"NYC", "PHL", "NONE"}, (
        f"unexpected work_locality: {data.get('work_locality')!r}"
    )
    assert isinstance(data.get("hourly_rate_cents"), int)
    assert data["hourly_rate_cents"] >= 0, (
        "hourly_rate_cents must be non-negative"
    )
    assert isinstance(data.get("ytd_gross_wages_cents"), int)
    assert isinstance(data.get("ytd_social_security_wages_cents"), int)
    assert isinstance(data.get("ytd_medicare_wages_cents"), int)
    assert data.get("status") in {"ACTIVE", "TERMINATED"}, (
        f"unexpected employee status: {data.get('status')!r}"
    )


def assert_w4_profile(data: Dict[str, Any]) -> None:
    """PRD §3.1 W4Profile shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("filing_status") in {
        "SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD",
    }, f"unexpected filing_status: {data.get('filing_status')!r}"
    assert isinstance(data.get("dependents_amount_cents"), int)
    assert isinstance(data.get("other_income_cents"), int)
    assert isinstance(data.get("additional_withholding_cents"), int)
    assert isinstance(data.get("state_allowances"), int)
    assert isinstance(data.get("prefilled_from_prior_year"), bool)
    assert isinstance(data.get("effective_pay_period_id"), str)


def assert_pay_period(data: Dict[str, Any]) -> None:
    """PRD §3.2 PayPeriod shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("pay_date"), str)
    assert data.get("status") in {"OPEN", "LOCKED", "CLOSED"}, (
        f"unexpected pay_period status: {data.get('status')!r}"
    )
    assert isinstance(data.get("paycheck_count"), int)
    assert data["paycheck_count"] >= 0


def assert_payroll_item(data: Dict[str, Any]) -> None:
    """PRD §3.3 PayrollItem shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("pay_period_id"), str)
    assert isinstance(data.get("employee_id"), str)
    # PRD §3.3: 'three hour fields must each be non-negative'.
    for k in ("regular_hours", "overtime_hours", "double_hours"):
        v = data.get(k)
        assert isinstance(v, (int, float)), (
            f"{k} must be a number, got {type(v)}"
        )
        assert v >= 0, f"{k} must be non-negative, got {v}"
    assert isinstance(data.get("retro_adjustment_cents"), int)
    assert isinstance(data.get("locked"), bool)


def assert_paycheck(data: Dict[str, Any]) -> None:
    """PRD §3.4, §3.6 Paycheck shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("pay_period_id"), str)
    assert isinstance(data.get("payroll_item_id"), str)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("status") in {
        "DRAFT", "CALCULATED", "APPROVED", "PAID", "VOIDED",
    }, f"unexpected paycheck status: {data.get('status')!r}"
    # is_retro_correction is a boolean flag — PRD §3.7.
    assert isinstance(data.get("is_retro_correction"), bool)


def assert_paycheck_computed_fields(data: Dict[str, Any]) -> None:
    """PRD §3.4, §3.5: post-calculation a Paycheck carries the full
    set of cents-denominated withholding fields. Each MUST be an
    integer when the paycheck is in CALCULATED / APPROVED / PAID /
    VOIDED."""
    for k in (
        "gross_wages_cents",
        "federal_withholding_cents",
        "state_withholding_cents",
        "local_withholding_cents",
        "social_security_cents",
        "medicare_base_cents",
        "medicare_additional_cents",
        "garnishment_total_cents",
        "net_pay_cents",
    ):
        v = data.get(k)
        assert isinstance(v, int), (
            f"{k} must be an integer cents value after calculation, "
            f"got {type(v).__name__}: {v!r}"
        )


def assert_garnishment_order(data: Dict[str, Any]) -> None:
    """PRD §3.5 GarnishmentOrder shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("order_type") in {
        "CHILD_SUPPORT", "FEDERAL_TAX_LEVY", "STUDENT_LOAN", "CREDITOR",
    }, f"unexpected order_type: {data.get('order_type')!r}"
    assert isinstance(data.get("priority_rank"), int)
    assert isinstance(data.get("total_owed_cents"), int)
    assert data["total_owed_cents"] >= 0
    assert isinstance(data.get("amount_collected_cents"), int)
    assert data["amount_collected_cents"] >= 0
    assert isinstance(data.get("cap_pct_of_disposable"), int)
    assert 1 <= data["cap_pct_of_disposable"] <= 100, (
        f"cap_pct_of_disposable must be in [1, 100], got "
        f"{data['cap_pct_of_disposable']}"
    )
    assert isinstance(data.get("effective_pay_date"), str)
    assert data.get("status") in {"ACTIVE", "SATISFIED", "RELEASED"}, (
        f"unexpected garnishment status: {data.get('status')!r}"
    )


def assert_remittance_period(data: Dict[str, Any]) -> None:
    """PRD §3.10 RemittancePeriod shape."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("tax_month"), int)
    assert 1 <= data["tax_month"] <= 12, (
        f"tax_month must be 1..12, got {data['tax_month']}"
    )
    for k in (
        "total_federal_withholding_cents",
        "total_state_withholding_cents",
        "total_local_withholding_cents",
        "total_social_security_cents",
        "total_medicare_cents",
        "total_medicare_additional_cents",
    ):
        v = data.get(k)
        assert isinstance(v, int), (
            f"{k} must be integer cents, got {type(v).__name__}: {v!r}"
        )
        assert v >= 0
    sb = data.get("state_breakdown")
    assert isinstance(sb, list), (
        f"state_breakdown must be an array, got {type(sb).__name__}"
    )
    for entry in sb:
        assert isinstance(entry, dict)
        assert isinstance(entry.get("state"), str)
        assert isinstance(entry.get("amount_cents"), int)
        assert entry["amount_cents"] >= 0
    assert data.get("status") in {
        "DRAFT", "FINALIZED", "REMITTED", "AMENDED",
    }, f"unexpected remittance status: {data.get('status')!r}"


# ===========================================================================
# Append-only / immutable records — PRD §2.4
# ===========================================================================
def assert_ytd_ledger_entry(data: Dict[str, Any]) -> None:
    """PRD §2.11 YTDLedgerEntry shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert isinstance(data.get("employee_id"), str)
    assert isinstance(data.get("paycheck_id"), str)
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("gross_wages_delta_cents"), int)
    assert isinstance(data.get("social_security_wages_delta_cents"), int)
    assert isinstance(data.get("medicare_wages_delta_cents"), int)
    assert data.get("entry_kind") in {"ACCRUAL", "REVERSAL"}, (
        f"unexpected entry_kind: {data.get('entry_kind')!r}"
    )


def assert_tax_bracket_table(data: Dict[str, Any]) -> None:
    """PRD §3.9 TaxBracketTable shape — lean (id + created_at)."""
    _assert_id_and_created_at(data)
    assert data.get("jurisdiction") in {
        "FEDERAL", "CA", "NY", "TX", "IL", "PA", "NYC", "PHL",
    }, f"unexpected jurisdiction: {data.get('jurisdiction')!r}"
    assert data.get("filing_status") in {
        "SINGLE", "MARRIED_JOINT", "HEAD_OF_HOUSEHOLD", "ANY",
    }, f"unexpected filing_status: {data.get('filing_status')!r}"
    assert isinstance(data.get("tax_year"), int)
    assert isinstance(data.get("brackets"), list)


# ===========================================================================
# Domain invariants — PRD §3.4, §3.5, §3.10
# ===========================================================================
def assert_paycheck_net_pay_invariant(data: Dict[str, Any]) -> None:
    """PRD §3.4: 'The paycheck's net_pay_cents is gross_wages_cents
    minus federal, state, and local withholdings, minus Social
    Security, base Medicare, and Additional Medicare, minus
    garnishment_total_cents.'"""
    expected = (
        data["gross_wages_cents"]
        - data["federal_withholding_cents"]
        - data["state_withholding_cents"]
        - data["local_withholding_cents"]
        - data["social_security_cents"]
        - data["medicare_base_cents"]
        - data["medicare_additional_cents"]
        - data["garnishment_total_cents"]
    )
    assert data["net_pay_cents"] == expected, (
        f"net_pay_cents invariant violated: stored "
        f"{data['net_pay_cents']} != computed {expected}"
    )


def assert_remittance_state_breakdown_sums_to_total(
    data: Dict[str, Any],
) -> None:
    """PRD §3.10: 'The grand total_state_withholding_cents equals the
    sum of these breakdown amounts.'"""
    summed = sum(int(e["amount_cents"]) for e in data["state_breakdown"])
    assert summed == data["total_state_withholding_cents"], (
        f"state_breakdown sum ({summed}) != "
        f"total_state_withholding_cents "
        f"({data['total_state_withholding_cents']})"
    )


def assert_version_incremented_by_one(prev: Dict[str, Any],
                                      curr: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that begins at 1 on creation
    and increments by exactly 1 on every mutation.'"""
    assert "version" in prev and "version" in curr, (
        "both records must carry version"
    )
    assert curr["version"] == prev["version"] + 1, (
        f"version expected to increment by exactly 1: "
        f"prev={prev['version']} curr={curr['version']}"
    )


__all__ = [
    "assert_employee",
    "assert_w4_profile",
    "assert_pay_period",
    "assert_payroll_item",
    "assert_paycheck",
    "assert_paycheck_computed_fields",
    "assert_garnishment_order",
    "assert_remittance_period",
    "assert_ytd_ledger_entry",
    "assert_tax_bracket_table",
    "assert_paycheck_net_pay_invariant",
    "assert_remittance_state_breakdown_sums_to_total",
    "assert_version_incremented_by_one",
]
