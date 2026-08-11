"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_customer(data: dict):
    """Validate a Customer response against the PRD contract (§2.5, §2.10, §3.2)."""
    _assert_common_fields(data)
    assert data["account_type"] in ("OFFICE", "HOME")
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert isinstance(data["service_address"], str)
    assert is_valid_uuid(data.get("delivery_zone_id", ""))
    assert data["service_mode"] in ("AUTO", "WILL_CALL")
    assert isinstance(data["par_level_bottles"], int) and data["par_level_bottles"] >= 0
    assert data["pricing_tier"] in ("STANDARD", "SILVER", "GOLD")
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["bottles_on_site"], int)
    assert isinstance(data["deposit_liability_cents"], int)
    assert "overdue_since" in data


def assert_delivery_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["active"], bool)


def assert_route(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", ""))
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert isinstance(data["driver_name"], str) and data["driver_name"]
    assert isinstance(data["truck_capacity_bottles"], int) and data["truck_capacity_bottles"] > 0
    assert isinstance(data["committed_bottles"], int) and data["committed_bottles"] >= 0
    assert data["route_status"] in ("DRAFT", "PUBLISHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["planned_bottles"], int) and data["planned_bottles"] >= 0
    assert isinstance(data["planned_empties_pickup"], int) and data["planned_empties_pickup"] >= 0
    assert data["stop_status"] in (
        "PLANNED", "EN_ROUTE", "ARRIVED", "DELIVERED",
        "SKIPPED", "PARTIAL", "FAILED", "CANCELLED",
    )
    assert isinstance(data["actual_bottles_delivered"], int) and data["actual_bottles_delivered"] >= 0
    assert isinstance(data["actual_empties_collected"], int) and data["actual_empties_collected"] >= 0
    assert isinstance(data["shortage_count"], int) and data["shortage_count"] >= 0


def assert_ledger_entry(data: dict):
    """Bottle custody ledger entries are immutable: id + created_at only,
    with no updated_at and no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert "version" not in data, "ledger entries must not carry version"
    assert is_valid_uuid(data.get("customer_ref", ""))
    assert data["entry_kind"] in (
        "DELIVER_FULL", "PICKUP_EMPTY", "MARK_SHORTAGE",
        "ADJUSTMENT", "RETURN_FULL", "EXCHANGE",
    )
    assert isinstance(data["quantity"], int)
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_cooler_rental(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["cooler_model"] in ("COUNTERTOP", "FREESTANDING", "BOTTOM_LOAD", "FILTRATION_POE")
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["rental_status"] in (
        "PENDING_INSTALL", "INSTALLED", "SUSPENDED",
        "RETURN_REQUESTED", "RETURNED", "CLOSED",
    )
    assert isinstance(data["accrued_rent_cents"], int) and data["accrued_rent_cents"] >= 0


def assert_addon(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["addon_kind"] in ("COFFEE", "FILTRATION", "CUPS", "SANITIZATION")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert data["cadence"] in ("RECURRING", "ONE_TIME")
    assert data["addon_status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["billing_period_start"], str) and data["billing_period_start"]
    assert isinstance(data["billing_period_end"], str) and data["billing_period_end"]
    for field in (
        "subtotal_water_cents", "subtotal_addon_cents", "subtotal_rent_cents",
        "shortage_charge_cents", "deposit_credit_cents",
        "total_due_cents", "balance_due_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["invoice_status"] in (
        "DRAFT", "OPEN", "PARTIALLY_PAID", "PAID", "OVERDUE", "DISPUTED", "VOID",
    )
    assert isinstance(data["due_date"], str) and data["due_date"]


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "ACH", "CHECK", "CREDIT_MEMO")
    assert data["payment_status"] in ("PENDING", "APPLIED", "FAILED", "REFUNDED")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["order_kind"] in (
        "DELIVERY", "COOLER_INSTALL", "COOLER_RETURN", "PICKUP_ONLY", "EXCHANGE_ONLY",
    )
    assert isinstance(data["requested_date"], str) and data["requested_date"]
    assert isinstance(data["quantity_bottles"], int) and data["quantity_bottles"] >= 0
    assert data["order_status"] in (
        "PENDING", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "REJECTED",
    )
    assert "linked_stop_id" in data
    assert "linked_rental_id" in data


def assert_pricing_config(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    for field in (
        "bottle_deposit_cents", "bottle_shortage_fee_cents",
        "standard_per_bottle_cents", "silver_per_bottle_cents", "gold_per_bottle_cents",
    ):
        assert isinstance(data[field], int) and data[field] > 0
    assert isinstance(data["silver_volume_threshold"], int) and data["silver_volume_threshold"] > 0
    assert isinstance(data["gold_volume_threshold"], int)
    assert data["gold_volume_threshold"] > data["silver_volume_threshold"]
    assert isinstance(data["late_fee_flat_cents"], int) and data["late_fee_flat_cents"] >= 0


def assert_skip_credit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("stop_id", ""))
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert data["credit_status"] in ("PENDING", "APPLIED", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def assert_customer_balance_invariants(customer: dict):
    """Domain invariants on a customer record (PRD §2.10, §3.8)."""
    assert customer["outstanding_balance_cents"] >= 0
    assert customer["bottles_on_site"] >= 0
    assert customer["deposit_liability_cents"] >= 0
