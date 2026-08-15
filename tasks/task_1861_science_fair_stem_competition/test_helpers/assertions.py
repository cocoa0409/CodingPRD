"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvancementResult,
    AssignmentStatus,
    AwardStatus,
    AwardType,
    CategoryStatus,
    EthicsDecision,
    EthicsStatus,
    FairEditionStatus,
    GradeBand,
    InspectionStatus,
    JudgeStatus,
    JudgingStatus,
    RecognitionTier,
    RegistrationStatus,
    ResearchPlanStatus,
    RiskLevel,
)

_ENUM_VALUES = lambda enum_cls: [member.value for member in enum_cls]

FAIR_EDITION_STATUSES = _ENUM_VALUES(FairEditionStatus)
CATEGORY_STATUSES = _ENUM_VALUES(CategoryStatus)
GRADE_BANDS = _ENUM_VALUES(GradeBand)
RECOGNITION_TIERS = _ENUM_VALUES(RecognitionTier)
REGISTRATION_STATUSES = _ENUM_VALUES(RegistrationStatus)
ETHICS_STATUSES = _ENUM_VALUES(EthicsStatus)
INSPECTION_STATUSES = _ENUM_VALUES(InspectionStatus)
JUDGING_STATUSES = _ENUM_VALUES(JudgingStatus)
ADVANCEMENT_RESULTS = _ENUM_VALUES(AdvancementResult)
RESEARCH_PLAN_STATUSES = _ENUM_VALUES(ResearchPlanStatus)
RISK_LEVELS = _ENUM_VALUES(RiskLevel)
ETHICS_DECISIONS = _ENUM_VALUES(EthicsDecision)
JUDGE_STATUSES = _ENUM_VALUES(JudgeStatus)
ASSIGNMENT_STATUSES = _ENUM_VALUES(AssignmentStatus)
AWARD_TYPES = _ENUM_VALUES(AwardType)
AWARD_STATUSES = _ENUM_VALUES(AwardStatus)
NORMALIZATION_ALGORITHMS = ["Z_SCORE", "MIN_MAX"]


def _assert_common_fields(data: dict):
    """Standard system-managed fields present on every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"version must be an int, got {data.get('version')!r}"


def _assert_immutable_record_fields(data: dict):
    """Judge-conflict records and score sheets carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "immutable records must not expose updated_at"
    assert "version" not in data, "immutable records must not expose version"


def assert_fair_edition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["status"] in FAIR_EDITION_STATUSES, f"bad edition status {data.get('status')!r}"
    assert data["normalization_algorithm"] in NORMALIZATION_ALGORITHMS
    assert isinstance(data["max_judges_per_project"], int)
    assert data["max_judges_per_project"] >= 2
    assert isinstance(data["min_quorum_ratio_pct"], int)
    assert 1 <= data["min_quorum_ratio_pct"] <= 100
    assert isinstance(data["advancement_freeze"], bool)


def assert_category(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fair_edition_id", ""))
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["grade_band"] in GRADE_BANDS
    assert isinstance(data["advancement_slots"], int) and data["advancement_slots"] >= 0
    assert data["status"] in CATEGORY_STATUSES


def assert_mentor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data["recognition_points"], int) and data["recognition_points"] >= 0
    assert isinstance(data["leaderboard_points"], int) and data["leaderboard_points"] >= 0
    assert data["recognition_tier"] in RECOGNITION_TIERS


def assert_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fair_edition_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("mentor_id", ""))
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data["team_size"], int) and 1 <= data["team_size"] <= 3
    assert isinstance(data["involves_human_subjects"], bool)
    assert isinstance(data["involves_animal_subjects"], bool)
    assert data["registration_status"] in REGISTRATION_STATUSES
    assert data["ethics_status"] is None or data["ethics_status"] in ETHICS_STATUSES
    assert data["inspection_status"] in INSPECTION_STATUSES
    assert data["judging_status"] in JUDGING_STATUSES
    assert data["provisional_aggregate"] is None or isinstance(
        data["provisional_aggregate"], (int, float)
    )
    assert data["final_aggregate"] is None or isinstance(data["final_aggregate"], (int, float))
    assert data["advancement_result"] in ADVANCEMENT_RESULTS
    assert data["advancement_rank"] is None or isinstance(data["advancement_rank"], int)


def assert_research_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data.get("plan_text"), str)
    assert data["risk_level"] in RISK_LEVELS
    assert data["status"] in RESEARCH_PLAN_STATUSES
    assert isinstance(data["review_cycle_count"], int) and data["review_cycle_count"] >= 0
    assert data["approved_plan_version"] is None or isinstance(data["approved_plan_version"], int)


def assert_ethics_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("research_plan_id", ""))
    assert is_valid_uuid(data.get("reviewer_mentor_id", ""))
    assert data["decision"] in ETHICS_DECISIONS
    assert is_iso8601_timestamp(data.get("decided_at", ""))


def assert_judge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fair_edition_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("expertise_category_ids"), list)
    assert isinstance(data["max_assignments"], int) and data["max_assignments"] >= 1
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0
    assert data["status"] in JUDGE_STATUSES


def assert_judge_conflict(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data.get("judge_id", ""))
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data.get("reason"), str)


def assert_judging_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("judge_id", ""))
    assert data["status"] in ASSIGNMENT_STATUSES
    assert is_iso8601_timestamp(data.get("assigned_at", ""))


def assert_score_sheet(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data.get("judging_assignment_id", ""))
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("judge_id", ""))
    assert isinstance(data["raw_score"], int) and 0 <= data["raw_score"] <= 100
    assert isinstance(data["normalized_score"], (int, float))
    assert is_iso8601_timestamp(data.get("submitted_at", ""))


def assert_booth_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data.get("hall"), str) and data["hall"]
    assert isinstance(data["booth_number"], int)
    assert is_iso8601_timestamp(data.get("inspection_window_start", ""))
    assert is_iso8601_timestamp(data.get("inspection_window_end", ""))


def assert_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fair_edition_id", ""))
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["award_type"] in AWARD_TYPES
    assert data["status"] in AWARD_STATUSES
    if data.get("scholarship_amount_cents") is not None:
        assert isinstance(data["scholarship_amount_cents"], int)
        assert data["scholarship_amount_cents"] >= 0


def assert_scholarship_pool(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fair_edition_id", ""))
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["remaining_cents"], int)
    assert 0 <= data["remaining_cents"] <= data["total_cents"]


def assert_pool_conservation(pool: dict):
    """The pool is debited only as awards are conferred; remaining never exceeds total."""
    assert 0 <= pool["remaining_cents"] <= pool["total_cents"], (
        f"pool conservation broken: remaining {pool['remaining_cents']} vs total {pool['total_cents']}"
    )
