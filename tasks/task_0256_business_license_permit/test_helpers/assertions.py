"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}(data) validate response structure and field types
against the PRD contract. Money fields are checked for two-decimal precision
(§2.6); the compliance_risk_score is checked for integer clamping to [0,100].
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _common_audited(data: dict):
    """id/created_at/updated_at/version checks for mutable, audited entities (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_activity_category(data: dict):
    """ActivityCategory is config-only: id + created_at, NO updated_at/version (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ActivityCategory must NOT expose updated_at"
    assert "version" not in data, "ActivityCategory must NOT expose version"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["activity_base_risk"], int)
    assert 0 <= data["activity_base_risk"] <= 40
    assert isinstance(data["required_inspection_count"], int)
    assert 0 <= data["required_inspection_count"] <= 5
    assert isinstance(data["requires_zoning_check"], bool)
    assert data["term_months"] in (12, 24, 36)
    assert isinstance(data["allowed_zones"], list) and len(data["allowed_zones"]) > 0


def assert_business(data: dict):
    _common_audited(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["owner_name"], str) and len(data["owner_name"]) > 0
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0
    assert data["standing"] in ("GOOD", "DELINQUENT", "REVOKED")
    assert isinstance(data["prior_revocation_flag"], bool)
    assert isinstance(data["compliance_risk_score"], int)
    assert 0 <= data["compliance_risk_score"] <= 100, "risk score clamped to [0,100]"


def assert_application(data: dict):
    _common_audited(data)
    assert isinstance(data["business_id"], str)
    assert isinstance(data["activity_category_id"], str)
    assert isinstance(data["declared_employee_count"], int)
    assert isinstance(data["requested_zone_code"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ZONING_CLEARED", "VARIANCE_REQUIRED",
        "APPROVED", "REJECTED", "ISSUED", "WITHDRAWN",
    )
    assert data["zoning_status"] in ("PENDING", "CLEARED", "VARIANCE_REQUIRED")
    assert isinstance(data["estimated_fee"], (int, float))
    assert_cost_precision(data["estimated_fee"])


def assert_inspection(data: dict):
    _common_audited(data)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["inspector_user_id"], str)
    assert data["result"] in ("SCHEDULED", "PASSED", "FAILED")


def assert_license(data: dict):
    _common_audited(data)
    assert isinstance(data["business_id"], str)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["activity_category_id"], str)
    assert data["status"] in ("ACTIVE", "DELINQUENT", "REVOKED", "SURRENDERED")
    assert is_iso8601_timestamp(data["issued_on"]), "issued_on must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_on"]), "expires_on must be ISO 8601"
    assert isinstance(data["final_fee"], (int, float))
    assert_cost_precision(data["final_fee"])
    assert isinstance(data["renewal_count"], int)
    assert data["renewal_count"] >= 0


def assert_endorsement(data: dict):
    _common_audited(data)
    assert isinstance(data["license_id"], str)
    assert data["kind"] in ("LATE_HOURS", "OUTDOOR_SEATING", "HAZMAT_HANDLING", "SIDEWALK_USE")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "VOIDED")


def assert_ownership_transfer(data: dict):
    _common_audited(data)
    assert isinstance(data["license_id"], str)
    assert isinstance(data["from_business_id"], str)
    assert isinstance(data["to_business_id"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "COMPLETED", "CANCELLED")
    assert isinstance(data["transfer_fee"], (int, float))
    assert_cost_precision(data["transfer_fee"])


def assert_fee_assessment(data: dict):
    _common_audited(data)
    assert data["kind"] in (
        "APPLICATION_FEE", "ISSUANCE_FEE", "RENEWAL_FEE",
        "DELINQUENCY_PENALTY", "TRANSFER_FEE", "REVERSAL",
    )
    assert isinstance(data["amount"], (int, float))
    assert_cost_precision(data["amount"])
    assert isinstance(data["settled"], bool)


# ─── Ledger helpers ────────────────────────────────────────────────────────
def fee_sum(assessments: list) -> float:
    """Net signed sum of fee-assessment amounts (the ledger conservation quantity)."""
    return round(sum(a["amount"] for a in assessments), 2)


def assessments_of_kind(assessments: list, kind: str) -> list:
    return [a for a in assessments if a["kind"] == kind]
