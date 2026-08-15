"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.5: timestamps carry three fractional digits.
_3FRAC_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_common_fields(data: dict):
    """Common system-managed fields of PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_three_fractional_digits(timestamp: str):
    assert _3FRAC_TS_RE.match(timestamp or ""), (
        f"Expected ISO 8601 UTC timestamp with three fractional digits, got {timestamp!r}"
    )


def assert_clinic(data: dict):
    assert_common_fields(data)
    assert isinstance(data["clinic_name"], str) and data["clinic_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["ship_to_address"], str)
    assert data.get("dea_registration_number") is None or isinstance(
        data["dea_registration_number"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED")
    for field in ("credit_limit_cents", "credit_used_cents",
                  "minimum_order_value_cents", "delivery_frequency_per_week",
                  "free_freight_threshold_cents"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["manufacturer_code"], str) and data["manufacturer_code"]
    assert data["product_type"] in ("RX_PHARMACEUTICAL", "VACCINE", "EQUIPMENT",
                                    "CONSUMABLE")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["is_controlled_substance"], bool)
    # PRD §2.10: computed — true exactly when product_type is VACCINE.
    assert data["requires_cold_chain"] is (data["product_type"] == "VACCINE")
    assert data["status"] in ("LISTED", "DISCONTINUED")


def assert_authorization(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert isinstance(data["manufacturer_code"], str) and data["manufacturer_code"]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert isinstance(data["approved_ship_to_address"], str)
    assert isinstance(data["quarterly_quantity_cap"], int)
    assert isinstance(data["quantity_approved_this_quarter"], int)
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED", "REVOKED", "EXPIRED")


def assert_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["expiry_date"], str)
    for field in ("qty_on_hand", "qty_allocated", "qty_available"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert data["status"] in ("AVAILABLE", "DEPLETED", "EXPIRED")


def assert_lot_conservation(data: dict):
    """PRD §3.2 conservation invariant: on_hand == allocated + available."""
    assert data["qty_on_hand"] == data["qty_allocated"] + data["qty_available"], (
        f"Conservation violated: {data['qty_on_hand']} != "
        f"{data['qty_allocated']} + {data['qty_available']}"
    )


def assert_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert isinstance(data["ship_to_address"], str)
    assert isinstance(data["delivery_window_start"], str)
    assert isinstance(data["delivery_window_end"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "BACKORDERED",
                              "SHIPPED", "DELIVERED", "REJECTED", "CANCELLED")
    # Totals are computed at submission (PRD §3.4); before that they may be
    # null, zero, or absent.
    for field in ("merchandise_subtotal_cents", "bundle_discount_cents",
                  "merchandise_net_cents", "equipment_surcharge_cents",
                  "freight_fee_cents", "total_cents"):
        assert data.get(field) is None or isinstance(data.get(field), int)
    assert data.get("rejection_reason") is None or isinstance(
        data["rejection_reason"], str)


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] > 0
    assert isinstance(data["qty_allocated"], int) and data["qty_allocated"] >= 0
    assert data.get("lot_id") is None or is_valid_uuid(data["lot_id"])
    assert data.get("unit_price_cents") is None or isinstance(
        data["unit_price_cents"], int)
    assert data.get("line_total_cents") is None or isinstance(
        data["line_total_cents"], int)
    assert data["status"] in ("PENDING", "ALLOCATED", "BACKORDERED", "SHIPPED",
                              "DELIVERED", "CANCELLED")


def assert_backorder_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert isinstance(data["qty_open"], int) and data["qty_open"] >= 0
    assert isinstance(data["allocation_sequence"], int)
    assert data["status"] in ("OPEN", "FILLED", "CANCELLED")


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["carrier_cold_chain_certified"], bool)
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["has_unresolved_excursion"], bool)
    assert isinstance(data.get("temperature_log"), list)
    for reading in data.get("temperature_log", []):
        assert isinstance(reading.get("recorded_at"), str)
        assert isinstance(reading.get("temperature_celsius"), (int, float))
    assert data["status"] in ("PREPARING", "IN_TRANSIT", "QUARANTINED",
                              "DELIVERED", "DESTROYED")


def assert_bundle_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["manufacturer_code"], str) and data["manufacturer_code"]
    assert isinstance(data["qualifying_product_types"], list)
    for ptype in data["qualifying_product_types"]:
        assert ptype in ("RX_PHARMACEUTICAL", "VACCINE", "EQUIPMENT", "CONSUMABLE")
    assert isinstance(data["min_distinct_categories"], int)
    assert isinstance(data["bundle_discount_pct"], int)
    assert isinstance(data["rebate_base_rate_bp"], int)
    assert isinstance(data["rebate_bonus_rate_bp"], int)
    assert isinstance(data["bonus_threshold_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")


def assert_bundle_enrollment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["quarter"], str) and data["quarter"]
    assert isinstance(data["qtd_qualifying_cents"], int)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "FINALIZED")


def assert_rebate_accrual(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["provisional_amount_cents"], int)
    # PRD §3.8: final_amount_cents stays null until finalization.
    assert data.get("final_amount_cents") is None or isinstance(
        data["final_amount_cents"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "REVERSED")


def assert_short_date_credit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["days_to_expiry_at_request"], int)
    assert isinstance(data["claimed_credit_cents"], int)
    # PRD §3.9: final_credit_cents remains null until finalization.
    assert data.get("final_credit_cents") is None or isinstance(
        data["final_credit_cents"], int)
    assert data.get("received_qty") is None or isinstance(data["received_qty"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "CREDITED", "DENIED", "EXPIRED")
