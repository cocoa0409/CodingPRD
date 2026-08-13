"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdjudicationStatus,
    AuditStatus,
    CandidateStatus,
    CaseStatus,
    ConsentStatus,
    DisputeStatus,
    FulfillmentStatus,
    IAStatus,
    MatrixStatus,
    OrderType,
    PackageStatus,
    RecommendedOutcome,
    ReportStatus,
    RuleStatus,
    VendorStatus,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert is_iso8601_timestamp(value), f"Not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Assert two ISO 8601 instants denote the same point in time, regardless
    of whether fractional digits are rendered."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """PRD Common Resource Properties: id is a prefix-free UUID; created_at and
    updated_at are ISO 8601 UTC timestamps; version is an integer."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_tat_business_hours"], int)
    assert isinstance(data["max_concurrent_orders"], int)
    assert data["max_concurrent_orders"] >= 1
    assert isinstance(data["surcharge_cents"], int)
    assert data["status"] in [s.value for s in VendorStatus]
    assert isinstance(data["active_order_count"], int)
    assert isinstance(data["consecutive_sla_breaches"], int)
    assert isinstance(data["accuracy_bps_finalized"], int)
    assert isinstance(data["accuracy_bps_including_draft"], int)


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vendor_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    assert isinstance(data["mismatches_found"], int)
    assert 0 <= data["mismatches_found"] <= data["sample_size"]
    assert isinstance(data["mismatch_rate_bps"], int)
    assert data["status"] in [s.value for s in AuditStatus]
    assert isinstance(data["rescreen_order_ids"], list)


def assert_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["check_types"], list) and len(data["check_types"]) >= 1
    assert isinstance(data["tat_business_hours"], int)
    assert data["tat_business_hours"] >= 1
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in [s.value for s in PackageStatus]


def assert_jurisdiction_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["screening_gate_stage"] in ("POST_CONDITIONAL_OFFER", "ANYTIME")
    assert isinstance(data["lookback_years_limit"], int)
    assert isinstance(data["arrest_records_considerable"], bool)
    assert isinstance(data["lookback_exemption_salary_cents"], int)
    assert isinstance(data["pre_adverse_wait_business_days"], int)
    assert isinstance(data["individualized_assessment_required"], bool)
    assert isinstance(data["credit_check_allowed"], bool)
    assert data["status"] in [s.value for s in RuleStatus]


def assert_matrix(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["rules"], list) and len(data["rules"]) >= 1
    for rule in data["rules"]:
        assert rule["min_severity"] in ("LOW", "MEDIUM", "HIGH")
        assert rule["action"] in ("CLEAR", "IA_REQUIRED", "ADVERSE_ELIGIBLE")
        assert isinstance(rule["max_recency_years"], int)
    assert data["status"] in [s.value for s in MatrixStatus]


def assert_position(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["department"], str)
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert isinstance(data["annual_salary_cents"], int)
    assert data["annual_salary_cents"] >= 0


def assert_candidate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["home_jurisdiction_code"], str)
    assert data["status"] in [s.value for s in CandidateStatus]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["position_id"])
    assert data["order_type"] in [t.value for t in OrderType]
    assert data["fulfillment_status"] in [s.value for s in FulfillmentStatus]
    assert data["adjudication_status"] in [s.value for s in AdjudicationStatus]
    assert isinstance(data["escalation_level"], int)
    if data.get("recommended_outcome") is not None:
        assert data["recommended_outcome"] in [o.value for o in RecommendedOutcome]


def assert_consent(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["disclosure_form_id"], str)
    assert isinstance(data["contains_extraneous_terms"], bool)
    assert is_iso8601_timestamp(data["authorization_signed_at"])
    assert data["status"] in [s.value for s in ConsentStatus]


def assert_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["vendor_id"])
    assert is_iso8601_timestamp(data["delivered_at"])
    assert isinstance(data["sla_breached"], bool)
    assert data["status"] in [s.value for s in ReportStatus]


def assert_finding(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["report_id"])
    assert isinstance(data["check_type"], str)
    assert isinstance(data["offense_category"], str)
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["disposition"] in ("CONVICTION", "DISMISSED", "PENDING", "ARREST_ONLY")
    assert isinstance(data["considerable"], bool)


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    for field in (
        "green_factor_nature_gravity",
        "green_factor_time_elapsed",
        "green_factor_job_relatedness",
    ):
        assert data[field] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["evidence_considered"], bool)
    assert data["decision"] in ("PROCEED_ADVERSE", "CLEAR_CANDIDATE")
    assert data["status"] in [s.value for s in IAStatus]


def assert_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["initiated_by_user_id"], str)
    assert is_iso8601_timestamp(data["pre_notice_sent_at"])
    assert isinstance(data["wait_business_days_required"], int)
    assert isinstance(data["total_hold_business_days"], int)
    assert is_iso8601_timestamp(data["earliest_final_notice_at"])
    assert data["status"] in [s.value for s in CaseStatus]


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["reason"], str) and len(data["reason"]) >= 10
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["overdue"], bool)
    assert data["status"] in [s.value for s in DisputeStatus]


def assert_vendor_capacity_invariant(vendor: dict, dispatched_orders: list):
    """active_order_count equals the count of that vendor's orders with
    fulfillment_status DISPATCHED, after every mutation."""
    expected = sum(
        1
        for o in dispatched_orders
        if o.get("vendor_id") == vendor["id"]
        and o.get("fulfillment_status") == FulfillmentStatus.DISPATCHED.value
    )
    assert vendor["active_order_count"] == expected, (
        f"active_order_count {vendor['active_order_count']} != {expected} "
        "DISPATCHED orders"
    )
