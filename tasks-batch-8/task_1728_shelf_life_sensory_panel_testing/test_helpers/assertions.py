"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Status vocabularies (PRD §3)
CLIENT_TIERS = ["STANDARD", "PREMIUM"]
STUDY_STATUSES = ["DRAFT", "DESIGN_REVIEW", "SCHEDULED", "IN_PROGRESS",
                  "ANALYSIS", "REPORTING", "COMPLETED", "ABORTED"]
STUDY_TYPES = ["REAL_TIME", "ACCELERATED"]
PACKAGING_VARIANTS = ["STANDARD_FILM", "HIGH_BARRIER", "MAP", "VACUUM"]
TIME_POINT_STATUSES = ["PENDING", "PULLED", "EVALUATED", "CLOSED", "SKIPPED"]
SAMPLE_UNIT_STATUSES = ["STORED", "CHECKED_OUT", "CONSUMED", "DISCARDED", "EXPIRED"]
UNIT_PURPOSES = ["EVALUATION", "RETAIN"]
PANELIST_STATUSES = ["APPLIED", "TRAINING", "QUALIFIED", "INACTIVE",
                     "SUSPENDED", "SCREENED_OUT"]
ATTRIBUTES = ["APPEARANCE", "AROMA", "FLAVOR", "TEXTURE", "OFF_FLAVOR", "OVERALL"]
SESSION_STATUSES = ["PLANNED", "OPEN", "LOCKED", "ANALYZED", "CANCELLED"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "SUBMITTED", "NO_SHOW", "EXCUSED"]
TEST_TYPES = ["APC", "YEAST_MOLD", "LACTIC", "PEROXIDE_VALUE", "PH", "WATER_ACTIVITY"]
RECOMMENDATION_STATUSES = ["PROPOSED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
RECOMMENDATION_BASES = ["ENDPOINT_MIN", "TARGET_FALLBACK"]
REPORT_STATUSES = ["DRAFT", "INTERNAL_REVIEW", "CLIENT_REVIEW", "RELEASED", "REJECTED"]
CLAIM_TYPES = ["SHELF_LIFE_DAYS", "PACKAGING_SUPERIORITY"]
CLAIM_VERDICTS = ["PENDING", "SUPPORTED", "NOT_SUPPORTED", "INSUFFICIENT_DATA"]


def _assert_common_fields(data: dict, label: str):
    """Primary resources carry id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_immutable_event_fields(data: dict, label: str):
    """Immutable event records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_client(data: dict):
    _assert_common_fields(data, "ClientAccount")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert data["tier"] in CLIENT_TIERS
    assert isinstance(data["retainer_hours_balance"], (int, float))
    assert isinstance(data["active_study_count"], int)


def assert_study(data: dict):
    _assert_common_fields(data, "Study")
    assert isinstance(data["client_id"], str)
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert data["study_type"] in STUDY_TYPES
    assert isinstance(data["storage_temp_c"], (int, float))
    assert isinstance(data["reference_temp_c"], (int, float))
    assert isinstance(data["q10_factor"], (int, float))
    assert isinstance(data["target_shelf_life_days"], int)
    assert isinstance(data["sensory_fail_threshold"], (int, float))
    assert isinstance(data["min_detectable_difference"], (int, float))
    assert isinstance(data["planned_start_utc"], str)
    assert data["actual_start_utc"] is None or isinstance(data["actual_start_utc"], str)
    assert isinstance(data["reserved_hours_escrow"], (int, float))
    assert isinstance(data["consumed_hours"], (int, float))
    assert data["earliest_failure_day_equiv"] is None or \
        isinstance(data["earliest_failure_day_equiv"], (int, float))
    assert data["status"] in STUDY_STATUSES


def assert_arm(data: dict):
    _assert_common_fields(data, "StudyArm")
    assert isinstance(data["study_id"], str)
    assert data["packaging_variant"] in PACKAGING_VARIANTS
    assert isinstance(data["is_control"], bool)
    assert data["computed_failure_day_equiv"] is None or \
        isinstance(data["computed_failure_day_equiv"], (int, float))


def assert_time_point(data: dict):
    _assert_common_fields(data, "SamplingTimePoint")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["day_index"], int) and data["day_index"] >= 0
    assert data["status"] in TIME_POINT_STATUSES


def assert_chamber(data: dict):
    _assert_common_fields(data, "StorageChamber")
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert isinstance(data["temp_c"], (int, float))
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0


def assert_sample_unit(data: dict):
    _assert_common_fields(data, "SampleUnit")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["arm_id"], str)
    assert isinstance(data["chamber_id"], str)
    assert isinstance(data["time_point_id"], str)
    assert data["unit_purpose"] in UNIT_PURPOSES
    assert data["session_id"] is None or isinstance(data["session_id"], str)
    assert data["retention_until_utc"] is None or \
        isinstance(data["retention_until_utc"], str)
    assert data["status"] in SAMPLE_UNIT_STATUSES


def assert_panelist(data: dict):
    _assert_common_fields(data, "Panelist")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["qualified_attributes"], list)
    assert all(a in ATTRIBUTES for a in data["qualified_attributes"])
    assert data["screening_acuity_score"] is None or \
        isinstance(data["screening_acuity_score"], (int, float))
    assert isinstance(data["training_sessions_completed"], int)
    assert isinstance(data["consecutive_no_shows"], int)
    assert data["consistency_index_provisional"] is None or \
        isinstance(data["consistency_index_provisional"], (int, float))
    assert data["consistency_index_final"] is None or \
        isinstance(data["consistency_index_final"], (int, float))
    assert data["status"] in PANELIST_STATUSES


def assert_session(data: dict):
    _assert_common_fields(data, "EvaluationSession")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["time_point_id"], str)
    assert isinstance(data["arm_id"], str)
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert data["makeup_of_id"] is None or isinstance(data["makeup_of_id"], str)
    assert isinstance(data["required_panelist_count"], int)
    assert data["overall_mean"] is None or isinstance(data["overall_mean"], (int, float))
    assert data["significance_delta"] is None or \
        isinstance(data["significance_delta"], (int, float))
    assert isinstance(data["sensory_failed"], bool)
    assert data["status"] in SESSION_STATUSES


def assert_assignment(data: dict):
    _assert_common_fields(data, "PanelAssignment")
    assert isinstance(data["session_id"], str)
    assert isinstance(data["panelist_id"], str)
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_score(data: dict):
    _assert_immutable_event_fields(data, "AttributeScore")
    assert isinstance(data["assignment_id"], str)
    assert data["attribute"] in ATTRIBUTES
    assert isinstance(data["score"], int) and 1 <= data["score"] <= 15


def assert_lab_result(data: dict):
    _assert_immutable_event_fields(data, "LabTestResult")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["arm_id"], str)
    assert isinstance(data["time_point_id"], str)
    assert data["test_type"] in TEST_TYPES
    assert isinstance(data["measured_value"], (int, float))
    assert isinstance(data["tripped"], bool)


def assert_recommendation(data: dict):
    _assert_common_fields(data, "DateCodeRecommendation")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["arm_id"], str)
    assert data["basis"] in RECOMMENDATION_BASES
    assert isinstance(data["computed_days"], int)
    assert data["status"] in RECOMMENDATION_STATUSES


def assert_report(data: dict):
    _assert_common_fields(data, "StudyReport")
    assert isinstance(data["study_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["author_user_id"], str)
    assert data["pinned_recommendation_id"] is None or \
        isinstance(data["pinned_recommendation_id"], str)
    assert data["snapshot_days"] is None or isinstance(data["snapshot_days"], int)
    assert isinstance(data["requires_revision"], bool)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in REPORT_STATUSES


def assert_claim(data: dict):
    _assert_common_fields(data, "ClaimSubstantiation")
    assert isinstance(data["report_id"], str)
    assert data["claim_type"] in CLAIM_TYPES
    assert isinstance(data["claim_text"], str)
    assert isinstance(data["claimed_value"], (int, float))
    assert data["verdict"] in CLAIM_VERDICTS
    assert data["verified_by"] is None or isinstance(data["verified_by"], str)


# --- Domain invariant checkers ------------------------------------------------

def assert_chamber_occupancy_invariant(chamber: dict, occupying_unit_count: int):
    """reserved_units tracks units in {STORED, CHECKED_OUT} exactly (PRD §2.9)."""
    assert chamber["reserved_units"] == occupying_unit_count, (
        f"reserved_units {chamber['reserved_units']} != actual occupying count "
        f"{occupying_unit_count} for chamber {chamber.get('id')}"
    )
    assert 0 <= chamber["reserved_units"] <= chamber["capacity_units"]


def assert_retainer_conservation(balance: float, escrow: float, funded_total: float):
    """retainer_hours_balance + reserved_hours_escrow stays constant across an
    activate/abort pair when nothing is consumed (PRD §3.2)."""
    assert abs((balance + escrow) - funded_total) < 1e-6, (
        f"fiscal conservation violated: {balance} + {escrow} != {funded_total}"
    )
