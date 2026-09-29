"""Entity assertions and domain invariant checkers (PRD §2.4, §2.10)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ADOPTION_RULE_STATUSES,
    ANALYSIS_ROW_STATUSES,
    ANALYSIS_STATUSES,
    ANALYSIS_TYPES,
    ATTENDEE_ROLES,
    BALLOTS,
    CODE_CYCLE_STATUSES,
    COMMENT_POSITIONS,
    COMMENT_WINDOW_STATUSES,
    COMMITTEE_STATUSES,
    DISCIPLINES,
    ENFORCEMENT_READINESS_VALUES,
    ENROLLMENT_STATUSES,
    HEARING_STATUSES,
    INTERPRETATION_STATUSES,
    LOCAL_AMENDMENT_STATUSES,
    LOCAL_AUTHORITY_LEVELS,
    MEMBER_STATUSES,
    REVIEW_STATUSES,
    SECTORS,
    STRINGENCY_DIRECTIONS,
    TRAINING_AUDIENCES,
    TRAINING_SESSION_STATUSES,
    VOTE_OUTCOME_REASONS,
    VOTE_OUTCOMES,
)


# ---------------------------------------------------------------------------
# Common record properties (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """Every persisted record exposes id and created_at; most also expose
    updated_at and an integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer of at least 1, got {data.get('version')}"
    )


def assert_append_only_fields(data: dict):
    """PublicComment and VoteRecord expose only id and created_at; both
    updated_at and version are absent from those record types entirely."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert "updated_at" not in data, "updated_at must be absent on an append-only record"
    assert "version" not in data, "version must be absent on an append-only record"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_code_cycle(data: dict):
    assert_common_fields(data)
    assert data["status"] in CODE_CYCLE_STATUSES, f"unexpected status {data['status']}"
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["model_code_edition"], str) and data["model_code_edition"]
    for counter in (
        "seated_committee_count",
        "proposal_count",
        "approved_proposal_count",
        "approved_incremental_cost_cents",
        "approved_permit_backlog_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer, got {data[counter]}"
        )


def assert_discipline_committee(data: dict):
    assert_common_fields(data)
    assert data["discipline"] in DISCIPLINES
    assert data["status"] in COMMITTEE_STATUSES
    assert 3 <= data["voting_seat_count"] <= 12
    assert isinstance(data["active_voting_member_count"], int)
    assert isinstance(data["quorum_required"], int)
    assert isinstance(data["sector_coverage_complete"], bool)
    assert isinstance(data["chair_member_count"], int)


def assert_committee_member(data: dict):
    assert_common_fields(data)
    assert data["sector"] in SECTORS
    assert data["status"] in MEMBER_STATUSES
    assert isinstance(data["voting_seat"], bool)
    assert isinstance(data["is_chair"], bool)
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_amendment_proposal(data: dict):
    assert_common_fields(data)
    assert data["review_status"] in REVIEW_STATUSES
    assert data["analysis_status"] in ANALYSIS_STATUSES
    assert data["discipline"] in DISCIPLINES
    assert data["stringency_direction"] in STRINGENCY_DIRECTIONS
    assert data["proposer_sector"] in SECTORS
    assert data["comment_window_status"] in COMMENT_WINDOW_STATUSES
    assert isinstance(data["energy_analysis_required"], bool)
    for counter in (
        "support_comment_count",
        "oppose_comment_count",
        "total_comment_count",
        "comment_extension_count",
        "comment_round",
        "revision_round",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_impact_analysis(data: dict):
    assert_common_fields(data)
    assert data["analysis_type"] in ANALYSIS_TYPES
    assert data["status"] in ANALYSIS_ROW_STATUSES
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]


def assert_public_comment(data: dict):
    assert_append_only_fields(data)
    assert data["position"] in COMMENT_POSITIONS
    assert data["commenter_sector"] in SECTORS
    assert isinstance(data["body"], str) and data["body"]
    assert isinstance(data["comment_round"], int)
    assert is_iso8601_timestamp(data["received_at"])


def assert_hearing(data: dict):
    assert_common_fields(data)
    assert data["status"] in HEARING_STATUSES
    assert isinstance(data["agenda_proposal_ids"], list)


def assert_vote_record(data: dict):
    assert_append_only_fields(data)
    assert data["outcome"] in VOTE_OUTCOMES
    assert data["outcome_reason"] in VOTE_OUTCOME_REASONS
    for entry in data["ballots"]:
        assert entry["ballot"] in BALLOTS
    assert_vote_tally_invariants(data)


def assert_adoption_rule(data: dict):
    assert_common_fields(data)
    assert data["status"] in ADOPTION_RULE_STATUSES
    assert isinstance(data["title"], str) and data["title"]


def assert_jurisdiction(data: dict):
    assert_common_fields(data)
    assert data["local_authority_level"] in LOCAL_AUTHORITY_LEVELS
    assert data["enforcement_readiness"] in ENFORCEMENT_READINESS_VALUES
    assert data["official_headcount"] >= 1
    assert data["compliance_pct_enrollment_basis"] <= 100.00
    assert data["compliance_pct_attendance_basis"] <= 100.00


def assert_local_amendment(data: dict):
    assert_common_fields(data)
    assert data["status"] in LOCAL_AMENDMENT_STATUSES
    assert data["stringency_direction"] in STRINGENCY_DIRECTIONS
    assert isinstance(data["filed_within_window"], bool)
    assert isinstance(data["revision_round"], int)


def assert_interpretation_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in INTERPRETATION_STATUSES
    assert isinstance(data["appeal_round"], int)


def assert_training_session(data: dict):
    assert_common_fields(data)
    assert data["status"] in TRAINING_SESSION_STATUSES
    assert data["audience"] in TRAINING_AUDIENCES
    assert data["discipline"] in DISCIPLINES
    assert_session_seat_ledger(data)


def assert_training_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ENROLLMENT_STATUSES
    assert data["attendee_role"] in ATTENDEE_ROLES


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.10)
# ---------------------------------------------------------------------------
def assert_session_seat_ledger(session: dict):
    """seat_capacity equals seats_available plus enrolled_count plus
    attended_count plus no_show_count, at every instant."""
    total = (
        session["seats_available"]
        + session["enrolled_count"]
        + session["attended_count"]
        + session["no_show_count"]
    )
    assert session["seat_capacity"] == total, (
        f"seat ledger broken: seat_capacity {session['seat_capacity']} != "
        f"{session['seats_available']} + {session['enrolled_count']} + "
        f"{session['attended_count']} + {session['no_show_count']}"
    )


def assert_cycle_cost_ledger(cycle: dict, approved_proposals: list):
    """The cycle cost ledger sums the certified figures of exactly the cycle's
    APPROVED proposals."""
    expected_cost = sum(
        p["statewide_incremental_cost_cents"] or 0 for p in approved_proposals
    )
    expected_backlog = sum(p["affected_permit_count"] or 0 for p in approved_proposals)
    assert cycle["approved_proposal_count"] == len(approved_proposals), (
        f"approved_proposal_count {cycle['approved_proposal_count']} != "
        f"{len(approved_proposals)}"
    )
    assert cycle["approved_incremental_cost_cents"] == expected_cost, (
        f"approved_incremental_cost_cents {cycle['approved_incremental_cost_cents']} "
        f"!= {expected_cost}"
    )
    assert cycle["approved_permit_backlog_count"] == expected_backlog, (
        f"approved_permit_backlog_count {cycle['approved_permit_backlog_count']} != "
        f"{expected_backlog}"
    )


def assert_vote_tally_invariants(vote: dict):
    """absent_count is voting_seats_at_call less the cast total."""
    cast = vote["yes_count"] + vote["no_count"] + vote["abstain_count"]
    assert vote["absent_count"] == vote["voting_seats_at_call"] - cast, (
        f"absent_count {vote['absent_count']} != voting_seats_at_call "
        f"{vote['voting_seats_at_call']} - cast {cast}"
    )
    assert vote["yes_count"] + vote["no_count"] + vote["abstain_count"] >= vote[
        "quorum_required"
    ], "a vote record may only exist when the cast total met quorum"


def assert_money_is_integer_cents(value):
    """Money is carried as integer cents throughout; no money value is ever
    rounded and there is no floating-point currency anywhere in the system."""
    assert value is None or isinstance(value, int), (
        f"money must be integer cents, got {value!r}"
    )
