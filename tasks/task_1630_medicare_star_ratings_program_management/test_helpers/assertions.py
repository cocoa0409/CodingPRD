"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CYCLE_STATUSES = ["SETUP", "DATA_COLLECTION", "CUTPOINT_REVIEW",
                  "OFFICIAL_PUBLISHED", "CLOSED"]
MEASURE_STATUSES = ["DRAFT", "ACTIVE", "RETIRED"]
CUTPOINT_SET_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED"]
PERFORMANCE_STATUSES = ["REPORTED", "VALIDATED", "LOCKED"]
MEMBER_STATUSES = ["ENROLLED", "DISENROLLED"]
GAP_STATUSES = ["OPEN", "CLOSED", "REOPENED", "EXCLUDED"]
GROUP_STATUSES = ["ACTIVE", "CLOSED"]
PAYOUT_STATUSES = ["PENDING", "APPROVED", "PAID", "DENIED"]
WAVE_STATUSES = ["PLANNED", "FIELDING", "CLOSED_FIELD", "SCORED"]
COMPLAINT_STATUSES = ["FILED", "RESOLVED_VALID", "RESOLVED_INVALID"]


def _assert_common(data: dict):
    """Common resource properties: UUID id, ISO timestamps, integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_optional_number(data: dict, field: str):
    assert field in data, f"{field} must be present"
    assert data[field] is None or isinstance(data[field], (int, float)), (
        f"{field} must be null or numeric, got {data[field]!r}"
    )


def _assert_optional_int(data: dict, field: str):
    assert field in data, f"{field} must be present"
    assert data[field] is None or isinstance(data[field], int), (
        f"{field} must be null or an integer, got {data[field]!r}"
    )


def assert_rating_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["measurement_year"], int)
    assert isinstance(data["rating_year"], int)
    assert data["rating_year"] > data["measurement_year"]
    assert isinstance(data["benchmark_pmpm"], (int, float)) and data["benchmark_pmpm"] > 0
    assert data["status"] in CYCLE_STATUSES
    assert "published_cutpoint_set_id" in data
    assert data["published_cutpoint_set_id"] is None or isinstance(
        data["published_cutpoint_set_id"], str)
    _assert_optional_number(data, "live_weighted_stars")
    _assert_optional_number(data, "official_overall_stars")
    _assert_optional_number(data, "official_rebate_amount")
    _assert_optional_int(data, "official_improvement_star")


def assert_measure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str)
    assert data["domain"] in ["STAYING_HEALTHY", "CHRONIC_CARE", "MEMBER_EXPERIENCE",
                              "MEMBER_COMPLAINTS", "CUSTOMER_SERVICE", "DRUG_SAFETY"]
    assert data["measure_type"] in ["PROCESS", "OUTCOME", "PATIENT_EXPERIENCE"]
    assert data["weight"] in (1, 3, 4)
    assert data["direction"] in ["HIGHER_BETTER", "LOWER_BETTER"]
    assert data["data_source"] in ["HEDIS", "CAHPS", "HOS", "PHARMACY_PDE",
                                   "COMPLAINTS", "APPEALS"]
    assert isinstance(data["improvement_eligible"], bool)
    assert "prior_cycle_star" in data
    assert data["prior_cycle_star"] is None or data["prior_cycle_star"] in (1, 2, 3, 4, 5)
    assert data["status"] in MEASURE_STATUSES


def assert_cutpoint_set(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert isinstance(data["label"], str)
    assert isinstance(data["rows"], list)
    for row in data["rows"]:
        assert is_valid_uuid(row.get("measure_id", ""))
        for band in ("band_2_floor", "band_3_floor", "band_4_floor", "band_5_floor"):
            assert isinstance(row[band], (int, float)), f"{band} must be numeric"
    assert data["status"] in CUTPOINT_SET_STATUSES


def assert_measure_performance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert is_valid_uuid(data.get("measure_id", ""))
    assert isinstance(data["numerator"], int) and data["numerator"] >= 0
    assert isinstance(data["denominator"], int) and data["denominator"] >= 0
    assert data["numerator"] <= data["denominator"]
    assert isinstance(data["exclusion_count"], int) and data["exclusion_count"] >= 0
    _assert_optional_number(data, "raw_value")
    _assert_optional_int(data, "published_star")
    _assert_optional_int(data, "draft_star")
    for star_field in ("published_star", "draft_star"):
        if data[star_field] is not None:
            assert data[star_field] in (1, 2, 3, 4, 5)
    assert isinstance(data["timeliness_alert"], bool)
    assert isinstance(data["reported_by_user_id"], str) and data["reported_by_user_id"]
    assert data["status"] in PERFORMANCE_STATUSES


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["member_ref"], str) and data["member_ref"]
    assert isinstance(data["plan_contract"], str) and data["plan_contract"]
    assert isinstance(data["enrolled_months"], int) and 1 <= data["enrolled_months"] <= 12
    assert data["status"] in MEMBER_STATUSES


def assert_care_gap(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("measure_id", ""))
    assert data["gap_type"] in ["PHARMACY_ADHERENCE", "SCREENING", "FOLLOW_UP", "IMMUNIZATION"]
    assert isinstance(data["intervention_count"], int) and 0 <= data["intervention_count"] <= 3
    assert "last_intervention_channel" in data
    assert data["last_intervention_channel"] is None or data["last_intervention_channel"] in (
        ["CALL", "MAIL", "SMS", "PHARMACIST_CONSULT"])
    assert data["status"] in GAP_STATUSES


def assert_provider_group(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["program_type"] in ["ATTAINMENT", "GAP_CLOSURE"]
    assert is_valid_uuid(data.get("linked_measure_id", ""))
    assert data["target_star"] in (1, 2, 3, 4, 5)
    assert isinstance(data["unit_reward_per_gap"], (int, float)) and data["unit_reward_per_gap"] > 0
    assert isinstance(data["max_pool_amount"], (int, float)) and data["max_pool_amount"] >= 0
    assert isinstance(data["paid_total"], (int, float))
    assert isinstance(data["reserved_total"], (int, float))
    assert isinstance(data["remaining_amount"], (int, float))
    assert data["status"] in GROUP_STATUSES


def assert_pool_invariant(group: dict):
    """Fiscal invariant: max_pool_amount == paid_total + reserved_total + remaining_amount."""
    total = group["paid_total"] + group["reserved_total"] + group["remaining_amount"]
    assert abs(group["max_pool_amount"] - total) < 1e-6, (
        f"pool invariant broken: max_pool_amount {group['max_pool_amount']} != "
        f"paid {group['paid_total']} + reserved {group['reserved_total']} + "
        f"remaining {group['remaining_amount']}"
    )


def assert_incentive_payout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_group_id", ""))
    assert isinstance(data["amount"], (int, float)) and data["amount"] >= 0
    assert isinstance(data["basis_snapshot"], dict)
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    assert data["status"] in PAYOUT_STATUSES


def assert_survey_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["max_concurrent_waves"], int) and data["max_concurrent_waves"] >= 1


def assert_survey_wave(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert data["survey_type"] in ["CAHPS", "HOS"]
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["sample_size"], int) and data["sample_size"] > 0
    _assert_optional_int(data, "response_count")
    _assert_optional_number(data, "response_rate")
    assert "sufficient" in data
    assert data["sufficient"] is None or isinstance(data["sufficient"], bool)
    assert data["status"] in WAVE_STATUSES


def assert_complaint_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["category"] in ["APPEALS_TIMELINESS", "COVERAGE_DETERMINATION", "BILLING",
                                "ENROLLMENT", "SERVICE_QUALITY"]
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert "resolved_at" in data
    assert data["resolved_at"] is None or is_iso8601_timestamp(data["resolved_at"])
    assert "late_resolution" in data
    assert data["late_resolution"] is None or isinstance(data["late_resolution"], bool)
    assert data["status"] in COMPLAINT_STATUSES


def assert_rating_forecast(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rating_cycle_id", ""))
    assert data["basis"] in ["PUBLISHED_CUTPOINTS", "DRAFT_CUTPOINTS"]
    assert isinstance(data["measures_included"], int) and data["measures_included"] >= 0
    assert isinstance(data["measures_improved"], int) and data["measures_improved"] >= 0
    assert isinstance(data["measures_declined"], int) and data["measures_declined"] >= 0
    assert isinstance(data["measures_eligible"], int) and data["measures_eligible"] >= 0
    _assert_optional_number(data, "improvement_score")
    _assert_optional_int(data, "improvement_star")
    _assert_optional_number(data, "projected_overall_stars")
    assert isinstance(data["member_months_used"], int) and data["member_months_used"] >= 0
    assert isinstance(data["rebate_tier_rate"], (int, float))
    assert isinstance(data["projected_rebate_amount"], (int, float))
