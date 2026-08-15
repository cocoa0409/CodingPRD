"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_iso8601_instant_equal(actual: str, expected: str):
    """Two ISO 8601 strings denote the same instant (serialization-agnostic)."""
    assert parse_iso8601(actual) == parse_iso8601(expected), (
        f"expected instant {expected}, got {actual}")


def assert_logical_clock_instant(actual: str, expected_iso: str):
    """A recorded logical timestamp equals the logical clock instant."""
    assert_iso8601_instant_equal(actual, expected_iso)


def _assert_common_fields(data: dict):
    """PRD §2.4: id is a prefix-free UUID; created_at/updated_at are ISO 8601
    with three fractional digits; version is an integer starting at 1."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


_REGIONS = ["NA", "EU", "APAC", "LATAM"]


def assert_tournament(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["game_title"], str) and data["game_title"]
    assert data["region"] in _REGIONS
    assert isinstance(data["prize_pool_target_cents"], int)
    assert isinstance(data["funded_pool_cents"], int)
    assert data["funded_pool_cents"] >= 0
    assert isinstance(data["roster_size"], int)
    assert isinstance(data["max_roster_size"], int)
    assert data["max_roster_size"] >= data["roster_size"]
    assert isinstance(data["registration_opens_at"], str)
    assert isinstance(data["registration_closes_at"], str)
    assert isinstance(data["minor_curfew_local"], str)
    assert data["status"] in [
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_LOCKED", "SEEDED",
        "IN_PROGRESS", "COMPLETED", "PAYOUTS_FINALIZED", "CANCELLED",
    ]
    assert isinstance(data["bracket_version"], int)
    assert data["bracket_version"] >= 0
    assert isinstance(data["placements_assigned"], bool)


def assert_player(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["handle"], str) and data["handle"]
    assert isinstance(data["date_of_birth"], str)
    datetime.strptime(data["date_of_birth"], "%Y-%m-%d")
    assert data["region"] in _REGIONS
    assert data["eligibility_status"] in ["ELIGIBLE", "SUSPENDED", "BANNED"]
    assert isinstance(data["ac_strike_events"], list)
    for event in data["ac_strike_events"]:
        assert "integrity_case_id" in event
        assert is_iso8601_timestamp(event.get("issued_at", ""))
    assert isinstance(data["active_strike_count"], int)
    assert data["active_strike_count"] >= 0


def assert_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["team_name"], str) and data["team_name"]
    assert isinstance(data["manager_contact_email"], str)
    assert isinstance(data["region_rank_points"], int)
    assert isinstance(data["prior_event_points"], int)
    assert isinstance(data["qualifier_wins"], int)
    assert is_valid_uuid(data.get("captain_player_id", ""))
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "APPEALED", "LOCKED",
        "FORFEITED",
    ]
    assert isinstance(data["appeal_used"], bool)
    assert data["seed_score"] is None or isinstance(
        data["seed_score"], (int, float))
    assert data["seed_position"] is None or isinstance(
        data["seed_position"], int)
    assert data["placement"] is None or isinstance(data["placement"], int)


def assert_roster_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("player_id", ""))
    assert data["slot_role"] in ["STARTER", "SUBSTITUTE"]
    assert data["status"] in ["ACTIVE", "REMOVED", "INELIGIBLE"]
    assert data["age_at_lock_years"] is None or isinstance(
        data["age_at_lock_years"], int)
    assert data["is_minor"] is None or isinstance(data["is_minor"], bool)


def assert_server_instance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["label"], str) and data["label"]
    assert data["region"] in _REGIONS
    assert data["status"] in ["ACTIVE", "MAINTENANCE"]
    assert isinstance(data["booked_minutes"], int)
    assert data["booked_minutes"] >= 0


def assert_match(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["bracket_round"], int) and data["bracket_round"] >= 1
    assert isinstance(data["bracket_slot"], int) and data["bracket_slot"] >= 1
    assert data["next_match_id"] is None or is_valid_uuid(
        data["next_match_id"])
    for key in ("home_registration_id", "away_registration_id",
                "winner_registration_id", "forfeiting_registration_id"):
        assert data[key] is None or is_valid_uuid(data[key]), key
    assert data["server_id"] is None or is_valid_uuid(data["server_id"])
    assert data["scheduled_start_at"] is None or is_iso8601_timestamp(
        data["scheduled_start_at"])
    assert data["duration_minutes"] is None or isinstance(
        data["duration_minutes"], int)
    assert data["status"] in [
        "PENDING", "SCHEDULED", "LOBBY_OPEN", "LIVE", "PAUSED", "COMPLETED",
        "UNDER_DISPUTE", "CONFIRMED", "OVERTURNED", "FORFEIT", "CANCELLED",
    ]
    assert data["home_score"] is None or (
        isinstance(data["home_score"], int) and data["home_score"] >= 0)
    assert data["away_score"] is None or (
        isinstance(data["away_score"], int) and data["away_score"] >= 0)
    assert isinstance(data["tactical_pauses_home"], int)
    assert isinstance(data["tactical_pauses_away"], int)
    assert data["completed_at"] is None or is_iso8601_timestamp(
        data["completed_at"])
    assert data["dispute_window_closes_at"] is None or is_iso8601_timestamp(
        data["dispute_window_closes_at"])


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("match_id", ""))
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data["reason"] in [
        "RULE_VIOLATION", "SCORE_DISCREPANCY", "TECHNICAL_FAILURE", "CONDUCT",
    ]
    assert isinstance(data["details"], str)
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "CLOSED_UPHELD", "CLOSED_OVERTURNED",
        "APPEALED",
    ]
    assert isinstance(data["appeal_used"], bool)
    assert data["ruling"] is None or data["ruling"] in ["UPHELD", "OVERTURNED"]
    assert data["remedy"] is None or data["remedy"] in [
        "WINNER_FLIP", "REMATCH",
    ]


def assert_integrity_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("player_id", ""))
    assert data["match_id"] is None or is_valid_uuid(data["match_id"])
    assert isinstance(data["evidence_summary"], str)
    assert data["status"] in [
        "OPEN", "INVESTIGATING", "RESOLVED_CLEARED", "RESOLVED_VIOLATION",
    ]
    assert isinstance(data["opened_by_user_id"], str)
    assert data["resolved_by_user_id"] is None or isinstance(
        data["resolved_by_user_id"], str)
    assert isinstance(data["strike_issued"], bool)
    assert data["resolved_at"] is None or is_iso8601_timestamp(
        data["resolved_at"])


def assert_talent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert data["home_region"] in _REGIONS
    assert isinstance(data["day_rate_cents"], int)
    assert isinstance(data["cross_region"], bool)


def assert_talent_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data["stage_label"], str)
    assert is_iso8601_timestamp(data.get("shift_start_at", ""))
    assert is_iso8601_timestamp(data.get("shift_end_at", ""))
    assert data["status"] in ["TENTATIVE", "CONFIRMED", "SETTLED", "CANCELLED"]
    assert isinstance(data["fee_quote_cents"], int)
    assert data["fee_quote_cents"] >= 0
    assert data["fee_final_cents"] is None or isinstance(
        data["fee_final_cents"], int)


def assert_payout_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert is_valid_uuid(data.get("registration_id", ""))
    assert is_valid_uuid(data.get("payee_player_id", ""))
    assert isinstance(data["placement"], int)
    assert data["compute_run_mode"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["bracket_version"], int)
    assert isinstance(data["gross_amount_cents"], int)
    assert data["gross_amount_cents"] >= 0
    assert isinstance(data["withholding_cents"], int)
    assert data["withholding_cents"] >= 0
    assert isinstance(data["net_amount_cents"], int)
    assert data["net_amount_cents"] == (
        data["gross_amount_cents"] - data["withholding_cents"]), (
        "net_amount_cents must equal gross minus withholding")
    assert isinstance(data["payee_is_minor"], bool)
    assert data["doc_status"] in ["PENDING", "SUBMITTED", "VERIFIED",
                                  "REJECTED"]
    assert data["doc_type"] is None or data["doc_type"] in [
        "W9", "W8BEN", "GUARDIAN_W9",
    ]
    assert data["disbursement_status"] in ["COMPUTED", "APPROVED", "PAID",
                                           "VOID"]
    assert data["paid_at"] is None or is_iso8601_timestamp(data["paid_at"])


def assert_sponsor_deal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["sponsor_name"], str) and data["sponsor_name"]
    assert isinstance(data["contact_user_id"], str)
    assert data["rights_tier"] in ["TITLE", "PRESENTING", "SUPPORTING"]
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["content_rights"], list)
    for right in data["content_rights"]:
        assert right in ["VOD", "CLIPS", "REPLAYS", "LOGOS"]
    assert data["status"] in ["PROPOSED", "CONTRACTED", "ACTIVATED", "VOID"]
    assert data["activated_at"] is None or is_iso8601_timestamp(
        data["activated_at"])
