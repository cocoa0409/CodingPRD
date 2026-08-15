"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """Every resource carries the four system-maintained properties (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be a positive int"


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["ein"], str) and len(data["ein"]) == 9 and data["ein"].isdigit()
    assert data["entity_type"] in [
        "CORPORATION", "S_CORPORATION", "PARTNERSHIP", "LLC",
        "SOLE_PROPRIETORSHIP", "NONPROFIT", "GOVERNMENTAL",
    ]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert data["plan_type"] in ["401K", "CAFETERIA_125", "DEPENDENT_CARE_FSA"]
    assert isinstance(data["plan_number"], str) and data["plan_number"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_plan_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["effective_start"], str)
    assert data["comp_definition"] in ["W2", "SEC415", "SEC3401"]
    assert data["safe_harbor_design"] in ["NONE", "BASIC_MATCH", "ENHANCED_MATCH", "QNEC_3PCT", "QACA"]
    assert data["entry_frequency"] in ["IMMEDIATE", "MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"]
    assert data["status"] in ["DRAFT", "ADOPTED", "SUPERSEDED"]


def assert_plan_year(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year_label"], int)
    assert isinstance(data["year_start"], str)
    assert isinstance(data["year_end"], str)
    assert isinstance(data["census_lock_version"], int) and data["census_lock_version"] >= 0
    assert data["status"] in [
        "DRAFT", "CENSUS_COLLECTING", "CENSUS_LOCKED", "TESTING",
        "RESULTS_REVIEW", "CORRECTING", "FILED", "TERMINATED",
    ]


def assert_census_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ssn"], str) and len(data["ssn"]) == 9
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["employment_status"] in ["ACTIVE", "TERMINATED", "LEAVE_OF_ABSENCE"]


def assert_compensation_record(data: dict):
    _assert_common_fields(data)
    assert data["comp_source"] in ["W2", "SEC415", "SEC3401"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["period"] in ["CURRENT_YEAR", "PRIOR_YEAR"]


def assert_contribution(data: dict):
    _assert_common_fields(data)
    assert data["contribution_type"] in [
        "ELECTIVE_DEFERRAL", "MATCH", "QNEC", "QMAC",
        "PROFIT_SHARING", "CAFETERIA_PRETAX", "DEPENDENT_CARE_ELECTIVE",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["POSTED", "PENDING_DISTRIBUTION", "DISTRIBUTED", "RECHARACTERIZED", "FORFEITED"]


def assert_regulatory_limit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year_label"], int)
    assert isinstance(data["hce_comp_threshold_cents"], int)
    assert isinstance(data["sec402g_limit_cents"], int)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_safe_harbor_election(data: dict):
    _assert_common_fields(data)
    assert data["design"] in ["BASIC_MATCH", "ENHANCED_MATCH", "QNEC_3PCT", "QACA"]
    assert data["status"] in ["PROPOSED", "EFFECTIVE", "SUSPENDED", "REVOKED"]


def assert_safe_harbor_notice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["notice_period_start"], str)
    assert isinstance(data["notice_period_end"], str)
    assert data["status"] in ["DRAFT", "DISTRIBUTED", "ACKNOWLEDGED", "LAPSED"]


def assert_test_run(data: dict):
    _assert_common_fields(data)
    assert data["test_scope"] in [
        "COVERAGE_410B", "ADP_401K", "ACP_401M", "TOP_HEAVY_416",
        "CAFETERIA_125", "DEPENDENT_CARE_129", "FULL_SUITE",
    ]
    assert data["run_mode"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["QUEUED", "RUNNING", "PASSED", "FAILED", "SUPERSEDED", "VOID"]


def assert_test_result_line(data: dict):
    _assert_common_fields(data)
    assert data["metric"] in [
        "COVERAGE_RATIO_PCT", "ADP_HCE_PCT", "ADP_NHCE_PCT", "ADP_CEILING_PCT",
        "ACP_HCE_PCT", "ACP_NHCE_PCT", "ACP_CEILING_PCT", "TOP_HEAVY_RATIO_PCT",
        "CAFETERIA_ELIGIBILITY_PCT", "CAFETERIA_UTILIZATION_PCT",
        "DEPENDENT_CARE_55PCT_AVG_PCT", "KEY_EMPLOYEE_CONCENTRATION_PCT",
    ]
    assert isinstance(data["value_pct"], (int, float))
    assert data["outcome"] in ["PASS", "FAIL", "NOT_APPLICABLE"]


def assert_correction(data: dict):
    _assert_common_fields(data)
    assert data["correction_type"] in [
        "CORRECTIVE_DISTRIBUTION", "QNEC_CONTRIBUTION", "QMAC_REALLOCATION",
        "RECHARACTERIZATION", "PLAN_AMENDMENT_RETRO",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["PROPOSED", "APPROVED", "EXECUTED", "VOIDED"]
    assert data["excise_status"] in ["NOT_ASSESSED", "ACCRUING", "ASSESSED", "PAID"]


def assert_pct(value, expected, tolerance=0.00005):
    """Percentages are carried to 4 decimal places, rounded half up (PRD §2.6)."""
    assert value == pytest.approx(expected, abs=tolerance), (
        f"Expected {expected}, got {value}"
    )


def get_result_line(result_lines: list, metric: str) -> dict:
    """Extract the single result line for a metric from a run's result lines."""
    matches = [line for line in result_lines if line.get("metric") == metric]
    assert len(matches) == 1, f"Expected exactly one {metric} line, got {len(matches)}"
    return matches[0]
