"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

AREA_STATUSES = ["DRAFT", "ACTIVE", "UNDER_REVIEW", "RETIRED"]
PROFILE_STATUSES = ["CURRENT", "SUPERSEDED"]
LOAN_STATUSES = ["DRAFT", "CONFIRMED", "REPORTED"]
LOAN_TYPES = ["SMALL_BUSINESS", "SMALL_FARM"]
TRACT_LEVELS = ["LOW", "MODERATE", "MIDDLE", "UPPER"]
ACTIVITY_STATUSES = ["SUBMITTED", "QUALIFIED", "DISQUALIFIED"]
ACTIVITY_TYPES = ["CD_LOAN", "QUALIFIED_INVESTMENT", "CD_SERVICE"]
PURPOSE_CATEGORIES = [
    "AFFORDABLE_HOUSING", "COMMUNITY_SERVICES_LMI",
    "ECONOMIC_DEVELOPMENT", "REVITALIZATION_STABILIZATION",
]
ALLOCATION_METHODS = ["FULL_COUNT", "PRO_RATA"]
BRANCH_STATUSES = ["PROPOSED", "OPEN", "CLOSED", "WITHDRAWN"]
COMMENT_STATUSES = ["RECEIVED", "PUBLISHED", "RESPONDED"]
POSTURES = ["COMPLETE", "INCOMPLETE"]
EXAM_STATUSES = [
    "SCHEDULED", "DATA_COLLECTION", "FIELDWORK",
    "PRELIMINARY_RATING", "APPEALED", "FINALIZED",
]
RATINGS = ["OUTSTANDING", "SATISFACTORY", "NEEDS_TO_IMPROVE", "SUBSTANTIAL_NONCOMPLIANCE"]
APPLICATION_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "DENIED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_assessment_area(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["msa_code"], str) and data["msa_code"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["census_tracts"], list)
    assert isinstance(data["annual_cd_budget_cents"], int)
    assert data["annual_cd_budget_cents"] >= 0
    assert isinstance(data["confirmed_loan_count"], int)
    assert isinstance(data["qualified_cd_total_cents"], int)
    assert data["status"] in AREA_STATUSES
    if data["status"] == "RETIRED":
        assert isinstance(data.get("effective_end_date"), str)
    else:
        assert data.get("effective_end_date") is None


def assert_demographic_profile(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assessment_area_id", ""))
    assert isinstance(data["data_year"], int)
    for field in ("total_tracts", "low_income_tracts", "moderate_income_tracts",
                  "total_population", "lmi_population", "median_family_income"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["lmi_population"] <= data["total_population"]
    assert isinstance(data["lmi_population_pct"], (int, float))
    assert isinstance(data["lmi_tract_pct"], (int, float))
    assert data["status"] in PROFILE_STATUSES


def assert_loan_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assessment_area_id", ""))
    assert data["loan_type"] in LOAN_TYPES
    assert isinstance(data["loan_amount_cents"], int) and data["loan_amount_cents"] > 0
    assert isinstance(data["borrower_gross_annual_revenue_cents"], int)
    assert data["borrower_gross_annual_revenue_cents"] >= 0
    assert isinstance(data["action_date"], str)
    assert isinstance(data["census_tract"], str)
    assert data["tract_income_level"] in TRACT_LEVELS
    assert isinstance(data["inside_assessment_area"], bool)
    assert isinstance(data["small_revenue_flag"], bool)
    assert isinstance(data["lmi_geography_flag"], bool)
    assert isinstance(data["reporting_year"], int)
    assert data["status"] in LOAN_STATUSES


def assert_cd_activity(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("assessment_area_id", ""))
    assert data["activity_type"] in ACTIVITY_TYPES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["primary_purpose_category"] in PURPOSE_CATEGORIES
    assert isinstance(data["lmi_benefit_pct"], (int, float))
    assert 0 <= data["lmi_benefit_pct"] <= 1
    assert isinstance(data["activity_date"], str)
    assert isinstance(data["qualified_amount_cents"], int)
    assert data["status"] in ACTIVITY_STATUSES


def assert_branch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert is_valid_uuid(data.get("assessment_area_id", ""))
    assert isinstance(data["census_tract"], str)
    assert data["tract_income_level"] in TRACT_LEVELS
    assert data["status"] in BRANCH_STATUSES


def assert_public_comment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["commenter_name"], str)
    assert data["channel"] in ["WRITTEN_LETTER", "EMAIL", "PUBLIC_MEETING"]
    assert data["subject_area"] in [
        "LENDING", "INVESTMENT", "SERVICE", "BRANCH_ACCESS", "OTHER",
    ]
    assert isinstance(data["content"], str)
    assert isinstance(data["received_at"], str)
    assert data["status"] in COMMENT_STATUSES


def assert_public_file(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bank_name"], str) and data["bank_name"]
    assert isinstance(data["branch_list_current"], bool)
    assert isinstance(data["aa_list_current"], bool)
    assert isinstance(data["disclosure_statement_present"], bool)
    assert isinstance(data["pending_comment_count"], int)
    assert data["pending_comment_count"] >= 0
    assert data["posture"] in POSTURES


def assert_exam_cycle(data: dict):
    _assert_common_fields(data)
    assert data["exam_type"] in ["LARGE_BANK", "INTERMEDIATE_SMALL_BANK"]
    assert isinstance(data["evaluation_window_start"], str)
    assert isinstance(data["evaluation_window_end"], str)
    assert isinstance(data["performance_context_narrative"], str)
    assert data["status"] in EXAM_STATUSES


def assert_expansion_application(data: dict):
    _assert_common_fields(data)
    assert data["application_type"] in ["BRANCH_OPENING", "BRANCH_CLOSURE", "MERGER"]
    assert is_valid_uuid(data.get("target_assessment_area_id", ""))
    assert data["status"] in APPLICATION_STATUSES


def assert_posture_invariants(data: dict):
    """PRD §2.10: posture is COMPLETE exactly when all three list flags are true
    and no comment is pending; otherwise INCOMPLETE."""
    complete = (
        data["branch_list_current"]
        and data["aa_list_current"]
        and data["disclosure_statement_present"]
        and data["pending_comment_count"] == 0
    )
    expected = "COMPLETE" if complete else "INCOMPLETE"
    assert data["posture"] == expected, (
        f"posture should be {expected} given flags "
        f"branch_list_current={data['branch_list_current']}, "
        f"aa_list_current={data['aa_list_current']}, "
        f"disclosure_statement_present={data['disclosure_statement_present']}, "
        f"pending_comment_count={data['pending_comment_count']}; got {data['posture']}"
    )
