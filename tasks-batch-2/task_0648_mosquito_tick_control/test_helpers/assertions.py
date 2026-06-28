"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_service_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ["BASIC", "PLUS", "PREMIER"]
    assert isinstance(data["visit_interval_days"], int)
    assert isinstance(data["per_visit_price_cents"], int)
    assert isinstance(data["seasonal_price_cents"], int)
    assert isinstance(data["includes_tick_barrier"], bool)
    assert isinstance(data["retreat_guarantee_days"], int)
    # Immutable config record: no version / updated_at.
    assert "version" not in data, "ServicePlan is immutable; must not carry version"


def assert_account_holder(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet credit cannot be negative"


def assert_property(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["account_holder_id"], str)
    assert isinstance(data["street_address"], str)
    assert isinstance(data["lot_size_sqft"], int) and data["lot_size_sqft"] > 0
    assert isinstance(data["service_region_code"], str)
    assert isinstance(data["zone_count"], int) and data["zone_count"] >= 0
    assert isinstance(data["total_treatable_sqft"], int) and data["total_treatable_sqft"] >= 0
    assert isinstance(data["version"], int)


def assert_treatment_zone(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["property_id"], str)
    assert data["zone_type"] in ["TURF", "PERIMETER", "WATER_FEATURE", "WOODLINE"]
    assert isinstance(data["area_sqft"], int) and data["area_sqft"] > 0
    assert data["status"] in ["ACTIVE", "EXCLUDED"]


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["property_id"], str)
    assert isinstance(data["service_plan_id"], str)
    assert data["billing_mode"] in ["PER_VISIT", "SEASONAL"]
    assert data["status"] in ["DRAFT", "ACTIVE", "OFF_SEASON", "RENEWED", "CANCELLED"]
    assert isinstance(data["visits_completed_count"], int) and data["visits_completed_count"] >= 0
    assert isinstance(data["season_balance_cents"], int)
    assert isinstance(data["version"], int)


def assert_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["subscription_id"], str)
    assert data["visit_kind"] in ["RECURRING", "SPECIAL_EVENT", "RETREAT"]
    assert data["status"] in [
        "SCHEDULED", "WEATHER_HOLD", "DISPATCHED", "COMPLETED",
        "RETREAT_REQUESTED", "RETREAT_SCHEDULED", "SKIPPED", "CANCELLED",
    ]
    assert isinstance(data["sequence_index"], int)
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    assert isinstance(data["version"], int)


def assert_application_log(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["treatment_zone_id"], str)
    assert data["product_code"] in ["BIFEN_IT", "TALSTAR", "ESSENTRIA_IC3"]
    assert float(data["gallons_applied"]) > 0
    # Append-only event record: no version / updated_at.
    assert "version" not in data, "ApplicationLog is append-only; must not carry version"
    assert "updated_at" not in data, "ApplicationLog is append-only; must not carry updated_at"


def assert_crew(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["tech_name"], str)
    assert isinstance(data["home_region_code"], str)
    assert isinstance(data["daily_capacity"], int) and 1 <= data["daily_capacity"] <= 40


def assert_crew_route(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["crew_id"], str)
    assert isinstance(data["region_code"], str)
    assert data["status"] in ["OPEN", "LOCKED", "CLOSED"]
    assert isinstance(data["assigned_visit_count"], int) and data["assigned_visit_count"] >= 0
    assert isinstance(data["remaining_capacity"], int)
    assert isinstance(data["version"], int)


def assert_weather_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["region_code"], str)
    assert data["severity"] in ["RAIN_LIGHT", "RAIN_HEAVY", "WIND_HIGH"]


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["subscription_id"], str)
    assert data["invoice_type"] in ["PER_VISIT", "SEASONAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ["ISSUED", "PAID", "VOID"]
    assert isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["version"], int)
