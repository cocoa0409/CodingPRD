"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """Common fields for entities carrying id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def _assert_common_append_only(data: dict):
    """Common fields for append-only entities: only id + created_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not carry a version field"
    assert "updated_at" not in data, "append-only entity must not carry an updated_at field"


def assert_merchant(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["online_rate_bps"], int)
    assert isinstance(data["instore_rate_bps"], int)
    assert isinstance(data["attribution_window_hours"], int)
    assert isinstance(data["double_dip_allowed"], bool)
    assert isinstance(data["maturity_hold_days"], int)
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_offer(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["offer_type"] in ("LINKED", "RECEIPT_REBATE")
    assert data["status"] in ("ACTIVE", "EXPIRED")
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_member(data: dict):
    _assert_common_full(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED")
    for f in ("pending_balance_cents", "available_balance_cents",
              "reserved_balance_cents", "net_cashoutable_cents", "lifetime_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_clickthrough(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert is_iso8601_timestamp(data["clicked_at"])


def assert_receipt_scan(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["purchase_total_cents"], int)
    assert data["status"] in ("SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED")


def assert_reward_claim(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert data["attribution"] in ("ONLINE", "IN_STORE")
    assert isinstance(data["purchase_amount_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "AVAILABLE", "RESERVED", "PAID",
                              "CLAWED_BACK", "EXPIRED")


def assert_cashout(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["member_id"])
    assert data["method"] in ("PAYPAL", "CHECK", "GIFT_CARD")
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["net_payout_cents"], int)
    assert data["status"] in ("REQUESTED", "PROCESSING", "PAID", "FAILED")


def assert_referral(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["referrer_member_id"])
    assert isinstance(data["referee_email"], str) and len(data["referee_email"]) > 0
    assert data["status"] in ("INVITED", "SIGNED_UP", "QUALIFIED", "REWARDED", "EXPIRED")


def assert_bonus_streak(data: dict):
    assert isinstance(data["current_streak_weeks"], int)
    assert isinstance(data["longest_streak_weeks"], int)
    assert isinstance(data["pending_streak_bonus_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data["member_id"])
    assert data["entry_type"] in (
        "CLAIM_PENDING", "CLAIM_MATURED", "CLAIM_CLAWBACK", "CLAIM_EXPIRED",
        "CASHOUT_DEBIT", "CASHOUT_REVERSAL", "REFERRAL_BONUS", "STREAK_BONUS",
    )
    assert isinstance(data["amount_cents"], int)


def assert_return_event(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data["reward_claim_id"])
    assert isinstance(data["returned_amount_cents"], int)
    assert isinstance(data["clawback_cents"], int)


def assert_wallet_invariants(member: dict):
    """Wallet invariants implied by the derived-wallet principle (PRD §2.6).
    net_cashoutable_cents equals available_balance_cents; balances never negative."""
    assert member["net_cashoutable_cents"] == member["available_balance_cents"], \
        "net_cashoutable_cents must equal available_balance_cents"
    for f in ("pending_balance_cents", "available_balance_cents",
              "reserved_balance_cents", "net_cashoutable_cents", "lifetime_paid_cents"):
        assert member[f] >= 0, f"{f} must be non-negative"
