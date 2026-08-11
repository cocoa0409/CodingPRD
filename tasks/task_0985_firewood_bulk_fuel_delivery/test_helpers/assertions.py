"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Primary-resource system fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["street_address"], str)
    assert isinstance(data["postal_code"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["outstanding_refund_cents"], int)
    assert isinstance(data["lifetime_cord_equivalent_delivered"], (int, float))
    assert data["loyalty_tier"] in ("STANDARD", "SILVER", "GOLD")
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["product_kind"] in ("CORD", "HALF_CORD", "PELLET_TON", "PELLET_BAG")
    assert data["species"] in ("OAK", "MAPLE", "BIRCH", "MIXED_HARDWOOD",
                               "HARDWOOD_BLEND", "SOFTWOOD_BLEND")
    assert data["seasoned_grade"] in ("GREEN", "SEMI_SEASONED", "KILN_DRIED")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["moisture_ceiling_pct"], (int, float))
    assert isinstance(data["available_qty"], (int, float))
    assert isinstance(data["reserved_qty"], (int, float))
    assert isinstance(data["discontinued"], bool)


def assert_area_restriction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["postal_codes"], list)
    assert isinstance(data["restricted_kinds"], list)
    assert isinstance(data["restricted_species"], list)
    assert isinstance(data["enforcement_window_start"], str)
    assert isinstance(data["enforcement_window_end"], str)
    assert isinstance(data["active"], bool)


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["tier"] in ("HEARTH", "HEARTH_PLUS", "ESTATE")
    assert isinstance(data["season_year"], int)
    assert isinstance(data["commitment_cord_equivalent"], (int, float))
    assert isinstance(data["delivered_cord_equivalent"], (int, float))
    assert isinstance(data["prepaid_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["stacking_included"], bool)
    assert data["status"] in ("PENDING", "ACTIVE", "FULFILLED", "SHORTFALL",
                              "CANCELLED", "EXPIRED")


def assert_delivery_route(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["depot_name"], str)
    assert isinstance(data["service_postal_prefixes"], list)
    assert isinstance(data["capacity_cord_equivalent"], (int, float))
    assert isinstance(data["active"], bool)


def assert_delivery_window(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["start_hour"], int)
    assert isinstance(data["end_hour"], int)
    assert isinstance(data["capacity_cord_equivalent"], (int, float))
    assert isinstance(data["committed_cord_equivalent"], (int, float))
    assert data["status"] in ("OPEN", "CLOSED", "LOCKED", "CANCELLED")


def assert_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["delivery_street_address"], str)
    assert isinstance(data["delivery_postal_code"], str)
    assert isinstance(data["requested_delivery_date"], str)
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "PAID",
                                      "PARTIALLY_REFUNDED", "REFUNDED", "PAYMENT_FAILED")
    assert data["fulfillment_status"] in ("DRAFT", "PENDING_PAYMENT", "CONFIRMED",
                                          "SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED",
                                          "DELIVERY_FAILED", "CANCELLED")
    for field in ("stacking_fee_cents", "subtotal_cents", "volume_discount_cents",
                  "subscription_discount_cents", "loyalty_discount_cents",
                  "seasonal_surcharge_cents", "delivery_fee_cents", "total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert isinstance(data["total_cord_equivalent"], (int, float))


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], (int, float))
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["cord_equivalent_per_unit"], (int, float))
    assert isinstance(data["line_cord_equivalent"], (int, float))
    assert data["volume_tier_applied"] in ("T0", "T1", "T2", "T3")
    assert isinstance(data["extended_price_cents"], int)


def assert_moisture_reading(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["moisture_pct"], (int, float))
    assert isinstance(data["reading_pass"], bool)


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["invoice_number"], str)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "REFUNDED", "VOID")
    assert isinstance(data["due_date"], str)


def assert_payment_event(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["invoice_id"], str)
    assert data["event_kind"] in ("AUTHORIZE", "CAPTURE", "REFUND", "CHARGEBACK",
                                  "ADJUST_CREDIT")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["external_ref"], str)


def assert_stock_conservation(product: dict, initial_qty: float):
    """Stock invariant: available + reserved always equals the initial stocked quantity."""
    total = product["available_qty"] + product["reserved_qty"]
    assert abs(total - initial_qty) < 1e-6, (
        f"stock conservation violated: available {product['available_qty']} + "
        f"reserved {product['reserved_qty']} != initial {initial_qty}"
    )


def assert_wallet_non_negative(customer: dict):
    """Wallet invariant: credit_balance_cents never goes negative (PRD §3.1)."""
    assert customer["credit_balance_cents"] >= 0, (
        f"credit_balance_cents went negative: {customer['credit_balance_cents']}"
    )
