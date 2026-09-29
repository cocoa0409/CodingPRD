"""Lifetime value, cohort membership, the retention rate and the win-back score ceiling.

The realized figure counts only settled invoices while the projection already books the
open cycle; cohort membership is half-open on the month boundary; two thirds rounds up at
the fourth decimal; and an involuntary churner's score is clipped after rounding.
"""

import pytest

from test_helpers import (
    add_target,
    assert_instant,
    assert_winback_target,
    charge_invoice,
    complete_session,
    create_attempt,
    invoice_at_cycle,
    new_cohort_snapshot,
    new_payment_method,
    new_plan,
    new_subscriber,
    new_subscription,
    pay_invoice,
    read_campaign,
    read_invoice,
    read_session,
    read_subscriber,
    read_subscription,
    run_renewal,
    send_renewal_reminder,
    set_clock,
    settle_attempt,
    setup_active_subscription,
    setup_launched_campaign,
    setup_reason_captured_session,
)


class TestLifetimeValueVariants:

    def test_an_open_invoice_is_worth_nothing_realized_but_everything_projected(self):
        """Realized reads 0 against a projection of 37687, then 2899 against 40586.

        PRD §3.9: "`realized_ltv_cents` is the sum, over every invoice belonging to any
        subscription of this subscriber whose `status` is `PAID`, of that invoice's
        `amount_cents` minus its `cogs_cents`, less the sum, over every such invoice whose
        `status` is `WRITTEN_OFF`, of that invoice's `cogs_cents`. Invoices in `OPEN` or
        `FAILED` contribute nothing at all to the realized figure."

        Design: Corner/calculations/realized_ltv_ignores_open_invoices_while_projection_still_counts_them
        """
        world = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "ORGANIC"})
        create_attempt(world["invoice"]["id"])

        before = read_subscriber(world["subscriber"]["id"])
        assert before["realized_ltv_cents"] == 0
        # ORGANIC 0.05 times the M0_1 multiplier 1.6 is 0.08, so 12.5 rounds to 13 cycles
        # of the open cycle's 2899-cent margin.
        assert before["projected_ltv_cents"] == 37687

        settle_attempt(world["invoice"]["id"], "SUCCEEDED")
        assert read_invoice(world["invoice"]["id"])["status"] == "PAID"

        after = read_subscriber(world["subscriber"]["id"])
        assert after["realized_ltv_cents"] == 2899
        assert after["projected_ltv_cents"] == 40586
        assert after["churn_type"] == "NONE"
        assert read_subscription(world["subscription"]["id"])["billing_state"] == "CURRENT"


class TestCohortMembership:

    def test_a_february_signup_is_invisible_to_the_january_cohort(self):
        """Each month holds exactly its own subscriber, and each mean averages only those.

        PRD §3.9: "A subscriber is a member when `first_subscribed_at` is not null and falls
        at or after the first instant of `cohort_month` in UTC and strictly before the first
        instant of the following month, and when each supplied filter matches — the channel
        filter against `acquisition_channel`, the plan filter against the `code` of the plan
        of the earliest subscription by `created_at` ascending, and the bucket filter
        against the current `tenure_bucket`."

        Design: Corner/calculations/cohort_membership_window_is_half_open_on_the_month_boundary
        """
        january = setup_active_subscription(
            clock="2026-01-10", subscriber_overrides={"acquisition_channel": "ORGANIC"})
        pay_invoice(january["invoice"]["id"])

        set_clock("2026-02-10")
        february_subscriber = new_subscriber(acquisition_channel="SEARCH")
        february_card = new_payment_method(february_subscriber["id"])
        new_subscription(february_subscriber["id"], january["plan"]["id"], february_card["id"])

        assert read_subscriber(january["subscriber"]["id"])["cohort_month"] == "2026-01"
        assert read_subscriber(february_subscriber["id"])["cohort_month"] == "2026-02"

        january_snapshot = new_cohort_snapshot("2026-01", "REALIZED")
        february_snapshot = new_cohort_snapshot("2026-02", "REALIZED")

        assert january_snapshot["member_count"] == 1
        assert january_snapshot["retained_count"] == 1
        assert january_snapshot["retention_rate"] == pytest.approx(1.0000, abs=5e-5)
        assert january_snapshot["mean_ltv_cents"] == 2899

        assert february_snapshot["member_count"] == 1
        # The February signup's only invoice is still OPEN, so it realized nothing.
        assert february_snapshot["mean_ltv_cents"] == 0


class TestRetentionRateRounding:

    def test_two_retained_of_three_members_stores_as_0_6667(self):
        """0.666666... rounds half up rather than truncating, and the leaver counts as churn.

        PRD §3.9: "`retention_rate` is `retained_count` divided by `member_count`, rounded
        half up to four decimal places, and exactly `0.0000` when `member_count` is 0."

        Design: Corner/calculations/retention_rate_rounds_two_thirds_half_up_to_four_decimals
        """
        set_clock("2026-01-10")
        plan = new_plan(code="BOUND", monthly_price_cents=5000, unit_cogs_cents=2500,
                        margin_floor_pct=0.4048, allowed_frequency_weeks=[4],
                        is_negative_option=False)
        stayers = [setup_active_subscription(
            plan=plan, subscriber_overrides={"acquisition_channel": "SEARCH"})
            for _ in range(2)]
        leaver = setup_active_subscription(
            plan=plan, subscriber_overrides={"acquisition_channel": "SEARCH"})

        session = setup_reason_captured_session(leaver, reason_code="PRICE")
        complete_session(session["id"], leaver["subscriber_headers"])

        set_clock("2026-02-07")
        run_renewal(leaver["subscription"]["id"])
        assert read_subscription(leaver["subscription"]["id"])["lifecycle_state"] == "CANCELLED"
        assert read_subscriber(leaver["subscriber"]["id"])["churn_type"] == "VOLUNTARY"
        for stayer in stayers:
            assert read_subscription(stayer["subscription"]["id"])["lifecycle_state"] == "ACTIVE"

        snapshot = new_cohort_snapshot("2026-01", "REALIZED")
        assert snapshot["member_count"] == 3
        assert snapshot["retained_count"] == 2
        assert snapshot["churned_voluntary_count"] == 1
        assert snapshot["churned_involuntary_count"] == 0
        assert snapshot["retention_rate"] == pytest.approx(0.6667, abs=5e-5)
        # Every invoice of the cohort is still OPEN, so nothing has been realized.
        assert snapshot["mean_ltv_cents"] == 0
        assert_instant(snapshot["computed_at"], "2026-02-07T00:00:00Z", "computed_at")


class TestInvoluntaryScoreCeiling:

    def test_a_high_scoring_involuntary_churner_is_clipped_to_0_4000(self):
        """The three weighted terms sum to 0.4888, but the ceiling stores 0.4000.

        PRD §3.8: "When the subscriber's `churn_type` is `INVOLUNTARY`, the rounded score is
        then capped at `0.4000`. An involuntary churner can therefore never outrank a
        voluntary one above that ceiling, no matter how strong the other two factors are —
        we would rather fix the card than send a discount."

        Design: Corner/calculations/involuntary_score_ceiling_clips_a_high_raw_priority_score
        """
        world = setup_active_subscription(
            clock="2026-01-10",
            subscriber_overrides={"acquisition_channel": "ORGANIC"},
            addons=[{"code": "MUG", "qty": 1}])
        session = setup_reason_captured_session(world, reason_code="PRICE")
        pay_invoice(world["invoice"]["id"])

        set_clock("2026-01-28")
        send_renewal_reminder(world, renewal_cycle_index=1)
        set_clock("2026-02-07")
        run_renewal(world["subscription"]["id"])

        renewal_invoice = invoice_at_cycle(world["subscription"]["id"], 1)
        assert renewal_invoice["amount_cents"] == 6298
        assert renewal_invoice["cogs_cents"] == 2620
        charge_invoice(renewal_invoice["id"], "HARD_DECLINE", "DO_NOT_HONOR")

        lapsed = read_subscriber(world["subscriber"]["id"])
        assert lapsed["churn_type"] == "INVOLUNTARY"
        # 3678 of paid margin less the written-off invoice's 2620 of goods.
        assert lapsed["realized_ltv_cents"] == 1058
        assert lapsed["projected_ltv_cents"] == 1058
        assert_instant(lapsed["lapsed_at"], "2026-02-07T00:00:00Z", "lapsed_at")
        assert_instant(lapsed["winback_suppressed_until"], "2026-03-09T00:00:00Z",
                       "winback_suppressed_until")
        # The write-off abandoned the conversation, which keeps the PRICE reason readable.
        assert read_session(session["id"])["reason_code"] == "PRICE"

        set_clock("2026-03-13")
        campaign = setup_launched_campaign(min_days_since_lapse=30, max_days_since_lapse=120)
        target = add_target(campaign, world["subscriber"]["id"])

        assert_winback_target(target)
        assert target["days_since_lapse_at_target"] == 34
        assert target["priority_score"] == pytest.approx(0.4000, abs=5e-5)
        assert target["projected_ltv_cents"] == 1058
        assert target["state"] == "ELIGIBLE"
        assert target["suppression_reason"] == "NONE"
        assert read_campaign(campaign["id"])["targeted_count"] == 1
