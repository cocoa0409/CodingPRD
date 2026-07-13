"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PENDING_PAYMENT", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED",
    ], f"unexpected subscription status {data.get('status')}"
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["pending_charge_cents"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["renewal_pending"], bool)
    assert data["bundle_type"] in ["INDIVIDUAL", "COUPLE"]


def assert_questionnaire(data: dict):
    _assert_common(data)
    assert data["status"] in ["IN_PROGRESS", "COMPLETED", "LOCKED"]
    assert data["document_type"] in ["WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"]
    assert isinstance(data["required_field_count"], int)
    assert isinstance(data["answered_field_count"], int)
    assert isinstance(data["completeness_pct"], (int, float))


def assert_estate_document(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "GENERATED", "IN_REVIEW", "PENDING_EXECUTION", "EXECUTED", "SUPERSEDED", "REVOKED",
    ]
    assert data["document_type"] in ["WILL", "TRUST", "POA", "HEALTHCARE_DIRECTIVE"]
    assert isinstance(data["doc_version"], int)
    assert isinstance(data["requires_notary"], bool)
    assert isinstance(data["witness_count_required"], int)
    assert isinstance(data["witnesses_count"], int)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert data["relationship"] in ["SPOUSE", "CHILD", "RELATIVE", "CHARITY", "OTHER"]
    assert isinstance(data["allocation_pct"], (int, float))
    assert isinstance(data["is_contingent"], bool)
    assert isinstance(data["allocated_cents"], int)


def assert_asset(data: dict):
    _assert_common(data)
    assert data["asset_type"] in [
        "REAL_ESTATE", "BANK", "INVESTMENT", "VEHICLE", "PERSONAL", "BUSINESS",
    ]
    assert data["funding_status"] in ["UNFUNDED", "PENDING", "FUNDED"]
    assert isinstance(data["estimated_value_cents"], int)


def assert_executor(data: dict):
    _assert_common(data)
    assert data["status"] in ["NOMINATED", "ACCEPTED", "DECLINED", "REVOKED"]
    assert isinstance(data["priority_order"], int)


def assert_share_grant(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "REVOKED"]
    assert data["scope"] in ["VIEW", "FULL", "EXECUTOR_ACCESS"]


def assert_attorney_review(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "REQUESTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "CLOSED",
    ]


def assert_estate_summary(data: dict):
    """The estate summary is a computed read (PRD §3.9)."""
    for field in [
        "gross_estate_value_cents", "net_probate_estate_cents",
        "total_assigned_value_cents", "total_allocated_cents", "primary_beneficiary_count",
    ]:
        assert field in data, f"estate summary missing {field}"
        assert isinstance(data[field], int), f"{field} must be an integer"
