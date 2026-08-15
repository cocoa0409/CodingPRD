"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_iso_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting the trailing 'Z' form."""
    assert isinstance(value, str) and value, f"expected ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a prefix-less UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    else:
        assert "updated_at" not in data, f"{entity} is an immutable event row and must not carry updated_at"
        assert "version" not in data, f"{entity} is an immutable event row and must not carry version"


def assert_season(data: dict):
    _assert_common(data, "Season")
    assert data["status"] in ["REGISTRATION", "ACTIVE", "FINALIZING", "COMPLETED"]
    assert isinstance(data["regular_due_cents"], int) and data["regular_due_cents"] > 0
    assert isinstance(data["late_due_cents"], int)
    assert isinstance(data["travel_base_cents"], int)


def assert_club(data: dict):
    _assert_common(data, "Club")
    assert data["status"] in ["GOOD_STANDING", "DELINQUENT", "SUSPENDED"]
    assert data["travel_tier"] in [1, 2, 3]
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["projected_travel_stipend_cents"], int)


def assert_coach(data: dict):
    _assert_common(data, "Coach")
    assert data["certification_level"] in ["CLUB", "CERTIFIED", "SENIOR"]
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_player(data: dict):
    _assert_common(data, "Player")
    assert data["status"] in ["ACTIVE", "INACTIVE", "SUSPENDED", "GRADUATED"]
    assert isinstance(data["rating"], int)
    assert isinstance(data["peak_rating"], int)
    assert isinstance(data["rated_games_played"], int)
    assert isinstance(data["is_provisional"], bool)
    assert isinstance(data["performance_points"], int)


def assert_membership(data: dict):
    _assert_common(data, "Membership")
    assert data["status"] in ["INVOICED", "PAID", "WAIVED", "REFUNDED"]
    assert isinstance(data["fee_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common(data, "LedgerEntry", with_version=False)
    assert data["entry_type"] in [
        "MEMBERSHIP_DUE", "ENTRY_FEE", "ENTRY_REFUND", "TRAVEL_STIPEND", "ADJUSTMENT", "REVERSAL",
    ]
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] != 0, "ledger amount_cents may never be zero"


def assert_meet(data: dict):
    _assert_common(data, "Meet")
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "PAIRINGS_PUBLISHED", "IN_PROGRESS",
        "COMPLETED", "POSTPONED", "CANCELLED",
    ]


def assert_pairing(data: dict):
    _assert_common(data, "Pairing")
    assert data["status"] in ["SCHEDULED", "REPORTED", "CONFIRMED", "DISPUTED", "REPLACED", "CANCELLED"]
    assert data["result"] in [
        "UNREPORTED", "WHITE_WIN", "BLACK_WIN", "DRAW",
        "WHITE_FORFEIT_WIN", "BLACK_FORFEIT_WIN", "DOUBLE_FORFEIT",
    ]


def assert_dispute(data: dict):
    _assert_common(data, "Dispute")
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "UPHELD", "OVERTURNED", "WITHDRAWN"]


def assert_tournament(data: dict):
    _assert_common(data, "Tournament")
    assert data["status"] in [
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "RUNNING", "COMPLETED", "CANCELLED",
    ]


def assert_section(data: dict):
    _assert_common(data, "TournamentSection")
    assert data["status"] in ["OPEN", "LOCKED", "CLOSED"]
    assert isinstance(data["current_entries"], int)


def assert_entry(data: dict):
    _assert_common(data, "TournamentEntry")
    assert data["status"] in ["REGISTERED", "CHECKED_IN", "FINISHED", "WITHDRAWN"]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["refund_cents"], int)


def assert_proctor_assignment(data: dict):
    _assert_common(data, "ProctorAssignment")
    assert data["event_type"] in ["MEET", "TOURNAMENT"]
    assert data["status"] in ["ASSIGNED", "CONFIRMED", "RELEASED", "COMPLETED", "NO_SHOW"]


def assert_bid(data: dict):
    _assert_common(data, "QualificationBid")
    assert data["bid_type"] in ["INDIVIDUAL_STATE", "TEAM_STATE", "NATIONAL"]
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"]


def assert_rating_event(data: dict):
    _assert_common(data, "RatingEvent", with_version=False)
    assert data["formula_variant"] in ["PROVISIONAL", "ESTABLISHED"]
    assert data["status"] in ["EFFECTIVE", "VOIDED"]
    assert data["score"] in (1, 0.5, 0)
    assert isinstance(data["rating_before"], int)
    assert isinstance(data["rating_after"], int)


def assert_standing_row(data: dict):
    """A live standings row or snapshot carries the pinned metric fields (PRD §3.9)."""
    assert isinstance(data.get("match_points"), (int, float))
    assert isinstance(data.get("game_points"), (int, float))
    assert isinstance(data.get("sonneborn_berger"), (int, float))
    assert isinstance(data.get("forfeit_losses"), int)
    assert is_valid_uuid(data.get("club_id", "")), "standings row must name its club_id"


def assert_stipend(data: dict):
    _assert_common(data, "TravelStipend")
    assert isinstance(data["meets_counted"], int)
    assert isinstance(data["amount_cents"], int)
