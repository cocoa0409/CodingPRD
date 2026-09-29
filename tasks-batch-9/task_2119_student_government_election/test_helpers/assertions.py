"""Entity assertions and the two ledger conservation checkers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppealStatus,
    BallotIntegrityStatus,
    BallotLineStatus,
    BallotLineType,
    BallotStatus,
    CandidacyStatus,
    CaseSeverity,
    CaseStatus,
    ClassYear,
    DraftingStatus,
    ElectionStatus,
    EligibilityResult,
    EnrollmentStatus,
    ExpenseCategory,
    ExpenseStatus,
    OfficeStatus,
    OutcomeStatus,
    RemedyRequested,
    SignatureStatus,
    TransitionStatus,
    VoteStatus,
)


# ─── Instants and percentages ─────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant at full millisecond resolution."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual, expected: str, label: str = "instant") -> None:
    """Instant comparisons are performed at full ISO 8601 millisecond resolution
    (PRD §2.7), so the trailing-millisecond spelling is irrelevant."""
    assert actual is not None, f"{label} must be present, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_stamped_timestamp(value: str, label: str = "timestamp") -> None:
    """Server-stamped timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"
    assert value.endswith("Z"), f"{label} must be UTC and end with Z, got {value!r}"
    assert "." in value and len(value.split(".")[1]) == 4, (
        f"{label} must carry three fractional digits, got {value!r}"
    )


def assert_pct(actual, expected: float, label: str = "percentage") -> None:
    """Percentages are numbers rounded half up to exactly two decimal places and
    are returned as JSON numbers rather than strings (PRD §2.7)."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict, entity: str) -> None:
    """`id`, `created_at`, `updated_at` and `version` are carried by every
    resource in this system (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a server-minted UUID with no prefix, got {data.get('id')!r}"
    )
    assert_stamped_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_stamped_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# ─── Per-entity assertions ────────────────────────────────────────────────────

def assert_election(data: dict) -> None:
    assert_common_fields(data, "Election")
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert isinstance(data["academic_year"], str)
    assert data["status"] in _enum_values(ElectionStatus)
    assert isinstance(data["current_round"], int) and data["current_round"] >= 1
    assert data["petition_deadline"] is not None
    assert isinstance(data["quiet_period_hours"], int) and data["quiet_period_hours"] >= 0
    assert isinstance(data["spending_cap_cents"], int) and data["spending_cap_cents"] >= 0
    assert isinstance(data["poster_cap"], int) and data["poster_cap"] >= 0
    assert 0.0 <= data["quorum_pct"] <= 100.0
    assert 0.0 <= data["runoff_threshold_pct"] <= 100.0
    assert isinstance(data["eligible_voter_count"], int) and data["eligible_voter_count"] >= 0
    assert isinstance(data["ballots_cast_count"], int) and data["ballots_cast_count"] >= 0
    assert 0.0 <= data["turnout_pct"] <= 100.0
    assert isinstance(data["runoff_required_office_count"], int)
    assert data["ballot_integrity_status"] in _enum_values(BallotIntegrityStatus)


def assert_office(data: dict) -> None:
    assert_common_fields(data, "Office")
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["eligible_class_years"], list) and data["eligible_class_years"]
    for year in data["eligible_class_years"]:
        assert year in _enum_values(ClassYear), f"unknown class year {year!r}"
    assert isinstance(data["required_signature_count"], int)
    assert 0.0 <= data["min_gpa"] <= 4.0
    assert isinstance(data["min_credits"], int) and data["min_credits"] >= 0
    assert isinstance(data["required_training_modules"], int)
    assert data["term_start_date"] is not None and data["term_end_date"] is not None
    assert data["status"] in _enum_values(OfficeStatus)
    assert isinstance(data["filled_seat_count"], int) and data["filled_seat_count"] >= 0
    assert isinstance(data["valid_votes_count"], int) and data["valid_votes_count"] >= 0
    assert isinstance(data["abstain_votes_count"], int) and data["abstain_votes_count"] >= 0
    assert isinstance(data["invalidated_votes_count"], int)


def assert_student(data: dict) -> None:
    assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["student_number"], str) and 1 <= len(data["student_number"]) <= 32
    assert data["class_year"] in _enum_values(ClassYear)
    assert data["enrollment_status"] in _enum_values(EnrollmentStatus)
    assert 0.0 <= data["gpa"] <= 4.0
    assert isinstance(data["credits_completed"], int) and data["credits_completed"] >= 0
    assert isinstance(data["disciplinary_hold"], bool)


def assert_candidacy(data: dict) -> None:
    assert_common_fields(data, "Candidacy")
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["office_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in _enum_values(CandidacyStatus)
    assert data["transition_status"] in _enum_values(TransitionStatus)
    assert isinstance(data["training_modules_completed"], int)
    for counter in (
        "petition_signature_total_count",
        "petition_signature_valid_count",
        "petition_signature_ineligible_count",
        "petition_signature_pending_count",
        "petition_signature_rejected_count",
        "petition_signature_voided_count",
        "spending_reported_cents",
        "spending_committed_cents",
        "spending_reversed_cents",
        "poster_count",
        "penalty_points_total",
        "raw_votes_count",
        "certified_votes_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Candidacy.{counter} must be a non-negative integer, got {data[counter]!r}"
        )
    assert isinstance(data["slate_snapshot_member_ids"], list)
    assert 0.0 <= data["provisional_share_pct"] <= 100.0
    assert 0.0 <= data["certified_share_pct"] <= 100.0


def assert_petition_signature(data: dict) -> None:
    assert_common_fields(data, "PetitionSignature")
    assert is_valid_uuid(data["candidacy_id"])
    assert is_valid_uuid(data["signer_student_id"])
    assert data["signed_at"] is not None
    assert data["status"] in _enum_values(SignatureStatus)
    assert data["eligibility_result"] in _enum_values(EligibilityResult)


def assert_campaign_expense(data: dict) -> None:
    assert_common_fields(data, "CampaignExpense")
    assert is_valid_uuid(data["candidacy_id"])
    assert data["category"] in _enum_values(ExpenseCategory)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert isinstance(data["shared_with_slate"], bool)
    assert data["incurred_at"] is not None
    assert data["status"] in _enum_values(ExpenseStatus)


def assert_compliance_case(data: dict) -> None:
    assert_common_fields(data, "ComplianceCase")
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["candidacy_id"])
    assert isinstance(data["rule_code"], str) and data["rule_code"]
    assert data["severity"] in _enum_values(CaseSeverity)
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in _enum_values(CaseStatus)
    assert isinstance(data["penalty_points"], int) and data["penalty_points"] >= 0
    assert isinstance(data["prior_upheld_count"], int) and data["prior_upheld_count"] >= 0
    assert isinstance(data["timing_factor_applied"], (int, float))
    assert isinstance(data["overspend_points_applied"], int)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]


def assert_referendum(data: dict) -> None:
    assert_common_fields(data, "Referendum")
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["article_reference"], str) and data["article_reference"]
    assert isinstance(data["body_text"], str) and data["body_text"]
    assert 0.0 <= data["approval_threshold_pct"] <= 100.0
    assert data["drafting_status"] in _enum_values(DraftingStatus)
    assert data["outcome_status"] in _enum_values(OutcomeStatus)
    for counter in ("yes_votes_count", "no_votes_count", "abstain_votes_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert 0.0 <= data["approval_pct"] <= 100.0


def assert_ballot(data: dict) -> None:
    assert_common_fields(data, "Ballot")
    assert is_valid_uuid(data["election_id"])
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert data["status"] in _enum_values(BallotStatus)
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["active_line_count"], int) and data["active_line_count"] >= 0
    assert data["active_line_count"] <= data["line_count"], (
        "Ballot.active_line_count may never exceed Ballot.line_count"
    )


def assert_ballot_line(data: dict) -> None:
    assert_common_fields(data, "BallotLine")
    assert is_valid_uuid(data["ballot_id"])
    assert data["line_type"] in _enum_values(BallotLineType)
    assert data["status"] in _enum_values(BallotLineStatus)
    assert isinstance(data["position"], int) and data["position"] >= 1, (
        f"BallotLine.position is 1-based, got {data.get('position')!r}"
    )
    if data["line_type"] == BallotLineType.CANDIDATE.value:
        assert data["office_id"] and data["candidacy_id"], (
            "a CANDIDATE line supplies both office_id and candidacy_id"
        )
        assert data["referendum_id"] is None, "a CANDIDATE line omits referendum_id"
    else:
        assert data["referendum_id"], "a REFERENDUM line supplies referendum_id"
        assert data["office_id"] is None and data["candidacy_id"] is None, (
            "a REFERENDUM line omits both office_id and candidacy_id"
        )


def assert_vote(data: dict) -> None:
    assert_common_fields(data, "Vote")
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["ballot_id"])
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert isinstance(data["selections"], list)
    assert data["status"] in _enum_values(VoteStatus)
    assert_stamped_timestamp(data["cast_at"], "Vote.cast_at")


def assert_appeal(data: dict) -> None:
    assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data["election_id"])
    assert is_valid_uuid(data["candidacy_id"])
    assert isinstance(data["grounds"], str) and data["grounds"]
    assert data["remedy_requested"] in _enum_values(RemedyRequested)
    assert data["status"] in _enum_values(AppealStatus)
    assert_stamped_timestamp(data["filed_at"], "Appeal.filed_at")


# ─── Ledger conservation (PRD §2.9) ───────────────────────────────────────────

def assert_petition_ledger_conserved(candidacy: dict) -> None:
    """For every candidacy, the sum of the five signature sub-counters always
    equals `petition_signature_total_count`."""
    parts = (
        candidacy["petition_signature_valid_count"]
        + candidacy["petition_signature_ineligible_count"]
        + candidacy["petition_signature_pending_count"]
        + candidacy["petition_signature_rejected_count"]
        + candidacy["petition_signature_voided_count"]
    )
    assert parts == candidacy["petition_signature_total_count"], (
        "petition ledger drift: valid+ineligible+pending+rejected+voided "
        f"= {parts} but petition_signature_total_count "
        f"= {candidacy['petition_signature_total_count']}"
    )


def assert_spend_ledger_conserved(candidacy: dict, own_active_cents: int) -> None:
    """`spending_reported_cents` equals the sum of `amount_cents` over every one
    of that candidacy's expense rows in any status whatsoever, and the sum of
    that candidacy's own reported-or-approved amounts plus
    `spending_reversed_cents` also equals `spending_reported_cents`."""
    assert own_active_cents + candidacy["spending_reversed_cents"] == candidacy[
        "spending_reported_cents"
    ], (
        "campaign-spend ledger drift: own reported-or-approved "
        f"{own_active_cents} + reversed {candidacy['spending_reversed_cents']} "
        f"!= reported {candidacy['spending_reported_cents']}"
    )
