"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. The common-field assertions (UUID id,
ISO 8601 created_at/updated_at, integer version) apply to every resource per
the PRD common-resource-properties section.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_event(data: dict):
    _assert_common_fields(data, "Event")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert data["status"] in [
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "SCHEDULED",
        "LIVE", "FINALIZED",
    ]


def assert_division(data: dict):
    _assert_common_fields(data, "Division")
    assert data["category"] in ["CHEER", "DANCE"]
    assert isinstance(data["level"], int) and 1 <= data["level"] <= 6
    assert isinstance(data["min_age"], int) and isinstance(data["max_age"], int)
    assert data["max_age"] >= data["min_age"]
    assert isinstance(data["min_athletes"], int)
    assert isinstance(data["max_athletes"], int)
    assert data["max_athletes"] >= data["min_athletes"]
    assert isinstance(data["routine_time_limit_seconds"], int)
    assert isinstance(data["warmup_duration_seconds"], int)
    assert isinstance(data["warmup_mats"], list)
    assert isinstance(data["judge_ids"], list) and 3 <= len(data["judge_ids"]) <= 9
    assert isinstance(data["paid_bid_count"], int)
    assert isinstance(data["at_large_bid_count"], int)
    assert isinstance(data["bid_pool_available"], int)
    assert isinstance(data["scheduled"], bool)


def assert_team(data: dict):
    _assert_common_fields(data, "Team")
    assert data["category"] in ["CHEER", "DANCE"]
    assert isinstance(data["level"], int) and 1 <= data["level"] <= 6
    assert isinstance(data["coach_user_id"], str) and data["coach_user_id"]
    assert data["reg_status"] in [
        "REGISTERED", "ROSTER_LOCKED", "CHECKED_IN", "COMPETED",
        "WITHDRAWN", "DISQUALIFIED",
    ]
    assert data["music_status"] in ["PENDING", "SUBMITTED", "VERIFIED", "FLAGGED"]


def assert_athlete(data: dict):
    _assert_common_fields(data, "Athlete")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]


def assert_roster_entry(data: dict):
    _assert_common_fields(data, "RosterEntry")
    assert is_valid_uuid(data.get("team_id", ""))
    assert is_valid_uuid(data.get("athlete_id", ""))
    assert isinstance(data["bib_number"], int)
    assert data["eligibility_status"] in ["ACTIVE", "INELIGIBLE"]
    assert isinstance(data["checked_in"], bool)
    assert isinstance(data["removed"], bool)


def assert_judge(data: dict):
    _assert_common_fields(data, "Judge")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certified_levels"], list)
    for level in data["certified_levels"]:
        assert isinstance(level, int) and 1 <= level <= 6


def assert_performance(data: dict):
    _assert_common_fields(data, "Performance")
    assert is_valid_uuid(data.get("team_id", ""))
    assert is_valid_uuid(data.get("division_id", ""))
    assert isinstance(data["performance_order"], int) and data["performance_order"] >= 1
    assert data["status"] in [
        "SCHEDULED", "PERFORMED", "SCORED", "OFFICIAL", "EXCLUDED", "CANCELLED",
    ]
    assert "provisional_score" in data, "provisional_score field must be present"
    assert "official_score" in data, "official_score field must be present"
    assert "rank_in_division" in data, "rank_in_division field must be present"


def assert_score_sheet(data: dict):
    _assert_common_fields(data, "ScoreSheet")
    assert is_valid_uuid(data.get("performance_id", ""))
    assert isinstance(data.get("judge_id"), str) and data["judge_id"]
    for field in ("building_difficulty", "building_execution",
                  "tumbling_difficulty", "overall_impression"):
        assert 0 <= data[field] <= 10, f"{field} must be within 0..10"
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED"]


def assert_deduction(data: dict):
    _assert_common_fields(data, "Deduction")
    assert is_valid_uuid(data.get("performance_id", ""))
    assert data["type"] in ["SAFETY", "TIME", "BOUNDARY"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["rate_applied"], (int, float))
    assert isinstance(data["points"], (int, float))
    assert data["source"] in ["SYSTEM", "MANUAL"]
    assert data["status"] in [
        "APPLIED", "UNDER_APPEAL", "UPHELD", "OVERTURNED", "VOIDED",
    ]
    assert "applied_by_judge_id" in data


def assert_appeal(data: dict):
    _assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data.get("deduction_id", ""))
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]
    assert "decided_by_judge_id" in data


def assert_bid(data: dict):
    _assert_common_fields(data, "Bid")
    assert is_valid_uuid(data.get("division_id", ""))
    assert is_valid_uuid(data.get("team_id", ""))
    assert data["kind"] in ["PAID", "AT_LARGE"]
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED"]
    assert isinstance(data["rank_at_offer"], int)
    assert is_iso8601_timestamp(data.get("offered_at", ""))
    assert is_iso8601_timestamp(data.get("acceptance_deadline", ""))


def assert_music_submission(data: dict):
    _assert_common_fields(data, "MusicSubmission")
    assert is_valid_uuid(data.get("team_id", ""))
    assert isinstance(data["track_count"], int) and data["track_count"] >= 1
    assert isinstance(data["license_provider"], str)
    assert isinstance(data["license_reference"], str)
    assert data["status"] in ["SUBMITTED", "VERIFIED", "FLAGGED", "SUPERSEDED"]


def assert_session(data: dict):
    _assert_common_fields(data, "Session")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["seats_held"], int) and data["seats_held"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert isinstance(data["seats_available"], int)


def assert_ticket_order(data: dict):
    _assert_common_fields(data, "TicketOrder")
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data["purchaser_user_id"], str) and data["purchaser_user_id"]
    assert isinstance(data["quantity"], int) and 1 <= data["quantity"] <= 40
    assert data["tier"] in ["ADVANCE", "GATE"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["HELD", "PAID", "CANCELLED", "REFUNDED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("hold_expires_at", ""))


def assert_warm_up_assignment(data: dict):
    _assert_common_fields(data, "WarmUpAssignment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("team_id", ""))
    assert isinstance(data["mat"], str) and data["mat"]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["source"] in ["SYSTEM", "MANUAL"]
    assert data["status"] in ["BOOKED", "RELEASED"]


def assert_session_seat_invariant(session: dict):
    """The compensating seat invariant must hold at every moment."""
    assert session["seats_available"] + session["seats_held"] + session["seats_sold"] \
        == session["capacity"], (
            f"seat invariant broken: {session['seats_available']} + "
            f"{session['seats_held']} + {session['seats_sold']} != "
            f"{session['capacity']}"
        )


def assert_bid_pool_invariant(division: dict, bids: list):
    """Bid pool conservation: OFFERED + ACCEPTED + pool == paid + at_large."""
    outstanding = sum(1 for b in bids if b["status"] in ("OFFERED", "ACCEPTED"))
    expected = division["paid_bid_count"] + division["at_large_bid_count"]
    assert outstanding + division["bid_pool_available"] == expected, (
        f"bid pool invariant broken: outstanding {outstanding} + "
        f"pool {division['bid_pool_available']} != {expected}"
    )
