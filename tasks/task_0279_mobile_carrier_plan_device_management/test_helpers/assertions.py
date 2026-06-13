"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract
(§2.5 common fields; §3 per-entity fields). Charge and UsageRecord are
append-only events and therefore carry no updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_event(data: dict):
    """Append-only event: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert isinstance(data["holder_email"], str) and len(data["holder_email"]) > 0
    assert isinstance(data["billing_day_of_month"], int)
    assert 1 <= data["billing_day_of_month"] <= 28
    assert data["status"] in ("ACTIVE", "DELINQUENT")
    assert isinstance(data["active_line_count"], int) and data["active_line_count"] >= 0
    assert isinstance(data["group_discount_pct"], (int, float))
    assert isinstance(data["total_eip_outstanding_cents"], int)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_data_mb"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["retail_price_cents"], int)
    assert isinstance(data["stock_count"], int)
    assert data["status"] == "AVAILABLE"


def assert_line(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["plan_id"], str)
    assert data["status"] in ("PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "CANCELLED")
    assert data["sim_type"] in ("PHYSICAL", "ESIM")
    assert data.get("phone_number") is None or isinstance(data["phone_number"], str)


def assert_sim_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["line_id"], str)
    assert data["sim_type"] in ("PHYSICAL", "ESIM")
    assert data["status"] in ("ISSUED", "ACTIVATED", "DEACTIVATED")


def assert_installment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["line_id"], str)
    assert isinstance(data["device_id"], str)
    assert data["term_months"] in (12, 24, 36)
    assert isinstance(data["financed_cents"], int)
    assert isinstance(data["monthly_installment_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert isinstance(data["installments_paid"], int)
    assert data["status"] in ("ACTIVE", "PAID_OFF", "CANCELLED")


def assert_addon(data: dict):
    _assert_common(data)
    assert isinstance(data["line_id"], str)
    assert data["addon_type"] in ("ROAMING_DAYPASS", "INTL_MONTHLY")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED", "CANCELLED")


def assert_port_request(data: dict):
    _assert_common(data)
    assert isinstance(data["line_id"], str)
    assert data["direction"] in ("PORT_IN", "PORT_OUT")
    assert data["status"] in ("REQUESTED", "VALIDATED", "COMPLETED", "REJECTED", "REVERTED")


def assert_upgrade_order(data: dict):
    _assert_common(data)
    assert isinstance(data["line_id"], str)
    assert isinstance(data["payoff_charge_cents"], int)
    assert data["status"] == "COMPLETED"


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["days_in_cycle"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_charge(data: dict):
    _assert_event(data)
    assert data["charge_type"] in (
        "PLAN_BASE", "OVERAGE", "EIP_INSTALLMENT", "ADDON", "EIP_PAYOFF", "CREDIT")
    assert isinstance(data["amount_cents"], int)
    # Append-only event: no updated_at / version (PRD §2.5).
    assert "updated_at" not in data, "Charge is append-only and has no updated_at"
    assert "version" not in data, "Charge is append-only and has no version"


def assert_usage_record(data: dict):
    _assert_event(data)
    assert data["usage_type"] in ("DATA", "VOICE", "TEXT")
    assert "updated_at" not in data, "UsageRecord is append-only and has no updated_at"
    assert "version" not in data, "UsageRecord is append-only and has no version"


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_account_eip_invariant(account: dict, active_eip_remaining_sum: int):
    """PRD §3.6: total_eip_outstanding_cents is at all times the sum of
    remaining_balance_cents across ACTIVE installment plans on the account."""
    assert account["total_eip_outstanding_cents"] == active_eip_remaining_sum, (
        f"total_eip_outstanding_cents {account['total_eip_outstanding_cents']} "
        f"!= sum of ACTIVE EIP remaining {active_eip_remaining_sum}"
    )
