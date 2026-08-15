"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CaseStatus, CycleStatus, GiftedStatus, PlacementStatus, ProfileStatus,
    ReEvaluationStatus, ReviewOutcome, ReviewStatus, ScoredVariant,
)

DEMOGRAPHIC_GROUPS = [
    "AMERICAN_INDIAN", "ASIAN", "BLACK", "HISPANIC", "WHITE",
    "MULTIRACIAL", "PACIFIC_ISLANDER",
]
MEASURE_TYPES = ["ABILITY", "ACHIEVEMENT", "RATING_SCALE", "PORTFOLIO"]
GRADE_BANDS = ["ELEMENTARY", "MIDDLE", "HIGH"]
SERVICE_MODELS = ["PULL_OUT", "CLUSTER", "ACCELERATION"]
PATHWAYS = ["UNIVERSAL_SCREEN", "REFERRAL", "TRANSFER_HONOR"]
PLAN_TYPES = ["IEP", "PLAN_504"]
REVIEW_KINDS = ["BAND_REVIEW", "APPEAL"]
VERDICTS = ["QUALIFY", "DENY", "ABSTAIN"]


def _assert_full_lifecycle_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be int"


def _assert_ledger_common(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def assert_school_site(data: dict):
    _assert_full_lifecycle_common(data, "SchoolSite")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for f in ("pull_out_capacity", "cluster_capacity", "acceleration_capacity"):
        assert isinstance(data[f], int) and data[f] >= 0, \
            f"SchoolSite.{f} must be a non-negative integer"
    for f in ("pull_out_occupied", "cluster_occupied", "acceleration_occupied"):
        assert isinstance(data[f], int), f"SchoolSite.{f} must be an integer"


def assert_site_occupancy_invariants(site: dict):
    """Seat inventory: 0 <= occupied <= capacity per service model."""
    assert_school_site(site)
    for model in ("pull_out", "cluster", "acceleration"):
        occ = site[f"{model}_occupied"]
        cap = site[f"{model}_capacity"]
        assert 0 <= occ <= cap, \
            f"Site occupancy invariant broken for {model}: occupied={occ} capacity={cap}"


def assert_student(data: dict):
    _assert_full_lifecycle_common(data, "Student")
    assert isinstance(data["student_number"], str) and len(data["student_number"]) > 0
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12
    assert is_valid_uuid(data["school_site_id"])
    assert data["demographic_group"] in DEMOGRAPHIC_GROUPS
    assert isinstance(data["is_ell"], bool)
    assert data.get("primary_guardian_user_id") is None or \
        isinstance(data["primary_guardian_user_id"], str)
    assert data["gifted_status"] in [s.value for s in GiftedStatus]
    assert isinstance(data["has_active_sped_plan"], bool)


def assert_sped_plan(data: dict):
    _assert_ledger_common(data, "SpedPlan")
    assert is_valid_uuid(data["student_id"])
    assert data["plan_type"] in PLAN_TYPES
    assert isinstance(data["started_on"], str) and len(data["started_on"]) == 10


def assert_screening_cycle(data: dict):
    _assert_full_lifecycle_common(data, "ScreeningCycle")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["school_year"], str)
    assert data["grade_band"] in GRADE_BANDS
    for f in ("screening_open_on", "screening_close_on", "referral_close_on"):
        assert isinstance(data[f], str) and len(data[f]) == 10
    assert data["status"] in [s.value for s in CycleStatus]
    assert data.get("published_profile_id") is None or \
        is_valid_uuid(data["published_profile_id"])


def assert_cut_score_profile(data: dict):
    _assert_full_lifecycle_common(data, "CutScoreProfile")
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    for f in ("ability_weight", "achievement_weight", "rating_weight",
              "portfolio_weight"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    total = (data["ability_weight"] + data["achievement_weight"]
             + data["rating_weight"] + data["portfolio_weight"])
    assert abs(total - 1.0) <= 0.0001 + 1e-9, "profile weights must sum to 1.0"
    for f in ("cut_score", "review_band_floor", "cut_score_2e",
              "review_band_floor_2e"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["review_band_floor"] < data["cut_score"]
    assert data["review_band_floor_2e"] < data["cut_score_2e"]
    assert data["cut_score_2e"] <= data["cut_score"]
    assert isinstance(data["measure_validity_days"], int)
    assert data["status"] in [s.value for s in ProfileStatus]


def assert_gifted_case(data: dict):
    _assert_full_lifecycle_common(data, "GiftedCase")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["cycle_id"])
    assert data["pathway"] in PATHWAYS
    assert data.get("referral_source") is None or \
        data["referral_source"] in ("TEACHER", "PARENT", "SELF")
    assert data.get("referrer_user_id") is None or \
        isinstance(data["referrer_user_id"], str)
    assert data.get("external_district_name") is None or \
        isinstance(data["external_district_name"], str)
    assert data.get("external_identified_on") is None or \
        isinstance(data["external_identified_on"], str)
    assert data["status"] in [s.value for s in CaseStatus]
    assert data.get("composite_score") is None or \
        isinstance(data["composite_score"], (int, float))
    assert data.get("scored_variant") is None or \
        data["scored_variant"] in [v.value for v in ScoredVariant]
    assert isinstance(data["appeal_used"], bool)
    assert data.get("decided_on") is None or isinstance(data["decided_on"], str)


def assert_measure_score(data: dict):
    _assert_ledger_common(data, "MeasureScore")
    assert is_valid_uuid(data["case_id"])
    assert data["measure_type"] in MEASURE_TYPES
    assert isinstance(data["percentile"], (int, float))
    assert 1.0 <= data["percentile"] <= 99.9
    assert isinstance(data["administered_on"], str) and len(data["administered_on"]) == 10
    assert data.get("weighted_contribution") is None or \
        isinstance(data["weighted_contribution"], (int, float))


def assert_committee_review(data: dict):
    _assert_full_lifecycle_common(data, "CommitteeReview")
    assert is_valid_uuid(data["case_id"])
    assert data["review_kind"] in REVIEW_KINDS
    assert data.get("grounds") is None or isinstance(data["grounds"], str)
    assert data["status"] in [s.value for s in ReviewStatus]
    assert data.get("outcome") is None or \
        data["outcome"] in [o.value for o in ReviewOutcome]
    assert data.get("decided_on") is None or isinstance(data["decided_on"], str)
    for f in ("qualify_votes", "deny_votes", "abstain_votes"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_committee_vote(data: dict):
    _assert_ledger_common(data, "CommitteeVote")
    assert is_valid_uuid(data["review_id"])
    assert isinstance(data["member_user_id"], str) and len(data["member_user_id"]) > 0
    assert data["verdict"] in VERDICTS


def assert_service_placement(data: dict):
    _assert_full_lifecycle_common(data, "ServicePlacement")
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["site_id"])
    assert data["service_model"] in SERVICE_MODELS
    assert isinstance(data["start_on"], str) and len(data["start_on"]) == 10
    assert data.get("end_on") is None or isinstance(data["end_on"], str)
    assert data["status"] in [s.value for s in PlacementStatus]
    assert data.get("offered_on") is None or isinstance(data["offered_on"], str)
    assert data.get("accept_by") is None or isinstance(data["accept_by"], str)
    assert data.get("waitlisted_at") is None or \
        isinstance(data["waitlisted_at"], str)
    assert isinstance(data["is_on_probation"], bool)


def assert_re_evaluation(data: dict):
    _assert_full_lifecycle_common(data, "ReEvaluation")
    assert is_valid_uuid(data["placement_id"])
    assert isinstance(data["due_on"], str) and len(data["due_on"]) == 10
    assert data["status"] in [s.value for s in ReEvaluationStatus]
    assert data.get("growth_percentile") is None or \
        isinstance(data["growth_percentile"], (int, float))
    assert data.get("service_rating") is None or isinstance(data["service_rating"], int)
    assert data.get("teacher_rating") is None or isinstance(data["teacher_rating"], int)
    assert data.get("exit_score") is None or \
        isinstance(data["exit_score"], (int, float))
    assert data.get("outcome") is None or \
        data["outcome"] in ("RETAINED", "PROBATION", "EXITED")
    assert data.get("concluded_on") is None or isinstance(data["concluded_on"], str)
