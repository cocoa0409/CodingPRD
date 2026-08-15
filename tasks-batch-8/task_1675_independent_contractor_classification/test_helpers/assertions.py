"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_jurisdiction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["test_type"] in ("ABC_TEST", "COMMON_LAW_WEIGHTED", "ECONOMIC_REALITY")
    assert data["state_filing_threshold_cents"] >= 0
    assert data["max_active_exceptions"] >= 0
    assert data["min_insurance_cents"] >= 0


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["entity_type"] in (
        "INDIVIDUAL",
        "SOLE_PROPRIETOR",
        "LLC",
        "S_CORP",
        "PARTNERSHIP",
    )
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "VERIFICATION_FAILED")
    assert data["standing_status"] in (
        "GOOD_STANDING",
        "WATCH",
        "SUSPENDED_STANDING",
        "CONVERTED_TO_EMPLOYEE",
    )
    assert isinstance(data["lifetime_reported_cents"], int)
    assert data["lifetime_reported_cents"] >= 0


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "INTAKE_SUBMITTED",
        "CLASSIFIED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVAL_PENDING",
        "APPROVED",
        "ACTIVE",
        "SUSPENDED",
        "REJECTED",
        "TERMINATED",
        "CONVERTED",
    )
    assert data.get("risk_tier") in (None, "STANDARD", "ELEVATED", "HIGH")
    assert isinstance(data["scope_creep_index"], int)
    assert 0 <= data["scope_creep_index"] <= 100
    assert data["scope_creep_tier"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")


def assert_questionnaire(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert isinstance(data["complete"], bool)


def assert_determination(data: dict):
    # Append-only record: id + created_at only; no updated_at / version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["jurisdiction_test_type"] in (
        "ABC_TEST",
        "COMMON_LAW_WEIGHTED",
        "ECONOMIC_REALITY",
    )
    assert isinstance(data["questionnaire_revision"], int)
    assert data["outcome"] in ("CONTRACTOR", "EMPLOYEE_RISK")
    assert isinstance(data["failed_prongs"], int)
    assert isinstance(data["superseded"], bool)


def assert_exception_grant(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data.get("granted_by_user_id"), str)


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "EXECUTED", "SUSPENDED", "TERMINATED", "EXPIRED")
    assert isinstance(data["rate_cents"], int) and data["rate_cents"] > 0
    assert data["rate_unit"] in ("HOURLY", "DAILY", "PROJECT")


def assert_amendment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "APPLIED", "REJECTED", "VOIDED")


def assert_review(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "CLOSED")
    assert isinstance(data["findings_count"], int) and data["findings_count"] >= 0


def assert_audit(data: dict):
    _assert_common_fields(data)
    assert data["audit_type"] in ("SCREENING", "FIELDWORK")
    assert data["status"] in ("OPEN", "FINDINGS_FINALIZED", "REMEDIATION", "CLOSED")
    assert data["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert isinstance(data["open_action_count"], int) and data["open_action_count"] >= 0


def assert_remediation_action(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("OPEN", "CLOSED", "WAIVED")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")


def assert_filing(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "ACCEPTED",
        "REJECTED_AGENCY",
        "SUPERSEDED",
        "VOID",
    )
    assert data["kind"] in ("ORIGINAL", "CORRECTION")
    assert isinstance(data["reportable_amount_cents"], int)
    assert data["reportable_amount_cents"] >= 0
    assert isinstance(data["federal_filing_required"], bool)
    assert isinstance(data["state_filing_required"], bool)
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0


def assert_inquiry(data: dict):
    _assert_common_fields(data)
    assert data["agency_type"] in ("IRS", "DOL", "STATE_EDD", "STATE_UI")
    assert data["status"] in ("RECEIVED", "RESPONSE_SUBMITTED", "RESOLVED", "AUDIT_OPENED")
    assert isinstance(data["exposure_estimate_cents"], int)
    assert data["exposure_estimate_cents"] >= 0


def assert_conversion(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "INITIATED",
        "OFFER_EXTENDED",
        "COMPLETED",
        "DECLINED",
        "RESCINDED",
    )
    assert isinstance(data["w2_equivalent_total_cents"], int)
    assert isinstance(data["lookback_delta_cents"], int)


def assert_engagement_invariants(data: dict):
    """Domain invariants that hold for any engagement read (PRD §3.3, §3.4, §3.7)."""
    assert_engagement(data)
    if data.get("risk_tier") is not None:
        assert data["required_approval_count"] == {
            "STANDARD": 1,
            "ELEVATED": 2,
            "HIGH": 3,
        }[data["risk_tier"]]
    idx = data["scope_creep_index"]
    expected_tier = (
        "LOW" if idx < 25 else "MODERATE" if idx < 50 else "HIGH" if idx < 75 else "CRITICAL"
    )
    assert data["scope_creep_tier"] == expected_tier
