"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_program(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED", "EXHAUSTED")
    assert data["distribution_method"] in ("FIXED", "PRO_RATA")
    assert isinstance(data["fund_total_cents"], int)
    assert data["fund_total_cents"] > 0


def assert_consumer(data: dict):
    _assert_versioned(data)
    assert data["identity_status"] in ("UNVERIFIED", "VERIFIED", "SUSPENDED")
    assert isinstance(data["total_recovered_cents"], int)
    assert isinstance(data["optimistic_risk_score"], int)
    assert isinstance(data["pessimistic_risk_score"], int)
    assert 0 <= data["optimistic_risk_score"] <= 100
    assert 0 <= data["pessimistic_risk_score"] <= 100


def assert_match(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("CANDIDATE", "CONVERTED")
    assert 0 <= data["match_score"] <= 100


def assert_claim(data: dict):
    _assert_versioned(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO",
        "APPROVED", "REJECTED", "EXPIRED",
    )
    assert data["eligibility_status"] in ("UNASSESSED", "ELIGIBLE", "INELIGIBLE")
    assert isinstance(data["document_count"], int)
    assert isinstance(data["needs_info_count"], int)


def assert_document(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")
    assert data["doc_type"] in ("RECEIPT", "PROOF_OF_PURCHASE", "ID", "OTHER")


def assert_payout(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["fee_amount_cents"], \
        "net must equal gross minus fee"
    assert data["attempt_count"] >= 1


def assert_fraud_flag(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("OPEN", "CONFIRMED", "CLEARED")


def assert_fund_transaction(data: dict):
    """Append-only ledger record: id + created_at only, no version/updated_at."""
    _assert_common(data)
    assert "version" not in data, "FundTransaction is append-only; must not expose version"
    assert "updated_at" not in data, "FundTransaction is append-only; must not expose updated_at"
    assert data["type"] in ("DEBIT", "CREDIT")
    assert data["reason"] in ("PAYOUT_COMMIT", "PAYOUT_REVERSAL")


def assert_notification(data: dict):
    """Append-only ledger record: id + created_at only, no version/updated_at."""
    _assert_common(data)
    assert "version" not in data, "Notification is append-only; must not expose version"
    assert "updated_at" not in data, "Notification is append-only; must not expose updated_at"
    assert data["channel"] == "EMAIL"
    assert isinstance(data["read"], bool)
