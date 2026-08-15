"""Entity assertions and domain invariant checkers (PRD §2.6, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
_WINDOW_KINDS = ["FALL", "WINTER", "SPRING"]
_SUBJECTS = ["READING", "MATH"]


def _assert_common_fields(data: dict):
    """Standard system-managed fields present on primary resources (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}")


def _assert_append_only_fields(data: dict):
    """Immutable/append-only resources carry only id + created_at (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resources must not carry updated_at"
    assert "version" not in data, "append-only resources must not carry version"


def assert_district(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    assert isinstance(data["sped_referral_min_weeks"], int)
    assert isinstance(data["fidelity_threshold_pct"], int)


def assert_school(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str) and data["district_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["grade_span_low"], int)
    assert isinstance(data["grade_span_high"], int)


def assert_screening_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert data["window_kind"] in _WINDOW_KINDS
    assert isinstance(data["opens_on"], str) and data["opens_on"]
    assert isinstance(data["closes_on"], str) and data["closes_on"]
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "SCORED"]
    assert isinstance(data["screened_student_count"], int)


def assert_benchmark_cut_point(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert data["window_kind"] in _WINDOW_KINDS
    assert isinstance(data["grade_level"], int)
    assert data["subject"] in _SUBJECTS
    assert isinstance(data["tier2_max_score"], int)
    assert isinstance(data["tier3_max_score"], int)
    assert data["tier3_max_score"] < data["tier2_max_score"], (
        "tier3_max_score must be strictly less than tier2_max_score")


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["grade_level"], int)
    assert isinstance(data["subgroup_codes"], list)
    assert data["current_tier"] in _TIERS
    assert isinstance(data["weeks_at_tier3_unresponsive"], int)
    assert data["weeks_at_tier3_unresponsive"] >= 0


def assert_screening_score(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["window_id"], str) and data["window_id"]
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["subject"] in _SUBJECTS
    assert isinstance(data["raw_score"], int)
    assert data["risk_band"] in _TIERS


def assert_catalog_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["district_id"], str) and data["district_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert data["subject"] in _SUBJECTS
    assert data["tier_target"] in ["TIER_2", "TIER_3"]
    assert isinstance(data["grade_min"], int)
    assert isinstance(data["grade_max"], int)
    assert isinstance(data["session_minutes"], int)
    assert isinstance(data["sessions_per_week"], int)
    assert data["probe_frequency"] in ["WEEKLY", "BIWEEKLY"]
    assert isinstance(data["is_active"], bool)


def assert_interventionist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["weekly_minute_capacity"], int)
    assert isinstance(data["committed_minutes_per_week"], int)
    assert data["committed_minutes_per_week"] >= 0
    assert isinstance(data["subjects"], list)
    for s in data["subjects"]:
        assert s in _SUBJECTS


def assert_student_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["catalog_entry_id"], str) and data["catalog_entry_id"]
    assert isinstance(data["interventionist_id"], str) and data["interventionist_id"]
    assert data["tier_at_start"] in ["TIER_2", "TIER_3"]
    assert isinstance(data["started_on"], str) and data["started_on"]
    assert isinstance(data["weekly_minute_cost"], int)
    assert isinstance(data["probe_due_on"], str) and data["probe_due_on"]
    assert isinstance(data["fidelity_pct"], int)
    assert 0 <= data["fidelity_pct"] <= 100, "fidelity_pct floor 0 cap 100"
    assert data["status"] in [
        "ACTIVE", "PAUSED", "EXIT_RESPONSIVE", "EXIT_MOVED",
        "EXIT_SPED_REFERRAL", "EXIT_NO_PROGRESS", "CANCELLED",
    ]


def assert_progress_probe(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["administered_on"], str) and data["administered_on"]
    assert isinstance(data["score"], int)
    assert isinstance(data["aimline_score"], int)
    assert data["slope_decision"] in ["RESPONSIVE", "NON_RESPONSIVE"]


def assert_intervention_session(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["plan_id"], str) and data["plan_id"]
    assert isinstance(data["scheduled_on"], str) and data["scheduled_on"]
    assert isinstance(data["minutes"], int)
    assert data["outcome"] in ["DELIVERED", "STUDENT_ABSENT", "STAFF_ABSENT", "CANCELLED"]


def assert_tier_movement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert data["from_tier"] in _TIERS
    assert data["to_tier"] in _TIERS
    assert isinstance(data["rationale"], str)
    assert "decided_at_meeting_id" in data
    assert data["status"] in ["PROPOSED", "RATIFIED", "REJECTED", "SUPERSEDED"]


def assert_team_meeting(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert isinstance(data["scheduled_on"], str) and data["scheduled_on"]
    assert data["status"] in ["SCHEDULED", "CONVENED", "MINUTED"]
    assert isinstance(data["minuted_movement_count"], int)
    assert data["minuted_movement_count"] >= 0


def assert_sped_referral(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["triggered_plan_id"], str) and data["triggered_plan_id"]
    assert "consent_received_on" in data
    assert data["status"] in [
        "PENDING_CONSENT", "CONSENTED", "EVAL_IN_PROGRESS",
        "ELIGIBLE", "NOT_ELIGIBLE", "WITHDRAWN",
    ]


def assert_capacity_ledger_invariant(interventionist: dict):
    """The committed-minutes ledger never goes negative and never exceeds capacity
    while plans are active (PRD §2.8)."""
    committed = interventionist["committed_minutes_per_week"]
    assert committed >= 0, "committed_minutes_per_week must not drift negative"
    assert committed <= interventionist["weekly_minute_capacity"], (
        "committed minutes must not exceed weekly_minute_capacity")
