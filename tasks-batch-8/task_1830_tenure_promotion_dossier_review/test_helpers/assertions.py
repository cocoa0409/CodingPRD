"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
import re
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating optional fractional seconds."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_date_eq(actual, expected_date: str, label: str = "date"):
    """Assert a date/datetime field falls on the expected calendar day.

    The PRD pins day-level outcomes (e.g. mandatory_review_date arithmetic);
    the wire serialization (bare date vs midnight timestamp) is left open.
    """
    assert actual is not None, f"{label}: expected {expected_date}, got null"
    actual_str = str(actual)
    assert _DATE_RE.match(actual_str), f"{label}: not an ISO date/timestamp: {actual_str!r}"
    assert actual_str[:10] == expected_date, (
        f"{label}: expected day {expected_date}, got {actual_str[:10]}"
    )


def assert_instant_eq(actual, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 instants denote the same moment (format-agnostic)."""
    assert actual is not None, f"{label}: expected {expected_iso}, got null"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_decimal_eq(actual, expected: float, label: str = "value"):
    """Assert a PRD decimal value (4-dp round-half-up results) matches."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert float(actual) == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_common_fields(data: dict, label: str = "entity"):
    """PRD §2.5: id is a bare UUID; created_at/updated_at ISO 8601; version int."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_candidate(data: dict):
    assert_common_fields(data, "Candidate")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["department"], str) and data["department"]
    assert isinstance(data["college"], str) and data["college"]
    assert data["status"] in ["ACTIVE", "TENURED", "NOT_RENEWED", "WITHDRAWN"]


def assert_case(data: dict):
    assert_common_fields(data, "TenureCase")
    assert is_valid_uuid(data.get("candidate_id", "")), "TenureCase.candidate_id must be a UUID"
    assert data["target_rank"] in ["ASSOCIATE_PROFESSOR", "FULL_PROFESSOR"]
    assert isinstance(data["seeking_tenure"], bool)
    assert data["clock_policy"] in ["ANNIVERSARY", "DAY_COUNT"]
    assert isinstance(data["waiver_signed"], bool)
    assert data["stage"] in [
        "DOSSIER_ASSEMBLY", "EXTERNAL_REVIEW", "DEPT_COMMITTEE", "COLLEGE_COMMITTEE",
        "UNIVERSITY_COMMITTEE", "PROVOST_REVIEW", "DECIDED", "NOTIFIED", "CLOSED",
        "ARCHIVED", "PURGED", "RETURNED_FOR_REVISION", "WITHDRAWN",
    ]
    assert isinstance(data["extension_days"], int)
    assert data["extension_days"] >= 0


def assert_dossier_item(data: dict):
    assert_common_fields(data, "DossierItem")
    assert data["category"] in ["TEACHING", "RESEARCH", "SERVICE"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["is_peer_reviewed"], bool)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RETURNED", "SUPERSEDED", "WITHDRAWN"]


def assert_reviewer(data: dict):
    assert_common_fields(data, "ExternalReviewer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["institution"], str) and data["institution"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["expertise_area"], str) and data["expertise_area"]


def assert_invitation(data: dict):
    assert_common_fields(data, "ReviewerInvitation")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("reviewer_id", ""))
    assert isinstance(data["is_arm_length"], bool)
    assert isinstance(data["declared_coauthor"], bool)
    assert data["status"] in [
        "SOLICITED", "ACCEPTED", "LETTER_RECEIVED", "DECLINED", "WITHDRAWN", "EXPIRED",
    ]


def assert_committee(data: dict):
    assert_common_fields(data, "Committee")
    assert data["level"] in ["DEPARTMENT", "COLLEGE", "UNIVERSITY"]
    assert isinstance(data["academic_unit"], str) and data["academic_unit"]
    assert data["pass_rule"] in ["STRICT_MAJORITY_OF_CAST", "SUPERMAJORITY_OF_ENTITLED"]


def assert_member(data: dict):
    assert_common_fields(data, "CommitteeMember")
    assert is_valid_uuid(data.get("committee_id", ""))
    assert data["role_in_committee"] in ["MEMBER", "CHAIR"]
    assert isinstance(data["is_active"], bool)


def assert_round(data: dict):
    assert_common_fields(data, "ReviewRound")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("committee_id", ""))
    assert data["level"] in ["DEPARTMENT", "COLLEGE", "UNIVERSITY"]
    assert data["status"] in ["SCHEDULED", "VOTING_OPEN", "TALLYING", "COMPLETED", "CANCELLED"]


def assert_vote(data: dict):
    assert_common_fields(data, "Vote")
    assert is_valid_uuid(data.get("round_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["ballot"] in ["YES", "NO", "ABSTAIN", "RECUSE"]
    assert data["status"] in ["CAST", "RETRACTED"]


def assert_clock_extension(data: dict):
    assert_common_fields(data, "ClockExtensionRequest")
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["reason"] in ["PARENTAL_LEAVE", "MEDICAL_LEAVE", "BEREAVEMENT", "OTHER"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED", "RESCINDED", "CANCELLED"]


def assert_midterm_review(data: dict):
    assert_common_fields(data, "MidTenureReview")
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["review_year"], int) and data["review_year"] >= 1
    assert data["status"] in ["IN_PROGRESS", "COMPLETED"]


def assert_decision(data: dict):
    assert_common_fields(data, "ProvostDecision")
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["decision"] in [
        "GRANT_TENURE", "GRANT_PROMOTION", "GRANT_BOTH", "DENY", "DEFER",
    ]
    assert data["status"] in ["RECORDED", "VOIDED"]


def assert_appeal(data: dict):
    assert_common_fields(data, "Appeal")
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["grounds"] in [
        "PROCEDURAL_ERROR", "NEW_EVIDENCE", "DISCRIMINATION", "CAPRICIOUS_EVALUATION",
    ]
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "UPHELD", "DENIED", "REMANDED", "WITHDRAWN",
    ]


def assert_round_tally_invariants(data: dict):
    """PRD §2.9/§3.5: electorate arithmetic must stay consistent on a round."""
    if data.get("active_member_count") is not None and data.get("recusal_count") is not None:
        assert data["eligible_voter_count"] == (
            data["active_member_count"] - data["recusal_count"]
        ), "eligible_voter_count must equal active_member_count minus recusal_count"
    if data.get("votes_cast") is not None:
        assert data["votes_cast"] == (
            data.get("yes_count", 0) + data.get("no_count", 0) + data.get("abstain_count", 0)
        ), "votes_cast must equal yes + no + abstain counts"
