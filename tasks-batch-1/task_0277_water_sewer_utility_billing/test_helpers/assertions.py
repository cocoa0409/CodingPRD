"""Entity assertions and domain invariant checkers.

Validates the PRD's structural promises: UUID ids, ISO-8601 timestamps,
status domains, append-only entities lacking updated_at/version, and the
derived-ledger non-negativity invariant.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AccountBillingStatus, AccountServiceStatus, MeterType, MeterStatus,
    BillingCycleStatus, BillStatus, BudgetBillingPlanStatus,
    AssistanceEnrollmentStatus, LeakAdjustmentStatus, ShutoffOrderStatus,
    MeterReadSource, PaymentMethod,
)


def _assert_common(data: dict):
    """Full-record entities carry id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_rate_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["fixed_water_charge_cents"] >= 0
    assert data["fixed_sewer_charge_cents"] >= 0
    assert isinstance(data["water_tiers"], list) and len(data["water_tiers"]) > 0
    assert data["sewer_rate_cents_per_kgal"] >= 0
    assert 0 <= data["sewer_ratio_pct"] <= 100


def assert_account(data: dict):
    _assert_common(data)
    assert data["billing_status"] in {s.value for s in AccountBillingStatus}
    assert data["service_status"] in {s.value for s in AccountServiceStatus}
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["past_due_cents"], int)
    assert isinstance(data["budget_billing_enrolled"], bool)
    assert isinstance(data["assistance_enrolled"], bool)
    assert_account_ledger_invariants(data)


def assert_account_ledger_invariants(data: dict):
    """Derived ledger figures are floored at zero (PRD §2.5)."""
    assert data["balance_due_cents"] >= 0, "balance_due_cents floored at 0"
    assert data["past_due_cents"] >= 0, "past_due_cents floored at 0"


def assert_meter(data: dict):
    _assert_common(data)
    assert data["meter_type"] in {t.value for t in MeterType}
    assert data["status"] in {s.value for s in MeterStatus}
    assert isinstance(data["serial"], str)
    assert isinstance(data["last_reading_gallons"], int)


def assert_meter_read(data: dict):
    _assert_append_only(data)
    assert isinstance(data["reading_gallons"], int)
    assert data["source"] in {s.value for s in MeterReadSource}
    assert isinstance(data["consumption_gallons"], int)
    assert data["consumption_gallons"] >= 0, "consumption clamped to non-negative"


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in BillingCycleStatus}


def assert_bill(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in BillStatus}
    for f in ("potable_consumption_gallons", "irrigation_consumption_gallons",
              "billable_sewer_gallons", "fixed_charge_cents",
              "water_volumetric_cents", "sewer_volumetric_cents",
              "leak_credit_cents", "amount_billed_cents", "total_cents",
              "budget_billing_amount_cents", "late_fee_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer cent value"
    assert data["amount_billed_cents"] >= 0, "amount_billed floored at 0 (PRD §3.4)"


def assert_budget_plan(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in BudgetBillingPlanStatus}
    assert isinstance(data["monthly_amount_cents"], int)
    assert isinstance(data["cycles_elapsed"], int)
    assert isinstance(data["trued_up_delta_cents"], int)


def assert_assistance_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in AssistanceEnrollmentStatus}
    assert isinstance(data["grants_shutoff_protection"], bool)


def assert_leak_adjustment(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in LeakAdjustmentStatus}
    assert isinstance(data["baseline_gallons"], int)
    assert isinstance(data["credit_cents"], int)


def assert_shutoff_order(data: dict):
    _assert_common(data)
    assert data["status"] in {s.value for s in ShutoffOrderStatus}
    assert isinstance(data["reconnect_fee_charged_cents"], int)


def assert_payment(data: dict):
    _assert_append_only(data)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in {m.value for m in PaymentMethod}


def assert_moratorium(data: dict):
    _assert_common(data)
    assert isinstance(data["active"], bool)
