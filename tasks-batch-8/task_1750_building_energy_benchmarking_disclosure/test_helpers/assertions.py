"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    """Common fields carried by every resource (PRD §2.4).

    `version` is only asserted to be an integer: PRD §2.4 pins that it increments
    by one on every mutation but does not name the initial value.
    """
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_owner(data: dict):
    _assert_common(data, "Owner")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["standing"] in ("NORMAL", "RESTRICTED")
    assert isinstance(data["outstanding_fines_cents"], int)
    assert data["outstanding_fines_cents"] >= 0


def assert_verifier(data: dict):
    _assert_common(data, "Verifier")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["accredited"], bool)


def assert_reporting_cycle(data: dict):
    _assert_common(data, "ReportingCycle")
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["filing_deadline_at"], str)
    assert isinstance(data["covered_floor_area_threshold_sqft"], int)
    assert isinstance(data["covered_property_types"], list)
    assert isinstance(data["late_fine_daily_rate_cents"], int)
    assert isinstance(data["late_fine_cap_days"], int)
    assert isinstance(data["non_compliance_fine_cents"], int)
    assert isinstance(data["performance_standards"], list)
    assert data["status"] in ("SCHEDULED", "OPEN", "FILING_CLOSED", "PUBLISHED")
    assert isinstance(data.get("created_by_officer_id"), str)


def assert_building(data: dict):
    _assert_common(data, "Building")
    assert isinstance(data.get("owner_id"), str) and data["owner_id"]
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["gross_floor_area_sqft"], int)
    assert data["gross_floor_area_sqft"] > 0
    assert data["property_type"] in ("OFFICE", "MULTIFAMILY", "RETAIL", "HOTEL", "INDUSTRIAL")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_tenant_unit(data: dict):
    _assert_common(data, "TenantUnit")
    assert isinstance(data.get("building_id"), str) and data["building_id"]
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert isinstance(data["floor_area_sqft"], int) and data["floor_area_sqft"] > 0
    assert data["space_type"] in ("OFFICE", "RETAIL", "RESIDENTIAL", "COMMON", "OTHER")
    assert isinstance(data["occupied"], bool)


def assert_consent_grant(data: dict):
    _assert_common(data, "ConsentGrant")
    assert isinstance(data.get("tenant_unit_id"), str) and data["tenant_unit_id"]
    assert data["scope"] == "WHOLE_BUILDING_AGGREGATION"
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED", "REVOKED", "EXPIRED")


def assert_utility_account(data: dict):
    _assert_common(data, "UtilityAccount")
    assert isinstance(data.get("building_id"), str) and data["building_id"]
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["commodity"] in ("ELECTRICITY", "NATURAL_GAS", "DISTRICT_STEAM", "FUEL_OIL")


def assert_usage_record(data: dict):
    _assert_common(data, "UsageRecord")
    assert isinstance(data.get("utility_account_id"), str) and data["utility_account_id"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["consumption_value"], (int, float))
    assert data["consumption_value"] > 0
    assert data["commodity"] in ("ELECTRICITY", "NATURAL_GAS", "DISTRICT_STEAM", "FUEL_OIL")
    assert isinstance(data["kbtu"], int) and data["kbtu"] >= 0
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_benchmark_report(data: dict):
    _assert_common(data, "BenchmarkReport")
    assert isinstance(data.get("building_id"), str) and data["building_id"]
    assert isinstance(data.get("cycle_id"), str) and data["cycle_id"]
    assert data["status"] in ("DRAFT", "SUBMITTED", "FLAGGED", "VERIFIED", "CERTIFIED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0
    assert isinstance(data["aggregated_kbtu"], int) and data["aggregated_kbtu"] >= 0
    assert isinstance(data["site_eui"], (int, float)) and data["site_eui"] >= 0
    assert isinstance(data["data_completeness_pct"], (int, float))
    assert 0 <= data["data_completeness_pct"] <= 100
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    if data.get("score_as_reported") is not None:
        assert 1 <= data["score_as_reported"] <= 100
    if data.get("label_grade") is not None:
        assert data["label_grade"] in ("A", "B", "C", "D", "E", "INSUFFICIENT_DATA")


def assert_verification_record(data: dict):
    _assert_common(data, "VerificationRecord")
    assert isinstance(data.get("report_id"), str) and data["report_id"]
    assert isinstance(data.get("verifier_id"), str) and data["verifier_id"]
    assert data["status"] in ("PENDING", "SIGNED_OFF", "REJECTED")


def assert_anomaly_flag(data: dict):
    _assert_common(data, "AnomalyFlag")
    assert isinstance(data.get("report_id"), str) and data["report_id"]
    assert data["anomaly_type"] in (
        "CONSUMPTION_SPIKE",
        "VERIFICATION_REOPENED",
        "VERIFICATION_FAILED",
        "MANUAL_REVIEW",
    )
    assert data["status"] in ("OPEN", "RESOLVED", "WAIVED")


def assert_fine_assessment(data: dict):
    _assert_common(data, "FineAssessment")
    assert isinstance(data.get("building_id"), str) and data["building_id"]
    assert isinstance(data.get("cycle_id"), str) and data["cycle_id"]
    assert data["fine_type"] in ("LATE_SUBMISSION", "NON_COMPLIANCE", "PERFORMANCE_SHORTFALL")
    assert data["status"] in ("ASSESSED", "NOTICED", "PAID", "WAIVED")
    assert isinstance(data["provisional_amount_cents"], int)
    assert data["provisional_amount_cents"] >= 0
    if data.get("final_amount_cents") is not None:
        assert isinstance(data["final_amount_cents"], int) and data["final_amount_cents"] >= 0


def assert_exemption_request(data: dict):
    _assert_common(data, "ExemptionRequest")
    assert isinstance(data.get("building_id"), str) and data["building_id"]
    assert isinstance(data.get("cycle_id"), str) and data["cycle_id"]
    assert data["request_type"] in ("EXEMPTION", "EXTENSION")
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "DENIED",
        "APPEALED",
        "DENIED_FINAL",
    )
    assert isinstance(data["appeal_used"], bool)


def assert_disclosure_publication(data: dict):
    _assert_common(data, "DisclosurePublication")
    assert isinstance(data.get("cycle_id"), str) and data["cycle_id"]
    assert isinstance(data["publication_version"], int) and data["publication_version"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["included_report_count"], int)
    assert data["included_report_count"] >= 0
