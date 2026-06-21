"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the structural contract of a response object:
the universal id/timestamp fields, the version field where the entity carries one,
and the entity-specific status enum domains. The leaner records (WaitEvent,
CancellationRecord) deliberately omit updated_at and version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_lifecycle(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_corporate_account(data: dict):
    _assert_full_lifecycle(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["billing_email"], str) and data["billing_email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_balance_cents"], int)
    assert 0 <= data["negotiated_discount_pct"] <= 40
    assert 0 <= data["default_gratuity_pct"] <= 30
    assert data["cancellation_grace_minutes"] >= 0


def assert_affiliate(data: dict):
    _assert_full_lifecycle(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_farmouts"], int)
    assert 0 <= data["payout_share_pct"] <= 90


def assert_vehicle_class(data: dict):
    _assert_full_lifecycle(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["base_fare_cents"] >= 0
    assert data["per_mile_cents"] >= 0
    assert data["hourly_rate_cents"] >= 0
    assert data["wait_per_minute_cents"] >= 0
    assert data["included_wait_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_vehicle(data: dict):
    _assert_full_lifecycle(data)
    assert is_valid_uuid(data.get("vehicle_class_id", "")), "vehicle_class_id must be a UUID"
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["turnaround_minutes"] >= 0
    assert data["status"] == "AVAILABLE"


def assert_chauffeur(data: dict):
    _assert_full_lifecycle(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_market_code"], str) and data["home_market_code"]
    assert data["rest_buffer_minutes"] >= 0
    assert data["status"] in ("OFF_DUTY", "ON_DUTY", "ON_TRIP", "SUSPENDED")
    aid = data.get("active_assignment_id")
    assert aid is None or is_valid_uuid(aid), "active_assignment_id is null or a UUID"


def assert_reservation(data: dict):
    _assert_full_lifecycle(data)
    assert is_valid_uuid(data.get("corporate_account_id", "")), "corporate_account_id must be a UUID"
    assert is_valid_uuid(data.get("vehicle_class_id", "")), "vehicle_class_id must be a UUID"
    assert data["trip_type"] in ("POINT_TO_POINT", "HOURLY", "AIRPORT")
    assert data["trip_status"] in (
        "DRAFT", "QUOTED", "CONFIRMED", "ASSIGNED", "EN_ROUTE",
        "ON_LOCATION", "PASSENGER_ABOARD", "COMPLETED", "CANCELLED",
    )
    assert data["settlement_status"] in ("UNBILLED", "INVOICED", "SETTLED", "WRITTEN_OFF")
    assert data["fulfillment_mode"] in ("IN_HOUSE", "FARMED_OUT")
    assert is_iso8601_timestamp(data["pickup_at"])
    assert is_iso8601_timestamp(data["planned_drop_at"])


def assert_flight_tracking(data: dict):
    _assert_full_lifecycle(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a UUID"
    assert isinstance(data["flight_number"], str) and data["flight_number"]
    assert is_iso8601_timestamp(data["scheduled_arrival_at"])
    assert isinstance(data["meet_and_greet"], bool)
    assert data["status"] in ("ON_TIME", "DELAYED", "LANDED")


def assert_assignment(data: dict):
    _assert_full_lifecycle(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a UUID"
    assert is_valid_uuid(data.get("chauffeur_id", "")), "chauffeur_id must be a UUID"
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a UUID"
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_farm_out_order(data: dict):
    _assert_full_lifecycle(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a UUID"
    assert is_valid_uuid(data.get("affiliate_id", "")), "affiliate_id must be a UUID"
    assert isinstance(data["offered_payout_cents"], int)
    assert data["status"] in ("OFFERED", "ACCEPTED", "REJECTED", "RECALLED")


def assert_wait_event(data: dict):
    """WaitEvent is an append-only log: id + created_at only, no version/updated_at."""
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a UUID"
    assert data["kind"] in ("CHAUFFEUR_ARRIVED", "PASSENGER_BOARDED")
    assert is_iso8601_timestamp(data["occurred_at"])
    assert "version" not in data, "WaitEvent must not carry version"
    assert "updated_at" not in data, "WaitEvent must not carry updated_at"


def assert_cancellation_record(data: dict):
    """CancellationRecord is an immutable audit row: id + created_at only."""
    _assert_common(data)
    assert is_valid_uuid(data.get("reservation_id", "")), "reservation_id must be a UUID"
    assert data["tier"] in ("FREE", "TIER1", "TIER2", "NO_SHOW")
    assert isinstance(data["lead_minutes"], int)
    assert isinstance(data["fee_cents"], int)
    assert "version" not in data, "CancellationRecord must not carry version"
    assert "updated_at" not in data, "CancellationRecord must not carry updated_at"
