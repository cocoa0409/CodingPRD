"""Entity assertions and domain invariant checkers for the P2P money transfer API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_account(data: dict):
    """Validate an Account response against the PRD contract."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert data["status"] in ("ACTIVE", "FROZEN")
    assert isinstance(data["available_balance_cents"], int)
    assert data["available_balance_cents"] >= 0, "available_balance_cents must never be negative"
    assert isinstance(data["held_balance_cents"], int)
    assert data["held_balance_cents"] >= 0, "held_balance_cents must never be negative"
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100, "risk_score must be within [0,100]"
    assert data["risk_tier"] in ("LOW", "ELEVATED", "HIGH")
    assert isinstance(data["is_recipient_verified"], bool)
    assert isinstance(data["version"], int)


def assert_risk_tier_matches_score(data: dict):
    """The risk_tier band must agree with risk_score (PRD §2.7):
    LOW if <30, ELEVATED if 30..69, HIGH if >=70."""
    score = data["risk_score"]
    if score < 30:
        expected = "LOW"
    elif score <= 69:
        expected = "ELEVATED"
    else:
        expected = "HIGH"
    assert data["risk_tier"] == expected, (
        f"risk_tier {data['risk_tier']} disagrees with risk_score {score} (expected {expected})"
    )


def assert_funding_source(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PENDING", "VERIFIED", "REMOVED")
    assert data["kind"] in ("BANK", "DEBIT")
    assert isinstance(data["last4"], str)
    assert isinstance(data["is_default_payout"], bool)


def assert_recipient_verification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PENDING", "CONFIRMED", "EXPIRED")
    assert data["channel"] in ("EMAIL", "SMS")
    # common_fields:false — no version / updated_at on this immutable record.
    assert "version" not in data, "RecipientVerification must not carry a version field"


def assert_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SENT", "HELD", "SETTLED", "REVERSED", "CANCELLED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["risk_flagged"], bool)


def assert_money_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PENDING", "FULFILLED", "DECLINED", "CANCELLED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_split_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("OPEN", "PARTIALLY_SETTLED", "SETTLED", "CANCELLED")
    assert data["split_mode"] in ("EVEN", "WEIGHTED")
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["collected_amount_cents"], int)


def assert_split_participant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("OWED", "PAID", "FORGIVEN")
    assert isinstance(data["share_amount_cents"], int)


def assert_risk_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PENDING_REVIEW", "CLEARED", "BLOCKED")
    assert data["reason_code"] in ("HIGH_TIER", "LARGE_AMOUNT", "UNVERIFIED_RECIPIENT")


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("OPEN", "NEEDS_INFO", "UPHELD", "DENIED")
    assert data["reason"] in ("UNAUTHORIZED", "NOT_RECEIVED", "DUPLICATE")


def assert_withdrawal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("REQUESTED", "PAID", "FAILED", "CANCELLED")
    assert data["speed"] in ("INSTANT", "STANDARD")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert isinstance(data["net_amount_cents"], int)
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["fee_cents"], (
        "net_amount_cents must equal gross_amount_cents - fee_cents"
    )


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["source_kind"] in ("TRANSFER", "WITHDRAWAL", "REVERSAL", "ADJUSTMENT")
