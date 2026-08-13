"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_nightly_rate_cents"], int)
    assert isinstance(data["no_show_grace_minutes"], int)
    assert isinstance(data["overstay_grace_minutes"], int)
    assert isinstance(data["cancellation_free_window_hours"], int)
    assert data["posture"] in ["NORMAL", "DEGRADED", "ESCALATED"]
    assert isinstance(data["ops_run_index"], int)


def assert_stall(data: dict):
    _assert_common_fields(data, "Stall")
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data["stall_number"], str) and data["stall_number"]
    assert data["stall_class"] in ["STANDARD", "OVERSIZED"]
    assert isinstance(data["is_reservable"], bool)
    assert data["status"] in ["ACTIVE", "OUT_OF_SERVICE"]


def assert_rate_plan(data: dict):
    _assert_common_fields(data, "RatePlan")
    assert is_valid_uuid(data.get("site_id", ""))
    for pct_field in ("tier2_pct", "tier3_pct", "tier4_pct"):
        assert isinstance(data[pct_field], int), f"{pct_field} must be int"
    for mult_field in ("mult_low", "mult_mid", "mult_high", "mult_max",
                       "peak_multiplier"):
        assert isinstance(data[mult_field], (int, float)), \
            f"{mult_field} must be numeric"
    assert isinstance(data["peak_days"], list)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"]


def assert_amenity_product(data: dict):
    _assert_common_fields(data, "AmenityProduct")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["code"] in ["SHOWER", "FUEL", "WIFI", "POWER"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["price_cents"], int)
    assert data.get("nightly_capacity") is None or \
        isinstance(data["nightly_capacity"], int)
    assert data["status"] in ["ACTIVE", "DISCONTINUED"]


def assert_driver(data: dict):
    _assert_common_fields(data, "Driver")
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["strike_events"], list)
    assert isinstance(data["strikes_90d"], int)
    assert data["standing"] in ["GOOD", "PROBATION", "SUSPENDED"]
    assert isinstance(data["settled_nights_90d"], int)
    assert data["loyalty_tier"] in ["STANDARD", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["loyalty_points_balance"], int)


def assert_fleet_account(data: dict):
    _assert_common_fields(data, "FleetAccount")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["payment_terms_days"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["auto_suspended"], bool)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["credit_cents"], int)


def assert_driver_authorization(data: dict):
    _assert_common_fields(data, "DriverAuthorization")
    assert is_valid_uuid(data.get("driver_id", ""))
    assert is_valid_uuid(data.get("fleet_account_id", ""))
    assert data.get("spend_cap_per_night_cents") is None or \
        isinstance(data["spend_cap_per_night_cents"], int)
    assert data["status"] in [
        "PENDING", "ACTIVE", "SUSPENDED", "REVOKED", "REJECTED",
    ]
    assert isinstance(data["auto_suspended"], bool)


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert is_valid_uuid(data.get("driver_id", ""))
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("stall_id", ""))
    assert data["booking_kind"] in ["RESERVED", "WALK_IN"]
    assert data["payment_mode"] in ["DRIVER_DIRECT", "FLEET_BILL"]
    assert isinstance(data["arrival_date"], str) and data["arrival_date"]
    assert isinstance(data["night_count"], int) and data["night_count"] >= 1
    assert is_iso8601_timestamp(data.get("checkin_open_at", "")), \
        "checkin_open_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("checkout_due_at", "")), \
        "checkout_due_at must be ISO 8601"
    assert data["status"] in [
        "BOOKED", "CHECKED_IN", "OVERSTAY", "CHECKED_OUT", "NO_SHOW",
        "CANCELLED", "EVICTED",
    ]
    assert data["billing_status"] in [
        "UNBILLED", "PARTIALLY_PAID", "PAID", "INVOICED", "WAIVED",
    ]
    assert isinstance(data["per_night_rates"], list)
    for line in data["per_night_rates"]:
        assert isinstance(line.get("date"), str)
        assert isinstance(line.get("rate_cents"), int)
    assert isinstance(data["quoted_total_cents"], int)


def assert_booking_amenity(data: dict):
    _assert_common_fields(data, "BookingAmenity")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("amenity_product_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["status"] in ["RESERVED", "FULFILLED", "CANCELLED"]


def assert_waitlist_entry(data: dict):
    _assert_common_fields(data, "WaitlistEntry")
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("driver_id", ""))
    assert isinstance(data["arrival_date"], str) and data["arrival_date"]
    assert isinstance(data["night_count"], int) and data["night_count"] >= 1
    assert data["stall_class"] in ["STANDARD", "OVERSIZED"]
    assert data["payment_mode"] in ["DRIVER_DIRECT", "FLEET_BILL"]
    assert data["status"] in [
        "QUEUED", "OFFERED", "PROMOTED", "EXPIRED", "WITHDRAWN",
    ]


def assert_incident(data: dict):
    _assert_common_fields(data, "IncidentReport")
    assert is_valid_uuid(data.get("site_id", ""))
    assert data["category"] in ["SECURITY", "LIGHTING", "FACILITY"]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["description"], str)
    assert data["status"] in [
        "OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED",
        "REOPENED",
    ]
    assert isinstance(data["reopened_count"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("fleet_account_id", ""))
    assert isinstance(data["period"], str) and data["period"]
    assert data["status"] in [
        "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "DISPUTED",
        "WRITTEN_OFF",
    ]
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["discount_pct"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["due_date"], str) and data["due_date"]
    assert isinstance(data["booking_ids"], list)
