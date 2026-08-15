"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_organization(data: dict):
    _assert_common_fields(data, "Organization")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_currency"], str) and data["base_currency"]
    assert isinstance(data["fiscal_year_start_month"], int)
    assert 1 <= data["fiscal_year_start_month"] <= 12
    assert isinstance(data["market_as_of_date"], str)


def assert_strategy(data: dict):
    _assert_common_fields(data, "MarketStrategyPolicy")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert data["target_percentile"] in (25, 50, 65, 75, 90)
    assert data["geo_differential_policy"] in ("NATIONAL", "METRO_TIER", "CUSTOM_GEO_INDEX")
    assert data["industry_cut"] in (
        "ALL_INDUSTRIES", "HIGH_TECH", "FINANCIAL_SERVICES",
        "HEALTHCARE", "MANUFACTURING", "RETAIL",
    )


def assert_employee(data: dict):
    _assert_common_fields(data, "Employee")
    assert data["status"] in ("ACTIVE", "LEAVE", "TERMINATED")
    assert isinstance(data["base_salary_annual_cents"], int)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["job_id"], str)


def assert_job(data: dict):
    _assert_common_fields(data, "Job")
    assert data["career_level"] in (
        "IC1", "IC2", "IC3", "IC4", "IC5", "M1", "M2", "M3")
    assert data["flsa_status"] in ("EXEMPT", "NON_EXEMPT")
    assert "current_market_composite_id" in data


def assert_vendor(data: dict):
    _assert_common_fields(data, "SurveyVendor")
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert data["data_use_scope"] in ("BENCHMARK_ONLY", "FULL_PARTICIPATION")
    assert data["confidentiality_tier"] in ("PUBLIC", "CONFIDENTIAL", "RESTRICTED")


def assert_survey(data: dict):
    _assert_common_fields(data, "Survey")
    assert data["status"] in (
        "DRAFT", "OPEN", "CLOSED", "SUBMITTED", "ACCEPTED", "REJECTED")
    assert isinstance(data["edition_year"], int)
    assert isinstance(data["industry_cut_supported"], list)


def assert_benchmark(data: dict):
    _assert_common_fields(data, "SurveyBenchmark")
    for field in ("p25_cents", "p50_cents", "p75_cents", "p90_cents", "sample_size"):
        assert isinstance(data[field], int), f"SurveyBenchmark.{field} must be int"


def assert_submission(data: dict):
    _assert_common_fields(data, "SurveySubmission")
    assert data["status"] in ("DRAFT", "READY", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert isinstance(data["incumbent_snapshot"], list)
    for nullable in ("prepared_at", "submitted_at", "rejection_reason"):
        assert nullable in data, f"SurveySubmission.{nullable} must be present"


def assert_match(data: dict):
    _assert_common_fields(data, "SurveyJobMatch")
    assert data["status"] in ("PROPOSED", "REVIEWED", "APPROVED", "REJECTED")
    assert data["match_confidence"] in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(data["match_weight_pct"], int)
    assert "reviewer_employee_id" in data


def assert_composite(data: dict):
    _assert_common_fields(data, "MarketComposite")
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    for field in ("blended_p25_cents", "blended_p50_cents",
                  "blended_p75_cents", "blended_p90_cents"):
        assert isinstance(data[field], int), f"MarketComposite.{field} must be int cents"
    assert isinstance(data["source_count"], int)
    assert "geo_differential_bp" in data
    assert "published_at" in data


def assert_cycle(data: dict):
    _assert_common_fields(data, "MarketAdjustmentCycle")
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED")
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["allocated_cents"], int)


def assert_adjustment(data: dict):
    _assert_common_fields(data, "MarketAdjustment")
    assert data["status"] in (
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "APPLIED", "REJECTED")
    assert isinstance(data["proposed_amount_cents"], int)


def assert_report(data: dict):
    _assert_common_fields(data, "CompensationReport")
    assert data["status"] in ("DRAFT", "FINALIZED", "PRESENTED")
    assert "snapshot_payload" in data
    assert "presented_at" in data


def assert_audit_event(data: dict):
    """AuditEvent is append-only: id + created_at only, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "AuditEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "AuditEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["target_entity"], str)
    assert isinstance(data["target_id"], str)
