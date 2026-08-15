"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common system-managed fields of PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_study(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["analysis_period_start"], str)
    assert isinstance(data["analysis_period_end"], str)
    assert isinstance(data["protected_classes"], list) and data["protected_classes"]
    assert data["status"] in [
        "DRAFT", "MODELING", "UNDER_LEGAL_REVIEW", "PRIVILEGED_FINAL",
        "REMEDIATION_OPEN", "MONITORING", "CLOSED",
    ]
    assert isinstance(data["review_rounds"], int)
    assert isinstance(data["privileged_model_run_ids"], list)


def assert_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["gender_class"] in ["MALE", "FEMALE", "NONBINARY"]
    assert data["ethnicity_class"] in ["WHITE", "BLACK", "HISPANIC", "ASIAN", "OTHER"]
    assert data["age_band"] in ["UNDER_40", "FORTY_PLUS"]
    assert isinstance(data["job_family"], str)
    assert isinstance(data["job_level"], int)
    assert isinstance(data["location_code"], str)
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["bonus_cents"], int)
    assert isinstance(data["annualized_base_cents"], int)
    assert isinstance(data["tenure_years"], (int, float))


def assert_group(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["job_family"], str)
    assert isinstance(data["min_job_level"], int)
    assert isinstance(data["max_job_level"], int)
    assert isinstance(data["location_code"], str)
    assert isinstance(data["member_count"], int)
    assert data["status"] in ["DRAFT", "LOCKED", "ANALYZED"]


def assert_model_run(data: dict):
    _assert_common(data)
    assert isinstance(data["comparator_group_id"], str)
    assert isinstance(data["study_id"], str)
    assert data["methodology"] in ["REGRESSION_OLS", "COHORT_MEDIAN"]
    assert isinstance(data["run_index"], int)
    assert isinstance(data["per_class_results"], dict)
    assert data["status"] in ["PROVISIONAL", "FINAL", "SUPERSEDED"]


def assert_finding(data: dict):
    _assert_common(data)
    assert isinstance(data["model_run_id"], str)
    assert isinstance(data["comparator_group_id"], str)
    assert isinstance(data["study_id"], str)
    assert data["protected_class"] in ["GENDER", "ETHNICITY", "AGE_BAND"]
    assert isinstance(data["class_value"], str)
    assert isinstance(data["reference_class"], str)
    assert isinstance(data["adjusted_gap_pct"], (int, float))
    assert isinstance(data["p_value"], (int, float))
    assert isinstance(data["affected_headcount"], int)
    assert isinstance(data["is_actionable"], bool)
    assert data["status"] in ["FLAGGED", "TARGETED", "MONITORED", "DISMISSED", "RESOLVED"]


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["total_budget_cents"], int)
    assert data["allocation_strategy"] in ["FULL_CLOSURE", "PRO_RATA"]
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["rejection_count"], int)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "EXECUTING", "FULLY_COMMITTED", "COMPLETED",
    ]


def assert_adjustment(data: dict):
    _assert_common(data)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["gap_finding_id"], str)
    assert isinstance(data["employee_snapshot_id"], str)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["proposed_increase_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert data["status"] in ["PROPOSED", "APPROVED", "REJECTED", "EFFECTIVE", "REVERSED"]


def assert_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert data["report_type"] in ["EEO_WORKFORCE_COMP", "STATE_PAY_DATA"]
    assert isinstance(data["reporting_year"], int)
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["COMPILING", "INTERNAL_REVIEW", "SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_jurisdiction_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]


def assert_posting(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_rule_id"], str)
    assert isinstance(data["job_posting_ref"], str) and data["job_posting_ref"]
    assert isinstance(data["title"], str)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED"]


def assert_pipeline_analysis(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert data["stage"] in ["APPLICATION", "SCREEN", "INTERVIEW", "OFFER", "HIRE", "PROMOTION"]
    assert isinstance(data["records"], list) and data["records"]
    assert isinstance(data["pass_rates"], dict)
    assert isinstance(data["adverse_impact_flag"], bool)


def assert_monitoring_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["study_id"], str)
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["cycle_index"], int)
    assert data["status"] in ["SCHEDULED", "DUE", "RE_TESTING", "COMPLETED"]


def assert_plan_budget_invariant(plan: dict):
    """PRD §2.10: committed_cents + remaining_cents always equals total_budget_cents."""
    assert plan["committed_cents"] + plan["remaining_cents"] == plan["total_budget_cents"], (
        f"Plan invariant broken: {plan['committed_cents']} + {plan['remaining_cents']} "
        f"!= {plan['total_budget_cents']}"
    )


def band_rows_as_set(band_rows):
    """Normalize a band_rows list into a set of (band, gender_class, headcount) tuples
    so tests can compare band tables without depending on row order."""
    return {
        (row["band"], row["gender_class"], row["headcount"]) for row in (band_rows or [])
    }
