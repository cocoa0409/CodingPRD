"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Entity-level assertions (shape only — values are asserted per-test)
# ---------------------------------------------------------------------------

def assert_airport(data: dict):
    assert isinstance(data, dict), "airport payload must be an object"
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("iata_code"), str) and len(data["iata_code"]) == 3
    assert isinstance(data.get("tz_offset_minutes"), int)
    assert isinstance(data.get("meet_buffer_minutes"), int)
    assert data.get("posture") in ("NORMAL", "DEGRADED", "LOCKDOWN")
    assert isinstance(data.get("ops_epoch"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_terminal(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data.get("code"), str) and len(data["code"]) > 0
    assert isinstance(data.get("requires_secure_escort"), bool)
    assert data.get("status") in ("OPEN", "CLOSED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_flight_segment(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data.get("flight_no"), str) and len(data["flight_no"]) > 0
    assert data.get("direction") in ("ARRIVAL", "DEPARTURE")
    assert is_valid_uuid(data.get("terminal_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_utc", ""))
    assert data.get("actual_utc") is None or is_iso8601_timestamp(data["actual_utc"])
    assert data.get("status") in ("SCHEDULED", "LANDED", "DEPARTED", "CANCELLED")
    assert isinstance(data.get("version"), int)


def assert_passenger(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("dob"), str) and len(data["dob"]) >= 8
    assert data.get("mobility_code") in ("WCHR", "WCHS", "WCHC")
    assert data.get("passenger_class") in ("ADULT", "SENIOR", "UMNR")
    assert isinstance(data.get("version"), int)


def assert_agent(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data.get("display_name"), str) and len(data["display_name"]) > 0
    assert is_iso8601_timestamp(data.get("tsa_cleared_until", ""))
    assert isinstance(data.get("ummr_certified"), bool)
    assert isinstance(data.get("senior_trained"), bool)
    assert isinstance(data.get("wc_certified"), bool)
    assert is_iso8601_timestamp(data.get("shift_start_utc", ""))
    assert is_iso8601_timestamp(data.get("shift_end_utc", ""))
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "OFF_SHIFT")
    assert isinstance(data.get("active_assignment_count"), int)
    assert isinstance(data.get("cumulative_delay_minutes"), int)
    assert isinstance(data.get("version"), int)


def assert_wheelchair(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("airport_id", ""))
    assert isinstance(data.get("asset_tag"), str) and len(data["asset_tag"]) > 0
    assert data.get("chair_class") in ("MANUAL", "POWER", "BARIATRIC")
    assert isinstance(data.get("is_wchc_rated"), bool)
    assert data.get("status") in ("AVAILABLE", "CHECKED_OUT", "MAINTENANCE", "RETIRED")
    assert data.get("last_maintenance_utc") is None or is_iso8601_timestamp(data["last_maintenance_utc"])
    assert isinstance(data.get("usage_count"), int)
    assert isinstance(data.get("version"), int)


def assert_assist_request(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("passenger_id", ""))
    assert data.get("bill_to") in ("AIRLINE", "PRIVATE")
    assert data.get("service_tier") in ("STANDARD", "PRIORITY", "CONCIERGE")
    assert data.get("request_status") in (
        "DRAFT", "SUBMITTED", "ASSIGNED", "IN_SERVICE",
        "COMPLETED", "CANCELLED", "FAILED",
    )
    assert data.get("billing_status") in (
        "UNBILLED", "PROVISIONAL", "FINALIZED", "PAID", "DISPUTED", "WRITTEN_OFF",
    )
    assert isinstance(data.get("version"), int)


def assert_service_leg(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("assist_request_id", ""))
    assert is_valid_uuid(data.get("segment_id", ""))
    assert data.get("leg_kind") in ("MEET_ARRIVAL", "DEPARTURE_ESCORT", "CONNECTION_TRANSFER")
    assert data.get("status") in (
        "PLANNED", "DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE",
        "HANDED_OFF", "COMPLETED", "NO_SHOW", "CANCELLED", "FAILED",
    )
    assert isinstance(data.get("requires_wheelchair"), bool)
    assert isinstance(data.get("requires_wchc_chair"), bool)
    assert isinstance(data.get("requires_ummr_agent"), bool)
    assert isinstance(data.get("requires_senior_agent"), bool)
    assert isinstance(data.get("requires_tsa_escort"), bool)
    assert isinstance(data.get("version"), int)


def assert_assignment(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("assist_request_id", ""))
    assert is_valid_uuid(data.get("service_leg_id", ""))
    assert is_valid_uuid(data.get("agent_id", ""))
    assert data.get("status") in (
        "DISPATCHED", "AT_PICKUP", "IN_TRANSIT", "AT_GATE",
        "COMPLETED", "NO_SHOW", "CANCELLED", "FAILED",
    )
    assert isinstance(data.get("assigned_by_user_id"), str)
    assert isinstance(data.get("tracking_token"), str) and len(data["tracking_token"]) > 0
    assert isinstance(data.get("version"), int)


def assert_incident(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("assist_request_id", ""))
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data.get("kind") in (
        "FALL", "MISSED_CONNECTION", "MEDICAL", "PROPERTY_DAMAGE", "SECURITY",
    )
    assert data.get("severity") in ("MINOR", "MAJOR", "CRITICAL")
    assert data.get("status") in ("OPEN", "ACKED", "RESOLVED")
    assert isinstance(data.get("version"), int)


def assert_invoice(data: dict):
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("assist_request_id", ""))
    assert data.get("invoice_kind") in ("PROVISIONAL", "FINAL", "ADJUSTMENT")
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("status") in ("OPEN", "PAID", "DISPUTED", "WRITTEN_OFF", "VOID")
    assert data.get("bill_to") in ("AIRLINE", "PRIVATE")
    assert isinstance(data.get("version"), int)


def assert_tracking_event(data: dict):
    """TrackingEvent is append-only: id + created_at only — NO version, NO updated_at."""
    assert isinstance(data, dict)
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("assignment_id", ""))
    assert data.get("event_kind") in (
        "LOCATION_PING", "PICKUP_CONFIRM", "GATE_ARRIVAL",
        "HANDOFF_START", "HANDOFF_COMPLETE",
    )
    assert is_iso8601_timestamp(data.get("occurred_at_utc", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "TrackingEvent must NOT carry a version field"
    assert "updated_at" not in data, "TrackingEvent must NOT carry an updated_at field"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_invoice_amount_matches_charge(invoice: dict, expected_cents: int):
    """An invoice's amount_cents equals the parent charge at the time of issue."""
    assert invoice["amount_cents"] == expected_cents, (
        f"Expected invoice amount_cents {expected_cents}, got {invoice['amount_cents']}"
    )


def assert_agent_count_consistent(agent: dict, expected_active: int):
    """Agent.active_assignment_count matches expected count of in-flight assignments."""
    assert agent["active_assignment_count"] == expected_active, (
        f"Expected active_assignment_count {expected_active}, got {agent['active_assignment_count']}"
    )
