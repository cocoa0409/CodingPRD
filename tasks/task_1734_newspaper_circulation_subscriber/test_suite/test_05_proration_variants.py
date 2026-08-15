"""Vacation-hold proration credits: PER_DAY vs PER_ISSUE and rounding order."""
from test_helpers import (
    REP,
    create_plan,
    create_subscriber,
    create_subscription,
    create_hold,
    get_hold,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
    validate_paginated,
)


def _memos_for_hold(api, hold_id):
    memos, _meta = validate_paginated(
        api.list_credit_memos(REP, params={"hold_id": hold_id, "limit": 100})
    )
    return memos


def _run_completed_credit_hold(api, proration_method):
    """One print subscription (base 1000, 7 issues/week) with a CREDIT hold
    over [2026-08-10, 2026-08-14) = 4 held days, completed by the batch."""
    set_clock("2026-08-03T00:00:00Z")
    plan = create_plan(
        name=f"P-{proration_method}", plan_type="PRINT", issues_per_week=7,
        base_weekly_rate_cents=1000, proration_method=proration_method,
        min_weekly_rate_cents=0,
    )
    subscriber = create_subscriber(
        display_name=proration_method, email=f"{proration_method.lower()}@x.com",
        service_address="1 Main St",
    )
    subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
    run_daily_cycle()
    hold = create_hold(subscription["id"], "2026-08-10", "2026-08-14", "CREDIT")
    set_clock_and_cycle("2026-08-10T00:00:00Z")  # activate hold
    set_clock_and_cycle("2026-08-14T00:00:00Z")  # complete hold
    return hold


class TestDualVariantProration:
    def test_proration_per_day_vs_per_issue_divergence(self, api):
        """PRD §3.3: "Under the `PER_DAY` variant, the credit is the snapshot
        rate multiplied by the held days, divided by seven, rounded half up
        to whole cents — a single rounding after the multiply. Under the
        `PER_ISSUE` variant, the rounding order is pinned differently: the
        per-issue rate is computed first as the snapshot rate divided by the
        plan's `issues_per_week`, rounded half up to whole cents, and only
        then multiplied by the held days. For a sense of the difference this
        ordering makes, a snapshot of 1000 cents over four held days yields
        571 cents under `PER_DAY`, while a seven-issue-per-week plan under
        `PER_ISSUE` rounds the per-issue rate to 143 cents and yields 572."

        Design: Difficulty/dual_variant_calc/proration_per_day_vs_per_issue_divergence
        """
        hold_pd = _run_completed_credit_hold(api, "PER_DAY")
        hold_pi = _run_completed_credit_hold(api, "PER_ISSUE")

        memos_pd = _memos_for_hold(api, hold_pd["id"])
        memos_pi = _memos_for_hold(api, hold_pi["id"])
        assert len(memos_pd) == 1, "PER_DAY hold must issue exactly one credit memo"
        assert len(memos_pi) == 1, "PER_ISSUE hold must issue exactly one credit memo"

        assert memos_pd[0]["amount_cents"] == 571  # round_half_up(1000*4/7)
        assert memos_pi[0]["amount_cents"] == 572  # round_half_up(1000/7)=143; 143*4
        assert memos_pd[0]["amount_cents"] != memos_pi[0]["amount_cents"]

    def test_proration_variants_both_mark_hold_completed(self, api):
        """PRD §3.3: "Either way the hold lands in `COMPLETED`, delivery
        flips back from `HELD` to `DELIVERING`, and the resolution determines
        the financial aftermath."
        PRD §3.3: "The resulting credit memo carries `source` of `PRORATION`
        with its `hold_id` pointing back to the hold, and it auto-applies
        through the payment waterfall at issuance."

        Design: Difficulty/dual_variant_calc/proration_per_day_vs_per_issue_divergence
        """
        hold_pd = _run_completed_credit_hold(api, "PER_DAY")
        hold_pi = _run_completed_credit_hold(api, "PER_ISSUE")

        for hold_id in (hold_pd["id"], hold_pi["id"]):
            hold = get_hold(hold_id)
            assert hold["status"] == "COMPLETED"
            memos = _memos_for_hold(api, hold_id)
            assert memos[0]["source"] == "PRORATION"
            assert memos[0]["hold_id"] == hold_id


class TestNestedRoundingOrder:
    def test_proration_nested_rounding_order_pinned(self, api):
        """PRD §3.3: "Under the `PER_ISSUE` variant, the rounding order is
        pinned differently: the per-issue rate is computed first as the
        snapshot rate divided by the plan's `issues_per_week`, rounded half
        up to whole cents, and only then multiplied by the held days. For a
        sense of the difference this ordering makes, a snapshot of 1000 cents
        over four held days yields 571 cents under `PER_DAY`, while a
        seven-issue-per-week plan under `PER_ISSUE` rounds the per-issue rate
        to 143 cents and yields 572."

        Design: Difficulty/combinatorial_formula/proration_nested_rounding_order_pinned
        """
        hold = _run_completed_credit_hold(api, "PER_ISSUE")
        memos = _memos_for_hold(api, hold["id"])
        assert len(memos) == 1
        assert memos[0]["amount_cents"] == 572, (
            "per-issue rate rounds first (143), then multiplies by 4 held days"
        )
        assert memos[0]["amount_cents"] != 571, (
            "multiply-then-round order (571) is the rejected variant"
        )

    def test_proration_credit_echoed_on_hold(self, api):
        """PRD §3.3: "For a `CREDIT` resolution, the system issues a
        proration credit memo and records the amount on the hold's
        `credit_amount_cents`."

        Design: Difficulty/combinatorial_formula/proration_nested_rounding_order_pinned
        """
        hold = _run_completed_credit_hold(api, "PER_ISSUE")
        completed = get_hold(hold["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["credit_amount_cents"] == 572
        assert completed["weekly_rate_snapshot_cents"] == 1000
