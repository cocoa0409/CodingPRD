"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_contractor_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["default_waste_pct_bp"], int)
    assert 0 <= data["default_waste_pct_bp"] <= 2000
    assert isinstance(data["ar_outstanding_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["board_kind"] in ["REGULAR", "FIRE_RATED", "MOISTURE_RATED"]
    assert data["length_ft"] in [8, 10, 12, 14, 16]
    assert data["width_ft"] == 4
    assert data["thickness_in"] in ["1/2", "5/8", "3/4"]
    assert isinstance(data["sheets_per_bundle"], int) and data["sheets_per_bundle"] > 0
    assert isinstance(data["unit_price_cents_per_sheet"], int)
    assert data["unit_price_cents_per_sheet"] > 0
    assert isinstance(data["lead_time_days"], int) and data["lead_time_days"] >= 0
    assert isinstance(data["active"], bool)


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["jobsite_name"], str) and len(data["jobsite_name"]) > 0
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] > 0
    assert isinstance(data["framing_pct_complete"], int)
    assert 0 <= data["framing_pct_complete"] <= 100
    assert data["status"] in ["PLANNING", "STOCKING_OPEN", "STOCKING_CLOSED", "CANCELLED"]


def assert_takeoff(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    if data.get("waste_pct_bp_override") is not None:
        assert isinstance(data["waste_pct_bp_override"], int)
        assert 0 <= data["waste_pct_bp_override"] <= 2000
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED", "CANCELLED"]
    for money_field in ("quoted_subtotal_cents", "final_subtotal_cents"):
        if money_field in data and data[money_field] is not None:
            assert isinstance(data[money_field], int)
    for count_field in ("base_sheet_count", "billable_sheet_count"):
        if count_field in data and data[count_field] is not None:
            assert isinstance(data[count_field], int) and data[count_field] >= 0


def assert_takeoff_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["takeoff_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["sheet_count"], int) and data["sheet_count"] > 0
    assert data["line_status"] in ["ACTIVE", "CANCELLED"]
    for computed in ("waste_sheets", "bundle_count", "quoted_line_cents", "final_line_cents"):
        if computed in data and data[computed] is not None:
            assert isinstance(data[computed], int) and data[computed] >= 0


def assert_stocking_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["takeoff_id"], str)
    assert isinstance(data["boom_truck_id"], str)
    assert isinstance(data["scheduled_date"], str) and len(data["scheduled_date"]) == 10
    assert data["shift_window"] in ["AM", "PM"]
    assert data["status"] in ["DRAFT", "SCHEDULED", "DISPATCHED", "STOCKED", "CANCELLED"]
    if data.get("freight_charge_cents") is not None:
        assert isinstance(data["freight_charge_cents"], int) and data["freight_charge_cents"] >= 0


def assert_stocking_drop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stocking_order_id"], str)
    assert isinstance(data["floor_label"], str) and len(data["floor_label"]) > 0
    assert isinstance(data["room_label"], str) and len(data["room_label"]) > 0
    assert isinstance(data["product_id"], str)
    assert isinstance(data["bundle_count"], int) and data["bundle_count"] > 0


def assert_boom_truck(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["truck_code"], str) and len(data["truck_code"]) > 0
    assert isinstance(data["max_bundle_capacity"], int) and data["max_bundle_capacity"] > 0
    assert isinstance(data["max_weight_lbs"], int) and data["max_weight_lbs"] > 0
    assert isinstance(data["active"], bool)


def assert_draw_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["stocking_order_id"], str)
    assert isinstance(data["requested_cents"], int) and data["requested_cents"] > 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert data["status"] in ["ISSUED", "PARTIALLY_PAID", "PAID", "VOIDED"]


def assert_payment(data: dict):
    """Payments are append-only ledger entries (PRD §2.4): id + created_at only,
    no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Payment must not expose updated_at"
    assert "version" not in data, "Payment must not expose version"
    assert isinstance(data["draw_request_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ["ACH", "CHECK", "CARD"]
    assert isinstance(data["received_at"], str)


def assert_bundle_return(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stocking_order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["bundles_returned"], int) and data["bundles_returned"] >= 0
    assert isinstance(data["loose_sheets_returned"], int) and data["loose_sheets_returned"] >= 0
    assert data["status"] in ["PENDING_INSPECTION", "ACCEPTED", "REJECTED"]
    for money_field in ("restock_fee_cents", "credit_cents"):
        if money_field in data and data[money_field] is not None:
            assert isinstance(data[money_field], int) and data[money_field] >= 0


def assert_draw_balance_invariants(draw: dict):
    """Draw monetary invariant (PRD §3.8): paid never exceeds requested."""
    assert 0 <= draw["paid_cents"] <= draw["requested_cents"]
    if draw["status"] == "PAID":
        assert draw["paid_cents"] == draw["requested_cents"]


def assert_account_ar_non_negative(account: dict):
    """AR ledger invariant (PRD §3.1, §3.9): the ledger never goes below zero."""
    assert account["ar_outstanding_cents"] >= 0
