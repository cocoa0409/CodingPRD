"""Entity assertions and domain invariant checkers for the Electric Utility
Billing API. Structural validators (UUID, ISO-8601) come from the framework.
Field names are PRD-exact. Lean resources (MeterRead, SystemClock) carry only
id + created_at and are asserted not to expose updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_TARIFF_STATES = {"DRAFT", "ACTIVE", "RETIRED"}
_SERVICE_STATES = {"ACTIVE", "DISCONNECT_PENDING", "DISCONNECTED", "RECONNECT_PENDING"}
_FINANCIAL_STATES = {"CURRENT", "DELINQUENT", "IN_ARREARS"}
_METER_TYPES = {"CONSUMPTION_ONLY", "BIDIRECTIONAL"}
_METER_STATES = {"ACTIVE", "REMOVED"}
_TOU_PERIODS = {"ON_PEAK", "MID_PEAK", "OFF_PEAK"}
_BILL_STATES = {"DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID"}
_PAYMENT_METHODS = {"ACH", "CARD", "CASH"}
_PAYMENT_STATES = {"POSTED", "REVERSED"}
_ORDER_TYPES = {"DISCONNECT", "RECONNECT"}
_ORDER_STATES = {"SCHEDULED", "COMPLETED", "CANCELLED"}
_ORDER_REASONS = {"NONPAY", "CUSTOMER_REQUEST", "RESTORE_AFTER_PAYMENT"}
_PLAN_STATES = {"ACTIVE", "TRUED_UP", "CANCELLED"}
_GRANT_PROGRAMS = {"LIHEAP", "EMERGENCY_CRISIS"}
_GRANT_STATES = {"PLEDGED", "APPLIED", "EXHAUSTED", "CANCELLED"}


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_tariff(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in _TARIFF_STATES, data["status"]
    assert isinstance(data["fixed_charge_cents"], int) and data["fixed_charge_cents"] >= 0
    assert isinstance(data["tier_breakpoints_kwh"], list)
    assert isinstance(data["tier_rates_cents_per_kwh"], list)
    assert len(data["tier_rates_cents_per_kwh"]) == len(data["tier_breakpoints_kwh"]) + 1
    assert set(data["tou_multipliers"].keys()) == _TOU_PERIODS
    assert isinstance(data["demand_charge_cents_per_kw"], int)
    assert isinstance(data["net_metering_credit_cents_per_kwh"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["tariff_id"], str)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert data["service_status"] in _SERVICE_STATES, data["service_status"]
    assert data["financial_status"] in _FINANCIAL_STATES, data["financial_status"]
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["net_metering_credit_balance_cents"], int)
    assert data["net_metering_credit_balance_cents"] >= 0
    oub = data.get("oldest_unpaid_bill_due_date")
    assert oub is None or is_iso8601_timestamp(oub)


def assert_meter(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["serial"], str) and len(data["serial"]) > 0
    assert data["meter_type"] in _METER_TYPES, data["meter_type"]
    assert data["status"] in _METER_STATES, data["status"]


def assert_meter_read(data: dict):
    """Lean resource (PRD §2.4): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "MeterRead must not expose updated_at"
    assert "version" not in data, "MeterRead must not expose version"
    assert isinstance(data["meter_id"], str)
    assert is_iso8601_timestamp(data["interval_start"])
    assert is_iso8601_timestamp(data["interval_end"])
    assert isinstance(data["import_kwh"], (int, float)) and data["import_kwh"] >= 0
    assert isinstance(data["export_kwh"], (int, float)) and data["export_kwh"] >= 0
    assert data["tou_period"] in _TOU_PERIODS, data["tou_period"]
    assert isinstance(data["avg_demand_kw"], (int, float))


def assert_bill(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["status"] in _BILL_STATES, data["status"]
    assert is_iso8601_timestamp(data["due_date"])
    for f in ("energy_charge_cents", "demand_charge_cents",
              "net_metering_credit_applied_cents", "assistance_applied_cents",
              "total_due_cents", "amount_paid_cents", "actual_cost_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert data["total_due_cents"] >= 0
    assert data["actual_cost_cents"] >= 0
    assert isinstance(data["is_budget_billed"], bool)


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in _PAYMENT_METHODS, data["method"]
    assert data["status"] in _PAYMENT_STATES, data["status"]
    assert isinstance(data["allocations"], list)


def assert_service_order(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["order_type"] in _ORDER_TYPES, data["order_type"]
    assert data["status"] in _ORDER_STATES, data["status"]
    assert data["reason"] in _ORDER_REASONS, data["reason"]


def assert_budget_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["status"] in _PLAN_STATES, data["status"]
    assert isinstance(data["levelized_amount_cents"], int) and data["levelized_amount_cents"] > 0
    for f in ("accumulated_actual_cents", "accumulated_levelized_cents",
              "true_up_balance_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_assistance_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert data["program"] in _GRANT_PROGRAMS, data["program"]
    assert data["status"] in _GRANT_STATES, data["status"]
    assert isinstance(data["pledged_cents"], int) and data["pledged_cents"] > 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_bill_charge_decomposition(data: dict, fixed_charge_cents: int):
    """Invariant from PRD §3.3: gross = fixed + energy + demand, and
    actual_cost = gross - net-metering credit - assistance, floored at 0."""
    gross = fixed_charge_cents + data["energy_charge_cents"] + data["demand_charge_cents"]
    expected_actual = max(
        0,
        gross
        - data["net_metering_credit_applied_cents"]
        - data["assistance_applied_cents"],
    )
    assert data["actual_cost_cents"] == expected_actual, (
        f"actual_cost_cents {data['actual_cost_cents']} != "
        f"gross({gross}) - credit({data['net_metering_credit_applied_cents']}) "
        f"- assist({data['assistance_applied_cents']})"
    )


def assert_credit_floor_respected(data: dict, fixed_charge_cents: int):
    """PRD §3.3 step six: net-metering credit may never push a bill below its
    fixed-charge-plus-demand-charge floor — only the energy portion is offset."""
    floor = fixed_charge_cents + data["demand_charge_cents"]
    gross = floor + data["energy_charge_cents"]
    max_creditable = max(0, gross - floor)
    assert data["net_metering_credit_applied_cents"] <= max_creditable, (
        f"applied credit {data['net_metering_credit_applied_cents']} exceeds "
        f"max creditable {max_creditable}"
    )
