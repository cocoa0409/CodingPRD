"""Entity assertions and domain invariant checkers.

Structural assertions only: identifier shape, ISO 8601 timestamps, enum
membership, and the immutable-measurement field contract from PRD §2.5.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_DESKS = ["METRO", "BUSINESS", "SPORTS", "FEATURES"]
_CAPABILITIES = [
    "REPORTER", "PHOTOGRAPHER", "COPY_EDITOR", "FACT_CHECKER", "LEGAL_REVIEWER",
    "DESK_EDITOR", "MANAGING_EDITOR", "NEWS_DIRECTOR", "ANALYST",
]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version starts at 1"


def _assert_immutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, \
        "immutable measurements carry no version field (PRD §2.5)"
    assert "updated_at" not in data, \
        "immutable measurements carry no updated_at field (PRD §2.5)"


def assert_staff_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_capability"] in _CAPABILITIES
    assert data["home_desk"] in _DESKS
    assert data["employment_status"] in ["ACTIVE", "ON_LEAVE", "INACTIVE"]
    assert isinstance(data["max_concurrent_assignments"], int)
    assert data["max_concurrent_assignments"] >= 1
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["hourly_rate_cents"] >= 0
    assert isinstance(data["active_assignment_count"], int)
    assert data["active_assignment_count"] >= 0


def assert_pitch(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["desk"] in _DESKS
    assert data["urgency"] in ["STANDARD", "URGENT", "BREAKING"]
    assert data["status"] in [
        "SUBMITTED", "DESK_REVIEW", "GREENLIT", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["rework_round"], int) and data["rework_round"] >= 0


def assert_story(data: dict):
    _assert_common(data)
    assert data["desk"] in _DESKS
    assert data["story_type"] in ["PRINT", "DIGITAL", "BROADCAST"]
    assert data["status"] in [
        "DRAFT", "IN_EDIT", "FACT_CHECK", "LEGAL_REVIEW", "CLEARED",
        "SCHEDULED", "ON_HOLD", "PUBLISHED", "RETRACTED", "KILLED",
    ]
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert isinstance(data["correction_count"], int)
    assert data["correction_count"] >= 0


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["assignment_role"] in ["REPORTER", "PHOTOGRAPHER"]
    assert data["status"] in [
        "PROPOSED", "ACCEPTED", "DECLINED", "CANCELLED", "COMPLETED", "BUMPED",
    ]
    assert isinstance(data["planned_effort_minutes"], int)
    assert data["planned_effort_minutes"] >= 1
    assert isinstance(data["provisional_cost_cents"], int)


def assert_publication_slot(data: dict):
    _assert_common(data)
    assert data["channel"] in ["PRINT", "DIGITAL", "BROADCAST"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert data["status"] in ["ACTIVE", "CANCELLED"]


def assert_review_record(data: dict):
    _assert_immutable(data)
    assert data["review_type"] in ["FACT_CHECK", "LEGAL"]
    assert data["verdict"] in ["PASS", "FAIL"]
    assert isinstance(data["reviewed_story_version"], int)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1
    assert isinstance(data["is_current"], bool)


def assert_correction(data: dict):
    _assert_common(data)
    assert data["severity"] in ["MINOR", "MAJOR", "RETRACTION"]
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "ISSUED"]


def assert_analytics_report(data: dict):
    _assert_immutable(data)
    assert data["variant"] in ["REALTIME", "SETTLED"]
    assert isinstance(data["views"], int) and data["views"] >= 0
    assert isinstance(data["engagement_minutes"], int)
    assert data["engagement_minutes"] >= 0
    assert data["tier"] in ["A", "B", "C"]
    assert data["status"] in ["ACTIVE", "VOID"]


def assert_breaking_event(data: dict):
    _assert_common(data)
    assert data["priority_band"] in [1, 2, 3]
    assert isinstance(data["call_in_pool_size"], int)
    assert data["call_in_pool_size"] >= 0
    assert data["status"] in ["DECLARED", "ACTIVE", "RESOLVED"]


def assert_call_in(data: dict):
    _assert_common(data)
    assert data["status"] in ["PAGED", "CONFIRMED", "DECLINED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("paged_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_active_count_invariant(staff: dict, assignments: list):
    """active_assignment_count == count of the staff member's assignments in
    PROPOSED or ACCEPTED status (PRD §2.11 live counter)."""
    live = [a for a in assignments
            if a["staff_id"] == staff["id"] and a["status"] in ("PROPOSED", "ACCEPTED")]
    assert staff["active_assignment_count"] == len(live), (
        f"active_assignment_count {staff['active_assignment_count']} != "
        f"actual live assignments {len(live)}"
    )


def assert_reserved_count_invariant(slot: dict, stories: list):
    """reserved_count == count of SCHEDULED stories pointing at the slot
    (PRD §2.11 live counter)."""
    scheduled = [s for s in stories
                 if s.get("slot_id") == slot["id"] and s["status"] == "SCHEDULED"]
    assert slot["reserved_count"] == len(scheduled), (
        f"reserved_count {slot['reserved_count']} != "
        f"actual scheduled stories {len(scheduled)}"
    )
