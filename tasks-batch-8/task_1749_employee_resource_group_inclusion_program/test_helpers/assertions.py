"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    EngagementStatus,
    EventFundingStatus,
    EventStatus,
    FundingRequestStatus,
    GroupStatus,
    MembershipStatus,
    ProgramPosture,
    ProgramStatus,
    RsvpStatus,
    SponsorStatus,
    SurveyStatus,
    TermStatus,
)

GROUP_CATEGORIES = {"AFFINITY", "PROFESSIONAL", "COMMUNITY_OUTREACH"}
EVENT_CATEGORIES = {"WORKSHOP", "SOCIAL", "RECRUITING", "COMMUNITY"}
FUNDING_CATEGORIES = {"EVENT", "TRAINING", "COMMUNITY_OUTREACH", "RECRUITING", "OTHER"}


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1"
    )


def assert_program(data: dict):
    _assert_common_fields(data, "InclusionProgram")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["pool_total_cents"], int) and data["pool_total_cents"] >= 0
    assert data["status"] in {s.value for s in ProgramStatus}
    assert data["posture"] in {p.value for p in ProgramPosture}
    assert isinstance(data["unallocated_pool_cents"], int)


def assert_sponsor(data: dict):
    _assert_common_fields(data, "ExecutiveSponsor")
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert isinstance(data["max_groups"], int) and data["max_groups"] >= 1
    assert isinstance(data["max_mentees"], int) and data["max_mentees"] >= 1
    assert data["status"] in {s.value for s in SponsorStatus}


def assert_group(data: dict):
    _assert_common_fields(data, "ErgGroup")
    assert is_valid_uuid(data.get("program_id", "")), "group.program_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in GROUP_CATEGORIES
    assert data["status"] in {s.value for s in GroupStatus}
    assert isinstance(data["active_member_count"], int)
    assert isinstance(data["has_active_leader"], bool)
    for field in ("allocated_cents", "reserved_cents", "spent_cents", "available_cents"):
        assert isinstance(data[field], int), f"group.{field} must be an integer"


def assert_membership(data: dict):
    _assert_common_fields(data, "GroupMembership")
    assert is_valid_uuid(data.get("group_id", "")), "membership.group_id must be a UUID"
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert data["status"] in {s.value for s in MembershipStatus}
    assert is_iso8601_timestamp(data.get("joined_at", "")), "joined_at must be ISO 8601"
    assert data.get("left_at") is None or is_iso8601_timestamp(data["left_at"])


def assert_leadership_term(data: dict):
    _assert_common_fields(data, "LeadershipTerm")
    assert is_valid_uuid(data.get("group_id", "")), "term.group_id must be a UUID"
    assert isinstance(data["leader_employee_id"], str) and data["leader_employee_id"]
    assert data["status"] in {s.value for s in TermStatus}
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"


def assert_funding_request(data: dict):
    _assert_common_fields(data, "FundingRequest")
    assert is_valid_uuid(data.get("group_id", "")), "funding_request.group_id must be a UUID"
    assert isinstance(data["created_by_employee_id"], str) and data["created_by_employee_id"]
    assert data["category"] in FUNDING_CATEGORIES
    assert isinstance(data["requested_cents"], int) and data["requested_cents"] > 0
    assert data["status"] in {s.value for s in FundingRequestStatus}


def assert_venue(data: dict):
    _assert_common_fields(data, "Venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0


def assert_event(data: dict):
    _assert_common_fields(data, "ErgEvent")
    assert is_valid_uuid(data.get("group_id", "")), "event.group_id must be a UUID"
    assert is_valid_uuid(data.get("venue_id", "")), "event.venue_id must be a UUID"
    assert data["category"] in EVENT_CATEGORIES
    assert data["status"] in {s.value for s in EventStatus}
    assert data["funding_status"] in {s.value for s in EventFundingStatus}
    assert isinstance(data["registered_count"], int)
    assert isinstance(data["checked_in_count"], int)


def assert_rsvp(data: dict):
    _assert_common_fields(data, "EventRsvp")
    assert is_valid_uuid(data.get("event_id", "")), "rsvp.event_id must be a UUID"
    assert isinstance(data["employee_id"], str) and data["employee_id"]
    assert data["status"] in {s.value for s in RsvpStatus}
    assert data.get("waitlist_position") is None or isinstance(data["waitlist_position"], int)


def assert_climate_survey(data: dict):
    _assert_common_fields(data, "ClimateSurvey")
    assert is_valid_uuid(data.get("program_id", "")), "survey.program_id must be a UUID"
    assert data["status"] in {s.value for s in SurveyStatus}
    assert isinstance(data["min_responses"], int) and data["min_responses"] >= 1
    assert isinstance(data["response_count"], int)


def assert_survey_response(data: dict):
    """SurveyResponse is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "SurveyResponse.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "SurveyResponse must not expose updated_at"
    assert "version" not in data, "SurveyResponse must not expose version"
    assert is_valid_uuid(data.get("survey_id", "")), "survey_id must be a UUID"
    assert isinstance(data["respondent_employee_id"], str) and data["respondent_employee_id"]
    for field in ("belonging_score", "growth_score", "fairness_score", "safety_score"):
        assert isinstance(data[field], int) and 1 <= data[field] <= 5, (
            f"{field} must be an integer in 1..5"
        )


def assert_mentoring_engagement(data: dict):
    _assert_common_fields(data, "MentoringEngagement")
    assert is_valid_uuid(data.get("program_id", "")), "engagement.program_id must be a UUID"
    assert is_valid_uuid(data.get("sponsor_id", "")), "engagement.sponsor_id must be a UUID"
    assert isinstance(data["mentee_employee_id"], str) and data["mentee_employee_id"]
    assert data["status"] in {s.value for s in EngagementStatus}


def assert_group_budget_partition(group: dict):
    """allocated_cents always equals available + reserved + spent."""
    total = group["available_cents"] + group["reserved_cents"] + group["spent_cents"]
    assert group["allocated_cents"] == total, (
        f"Budget partition broken: allocated {group['allocated_cents']} != "
        f"available {group['available_cents']} + reserved {group['reserved_cents']} "
        f"+ spent {group['spent_cents']}"
    )
