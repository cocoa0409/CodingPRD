"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── Instant helpers ──────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """Two timestamps denote the same instant regardless of fractional-digit styling."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}"
    )


def assert_cg(actual, expected: float, label: str = "actual_cg_in"):
    """CG values are rounded half-up to two decimals (PRD §2.7) before comparison."""
    assert actual is not None, f"{label} must not be null"
    assert float(actual) == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


# ─── Per-entity structural assertions ─────────────────────────────────────────

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_base(data: dict):
    _assert_common_fields(data, "Base")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["quiet_hours_start_min_utc"], int)
    assert isinstance(data["quiet_hours_end_min_utc"], int)
    assert isinstance(data["current_waiver_version"], str)
    assert data["posture"] in ("NORMAL", "WEATHER_HOLD")
    assert isinstance(data["ops_run_index"], int)


def assert_route(data: dict):
    _assert_common_fields(data, "Route")
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert data["tier"] in ("SHORT", "STANDARD", "GRAND")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["turn_minutes"], int)


def assert_season(data: dict):
    _assert_common_fields(data, "Season")
    assert data["status"] in ("PUBLISHED", "RETIRED")
    assert isinstance(data["multiplier_bps"], int)


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert data["noise_class"] in ("QUIET", "STANDARD")
    assert data["status"] in ("AVAILABLE", "IN_MAINTENANCE", "GROUNDED")
    assert isinstance(data["seat_arms_inches"], list)
    assert len(data["seat_arms_inches"]) == data["seat_capacity"]


def assert_pilot(data: dict):
    _assert_common_fields(data, "Pilot")
    assert isinstance(data["certificate_no"], str) and data["certificate_no"]
    assert data["status"] in ("AVAILABLE", "FATIGUE_LOCKED")


def assert_duty_day(data: dict):
    _assert_common_fields(data, "DutyDay")
    assert is_valid_uuid(data.get("pilot_id", "")), "DutyDay.pilot_id must be a UUID"
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["flight_minutes_scheduled"], int)
    assert isinstance(data["flight_minutes_actual"], int)
    assert isinstance(data["duty_minutes_projected"], int)


def assert_flight(data: dict):
    _assert_common_fields(data, "Flight")
    assert data["status"] in (
        "SCHEDULED", "DELAYED", "BOARDING", "MANIFEST_CLOSED",
        "DISPATCHED", "COMPLETED", "CANCELLED_WEATHER", "CANCELLED_OPS",
    )
    assert is_iso8601_timestamp(data["scheduled_departure_utc"])
    assert is_iso8601_timestamp(data["scheduled_arrival_utc"])
    assert isinstance(data["rotation_seq"], int) and data["rotation_seq"] >= 1
    assert isinstance(data["pilot_acknowledged"], bool)
    assert isinstance(data["seats_booked"], int)
    assert isinstance(data["seats_available"], int)
    assert isinstance(data["estimated_gross_weight_lb"], int)


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert data["status"] in (
        "HELD", "CONFIRMED", "CHECKED_IN", "MANIFESTED", "FLOWN",
        "CANCELLED", "EXPIRED", "NO_SHOW", "CREDITED",
    )
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["quoted_per_seat_cents"], int)
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["refunded_card_cents"], int)
    assert isinstance(data["credited_cents"], int)
    assert isinstance(data["retained_fee_cents"], int)
    assert isinstance(data["credits_applied_cents"], int)


def assert_passenger(data: dict):
    _assert_common_fields(data, "Passenger")
    assert isinstance(data["pax_index"], int) and data["pax_index"] >= 0
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["waiver_signed"], bool)
    assert isinstance(data["briefing_completed"], bool)
    assert isinstance(data["checked_in"], bool)


def assert_credit(data: dict):
    _assert_common_fields(data, "RebookingCredit")
    assert data["status"] in ("ISSUED", "PARTIALLY_REDEEMED", "REDEEMED", "EXPIRED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["redeemed_cents"], int)
    assert isinstance(data["remaining_cents"], int)


def assert_weather_observation(data: dict):
    """WeatherObservation is immutable: id + created_at only (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "WeatherObservation.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "WeatherObservation.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "WeatherObservation must not carry updated_at"
    assert "version" not in data, "WeatherObservation must not carry version"
    assert isinstance(data["adverse"], bool)
    assert is_iso8601_timestamp(data["observed_at"])
    assert is_iso8601_timestamp(data["validity_until"])


def assert_complaint(data: dict):
    _assert_common_fields(data, "Complaint")
    assert data["zone"] in ("VILLAGE", "RIM", "AIRPORT")
    assert data["status"] in (
        "LOGGED", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED", "CLOSED"
    )
    assert data["match_status"] in ("MATCHED", "UNMATCHED")


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_seat_conservation(flight: dict, seat_capacity: int):
    """seats_booked + seats_available == aircraft seat_capacity at all times (PRD §3.3)."""
    assert flight["seats_booked"] + flight["seats_available"] == seat_capacity, (
        f"seat conservation violated: {flight['seats_booked']} booked + "
        f"{flight['seats_available']} available != {seat_capacity}"
    )


def assert_payment_conservation(booking: dict):
    """paid_cents == refunded_card_cents + credited_cents + retained_fee_cents
    after any voluntary cancellation settlement (PRD §3.8)."""
    total = (
        booking["refunded_card_cents"]
        + booking["credited_cents"]
        + booking["retained_fee_cents"]
    )
    assert booking["paid_cents"] == total, (
        f"payment conservation violated: paid {booking['paid_cents']} != "
        f"refunded {booking['refunded_card_cents']} + credited "
        f"{booking['credited_cents']} + retained {booking['retained_fee_cents']}"
    )


def assert_credit_invariant(credit: dict):
    """amount_cents == redeemed_cents + remaining_cents at all times (PRD §3.8)."""
    assert credit["amount_cents"] == credit["redeemed_cents"] + credit["remaining_cents"], (
        f"credit invariant violated: {credit['amount_cents']} != "
        f"{credit['redeemed_cents']} + {credit['remaining_cents']}"
    )
