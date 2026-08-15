"""Carrier settlement: GROSS vs NET variants, held-day filtering, empty weeks."""
from test_helpers import (
    MGR,
    REP,
    assert_settlement,
    create_assignment,
    create_carrier,
    create_complaint,
    create_hold,
    create_plan,
    create_route,
    create_subscriber,
    create_subscription,
    get_settlement,
    run_daily_cycle,
    set_clock,
    set_clock_and_cycle,
)


def _carrier_with_full_week_delivery(compensation_model, name, email):
    """Carrier + route + ACTIVE print subscription assigned open-ended from
    2026-07-27; clock left at 2026-08-05 with one OPEN complaint dated
    2026-08-05 on the carrier's route."""
    set_clock("2026-07-27T00:00:00Z")
    plan = create_plan(
        name="P", plan_type="PRINT", issues_per_week=7,
        base_weekly_rate_cents=700, proration_method="PER_DAY",
        min_weekly_rate_cents=0,
    )
    carrier = create_carrier(
        display_name=name, compensation_model=compensation_model,
        per_copy_rate_cents=50,
    )
    route = create_route(route_code=f"R-{name}", carrier_id=carrier["id"], max_stops=10)
    subscriber = create_subscriber(
        display_name=name, email=email, service_address="1 Main St"
    )
    subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-27")
    run_daily_cycle()
    create_assignment(subscription["id"], route["id"], "2026-07-27")
    set_clock("2026-08-05T00:00:00Z")
    create_complaint(subscription["id"], "2026-08-05", "MISSED")
    return {"carrier": carrier, "route": route, "subscription": subscription}


class TestSettlementVariantDivergence:
    def test_carrier_settlement_gross_vs_net_divergence(self, api):
        """PRD §3.7: "To feel the variant difference: seven delivered copies
        at fifty cents each with one complaint yields 350 gross plus an
        18-cent bonus, settling at 368 cents under `PER_COPY_GROSS` but 218
        cents under `PER_COPY_NET_OF_COMPLAINTS` after the 150-cent
        deduction."

        Design: Difficulty/dual_variant_calc/carrier_settlement_gross_vs_net_divergence
        """
        gross_ctx = _carrier_with_full_week_delivery("PER_COPY_GROSS", "G", "g@x.com")
        net_ctx = _carrier_with_full_week_delivery(
            "PER_COPY_NET_OF_COMPLAINTS", "N", "n@x.com"
        )

        gross = get_settlement(gross_ctx["carrier"]["id"], "2026-08-03")
        assert_settlement(gross)
        assert gross["delivered_copies"] == 7
        assert gross["complaint_count"] == 1
        assert gross["gross_cents"] == 350
        assert gross["bonus_cents"] == 18       # round_half_up(350 * 0.05)
        assert gross["deduction_cents"] == 0    # GROSS forces deduction to 0
        assert gross["net_cents"] == 368

        net = get_settlement(net_ctx["carrier"]["id"], "2026-08-03")
        assert_settlement(net)
        assert net["delivered_copies"] == 7
        assert net["complaint_count"] == 1
        assert net["gross_cents"] == 350
        assert net["bonus_cents"] == 18
        assert net["deduction_cents"] == 150    # min(1 * 150, 3000)
        assert net["net_cents"] == 218

        assert gross["net_cents"] != net["net_cents"], (
            "identical operational inputs must diverge across compensation variants"
        )

    def test_carrier_settlement_bonus_dropped_over_two_complaints(self, api):
        """PRD §3.7: "A service bonus applies when complaints are few: at
        most two complaints earns a `bonus_cents` of five percent of gross,
        rounded half up; three or more complaints earns nothing."

        Design: Difficulty/dual_variant_calc/carrier_settlement_gross_vs_net_divergence
        """
        set_clock("2026-07-27T00:00:00Z")
        plan = create_plan(
            name="PB", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=700, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        carrier = create_carrier(
            display_name="B3", compensation_model="PER_COPY_GROSS",
            per_copy_rate_cents=50,
        )
        route = create_route(route_code="R-B3", carrier_id=carrier["id"], max_stops=10)
        subscriber = create_subscriber(
            display_name="B3", email="b3@x.com", service_address="2 Main St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-27")
        run_daily_cycle()
        create_assignment(subscription["id"], route["id"], "2026-07-27")

        # Three complaints on three distinct service dates inside the week.
        set_clock("2026-08-05T00:00:00Z")
        for service_date in ("2026-08-03", "2026-08-04", "2026-08-05"):
            create_complaint(subscription["id"], service_date, "MISSED")

        settlement = get_settlement(carrier["id"], "2026-08-03")
        assert settlement["delivered_copies"] == 7
        assert settlement["complaint_count"] == 3
        assert settlement["gross_cents"] == 350
        assert settlement["bonus_cents"] == 0, (
            "three or more complaints earns no bonus"
        )
        assert settlement["net_cents"] == 350


class TestSettlementHeldDays:
    def test_settlement_held_days_reduce_delivered_copies(self, api):
        """PRD §3.7: "The settlement walks the carrier's `ACTIVE` routes and,
        for every route assignment — regardless of assignment status — whose
        closed interval intersects the week, whose subscription's plan is
        print-capable, and whose subscription's billing state is `ACTIVE`,
        `GRACE`, or `CANCEL_PENDING`, it counts one delivered copy per
        delivery day: the overlap days between the assignment interval and
        the week, minus any held days falling inside that overlap."
        PRD §3.7: "`gross_cents` is the delivered copy count times the
        carrier's `per_copy_rate_cents`."

        Design: Corner/calculations/settlement_held_days_reduce_delivered_copies
        """
        set_clock("2026-07-27T00:00:00Z")
        plan = create_plan(
            name="SH", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=700, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        carrier = create_carrier(
            display_name="CH", compensation_model="PER_COPY_NET_OF_COMPLAINTS",
            per_copy_rate_cents=50,
        )
        route = create_route(route_code="RSH", carrier_id=carrier["id"], max_stops=10)
        subscriber = create_subscriber(
            display_name="SH", email="sh@x.com", service_address="7 Oak St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-07-27")
        run_daily_cycle()
        create_assignment(subscription["id"], route["id"], "2026-07-27")

        # Two held delivery days inside the settlement week of 2026-08-03.
        create_hold(subscription["id"], "2026-08-05", "2026-08-07", "CREDIT")
        set_clock_and_cycle("2026-08-05T00:00:00Z")  # hold activates
        set_clock_and_cycle("2026-08-07T00:00:00Z")  # hold completes

        settlement = get_settlement(carrier["id"], "2026-08-03")
        assert_settlement(settlement)
        assert settlement["delivered_copies"] == 5, "7 overlap days minus 2 held days"
        assert settlement["gross_cents"] == 250
        assert settlement["bonus_cents"] == 13  # round_half_up(250 * 0.05)
        assert settlement["deduction_cents"] == 0
        assert settlement["net_cents"] == 263

    def test_settlement_partial_week_assignment_overlap(self, api):
        """PRD §3.7: "Once a week, distribution settles with each carrier
        through a computed read parameterized by `week_start_date`, covering
        the Monday-anchored half-open week from that date through the
        following seven days."

        Design: Corner/calculations/settlement_held_days_reduce_delivered_copies
        """
        set_clock("2026-08-03T00:00:00Z")
        plan = create_plan(
            name="PW", plan_type="PRINT", issues_per_week=7,
            base_weekly_rate_cents=700, proration_method="PER_DAY",
            min_weekly_rate_cents=0,
        )
        carrier = create_carrier(
            display_name="PW", compensation_model="PER_COPY_GROSS",
            per_copy_rate_cents=50,
        )
        route = create_route(route_code="RPW", carrier_id=carrier["id"], max_stops=10)
        subscriber = create_subscriber(
            display_name="PW", email="pw@x.com", service_address="8 Oak St"
        )
        subscription = create_subscription(subscriber["id"], plan["id"], start_date="2026-08-03")
        run_daily_cycle()
        # Assignment covers only the last three days of the week.
        create_assignment(subscription["id"], route["id"], "2026-08-06", "2026-08-09")

        settlement = get_settlement(carrier["id"], "2026-08-03")
        assert settlement["delivered_copies"] == 3, (
            "only days inside both the week and the closed interval count"
        )
        assert settlement["gross_cents"] == 150
        assert settlement["bonus_cents"] == 8  # round_half_up(150 * 0.05)
        assert settlement["net_cents"] == 158


class TestSettlementEmptyWeek:
    def test_settlement_empty_week_zeros(self, api):
        """PRD §3.7: "The final `net_cents` is gross plus bonus minus
        deduction, floored at zero. To feel the variant difference: seven
        delivered copies at fifty cents each with one complaint yields 350
        gross plus an 18-cent bonus, settling at 368 cents under
        `PER_COPY_GROSS` but 218 cents under `PER_COPY_NET_OF_COMPLAINTS`
        after the 150-cent deduction."

        Design: Corner/endpoints/settlement_empty_week_zeros
        """
        carrier = create_carrier(
            display_name="EZ", compensation_model="PER_COPY_GROSS",
            per_copy_rate_cents=50,
        )
        settlement = get_settlement(carrier["id"], "2026-08-03")
        assert_settlement(settlement)
        assert settlement["delivered_copies"] == 0
        assert settlement["complaint_count"] == 0
        assert settlement["gross_cents"] == 0
        assert settlement["bonus_cents"] == 0
        assert settlement["deduction_cents"] == 0
        assert settlement["net_cents"] == 0

    def test_settlement_empty_week_net_model_also_zeros(self, api):
        """PRD §3.7: "Under `PER_COPY_NET_OF_COMPLAINTS`, the deduction is
        150 cents per complaint, capped at 3000 cents total. The final
        `net_cents` is gross plus bonus minus deduction, floored at zero."

        Design: Corner/endpoints/settlement_empty_week_zeros
        """
        carrier = create_carrier(
            display_name="EZN", compensation_model="PER_COPY_NET_OF_COMPLAINTS",
            per_copy_rate_cents=75,
        )
        settlement = get_settlement(carrier["id"], "2026-08-10")
        assert settlement["delivered_copies"] == 0
        assert settlement["gross_cents"] == 0
        assert settlement["bonus_cents"] == 0
        assert settlement["deduction_cents"] == 0
        assert settlement["net_cents"] == 0
