"""Entity assertions and domain invariant checkers.

Each assert_* checks the uniform identity/audit shape (PRD §2.4) plus the
field types and enum domains documented in PRD §3.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_category(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["compliance_class"] in [
        "STANDARD", "SENSITIVE_INGREDIENT", "HEMP_DERIVED", "KAVA",
        "FUNCTIONAL_MUSHROOM",
    ]
    assert isinstance(data["active"], bool)


def assert_sku(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["category_id"])
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["abv_basis_points"], int)
    assert data["age_neutral_class"] in [
        "OPEN", "ADULT_ONLY_SUGGESTED", "ADULT_ONLY_REQUIRED",
        "PROHIBITED_STATE_LIST",
    ]
    assert isinstance(data["discontinued"], bool)
    assert isinstance(data["on_hand_cached"], int) and data["on_hand_cached"] >= 0


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["lot_code"], str)
    assert isinstance(data["qty_received"], int) and data["qty_received"] >= 1
    assert isinstance(data["qty_remaining"], int) and data["qty_remaining"] >= 0
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ["ACTIVE", "DEPLETED", "EXPIRED", "QUARANTINED"]


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["home_state_code"], str)
    assert data["age_attestation_status"] in [
        "UNVERIFIED", "PENDING_REVIEW", "ATTESTED", "REJECTED", "REVOKED",
    ]
    assert data["loyalty_tier"] in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_points_balance"] >= 0, "loyalty_points_balance is never negative"
    assert isinstance(data["loyalty_points_lifetime"], int)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"


def assert_club_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)
    assert data["cadence"] in ["MONTHLY", "QUARTERLY", "ANNUAL"]
    assert isinstance(data["bottles_per_shipment"], int)
    assert isinstance(data["price_cents_per_cycle"], int)
    assert isinstance(data["allowed_category_ids"], list)
    assert isinstance(data["discount_bps_on_retail"], int)
    assert isinstance(data["max_active_subscriptions"], int)
    assert isinstance(data["active_subscription_count"], int)


def assert_club_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["plan_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in [
        "TRIALING", "ACTIVE", "PAST_DUE", "PAUSED", "CANCELLED", "EXPIRED",
    ]
    assert isinstance(data["started_on"], str)
    assert isinstance(data["next_billing_on"], str)
    assert isinstance(data["failed_billing_count"], int)
    assert isinstance(data["shipments_fulfilled"], int)


def assert_tasting_event(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert is_valid_uuid(data["host_member_id"])
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["seats_booked"], int) and data["seats_booked"] >= 0
    assert data["status"] in [
        "DRAFT", "PUBLISHED", "LOCKED", "IN_SESSION", "COMPLETED",
        "CANCELLED", "RESCHEDULED",
    ]
    assert isinstance(data["flight_price_cents"], int)
    assert isinstance(data["min_attendee_age_years"], int)
    assert isinstance(data["compliance_hold"], bool)


def assert_flight_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tasting_event_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["pour_size_ml"], int)
    assert isinstance(data["sequence_no"], int)


def assert_tasting_seat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tasting_event_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in [
        "RESERVED", "CONFIRMED", "ATTENDED", "NO_SHOW", "CANCELLED", "REFUNDED",
    ]
    assert isinstance(data["price_paid_cents"], int)
    assert isinstance(data["booked_at"], str)


def assert_special_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["requested_sku_code"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in [
        "REQUESTED", "APPROVED", "SOURCED", "RECEIVED", "FULFILLED",
        "DECLINED", "CANCELLED",
    ]


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["channel"] in ["RETAIL", "DTC"]
    assert data["payment_status"] in [
        "UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED_PARTIAL",
        "REFUNDED_FULL", "VOIDED",
    ]
    assert data["fulfillment_status"] in [
        "DRAFT", "PICKING", "PACKED", "SHIPPED", "DELIVERED", "PICKED_UP",
        "CANCELLED",
    ]
    for field in ("subtotal_cents", "discount_cents", "shipping_charge_cents",
                  "tax_cents", "grand_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["lot_allocation"], list)


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["carrier"], str)
    assert isinstance(data["tracking_no"], str)
    assert data["status"] in [
        "LABEL_CREATED", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED",
        "RETURNED", "LOST",
    ]
    assert isinstance(data["shipped_on"], str)


def assert_shipping_state_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["allows_dtc"], bool)
    assert isinstance(data["min_age_years"], int)
    assert isinstance(data["abv_cap_basis_points"], int)
    assert isinstance(data["surcharge_cents_per_order"], int)
    assert isinstance(data["tax_rate_bps"], int)


def assert_compliance_attestation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["attested_by_user_id"], str)
    assert data["outcome"] in ["APPROVED", "REJECTED"]
    assert isinstance(data["attested_on"], str)
    assert isinstance(data["document_reference"], str)


def assert_order_totals_reconcile(order: dict):
    """PRD §3.8 invariant: grand total = subtotal - discount + shipping + tax."""
    expected = (
        order["subtotal_cents"] - order["discount_cents"]
        + order["shipping_charge_cents"] + order["tax_cents"]
    )
    assert order["grand_total_cents"] == expected, (
        f"grand_total_cents {order['grand_total_cents']} does not reconcile with "
        f"subtotal - discount + shipping + tax = {expected}"
    )
