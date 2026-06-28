"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract
using the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_property(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["address_line"], str)
    assert data["foundation_type"] in ("SLAB", "BASEMENT", "CRAWLSPACE")
    assert isinstance(data["floor_area_sqft"], int) and data["floor_area_sqft"] > 0
    assert data["posture"] in (
        "OPEN", "TESTING", "MITIGATION_REQUIRED", "MITIGATING", "CLEARED",
    )
    assert isinstance(data["open_test_count"], int)
    assert isinstance(data["version"], int)


def assert_inspector(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["nrpp_license_id"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["version"], int)


def assert_crew(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["crew_name"], str)
    assert isinstance(data["max_jobs_per_day"], int) and data["max_jobs_per_day"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["version"], int)


def assert_radon_test(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be UUID"
    assert data["test_kind"] in ("SHORT_TERM_48HR", "CONTINUOUS_MONITOR")
    assert data["purpose"] in ("INITIAL", "POST_MITIGATION", "RECURRING")
    assert data["status"] in ("PLACED", "RETRIEVED", "RESULT_READY", "VOIDED")
    assert isinstance(data["version"], int)


def assert_mitigation_job(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be UUID"
    assert data["status"] in (
        "DESIGN", "QUOTED", "SCHEDULED", "INSTALLED",
        "RETEST_PENDING", "CLEARED", "REWORK", "CANCELLED",
    )
    assert isinstance(data["version"], int)


def assert_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("mitigation_job_id", "")), "mitigation_job_id must be UUID"
    assert data["status"] in ("ISSUED", "CLOSED", "REVOKED")
    assert isinstance(data["version"], int)


def assert_warranty(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["coverage_status"] in ("ACTIVE", "EXPIRED", "CANCELLED")
    assert data["claim_status"] in ("NONE", "CLAIM_OPEN", "CLAIM_RESOLVED")
    assert data["refund_method"] in ("STRAIGHT_LINE", "STEP_TIER")
    assert isinstance(data["covered_system_price_cents"], int)
    assert isinstance(data["version"], int)


def assert_retest_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ARMED", "PAUSED", "ENDED")
    assert isinstance(data["interval_days"], int) and data["interval_days"] >= 1
    assert isinstance(data["fired_count"], int)
    assert isinstance(data["version"], int)


def assert_payment_record(data: dict):
    """Append-only ledger entry: id + created_at only; no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("DEPOSIT", "BALANCE", "REFUND")
    assert isinstance(data["amount_cents"], int)
