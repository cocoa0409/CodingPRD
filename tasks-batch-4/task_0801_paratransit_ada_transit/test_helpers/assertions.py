"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

RIDER_ELIGIBILITY = ["UNCERTIFIED", "CONDITIONAL", "FULL", "EXPIRED", "SUSPENDED"]
ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED"]
PENALTY_TIERS = ["NONE", "WARNING", "SUSPENDED"]
TRIP_STATUSES = [
    "REQUESTED", "OFFERED", "COUNTERED", "SCHEDULED", "EN_ROUTE", "PICKED_UP",
    "COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW", "CANCELLED_BY_SYSTEM",
]
RUN_STATUSES = ["PLANNED", "OPEN", "DISPATCHED", "CLOSED", "CANCELLED"]


def _assert_audited(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight(data: dict):
    """common_fields:false entities carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_rider(data: dict):
    _assert_audited(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["eligibility_status"] in RIDER_ELIGIBILITY
    assert data["account_status"] in ACCOUNT_STATUSES
    assert data["penalty_tier"] in PENALTY_TIERS
    assert isinstance(data["no_show_points_rolling"], int)
    assert isinstance(data["no_show_points_lifetime"], int)
    assert isinstance(data["prior_suspension_count"], int)


def assert_service_zone(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert "version" not in data, "ServiceZone must NOT expose a version field"
    assert "updated_at" not in data, "ServiceZone must NOT expose an updated_at field"


def assert_application(data: dict):
    _assert_audited(data)
    assert is_valid_uuid(data["rider_id"])
    assert data["status"] in [
        "SUBMITTED", "ASSESSMENT_SCHEDULED", "ASSESSED", "CERTIFIED", "DENIED", "APPEALED",
    ]
    assert isinstance(data["appeal_count"], int)


def assert_assessment(data: dict):
    _assert_audited(data)
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ["SCHEDULED", "COMPLETED"]


def assert_trip(data: dict):
    _assert_audited(data)
    assert is_valid_uuid(data["rider_id"])
    assert data["status"] in TRIP_STATUSES
    assert isinstance(data["offer_round"], int)


def assert_run(data: dict):
    _assert_audited(data)
    assert data["status"] in RUN_STATUSES
    assert isinstance(data["available_ambulatory_seats"], int)
    assert isinstance(data["available_wheelchair_positions"], int)
    assert data["available_ambulatory_seats"] >= 0
    assert data["available_wheelchair_positions"] >= 0
    assert data["available_ambulatory_seats"] <= data["total_ambulatory_seats"]
    assert data["available_wheelchair_positions"] <= data["total_wheelchair_positions"]


def assert_subscription(data: dict):
    _assert_audited(data)
    assert is_valid_uuid(data["rider_id"])
    assert data["status"] in ["ACTIVE", "CANCELLED"]


def assert_negotiation_offer(data: dict):
    _assert_lightweight(data)
    assert data["offered_by"] in ["DISPATCHER", "RIDER"]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert "version" not in data, "NegotiationOffer must NOT expose a version field"


def assert_penalty(data: dict):
    _assert_audited(data)
    assert data["event_type"] in ["NO_SHOW", "LATE_CANCEL"]
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert isinstance(data["points"], int)
