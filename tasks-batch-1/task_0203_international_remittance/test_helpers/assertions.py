"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Versioned entities carry id/created_at/updated_at/version; immutable
audit records carry only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_versioned_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version begins at 1"


def _assert_audit_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # Immutable audit records carry no updated_at and no version.
    assert "updated_at" not in data, "audit records carry no updated_at"
    assert "version" not in data, "audit records carry no version"


def assert_corridor(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["reserved_minor"], int)
    assert data["reserved_minor"] >= 0, "reserved_minor never goes negative"
    assert isinstance(data["enabled_payout_methods"], list)
    for m in data["enabled_payout_methods"]:
        assert m in ("BANK", "CASH_PICKUP", "WALLET")


def assert_fx_rate(data: dict):
    _assert_audit_common(data)
    assert isinstance(data["mid_rate_micro"], int)
    assert is_valid_uuid(data.get("corridor_id", ""))


def assert_sender(data: dict):
    _assert_versioned_common(data)
    assert data["kyc_tier"] in ("TIER0", "TIER1", "TIER2")
    assert data["status"] in ("ACTIVE", "BLOCKED")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_recipient(data: dict):
    _assert_versioned_common(data)
    assert data["kyc_status"] in ("UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED")
    assert data["payout_method"] in ("BANK", "CASH_PICKUP", "WALLET")
    assert isinstance(data["kyc_review_count"], int)
    assert data["kyc_review_count"] >= 0
    assert is_valid_uuid(data.get("sender_id", ""))


def assert_quote(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("DRAFT", "LOCKED", "CONSUMED", "EXPIRED")
    assert data["payout_method"] in ("BANK", "CASH_PICKUP", "WALLET")
    assert isinstance(data["send_principal_minor"], int)
    assert is_valid_uuid(data.get("corridor_id", ""))
    assert is_valid_uuid(data.get("sender_id", ""))


def assert_quote_disclosure(data: dict):
    """A LOCKED quote carries fully-computed disclosure figures."""
    for f in ("locked_rate_micro", "fee_minor", "recipient_amount_minor", "total_pay_minor"):
        assert isinstance(data[f], int), f"{f} must be an int"
    assert data["total_pay_minor"] == data["send_principal_minor"] + data["fee_minor"], \
        "total_pay_minor == send_principal_minor + fee_minor"


def assert_transfer(data: dict):
    _assert_versioned_common(data)
    assert data["funding_status"] in ("UNFUNDED", "FUNDED")
    assert data["compliance_status"] in ("SCREENING", "CLEARED", "HELD", "REJECTED")
    assert data["delivery_status"] in (
        "PENDING", "IN_TRANSIT", "DELIVERED", "FAILED", "REFUNDED")
    assert is_valid_uuid(data.get("quote_id", ""))
    assert is_valid_uuid(data.get("recipient_id", ""))
    assert isinstance(data["send_principal_minor"], int)


def assert_compliance_case(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("OPEN", "AWAITING_INFO", "ESCALATED", "CLEARED", "REJECTED")
    assert data["opened_reason"] in ("SANCTIONS_SCORE", "MANUAL")
    assert isinstance(data["info_request_count"], int)
    assert data["info_request_count"] >= 0
    assert is_valid_uuid(data.get("transfer_id", ""))


def assert_sanctions_list_entry(data: dict):
    _assert_audit_common(data)
    assert isinstance(data["listed_name"], str) and len(data["listed_name"]) > 0
    assert isinstance(data["weight_name_bps"], int)
    assert isinstance(data["weight_country_bps"], int)


def assert_sanctions_hit(data: dict):
    _assert_audit_common(data)
    assert data["subject_kind"] in ("SENDER", "RECIPIENT")
    assert isinstance(data["score"], int)
    assert is_valid_uuid(data.get("transfer_id", ""))
    assert is_valid_uuid(data.get("list_entry_id", ""))


def assert_payout_attempt(data: dict):
    _assert_versioned_common(data)
    assert data["outcome"] in ("PENDING", "SUCCEEDED", "FAILED")
    assert data["payout_method"] in ("BANK", "CASH_PICKUP", "WALLET")
    assert isinstance(data["attempt_index"], int)
    assert data["attempt_index"] >= 1


def assert_refund(data: dict):
    _assert_versioned_common(data)
    assert data["status"] == "ISSUED"
    assert data["reason"] in ("SENDER_CANCEL", "COMPLIANCE_REJECT", "DELIVERY_FAILED")
    for f in ("principal_refunded_minor", "fee_refunded_minor", "total_refunded_minor"):
        assert isinstance(data[f], int)
    assert data["total_refunded_minor"] == \
        data["principal_refunded_minor"] + data["fee_refunded_minor"], \
        "total_refunded_minor == principal_refunded_minor + fee_refunded_minor"


def assert_ledger_entry(data: dict):
    _assert_audit_common(data)
    assert data["entry_type"] in (
        "SENDER_DEBIT", "RECIPIENT_CREDIT", "FEE_REVENUE", "REFUND_CREDIT", "FEE_REVERSAL")
    assert isinstance(data["amount_minor"], int)
    assert is_valid_uuid(data.get("transfer_id", ""))


def ledger_net(entries: list) -> int:
    """Sum of amount_minor over a list of LedgerEntry dicts."""
    return sum(int(e["amount_minor"]) for e in entries)
