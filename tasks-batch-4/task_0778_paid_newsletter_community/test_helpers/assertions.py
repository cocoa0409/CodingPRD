"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_publication(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["deliverability_status"] in ("HEALTHY", "THROTTLED", "SUSPENDED")
    assert isinstance(data["platform_fee_bps"], int)
    for f in (
        "sent_count", "bounce_count", "lifetime_net_cents", "payout_balance_cents",
        "pending_payout_cents", "lifetime_paid_out_cents", "active_member_count",
        "mrr_cents", "recognized_revenue_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_tier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["tier_rank"], int)
    assert isinstance(data["monthly_price_cents"], int)
    assert isinstance(data["is_free"], bool)


def assert_member(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "VERIFIED", "BOUNCED")
    assert isinstance(data["email_bounced"], bool)


def assert_subscription(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("TRIALING", "ACTIVE", "PAST_DUE", "CANCELED", "EXPIRED")
    assert isinstance(data["current_tier_rank"], int)


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert data["reason"] in ("INITIAL", "RENEWAL", "PRORATION_UPGRADE", "WIN_BACK")
    assert data["payment_status"] in ("OPEN", "PAID", "FAILED", "REFUNDED")


def assert_event(data: dict):
    assert_common_fields(data)
    assert isinstance(data["capacity"], int)
    # Seat conservation invariant (PRD §3.8).
    assert data["registered_count"] + data["available_slots"] == data["capacity"], (
        "registered_count + available_slots must equal capacity"
    )
    assert data["available_slots"] >= 0


def assert_registration(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REGISTERED", "WAITLISTED", "CANCELED")


def assert_comment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "HELD", "HIDDEN")


def assert_payout(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "PAID", "FAILED")


def assert_money_conservation(pub: dict):
    """PRD §2.7 ledger invariant: balance + pending + paid_out == lifetime_net."""
    total = (
        pub["payout_balance_cents"]
        + pub["pending_payout_cents"]
        + pub["lifetime_paid_out_cents"]
    )
    assert total == pub["lifetime_net_cents"], (
        f"money invariant violated: {total} != lifetime_net {pub['lifetime_net_cents']}"
    )
