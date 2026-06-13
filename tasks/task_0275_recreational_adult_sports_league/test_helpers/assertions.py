"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    SeasonStatus, SkillTier, StandingsTiebreaker, TeamStatus, RosterEntryState,
    RefereeAssignmentRole, RefereeAssignmentState, GameScheduleStatus,
    GameScoreStatus, GameStage, PlayerSuspensionStatus, PaymentKind,
    PaymentReason, ConductSeverity, ConductReportStatus, Sport,
)

_SEASON_STATES = [s.value for s in SeasonStatus]
_TEAM_STATES = [s.value for s in TeamStatus]
_GAME_SCHED = [s.value for s in GameScheduleStatus]
_GAME_SCORE = [s.value for s in GameScoreStatus]
_SUSP = [s.value for s in PlayerSuspensionStatus]
_REPORT_STATES = [s.value for s in ConductReportStatus]


def assert_season(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Season.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Season.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Season.updated_at must be ISO 8601"
    assert data["sport"] in [s.value for s in Sport], f"bad sport {data['sport']}"
    assert data["registration_status"] in _SEASON_STATES, f"bad status {data['registration_status']}"
    assert isinstance(data["refund_partial_pct"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_division(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Division.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Division.created_at must be ISO 8601"
    assert data["skill_tier"] in [s.value for s in SkillTier], f"bad skill_tier {data['skill_tier']}"
    assert data["standings_tiebreaker"] in [s.value for s in StandingsTiebreaker]
    assert isinstance(data["confirmed_team_count"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_team(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Team.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Team.created_at must be ISO 8601"
    assert data["status"] in _TEAM_STATES, f"bad team status {data['status']}"
    for f in ("roster_size", "fee_charged_cents", "refund_issued_cents",
              "wins", "losses", "draws", "points", "points_for", "points_against"):
        assert isinstance(data[f], int), f"Team.{f} must be int"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_player(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Player.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Player.created_at must be ISO 8601"
    assert isinstance(data["is_free_agent"], bool)
    assert isinstance(data["conduct_points"], int)
    assert data["suspension_status"] in _SUSP, f"bad suspension_status {data['suspension_status']}"
    assert isinstance(data["suspended_until_game_index"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_roster_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RosterEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "RosterEntry.created_at must be ISO 8601"
    assert data["state"] in [s.value for s in RosterEntryState]
    assert isinstance(data["is_captain"], bool)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Venue.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Venue.created_at must be ISO 8601"
    assert isinstance(data["field_count"], int) and data["field_count"] >= 1
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_referee(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Referee.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Referee.created_at must be ISO 8601"
    assert isinstance(data["certified_sports"], list)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_game(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Game.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Game.created_at must be ISO 8601"
    assert data["schedule_status"] in _GAME_SCHED, f"bad schedule_status {data['schedule_status']}"
    assert data["score_status"] in _GAME_SCORE, f"bad score_status {data['score_status']}"
    assert data["stage"] in [s.value for s in GameStage]
    assert isinstance(data["field_index"], int)
    assert isinstance(data["round_index"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_referee_assignment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "RefereeAssignment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "RefereeAssignment.created_at must be ISO 8601"
    assert data["role"] in [s.value for s in RefereeAssignmentRole]
    assert data["state"] in [s.value for s in RefereeAssignmentState]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_payment(data: dict):
    """Payment is an append-only ledger row: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "Payment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Payment.created_at must be ISO 8601"
    assert data["kind"] in [k.value for k in PaymentKind], f"bad kind {data['kind']}"
    assert data["status"] == "CAPTURED", "Payment.status must always be CAPTURED"
    assert data["reason"] in [r.value for r in PaymentReason], f"bad reason {data['reason']}"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert "version" not in data, "Payment is append-only: it must not carry a version field"
    assert "updated_at" not in data, "Payment is append-only: it must not carry an updated_at field"


def assert_conduct_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ConductReport.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ConductReport.created_at must be ISO 8601"
    assert data["severity"] in [s.value for s in ConductSeverity]
    assert data["status"] in _REPORT_STATES, f"bad report status {data['status']}"
    assert isinstance(data["points"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_refund_within_fee_bound(team: dict):
    """PRD §2.9 fiscal invariant: total refunds never exceed captured fee."""
    assert team["refund_issued_cents"] <= team["fee_charged_cents"], (
        f"refund_issued_cents {team['refund_issued_cents']} exceeds "
        f"fee_charged_cents {team['fee_charged_cents']}"
    )


def find_payment(payments: list, kind: str = None, reason: str = None):
    """Return the first payment row matching the given kind and/or reason, else None."""
    for p in payments:
        if kind is not None and p.get("kind") != kind:
            continue
        if reason is not None and p.get("reason") != reason:
            continue
        return p
    return None
