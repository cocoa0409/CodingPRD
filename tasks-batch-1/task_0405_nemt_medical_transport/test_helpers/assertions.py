"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

MODALITIES = ["AMBULATORY", "WHEELCHAIR", "STRETCHER"]
LEVELS_OF_SERVICE = ["ROUTINE", "URGENT", "BARIATRIC"]


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Member id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["medicaid_id"], str) and len(data["medicaid_id"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["mobility_level"] in MODALITIES
    assert isinstance(data["home_county"], str)
    assert data["eligibility_status"] in ["ELIGIBLE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["noshow_strike_count"], int) and data["noshow_strike_count"] >= 0
    assert isinstance(data["standing_orders_paused"], bool)


def assert_eligibility_span(data: dict):
    assert is_valid_uuid(data.get("id", "")), "EligibilitySpan id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["level_of_service"] in LEVELS_OF_SERVICE
    assert isinstance(data["voided"], bool)


def assert_broker(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Broker id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str)
    assert isinstance(data["covered_counties"], list)
    assert data["max_modality"] in MODALITIES
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_driver(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Driver id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["vehicle_modality"] in MODALITIES
    assert isinstance(data["base_county"], str)
    assert data["status"] in ["AVAILABLE", "ON_TRIP", "OFFLINE"]


def assert_rate_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RateSchedule id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["modality"] in MODALITIES
    assert isinstance(data["base_fare_cents"], int)
    assert isinstance(data["loaded_rate_cents_per_mile"], int)


def assert_trip(data: dict):
    assert is_valid_uuid(data.get("id", "")), "TripRequest id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["modality"] in MODALITIES
    assert data["requested_level_of_service"] in LEVELS_OF_SERVICE
    assert data["trip_status"] in [
        "DRAFT", "SCHEDULED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW",
    ]
    assert data["billing_status"] in [
        "UNBILLED", "CLAIMED", "ENCOUNTERED", "RECONCILED", "DISPUTED",
    ]
    assert isinstance(data["claimed_cost_cents"], int)
    assert isinstance(data["encounter_cost_cents"], int)
    assert isinstance(data["reconciliation_variance_cents"], int)


def assert_leg(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Leg id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["direction"] in ["OUTBOUND", "RETURN"]
    assert data["leg_status"] in [
        "PENDING", "READY", "EN_ROUTE", "ARRIVED", "PICKED_UP", "DROPPED_OFF", "NO_SHOW", "CANCELLED",
    ]
    assert isinstance(data["is_will_call"], bool)


def assert_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Assignment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "RELEASED"]


def assert_standing_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "StandingOrder id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["modality"] in MODALITIES
    assert data["level_of_service"] in LEVELS_OF_SERVICE
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Claim id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["SUBMITTED", "RECONCILED", "DENIED"]
    assert isinstance(data["billed_cents"], int)


def assert_encounter(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Encounter id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["OPEN", "RECONCILED"]
    assert isinstance(data["captured_cents"], int)


def assert_reconciliation_variance_identity(trip: dict):
    """PRD 3.9: reconciliation_variance_cents == encounter_cost_cents - claimed_cost_cents."""
    assert trip["reconciliation_variance_cents"] == (
        trip["encounter_cost_cents"] - trip["claimed_cost_cents"]
    ), "variance must equal encounter_cost_cents - claimed_cost_cents"
