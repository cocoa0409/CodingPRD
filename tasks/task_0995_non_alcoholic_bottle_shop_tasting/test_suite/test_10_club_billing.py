"""Club subscription billing cadence: multi-cycle catch-up and single-step
advance on successful billing runs (PRD §3.7).
"""
from test_helpers import (
    TEST_USERS,
    get_member,
    make_category,
    make_club_plan,
    make_member,
    make_member_headers,
    set_clock,
    subscribe_member,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _setup_monthly_subscription(api):
    """MONTHLY plan; subscription started 2026-01-15 (ACTIVE, no trial) while
    the clock reads 2026-01-01. Returns (subscription, member)."""
    set_clock("2026-01-01T00:00:00Z")
    category = make_category(code="tea16", display_name="Tea16")
    plan = make_club_plan(
        code="PLAN-C", cadence="MONTHLY", bottles_per_shipment=1,
        price_cents_per_cycle=1000, allowed_category_ids=[category["id"]],
        discount_bps_on_retail=0, max_active_subscriptions=10,
    )
    member = make_member(email="m16@x.com")
    subscription = subscribe_member(
        plan["id"], member["id"], started_on="2026-01-15", trial_days=0
    )
    return subscription, member


def _billing(api, subscription_id, outcome="SUCCEEDED"):
    return validate_success(
        api.simulate_billing(subscription_id, outcome, ADMIN), 200
    )


class TestBillingCatchUp:
    def test_catch_up_skips_whole_cadence_units(self, api):
        """PRD §3.7: "The cadence arithmetic on a successful billing run is
        as follows: the cadence in months is 1 for `MONTHLY`, 3 for
        `QUARTERLY`, and 12 for `ANNUAL`. The candidate next-billing date is
        the current `next_billing_on` advanced by that many months. If the
        candidate falls strictly before today — catch-up after a pause — the
        system keeps advancing by the cadence interval until the candidate is
        on or after today, and that final value becomes the new
        `next_billing_on`."

        Design: Difficulty/resource_temporal_overlap/club_subscription_billing_catch_up_multi_cycle_skip
        """
        subscription, member = _setup_monthly_subscription(api)
        # Clock jumps to 2026-05-01 — several MONTHLY cycles past due.
        set_clock("2026-05-01T00:00:00Z")
        updated = _billing(api, subscription["id"])
        # Cadence arithmetic anchored on the 15th: 02-15, 03-15, 04-15 are
        # all strictly before today, so the walk lands on 2026-05-15.
        assert updated["next_billing_on"] == "2026-05-15"

    def test_no_catch_up_needed_advances_exactly_one_cadence(self, api):
        """PRD §3.7: "The candidate next-billing date is the current
        `next_billing_on` advanced by that many months. If the candidate
        falls strictly before today — catch-up after a pause — the system
        keeps advancing by the cadence interval until the candidate is on or
        after today, and that final value becomes the new `next_billing_on`."
        PRD §3.7: "a `SUCCEEDED` outcome advances `next_billing_on` per the
        cadence rule above and resets `failed_billing_count`".

        Design: Difficulty/resource_temporal_overlap/club_subscription_billing_catch_up_multi_cycle_skip
        """
        subscription, member = _setup_monthly_subscription(api)
        set_clock("2026-05-01T00:00:00Z")
        updated = _billing(api, subscription["id"])
        assert updated["next_billing_on"] == "2026-05-15"
        # A second success at the same clock: candidate 2026-06-15 is already
        # on/after today, so exactly one cadence step is taken.
        updated = _billing(api, subscription["id"])
        assert updated["next_billing_on"] == "2026-06-15"
        assert updated["failed_billing_count"] == 0
