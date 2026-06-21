"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_VOLUNTEER_STATUSES = {"ACTIVE", "SUSPENDED", "WITHDRAWN"}
_BG_TIERS = {"NONE", "BASIC", "STANDARD", "ENHANCED"}
_MILESTONE_TIERS = {"NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"}
_BG_STATUSES = {"INITIATED", "IN_PROGRESS", "CLEARED", "REJECTED", "EXPIRED"}
_PUBLICATION_STATUSES = {"DRAFT", "PUBLISHED", "CLOSED"}
_STAFFING_STATUSES = {"UNDERSTAFFED", "FULLY_STAFFED"}
_SHIFT_STATUSES = {"OPEN", "FULL", "CANCELLED", "COMPLETED"}
_SIGNUP_STATUSES = {
    "RESERVED", "CONFIRMED", "ATTENDED", "HOURS_LOGGED",
    "HOURS_VERIFIED", "CANCELLED", "NO_SHOW",
}
_GROUP_STATUSES = {"PROPOSED", "APPROVED", "ALLOCATED", "REJECTED", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_common_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_organization(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in {"ACTIVE", "ARCHIVED"}, f"bad org status {data['status']!r}"
    assert isinstance(data["reliability_suspension_threshold"], int)
    assert isinstance(data["no_show_strike_limit"], int)


def assert_volunteer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert data["status"] in _VOLUNTEER_STATUSES, f"bad volunteer status {data['status']!r}"
    assert data["bg_check_tier"] in _BG_TIERS, f"bad bg_check_tier {data['bg_check_tier']!r}"
    assert data["milestone_tier"] in _MILESTONE_TIERS, f"bad milestone_tier {data['milestone_tier']!r}"
    assert isinstance(data["lifetime_no_show_count"], int)
    assert isinstance(data["reliability_score"], int)
    assert 0 <= data["reliability_score"] <= 100, "reliability_score must be in [0,100]"


def assert_background_check(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in _BG_STATUSES, f"bad bg status {data['status']!r}"
    assert data["requested_tier"] in {"BASIC", "STANDARD", "ENHANCED"}


def assert_skill(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["label"], str)


def assert_waiver_template(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["revision"], int)


def assert_training_module(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["valid_days"], int)


def assert_opportunity(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["publication_status"] in _PUBLICATION_STATUSES
    assert data["staffing_status"] in _STAFFING_STATUSES
    assert data["required_bg_tier"] in _BG_TIERS
    assert isinstance(data["required_skill_ids"], list)
    assert isinstance(data["is_group_event"], bool)


def assert_shift(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in _SHIFT_STATUSES, f"bad shift status {data['status']!r}"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert data["reserved_count"] <= data["capacity"], "reserved_count never exceeds capacity"
    assert isinstance(data["group_reserved_seats"], int)


def assert_signup(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in _SIGNUP_STATUSES, f"bad signup status {data['status']!r}"
    assert is_valid_uuid(data.get("shift_id", "")), "shift_id must be valid UUID"
    assert is_valid_uuid(data.get("volunteer_id", "")), "volunteer_id must be valid UUID"


def assert_corporate_group(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in _GROUP_STATUSES, f"bad group status {data['status']!r}"
    assert isinstance(data["requested_seats"], int) and data["requested_seats"] >= 1
    assert isinstance(data["allocated_seat_count"], int)


# ─── Append-only records (common_fields:false): id + created_at only ───────

def assert_volunteer_skill(data: dict):
    _assert_common(data)
    assert "version" not in data, "VolunteerSkill is append-only: no version field"
    assert "updated_at" not in data, "VolunteerSkill is append-only: no updated_at field"
    assert data["proficiency"] in {"SELF_DECLARED", "VERIFIED"}


def assert_waiver_acceptance(data: dict):
    _assert_common(data)
    assert "version" not in data, "WaiverAcceptance is append-only: no version field"
    assert "updated_at" not in data, "WaiverAcceptance is append-only: no updated_at field"
    assert isinstance(data["accepted_revision"], int)


def assert_training_completion(data: dict):
    _assert_common(data)
    assert "version" not in data, "TrainingCompletion is append-only: no version field"
    assert "updated_at" not in data, "TrainingCompletion is append-only: no updated_at field"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
