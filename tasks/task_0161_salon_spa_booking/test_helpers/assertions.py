"""Entity assertions and domain invariant checkers for the Salon Spa Booking API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# --------------------------------------------------------------------------- #
# Common-field helpers
# --------------------------------------------------------------------------- #
def _assert_common_fields(data: dict):
    """id / created_at / updated_at / version quartet (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


# --------------------------------------------------------------------------- #
# Salon
# --------------------------------------------------------------------------- #
def assert_salon(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["no_show_fee_pct"] <= 1
    assert data["no_show_suspend_threshold"] >= 1
    assert data["tip_split_policy"] in ("DIRECT", "POOLED")
    assert is_iso8601_timestamp(data.get("current_utc", "")), "current_utc must be ISO 8601"


# --------------------------------------------------------------------------- #
# Stylist
# --------------------------------------------------------------------------- #
def assert_stylist(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["compensation_model"] in ("COMMISSION", "BOOTH_RENT")
    assert 0 <= data["commission_pct"] <= 1
    assert data["booth_rent_per_appt_cents"] >= 0
    assert data["buffer_minutes"] >= 0


# --------------------------------------------------------------------------- #
# Resource
# --------------------------------------------------------------------------- #
def assert_resource(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["resource_type"] in ("CHAIR", "ROOM")
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #
def assert_service(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["duration_minutes"] >= 1
    assert data["base_price_cents"] >= 0
    assert 0 <= data["deposit_pct"] <= 1
    assert isinstance(data["requires_room"], bool)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
def assert_client(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "ARCHIVED")
    assert data["no_show_strikes"] >= 0, "no_show_strikes never negative"
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents never negative"


# --------------------------------------------------------------------------- #
# MembershipPlan
# --------------------------------------------------------------------------- #
def assert_membership_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["monthly_fee_cents"] >= 0
    assert 0 <= data["service_discount_pct"] <= 1
    assert 0 <= data["retail_discount_pct"] <= 1


# --------------------------------------------------------------------------- #
# Membership
# --------------------------------------------------------------------------- #
def assert_membership(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")


# --------------------------------------------------------------------------- #
# Package
# --------------------------------------------------------------------------- #
def assert_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert is_valid_uuid(data["service_id"])
    assert data["session_count"] >= 1
    assert data["price_cents"] >= 0


# --------------------------------------------------------------------------- #
# PackagePurchase
# --------------------------------------------------------------------------- #
def assert_package_purchase(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["package_id"])
    assert data["sessions_remaining"] >= 0, "sessions_remaining never negative"
    assert data["status"] in ("ACTIVE", "EXHAUSTED")


# --------------------------------------------------------------------------- #
# Appointment
# --------------------------------------------------------------------------- #
def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["stylist_id"])
    assert is_valid_uuid(data["resource_id"])
    assert is_valid_uuid(data["service_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["status"] in ("BOOKED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["quoted_service_price_cents"] >= 0
    assert data["deposit_held_cents"] >= 0


# --------------------------------------------------------------------------- #
# ProductSku
# --------------------------------------------------------------------------- #
def assert_product_sku(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["salon_id"])
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["unit_price_cents"] >= 0
    assert data["qty_on_hand"] >= 0, "qty_on_hand never negative"


# --------------------------------------------------------------------------- #
# Checkout
# --------------------------------------------------------------------------- #
def assert_checkout(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["tip_cents"] >= 0
    assert data["service_revenue_cents"] >= 0
    assert data["retail_revenue_cents"] >= 0
    assert data["status"] in ("SETTLED", "VOIDED")


def assert_checkout_split_conserved(data: dict):
    """The stylist + salon shares of service revenue sum to recognized revenue (PRD §3.5)."""
    assert (
        data["stylist_service_earning_cents"] + data["salon_service_earning_cents"]
        == data["service_revenue_cents"]
    ), "stylist + salon service earnings must equal recognized service revenue"


# --------------------------------------------------------------------------- #
# ProductSale — append-only: id + created_at only, NO updated_at / version
# --------------------------------------------------------------------------- #
def assert_product_sale(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["checkout_id"])
    assert is_valid_uuid(data["product_sku_id"])
    assert data["quantity"] >= 1
    assert data["line_total_cents"] >= 0
