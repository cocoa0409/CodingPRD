"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version trio (entities with common_fields:true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_job(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in [
        "LEAD", "INSPECTED", "QUOTED", "SOLD", "SCHEDULED",
        "INSTALLED", "WARRANTED", "CLOSED", "LOST",
    ]
    assert data["financing_status"] in ["NONE", "APPLIED", "APPROVED", "DECLINED", "CASH"]
    assert data["assessment_severity"] in ["NONE", "LOW", "MODERATE", "SEVERE"]
    assert isinstance(data["open_claim_count"], int) and data["open_claim_count"] >= 0
    assert isinstance(data["footprint_sqft"], int) and data["footprint_sqft"] >= 1
    assert data["structure_type"] in ["CRAWLSPACE", "BASEMENT", "COMBINED"]


def assert_homeowner(data: dict):
    """Homeowner is common_fields:false — only id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["credit_band"] in ["PRIME", "NEAR_PRIME", "SUBPRIME"]


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]
    if data.get("severity") is not None:
        assert data["severity"] in ["NONE", "LOW", "MODERATE", "SEVERE"]


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SENT", "ACCEPTED", "REVISED", "EXPIRED", "DECLINED"]
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    for c in ("subtotal_cents", "discount_cents", "tax_cents", "total_cents"):
        assert isinstance(data[c], int), f"{c} must be integer cents"


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DECLINED", "WITHDRAWN"]
    assert isinstance(data["amount_financed_cents"], int)
    assert isinstance(data["apr_bps"], int)
    assert isinstance(data["monthly_payment_cents"], int)


def assert_install_order(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PLANNED", "DISPATCHED", "IN_PROGRESS", "PASSED", "FAILED", "COMPLETED", "CANCELLED"]


def assert_crew_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "CONFIRMED", "RELEASED"]


def assert_warranty(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "TRANSFERRED", "VOID", "LAPSED"]
    assert isinstance(data["transfer_count"], int) and data["transfer_count"] >= 0


def assert_service_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["visit_type"] in ["ANNUAL", "CLAIM_REPAIR"]


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "IN_PROGRESS", "RESOLVED", "DENIED", "REOPENED"]
    assert data["category"] in ["WATER_INTRUSION", "PUMP_FAILURE", "STRUCTURAL"]
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_foundation_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SENT", "ACCEPTED", "REJECTED"]
