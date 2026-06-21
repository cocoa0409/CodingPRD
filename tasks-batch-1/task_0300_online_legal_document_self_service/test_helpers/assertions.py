"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id (UUID, no prefix) + created_at/updated_at (ISO 8601) + integer version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["state_of_residence"] in ("CA", "NY", "TX", "FL")


def assert_subscription_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("FREE", "STANDARD", "PREMIUM")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_project_credits"], int) and data["included_project_credits"] >= 0
    assert isinstance(data["included_clause_count"], int) and data["included_clause_count"] >= 0
    assert 0.0 <= data["subscription_discount_pct"] <= 1.0
    assert 0.0 <= data["review_discount_pct"] <= 1.0


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["tier"] in ("FREE", "STANDARD", "PREMIUM")
    assert data["status"] in ("PENDING_PAYMENT", "ACTIVE", "PAST_DUE", "CANCELLED")
    assert isinstance(data["credits_used"], int) and data["credits_used"] >= 0
    assert isinstance(data["credits_remaining"], int) and data["credits_remaining"] >= 0


def assert_clause_template(data: dict):
    _assert_common(data)
    assert data["document_type"] in ("WILL", "LLC", "POA", "LEASE")
    assert data["state_code"] in ("CA", "NY", "TX", "FL")
    assert isinstance(data["is_mandatory"], bool)
    assert isinstance(data["clause_key"], str) and len(data["clause_key"]) > 0


def assert_document_project(data: dict):
    _assert_common(data)
    assert data["document_type"] in ("WILL", "LLC", "POA", "LEASE")
    assert data["state_code"] in ("CA", "NY", "TX", "FL")
    assert data["status"] in (
        "DRAFT", "IN_PROGRESS", "ASSEMBLED", "IN_REVIEW", "CHANGES_REQUESTED",
        "FINALIZED", "SIGNED", "STORED", "ABANDONED", "STORAGE_LOCKED",
    )
    assert isinstance(data["attorney_review_addon"], bool)
    assert 0.0 <= data["provisional_completeness"] <= 1.0
    assert 0.0 <= data["assembled_completeness"] <= 1.0
    assert isinstance(data["assembled_clause_count"], int) and data["assembled_clause_count"] >= 0
    assert isinstance(data["credit_held"], bool)


def assert_assembled_clause(data: dict):
    """AssembledClause is immutable: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "AssembledClause must NOT carry updated_at"
    assert "version" not in data, "AssembledClause must NOT carry version"
    assert isinstance(data["clause_key"], str) and len(data["clause_key"]) > 0
    assert isinstance(data["is_mandatory"], bool)
    assert isinstance(data["body_text"], str)


def assert_document_revision(data: dict):
    _assert_common(data)
    assert data["status"] in ("FINAL", "SUPERSEDED")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["clause_snapshot_count"], int) and data["clause_snapshot_count"] >= 0


def assert_attorney(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["bar_state"] in ("CA", "NY", "TX", "FL")


def assert_attorney_review(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "ASSIGNED", "IN_REVIEW", "APPROVED", "CHANGES_REQUESTED", "CANCELLED",
    )
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0


def assert_signature_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SENT", "PARTIALLY_SIGNED", "COMPLETED", "VOIDED")
    assert isinstance(data["signer_emails"], list)
    assert isinstance(data["signed_count"], int) and data["signed_count"] >= 0


def assert_notary_referral(data: dict):
    _assert_common(data)
    assert data["status"] == "REFERRED"
    assert data["referral_state_code"] in ("CA", "NY", "TX", "FL")


def assert_order(data: dict):
    _assert_common(data)
    for f in (
        "provisional_quote_cents", "final_invoice_cents", "amount_charged_cents",
        "amount_refunded_cents", "net_collected_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer cent amount"


def assert_update_reminder(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "SENT", "CANCELLED")


def assert_money_conserved(order: dict):
    """PRD §3.8 invariant: net_collected_cents == amount_charged_cents - amount_refunded_cents."""
    assert order["net_collected_cents"] == order["amount_charged_cents"] - order["amount_refunded_cents"], (
        f"net_collected_cents {order['net_collected_cents']} != charged "
        f"{order['amount_charged_cents']} - refunded {order['amount_refunded_cents']}"
    )
