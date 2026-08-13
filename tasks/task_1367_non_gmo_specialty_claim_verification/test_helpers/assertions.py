"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_claim_standard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_code"], str) and data["claim_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ingredient_threshold_pct"], (int, float))
    assert data["ingredient_threshold_pct"] > 0
    assert isinstance(data["exemption_max_weight_pct"], (int, float))
    assert data["exemption_max_weight_pct"] >= 0
    assert isinstance(data["audit_validity_months"], int)
    assert isinstance(data["renewal_window_days"], int)
    assert isinstance(data["license_term_days"], int)


def assert_brand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["lifetime_penalty_points"], int)
    assert isinstance(data["rolling_penalty_points"], int)
    assert data["standing_status"] in ("GOOD_STANDING", "PROBATION")
    assert isinstance(data["verified_product_count"], int)


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_id"], str)
    assert isinstance(data["standard_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["gtin"], str)
    assert isinstance(data["annual_volume_units"], int)
    assert data["enrollment_status"] in (
        "DRAFT", "SUBMITTED", "UNDER_EVALUATION", "VERIFIED", "REJECTED",
        "RENEWAL_DUE", "SUSPENDED", "REVOKED", "LAPSED",
    )
    assert "rejection_reason" in data
    assert isinstance(data["provisional_exposure_pct"], (int, float))
    assert isinstance(data["confirmed_exposure_pct"], (int, float))


def assert_ingredient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["name"], str)
    assert data["crop_type"] in ("HIGH_RISK", "LOW_RISK", "NON_CROP")
    assert isinstance(data["declared_weight_pct"], (int, float))
    assert 0 < data["declared_weight_pct"] <= 100
    assert isinstance(data["is_exempt"], bool)
    assert isinstance(data["requires_pcr"], bool)
    assert isinstance(data["requires_affidavit"], bool)
    assert data["compliance_status"] in (
        "NON_COMPLIANT", "COMPLIANT", "EXEMPTED", "PENDING",
    )


def assert_affidavit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ingredient_id"], str)
    assert isinstance(data["supplier_name"], str)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED")
    assert isinstance(data["submitted_by_user_id"], str)


def assert_sampling_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert data["risk_point"] in ("INGREDIENT_INTAKE", "IN_PROCESS", "FINISHED_PRODUCT")
    assert isinstance(data["required_sample_count"], int)
    assert isinstance(data["confirmed_sample_count"], int)
    assert data["status"] in ("ACTIVE", "COMPLETED", "CANCELLED")
    assert "superseded_by_plan_id" in data


def assert_sample(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sampling_plan_id"], str)
    assert isinstance(data["ingredient_id"], str)
    assert "result_gmo_pct" in data
    if data["result_gmo_pct"] is not None:
        assert isinstance(data["result_gmo_pct"], (int, float))
        assert data["result_gmo_pct"] >= 0
    assert "outcome" in data
    if data["outcome"] is not None:
        assert data["outcome"] in ("COMPLIANT", "NON_COMPLIANT")
    assert data["status"] in ("COLLECTED", "RESULT_RECORDED", "CONFIRMED", "INVALIDATED")


def assert_facility_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["brand_id"], str)
    assert isinstance(data["facility_name"], str)
    assert isinstance(data["auditor_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in ("SCHEDULED", "REPORT_SUBMITTED", "PASSED", "FAILED")
    assert "traceability_score_pct" in data
    if data["traceability_score_pct"] is not None:
        assert isinstance(data["traceability_score_pct"], (int, float))
    assert "decided_at" in data


def assert_license(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["license_code"], str)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert "suspended_at" in data
    assert "suspend_reason" in data
    if data["suspend_reason"] is not None:
        assert data["suspend_reason"] in ("ENFORCEMENT", "SCOPE_CHANGE")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED")


def assert_enforcement_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_id"], str)
    assert data["source"] in (
        "CONSUMER_COMPLAINT", "MARKETPLACE_MONITOR", "RETEST_FAILURE",
    )
    assert isinstance(data["description"], str)
    assert isinstance(data["opened_by_user_id"], str)
    assert "resolved_by_user_id" in data
    assert "sanction" in data
    assert isinstance(data["penalty_points"], int)
    assert "substantiated_at" in data
    assert data["status"] in ("OPENED", "DISMISSED", "SUBSTANTIATED")
