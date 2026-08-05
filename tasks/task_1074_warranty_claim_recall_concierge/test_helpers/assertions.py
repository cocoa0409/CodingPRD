"""Entity assertions for the Warranty-Claim & Recall Concierge API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["primary_email"], str)
    assert isinstance(data["display_name"], str)
    assert data["exposure_scoring_mode"] in ("WEIGHTED", "COUNT")
    assert isinstance(data["recall_exposure_score"], int)
    assert isinstance(data["active_claim_count"], int)
    assert data["status"] == "ACTIVE"


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a UUID"
    assert data["role"] in ("OWNER", "ADULT", "MINOR")
    assert data["status"] == "ACTIVE"


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "PREMIUM")
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")
    assert isinstance(data["claims_used"], int)
    assert isinstance(data["auto_renew"], bool)


def assert_manufacturer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["coordination_enabled"], bool)
    assert isinstance(data["rma_required"], bool)


def assert_product(data: dict):
    _assert_common(data)
    assert data["registration_status"] in ("REGISTERED", "ARCHIVED")
    assert data["recall_status"] in ("NONE", "RECALLED", "REMEDIED")
    assert data["coverage_status"] in ("UNDER_WARRANTY", "EXPIRED", "COVERED_BY_RECALL")
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["serial_number"], int)


def assert_recall_notice(data: dict):
    _assert_common(data)
    assert data["severity"] in ("LOW", "HIGH", "CRITICAL")
    assert data["remedy_type"] in ("REPAIR", "REPLACE", "REFUND")
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")
    assert isinstance(data["matched_product_count"], int)


def assert_recall_match(data: dict):
    _assert_common(data)
    assert data["status"] in ("MATCHED", "ACKNOWLEDGED", "REMEDIED", "DISMISSED")
    assert isinstance(data["severity_weight"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ("WARRANTY", "RECALL")
    assert data["resolution_preference"] in ("REPLACEMENT", "REFUND")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_DOCS",
        "APPROVED", "REJECTED", "RESOLVED", "WITHDRAWN",
    )


def assert_claim_document(data: dict):
    """ClaimDocument is immutable (common_fields:false): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["doc_type"] in ("RECEIPT", "PHOTO", "SERIAL_PROOF", "OTHER")


def assert_resolution(data: dict):
    _assert_common(data)
    assert data["mode"] in ("REPLACEMENT", "REFUND")
    assert data["rma_status"] in ("NONE", "REQUESTED", "AUTHORIZED")
    assert data["status"] in ("PENDING", "DISPATCHED", "COMPLETED", "FAILED")
