"""The two lifetime-value readings of one subscriber, and the cohort mean over them.

A subscriber who has settled exactly one invoice carries a realized figure that
counts only that invoice and a projected figure that adds a forward tail sized by
their acquisition channel and tenure bucket.  Both are derived at read time from
the same stored rows, so the pair must diverge on a single subscriber.
"""

import pytest

from test_helpers import (
    assert_cohort_snapshot,
    assert_subscriber,
    new_cohort_snapshot,
    pay_invoice,
    read_subscriber,
    set_clock,
    setup_active_subscription,
)


def _paid_subscriber_seventy_five_days_in():
    """One PAID_SOCIAL subscriber on the 4999/2100 plan with one 1299/520 addon.

    The signup invoice bills 4999 + 1299 = 6298 against COGS 2100 + 520 = 2620 and
    is settled, then the clock advances to 75 days after the signup instant.
    """
    world = setup_active_subscription(
        clock="2026-01-10",
        subscriber_overrides={"acquisition_channel": "PAID_SOCIAL"},
        addons=[{"code": "MUG", "qty": 1}],
    )
    pay_invoice(world["invoice"]["id"])
    set_clock("2026-03-26")
    return world


class TestLifetimeValueVariants:

    def test_realized_counts_only_the_settled_invoice_while_projected_adds_a_tail(self):
        """One paid invoice: realized is its contribution margin, projected adds 8 cycles.

        PRD §3.9: "`realized_ltv_cents` is the sum, over every invoice belonging to
        any subscription of this subscriber whose `status` is `PAID`, of that
        invoice's `amount_cents` minus its `cogs_cents`, less the sum, over every
        such invoice whose `status` is `WRITTEN_OFF`, of that invoice's
        `cogs_cents`." and "`projected_ltv_cents` is then `realized_ltv_cents` plus
        the current cycle margin multiplied by the expected remaining cycles,
        rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/ltv_realized_versus_projected_on_same_subscriber
        """
        world = _paid_subscriber_seventy_five_days_in()

        subscriber = read_subscriber(world["subscriber"]["id"])
        assert_subscriber(subscriber)

        # 2026-01-10 to 2026-03-26 is 75 whole days; 75 // 30 == 2 months.
        assert subscriber["tenure_days"] == 75
        assert subscriber["tenure_bucket"] == "M2_3"

        # 6298 billed minus 2620 of goods.
        assert subscriber["realized_ltv_cents"] == 3678
        # PAID_SOCIAL 0.10 times the M2_3 multiplier 1.2 is 0.12; the reciprocal
        # 8.3333 rounds half up to 8 cycles, under the horizon cap of 24.
        assert subscriber["projected_ltv_cents"] == 3678 + 3678 * 8
        assert subscriber["projected_ltv_cents"] == 33102
        assert subscriber["projected_ltv_cents"] - subscriber["realized_ltv_cents"] == 29424
        assert subscriber["churn_type"] == "NONE"

    def test_cohort_snapshot_mean_follows_the_selected_ltv_variant(self):
        """Two snapshots over the same one-member cohort average different fields.

        PRD §3.9: "`mean_ltv_cents` is the sum across members of the selected
        variant — each member's `realized_ltv_cents` when `ltv_variant` is
        `REALIZED`, otherwise their `projected_ltv_cents` — divided by
        `member_count` and rounded half up to whole cents, and exactly 0 when
        `member_count` is 0."

        Design: Difficulty/dual_variant_calc/ltv_realized_versus_projected_on_same_subscriber
        """
        _paid_subscriber_seventy_five_days_in()

        realized = new_cohort_snapshot("2026-01", "REALIZED")
        projected = new_cohort_snapshot("2026-01", "PROJECTED")

        assert_cohort_snapshot(realized)
        assert_cohort_snapshot(projected)

        assert realized["member_count"] == 1
        assert realized["retained_count"] == 1
        assert realized["retention_rate"] == pytest.approx(1.0000, abs=5e-5)
        assert realized["churned_voluntary_count"] == 0
        assert realized["churned_involuntary_count"] == 0
        assert realized["mean_ltv_cents"] == 3678

        assert projected["member_count"] == 1
        assert projected["mean_ltv_cents"] == 33102
