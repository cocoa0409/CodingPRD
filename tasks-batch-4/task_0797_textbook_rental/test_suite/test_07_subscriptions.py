"""Subscriptions: closed-interval period non-overlap, prorated cancellation refund,
and cancel lifecycle guard."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_subscription_payload,
    setup_active_subscription, set_clock, get_customer,
)


# ─── Closed-interval period adjacency conflict ────────────────────────

def test_subscription_adjacent_period_overlap_rejected(api):
    """PRD 3.2: "a new period must not overlap any existing non-`CANCELLED` period of
    that customer. This overlap test treats each period as a closed interval, so even a
    boundary touch where one period's end equals the next period's start is a conflict,
    rejected with `ERR_SUBSCRIPTION_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_period_closed_interval_adjacency_conflict
    """
    ctx = setup_active_subscription(tier="STUDY", monthly_fee_cents=1499, rental_discount_pct=0.05,
                                    term_months=1, start_clock="2026-03-01T00:00:00Z",
                                    start_date="2026-03-01T00:00:00Z", email="adj1@x.com")
    # A second period that starts exactly where the first ends touches the boundary.
    boundary_start = ctx["subscription"]["period_end"]
    res = api.create_subscription(
        ctx["customer"]["id"],
        create_subscription_payload(ctx["plan"]["id"], start_date=boundary_start),
        ctx["headers"])
    validate_error(res, "ERR_SUBSCRIPTION_PERIOD_OVERLAP", expected_status=409)


def test_subscription_adjacency_conflict_creates_no_second_period(api):
    """PRD 3.2: "even a boundary touch where one period's end equals the next period's
    start is a conflict, rejected with `ERR_SUBSCRIPTION_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/subscription_period_closed_interval_adjacency_conflict
    """
    ctx = setup_active_subscription(tier="STUDY", monthly_fee_cents=1499, rental_discount_pct=0.05,
                                    term_months=1, start_clock="2026-03-01T00:00:00Z",
                                    start_date="2026-03-01T00:00:00Z", email="adj2@x.com")
    boundary_start = ctx["subscription"]["period_end"]
    api.create_subscription(
        ctx["customer"]["id"],
        create_subscription_payload(ctx["plan"]["id"], start_date=boundary_start),
        ctx["headers"])  # rejected
    _, meta = validate_paginated(
        api.list_subscriptions(ctx["headers"], params={"customer_id": ctx["customer"]["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]


# ─── Corner: proration refund on cancel ───────────────────────────────

def test_subscription_proration_refund_on_cancel(api):
    """PRD 3.2: "the refund is the snapshotted `monthly_fee_cents` multiplied by
    remaining days divided by the period length, rounded half up to whole cents. When
    that refund is greater than zero, a `WalletTransaction` of `kind`
    `SUBSCRIPTION_REFUND` is appended for that positive amount."

    Design: Corner/calculations/subscription_proration_refund_on_cancel
    """
    ctx = setup_active_subscription(tier="STUDY", monthly_fee_cents=1499, rental_discount_pct=0.05,
                                    term_months=1, topup=2000, start_clock="2026-03-01T00:00:00Z",
                                    start_date="2026-03-01T00:00:00Z", email="sp@x.com")
    # Wallet after subscribe: 2000 - 1499 = 501. Cancel 15 days into a 30-day period:
    # refund = round_half_up(1499 * 15 / 30) = 750 -> wallet 1251.
    set_clock("2026-03-16T00:00:00Z")
    cancelled = validate_success(api.cancel_subscription(ctx["subscription"]["id"], ctx["headers"]), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_customer(ctx["customer"]["id"])["wallet_credit_cents"] == 1251


def test_cancel_subscription_twice_returns_409(api):
    """PRD 3.2: "Cancelling a subscription requires it to be in `ACTIVE` status,
    otherwise the request is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Corner/state_machines/cancel_subscription_twice_returns_409
    """
    ctx = setup_active_subscription(tier="STUDY", monthly_fee_cents=1499, rental_discount_pct=0.05,
                                    term_months=1, start_clock="2026-03-01T00:00:00Z",
                                    start_date="2026-03-01T00:00:00Z", email="cs@x.com")
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], ctx["headers"]), 200)
    res = api.cancel_subscription(ctx["subscription"]["id"], ctx["headers"])
    validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE", expected_status=409)
