"""Entity assertions and domain invariant checkers (PRD §2.5 common fields)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_iso(value: str) -> datetime:
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_eq(actual: str, expected: str, msg: str = ""):
    """Instant equality for domain date fields, rendering-agnostic.

    PRD §2.2/§2.5 pin three fractional digits only for api_request_timestamp and
    created_at/updated_at; domain date fields (start_date, end_date,
    filing_due_date, current_period_end) are compared as instants, not strings.
    """
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC timestamp: {actual!r}"
    a, e = _parse_iso(actual), _parse_iso(expected)
    assert a == e, msg or f"expected instant {expected}, got {actual}"

from .types import (
    SKILL_TAGS,
    AmendmentStatus,
    AppointmentStatus,
    BylawsStatus,
    CommitteeStatus,
    CommitteeType,
    CompliancePosture,
    DisclosureStatus,
    EvaluationStatus,
    FilingStatus,
    MeetingStatus,
    MemberStatus,
    MotionCategory,
    MotionStatus,
    OfficerRole,
    PlanStatus,
    PolicyStatus,
    Rating,
    RegistrationStatus,
    TermStatus,
    VoteChoice,
)


def _assert_common(data: dict):
    """Common resource properties shared by all primary resources (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_nonprofit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ein"], str) and data["ein"]
    assert data["fiscal_year_end_month"] in range(1, 13)
    assert isinstance(data["annual_gross_receipts_cents"], int)
    assert data["compliance_posture"] in {p.value for p in CompliancePosture}


def assert_bylaws(data: dict):
    _assert_common(data)
    assert 1 <= data["quorum_pct"] <= 100
    assert data["quorum_basis"] in ("SEATED", "AUTHORIZED")
    assert 51 <= data["amendment_threshold_pct"] <= 100
    assert 1 <= data["term_length_years"] <= 6
    assert data["max_consecutive_terms"] >= 1
    assert data["term_cooloff_years"] >= 0
    assert data["board_size"] >= 3
    assert data["status"] in {s.value for s in BylawsStatus}


def assert_amendment(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["proposed_fields"], dict) and len(data["proposed_fields"]) > 0
    assert data["status"] in {s.value for s in AmendmentStatus}


def assert_board_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["skill_tags"], list)
    assert all(tag in SKILL_TAGS for tag in data["skill_tags"])
    assert data["officer_role"] in {r.value for r in OfficerRole}
    assert data["status"] in {s.value for s in MemberStatus}


def assert_board_term(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert data["status"] in {s.value for s in TermStatus}


def assert_committee(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["type"] in {t.value for t in CommitteeType}
    assert data["min_members"] >= 1
    assert data["authorized_size"] >= data["min_members"]
    assert data["status"] in {s.value for s in CommitteeStatus}


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["committee_role"] in ("CHAIR", "MEMBER")
    assert data["status"] in {s.value for s in AppointmentStatus}


def assert_meeting(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert data["duration_minutes"] > 0
    assert data["status"] in {s.value for s in MeetingStatus}


def assert_motion(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["category"] in {c.value for c in MotionCategory}
    assert data["status"] in {s.value for s in MotionStatus}
    for field in ("votes_for", "votes_against", "votes_abstain", "votes_recused"):
        assert isinstance(data.get(field), int) and data[field] >= 0


def assert_vote(data: dict):
    """Vote is append-only: only id + created_at from the common set (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["choice"] in {c.value for c in VoteChoice}
    assert "updated_at" not in data, "append-only vote must not carry updated_at"
    assert "version" not in data, "append-only vote must not carry version"


def assert_disclosure(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["answers"], list)
    assert data["status"] in {s.value for s in DisclosureStatus}
    assert isinstance(data["has_conflict"], bool)


def assert_evaluation(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["executive_name"], str) and data["executive_name"]
    assert data["status"] in {s.value for s in EvaluationStatus}
    if data.get("rating") is not None:
        assert data["rating"] in {r.value for r in Rating}


def assert_succession_plan(data: dict):
    _assert_common(data)
    assert data["target_role"] in ("EXECUTIVE_DIRECTOR", "BOARD_CHAIR", "TREASURER")
    assert data["readiness"] in ("READY_NOW", "ONE_YEAR", "TWO_PLUS_YEARS")
    assert data["status"] in {s.value for s in PlanStatus}


def assert_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_revenue_cents"], int)
    assert isinstance(data["total_expenses_cents"], int)
    assert isinstance(data["contributions_cents"], int)
    assert isinstance(data["program_service_revenue_cents"], int)
    assert data["status"] in {s.value for s in FilingStatus}


def assert_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in {s.value for s in RegistrationStatus}


def assert_policy(data: dict):
    _assert_common(data)
    assert data["policy_type"] in ("DNO", "GENERAL_LIABILITY")
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["premium_cents"], int)
    assert data["status"] in {s.value for s in PolicyStatus}
