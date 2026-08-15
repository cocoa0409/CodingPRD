"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity_label: str):
    """Common system-managed properties every resource carries."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_event(data: dict):
    _assert_common(data, "Event")
    assert data["posture"] in [
        "BIDDING", "AWARDED", "PLANNING", "REGISTRATION_OPEN", "COMPETITION_SETUP",
        "LIVE", "COMPLETED", "SETTLED", "BID_LOST", "CANCELLED",
    ]
    assert isinstance(data["registered_team_count"], int) and data["registered_team_count"] >= 0
    assert isinstance(data["finalized_match_count"], int) and data["finalized_match_count"] >= 0


def assert_bid(data: dict):
    _assert_common(data, "Bid")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "AWARDED", "REJECTED", "WITHDRAWN", "SUPERSEDED",
    ]
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_requirement(data: dict):
    _assert_common(data, "BidRequirement")
    assert data["status"] in ["PENDING", "EVIDENCE_SUBMITTED", "VERIFIED", "RETURNED", "WAIVED"]
    assert isinstance(data["weight_points"], int) and 1 <= data["weight_points"] <= 100


def assert_venue(data: dict):
    _assert_common(data, "Venue")
    assert data["status"] in ["PROPOSED", "CONTRACTED", "RELEASED"]
    assert isinstance(data["rental_fee_cents"], int) and data["rental_fee_cents"] >= 0


def assert_field(data: dict):
    _assert_common(data, "Field")
    assert data["status"] in ["AVAILABLE", "BLACKED_OUT"]
    assert isinstance(data["slot_minutes"], int) and 30 <= data["slot_minutes"] <= 180


def assert_hotel_block(data: dict):
    _assert_common(data, "HotelBlock")
    assert data["status"] in ["NEGOTIATING", "CONTRACTED", "CUTOFF_PASSED", "RECONCILED", "SETTLED", "RELEASED"]
    assert isinstance(data["picked_up_room_nights"], int) and data["picked_up_room_nights"] >= 0
    assert data["rebate_tier"] in ["TIER_0", "TIER_1", "TIER_2", "TIER_3"]
    assert isinstance(data["estimated_rebate_cents"], int) and data["estimated_rebate_cents"] >= 0


def assert_booking(data: dict):
    _assert_common(data, "RoomBooking")
    assert data["status"] in ["RESERVED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["room_nights"], int) and data["room_nights"] >= 1
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] >= 1
    assert isinstance(data["total_charge_cents"], int)
    assert data["total_charge_cents"] == data["room_nights"] * data["rate_cents"], (
        f"total_charge_cents {data['total_charge_cents']} != room_nights {data['room_nights']} * rate_cents {data['rate_cents']}"
    )


def assert_division(data: dict):
    _assert_common(data, "Division")
    assert data["status"] in ["OPEN", "SEEDING_LOCKED", "BRACKET_PUBLISHED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["entered_team_count"], int) and data["entered_team_count"] >= 0
    assert isinstance(data["eligible_team_count"], int) and data["eligible_team_count"] >= 0


def assert_team(data: dict):
    _assert_common(data, "Team")
    assert data["status"] in [
        "ENTERED", "WAITLISTED", "ROSTER_SUBMITTED", "ELIGIBLE", "CHECKED_IN",
        "ELIMINATED", "FINISHED", "CHAMPION", "WITHDRAWN", "DISQUALIFIED",
    ]
    assert isinstance(data["strength_rating"], int) and 1 <= data["strength_rating"] <= 100


def assert_match(data: dict):
    _assert_common(data, "Match")
    assert data["status"] in [
        "PENDING_TEAMS", "SCHEDULED", "WEATHER_DELAYED", "RESCHEDULE_QUEUE",
        "IN_PROGRESS", "FINAL", "FORFEITED", "CANCELLED",
    ]
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["bracket_slot"], int) and data["bracket_slot"] >= 1


def assert_official(data: dict):
    _assert_common(data, "Official")
    assert data["status"] in ["REGISTERED", "VETTED", "ACTIVE", "SUSPENDED", "INACTIVE"]
    assert data["certification_level"] in ["TRAINEE", "REGIONAL", "NATIONAL"]
    assert isinstance(data["assigned_game_count"], int) and data["assigned_game_count"] >= 0


def assert_assignment(data: dict):
    _assert_common(data, "OfficialAssignment")
    assert data["status"] in ["PROPOSED", "ACCEPTED", "DECLINED", "RELEASED", "WORKED"]
    assert data["slot_role"] in ["CREW_CHIEF", "ASSISTANT"]
    if data["status"] == "RELEASED":
        assert data["released_reason"] in ["WEATHER", "MANUAL", "OFFICIAL_SUSPENDED", "MATCH_CANCELLED"]
    else:
        assert data.get("released_reason") is None, (
            f"released_reason must be null on a non-RELEASED assignment, got {data.get('released_reason')!r}"
        )


def assert_volunteer(data: dict):
    _assert_common(data, "Volunteer")
    assert data["status"] in ["APPLIED", "APPROVED", "ACTIVE", "REJECTED", "INACTIVE"]
    assert isinstance(data["background_check_cleared"], bool)


def assert_shift(data: dict):
    _assert_common(data, "Shift")
    assert data["status"] in ["OPEN", "FILLED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0


def assert_signup(data: dict):
    _assert_common(data, "ShiftSignup")
    assert data["status"] in ["SIGNED_UP", "CONFIRMED", "WORKED", "NO_SHOW", "CANCELLED"]


def assert_weather_alert(data: dict):
    _assert_common(data, "WeatherAlert")
    assert data["status"] in ["ISSUED", "ACTIVE", "RESOLVED", "EXPIRED"]
    assert data["severity"] in ["WATCH", "WARNING", "EMERGENCY"]


def assert_impact_report(data: dict):
    _assert_common(data, "ImpactReport")
    assert data["status"] in ["DRAFT", "SUBMITTED", "UNDER_AUDIT", "ACCEPTED", "DISPUTED"]
    assert isinstance(data["projected_attendance"], int) and data["projected_attendance"] >= 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_settlement(data: dict):
    _assert_common(data, "Settlement")
    assert data["status"] in ["OPEN", "EXPENSES_CERTIFIED", "APPROVED", "PAID", "DISPUTED"]
    assert isinstance(data["sponsor_contributions_cents"], int) and data["sponsor_contributions_cents"] >= 0
    assert isinstance(data["expense_lines"], list)


def _parse_instant(value: str):
    """Parse an ISO 8601 UTC instant (with or without fractional digits)."""
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same moment, regardless of
    whether the server echoes fractional digits."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )
