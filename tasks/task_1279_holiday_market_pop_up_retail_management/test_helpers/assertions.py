"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.4: every entity carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')}"


def assert_market(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert data["posture"] in ["SETUP", "OPEN", "WEATHER_ALERT", "CLOSED_SEASON", "CANCELLED"]
    assert isinstance(data["total_accepted_vendors"], int)
    assert isinstance(data["total_booths_committed"], int)
    assert isinstance(data["run_ops_index"], int)
    assert isinstance(data["category_caps"], dict)


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["category"] in ["FOOD_BEVERAGE", "CRAFT", "APPAREL", "HOME_GOODS", "EXPERIENCE"]
    assert data["status"] in ["PROSPECT", "APPROVED", "SUSPENDED", "WITHDRAWN"]
    assert isinstance(data["no_show_strikes"], int)
    assert isinstance(data["lifetime_gross_sales_cents"], int)


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("market_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["requested_booth_type"] in ["STANDARD", "CHALET"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_JURY", "ACCEPTED",
                              "REJECTED", "WAITLISTED", "WITHDRAWN"]
    assert isinstance(data["jury_scores"], list)


def assert_booth(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["booth_code"], str) and data["booth_code"]
    assert data["booth_type"] in ["STANDARD", "CHALET"]
    assert data["zone"] in ["NORTH", "SOUTH", "EAST", "WEST"]
    assert isinstance(data["square_feet"], int)
    assert data["status"] in ["AVAILABLE", "RESERVED", "OCCUPIED", "OFFLINE"]


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("booth_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["base_rent_cents"], int)
    assert isinstance(data["heating_surcharge_cents"], int)
    assert isinstance(data["total_fee_cents"], int)
    assert data["status"] in ["PENDING_PAYMENT", "ACTIVE", "RELEASED", "FORFEITED"]


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data["permit_type"] in ["TEMP_STRUCTURE", "FOOD_SERVICE", "PROPANE_HEAT", "GENERATOR"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]


def assert_hookup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("booth_id", ""))
    assert data["hookup_type"] in ["ELECTRIC_15A", "ELECTRIC_30A", "WATER", "PROPANE"]
    assert data["status"] in ["REQUESTED", "INSTALLED", "ENERGIZED", "DECOMMISSIONED"]


def assert_pos_device(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["device_code"], str) and data["device_code"]
    assert data["status"] in ["PROVISIONED", "ACTIVE", "SUSPENDED", "RETURNED"]


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert isinstance(data["business_date"], str) and data["business_date"]
    assert isinstance(data["gross_card_cents"], int)
    assert isinstance(data["gross_cash_cents"], int)
    assert isinstance(data["pos_fee_cents"], int)
    assert isinstance(data["refund_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RECONCILED", "PAID", "DISPUTED"]


def assert_load_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data["direction"] in ["LOAD_IN", "LOAD_OUT"]
    assert data["status"] in ["RESERVED", "CHECKED_IN", "COMPLETED", "NO_SHOW"]


def assert_weather_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["wind_mph"], int)
    assert data["precipitation"] in ["NONE", "RAIN", "SNOW", "ICE"]
    assert data["source"] in ["NWS", "ON_SITE_SENSOR", "OPERATOR"]
    assert isinstance(data["triggers_alert"], bool)


def assert_renewal_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert isinstance(data["discount_pct"], int)
    assert data["status"] in ["EXTENDED", "ACCEPTED", "DECLINED", "EXPIRED"]


def assert_market_invariants(data: dict):
    """Domain invariants that must hold after any operation."""
    assert data["total_accepted_vendors"] >= 0
    assert data["total_booths_committed"] >= 0
    assert data["run_ops_index"] >= 0


def assert_assignment_fee_invariants(data: dict):
    """PRD §3.4: total_fee_cents == base_rent_cents + heating_surcharge_cents."""
    assert data["total_fee_cents"] == data["base_rent_cents"] + data["heating_surcharge_cents"], (
        f"total_fee_cents ({data['total_fee_cents']}) must equal base_rent_cents "
        f"({data['base_rent_cents']}) + heating_surcharge_cents "
        f"({data['heating_surcharge_cents']})"
    )
