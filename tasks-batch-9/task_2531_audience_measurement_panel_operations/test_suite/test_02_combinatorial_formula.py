"""The two multi-step money formulas, pinned step by step.

Both calculations in this file are combinatorial: the incentive accrual walks
nine numbered steps that each round to whole cents before the next step reads
the result, and deliverable billing walks seven steps whose two bracket lookups
are both keyed on the gross figure. Either formula gives a different - and
wrong - answer if the steps are folded together or the brackets are keyed on the
discounted net, so every intermediate figure is asserted here.
"""

from datetime import datetime

from prd_bench_local_runner.testing import validate_success
from test_helpers.assertions import (
    expected_accrual_breakdown,
    expected_billing,
    expected_days_late,
    expected_penalty_rate,
    expected_volume_discount_rate,
    assert_billing_matches,
)
from test_helpers.constants import (
    BOOSTED_MULTIPLIER,
    INCENTIVE_PERIOD_CAP_CENTS,
    UNBOOSTED_MULTIPLIER,
)
from test_helpers.fixtures import CLOCK_T1, PanelHarness

# 2026-08-01 plus 198 whole days: six thirty-day tenure months, so the tenure
# multiplier is 1.075 and not 1.000 or 1.150.
TENURE_CLOCK = "2027-02-15T00:00:00Z"


def _tenured_home(
    panel: PanelHarness,
    target_households: int = 1,
    base_incentive_cents: int = 3000,
    extra_meter_types: tuple = (),
) -> dict:
    """One home recruited at 2026-08-01, reporting 350 minutes, aged to 2027-02-15.

    The extra meters are shipped before the tuner install is confirmed, because
    PRD 3.3 check 1 only admits a shipment while the household is `RECRUITED` or
    `INSTALL_SCHEDULED`. The single 350-minute block leaves the home's
    `compliance_rate_rolling_30` at 1.0000, which is what qualifies it for the
    step 5 bonus.
    """
    market, cells = panel.market_with_cells(
        [
            {
                "target_households": target_households,
                "base_incentive_cents": base_incentive_cents,
            }
        ],
        incentive_budget_cents=1000000,
    )
    household = panel.recruit_household(market["id"], cells[0]["id"], persons_count=2)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    extras = [
        panel.ship_meter(household["id"], meter_type=meter_type)
        for meter_type in extra_meter_types
    ]
    panel.install_meter(tuner["id"])
    for meter in extras:
        panel.install_meter(meter["id"])
    panel.enumerate_household(household["id"], roster_persons_count=2, tv_sets_count=1)
    panel.set_clock(CLOCK_T1)
    panel.ingest_interval(
        tuner["id"],
        household["id"],
        "2026-08-01T18:00:00Z",
        "2026-08-01T23:50:00Z",
        350,
    )
    panel.set_clock(TENURE_CLOCK)
    return {
        "market": market,
        "cell": cells[0],
        "household": panel.read_household(household["id"]),
        "tuner": tuner,
        "extras": extras,
    }


class TestIncentiveAccrualRoundingOrder:
    """Each of the nine steps rounds to whole cents before the next one reads it."""

    def test_bonus_and_supplement_read_the_rounded_tenure_amount(self, panel: PanelHarness):
        """A filled cell with a portable meter accrues 3632, not the 3631 of one rounding.

        PRD 3.4: "The amount is computed in nine numbered steps, and **each step
        rounds to whole cents before the next step reads its result**."

        Design: Difficulty/combinatorial_formula/incentive_accrual_component_rounding_order_mode_b
        """
        built = _tenured_home(panel, extra_meter_types=("PORTABLE_OOH",))
        home = built["household"]
        assert home["status"] == "ACTIVE"
        assert home["compliance_rate_rolling_30"] == 1.0000
        assert panel.read_quota_cell(built["cell"]["id"])["quota_status"] == "FILLED"
        assert (
            panel.read_quota_cell(built["cell"]["id"])["effective_incentive_multiplier"]
            == UNBOOSTED_MULTIPLIER
        )

        panel.accrue(home["id"], period_label="2026-08")

        # Step 3: 3000 * 1.00 = 3000. Step 4: 3000 * 1.075 = 3225.
        # Step 5: 8.55% of 3225 = 275.7375 -> 276 (not 275).
        # Step 6: 4.05% of 3225 = 130.6125 -> 131 (not 130).
        # Step 7: 3225 + 276 + 131 = 3632, where one final rounding gives 3631.
        breakdown = expected_accrual_breakdown(3000, UNBOOSTED_MULTIPLIER, 6, 1.0, True, False)
        assert breakdown["tenure_months"] == 6
        assert breakdown["cell_base"] == 3000
        assert breakdown["tenure_amount"] == 3225
        assert breakdown["compliance_bonus"] == 276
        assert breakdown["ooh_supplement"] == 131
        assert breakdown["gross"] == 3632
        assert breakdown["fault_penalty"] == 0
        assert breakdown["period_amount"] == 3632
        assert 3632 < INCENTIVE_PERIOD_CAP_CENTS

        home = panel.read_household(home["id"])
        assert home["incentive_accrued_cents"] == 3632
        assert len(home["accrual_periods"]) == 1
        entry = home["accrual_periods"][0]
        assert entry["period_label"] == "2026-08"
        assert entry["accrued_cents"] == 3632
        assert entry["reversed"] is False
        market = panel.read_market(built["market"]["id"])
        assert market["incentive_budget_committed_cents"] == 3632
        assert market["incentive_budget_reserved_cents"] == 0

    def test_armed_boost_multiplies_the_cell_base_before_tenure_and_drops_the_supplement(
        self, panel: PanelHarness
    ):
        """An under-target cell with no portable meter accrues 4376 instead of 3632.

        PRD 3.4: "The cell base is the quota cell's `base_incentive_cents`
        multiplied by the cell's `effective_incentive_multiplier`, rounded to a
        whole cent. A cell with an armed boost therefore pays a quarter more
        before tenure is even considered."

        Design: Difficulty/combinatorial_formula/incentive_accrual_component_rounding_order_mode_b
        """
        built = _tenured_home(panel, target_households=3)
        home = built["household"]
        cell = panel.read_quota_cell(built["cell"]["id"])
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["effective_incentive_multiplier"] == BOOSTED_MULTIPLIER

        panel.accrue(home["id"], period_label="2026-08")

        # Step 3: 3000 * 1.25 = 3750. Step 4: 3750 * 1.075 = 4031.25 -> 4031.
        # Step 5: 8.55% of 4031 = 344.6505 -> 345. Step 6 is 0 with no
        # PORTABLE_OOH device installed. Step 7: 4031 + 345 = 4376.
        breakdown = expected_accrual_breakdown(3000, BOOSTED_MULTIPLIER, 6, 1.0, False, False)
        assert breakdown["cell_base"] == 3750
        assert breakdown["tenure_amount"] == 4031
        assert breakdown["compliance_bonus"] == 345
        assert breakdown["ooh_supplement"] == 0
        assert breakdown["period_amount"] == 4376

        home = panel.read_household(home["id"])
        assert home["incentive_accrued_cents"] == 4376
        assert home["accrual_periods"][0]["accrued_cents"] == 4376
        market = panel.read_market(built["market"]["id"])
        assert market["incentive_budget_committed_cents"] == 4376
        # 3000 * 0.25 * 3, still reserved for the armed boost.
        assert market["incentive_budget_reserved_cents"] == 2250

    def test_faulted_router_penalises_the_gross_without_holding_the_household(
        self, panel: PanelHarness
    ):
        """A faulted streaming router costs 25 percent of the gross: 3501 becomes 2626.

        PRD 3.4: "The fault penalty is 25 percent of that gross, rounded to a
        whole cent, and applies only when the household holds at least one meter
        whose `health_status` is `FAULTED`".

        Design: Difficulty/combinatorial_formula/incentive_accrual_component_rounding_order_mode_b
        """
        built = _tenured_home(panel, extra_meter_types=("STREAMING_ROUTER",))
        home = built["household"]
        router = built["extras"][0]
        validate_success(panel.client.report_meter_fault(panel.tech, router["id"], "NO_SIGNAL"), 200)
        assert panel.read_meter(router["id"])["health_status"] == "FAULTED"
        # PRD 3.3 link 2 never fires for a router, so the home is still earning.
        assert panel.read_household(home["id"])["status"] == "ACTIVE"

        panel.accrue(home["id"], period_label="2026-08")

        # Steps 3-7: 3000, 3225, 276, 0, 3501. Step 8: 25% of 3501 = 875.25 ->
        # 875. Step 9: 3501 - 875 = 2626, under the 5000 cap.
        breakdown = expected_accrual_breakdown(3000, UNBOOSTED_MULTIPLIER, 6, 1.0, False, True)
        assert breakdown["gross"] == 3501
        assert breakdown["fault_penalty"] == 875
        assert breakdown["period_amount"] == 2626

        home = panel.read_household(home["id"])
        assert home["incentive_accrued_cents"] == 2626
        assert home["accrual_periods"][0]["accrued_cents"] == 2626
        assert panel.read_market(built["market"]["id"])["incentive_budget_committed_cents"] == 2626


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC stamp whether or not it carries fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _placed_dataset(panel: PanelHarness, requested_cell_count: int, tier: str = "STANDARD") -> dict:
    """A dataset placed against a WEIGHTED run, then published to start the clock.

    The placement is made before publication precisely so that publication is
    what stamps `due_at`: PRD 3.7 makes every `SCHEDULED` deliverable of the run
    due at "the current logical clock plus that client's `delivery_sla_hours`",
    which for a `STANDARD` subscriber is 72 hours after 2026-08-02.
    """
    base = panel.weighted_run()
    client = panel.create_client([base["market"]["id"]], tier=tier)
    deliverable = panel.schedule_deliverable(
        client["id"], base["run"]["id"], requested_cell_count=requested_cell_count
    )
    run = panel.publish_run(base["run"]["id"])
    return {
        "market": base["market"],
        "run": run,
        "client": client,
        "deliverable": panel.read_deliverable(deliverable["id"]),
    }


class TestDeliverableBillingBracketsKeyOnGross:
    """Both bracket lookups read `gross_cents`, never the discounted net."""

    def test_penalty_bracket_reads_the_gross_and_not_the_discounted_net(
        self, panel: PanelHarness
    ):
        """155000 gross two days late totals 124000, not the 127100 of a net lookup.

        PRD 3.8: "This bracket is keyed on the **gross** figure and not on the
        discounted net; using the net figure would land a borderline item in a
        lower bracket and is wrong."

        Design: Difficulty/combinatorial_formula/deliverable_billing_penalty_bracket_keyed_on_gross_mode_c
        """
        built = _placed_dataset(panel, 18)
        assert built["client"]["tier_base_fee_cents"] == 65000
        assert built["client"]["delivery_sla_hours"] == 72
        assert _instant(built["deliverable"]["due_at"]) == _instant("2026-08-05T00:00:00Z")
        panel.set_clock("2026-08-07T00:00:00Z")

        row = validate_success(
            panel.client.dispatch_deliverable(panel.rep, built["deliverable"]["id"]), 200
        )

        # Step 1: 65000 + 18 * 5000 = 155000. Step 2: 155000 >= 150000 -> 0.15.
        # Step 3: 23250. Step 4: two whole days late. Step 5: the gross is still
        # 155000, so the rate is 0.025 and not the 0.015 the 131750 net would
        # buy. Step 6: 155000 * 0.025 * 2 = 7750. Step 7: 124000.
        assert row["state"] == "DELIVERED"
        assert row["gross_cents"] == 155000
        assert row["discount_cents"] == 23250
        assert row["days_late"] == 2
        assert row["late_penalty_cents"] == 7750
        assert row["total_cents"] == 124000
        assert expected_volume_discount_rate(155000) == 0.15
        assert expected_penalty_rate(155000) == 0.025
        assert expected_penalty_rate(155000 - 23250) == 0.015
        assert_billing_matches(row, expected_billing(65000, 18, days_late=2))
        assert expected_days_late(
            int(_instant("2026-08-05T00:00:00Z").timestamp()),
            int(_instant("2026-08-07T00:00:00Z").timestamp()),
        ) == 2

        assert row["findings_summary"] is None
        assert _instant(row["delivered_at"]) == _instant("2026-08-07T00:00:00Z")
        client = panel.read_client(built["client"]["id"])
        assert client["delivery_sla_credit_cents"] == 7750
        assert client["custom_analysis_used"] == 0

    def test_gross_at_exactly_eighty_thousand_takes_the_mid_bracket_both_ways(
        self, panel: PanelHarness
    ):
        """A gross of exactly 80000 is discounted at 0.10 and penalised at 0.015.

        PRD 3.8: "The penalty rate is 0.000 when `gross_cents` is below 80000,
        0.015 when it is at least 80000 but below 150000, and 0.025 when it is
        150000 or more."

        Design: Difficulty/combinatorial_formula/deliverable_billing_penalty_bracket_keyed_on_gross_mode_c
        """
        built = _placed_dataset(panel, 3)
        panel.set_clock("2026-08-07T00:00:00Z")

        row = validate_success(
            panel.client.dispatch_deliverable(panel.rep, built["deliverable"]["id"]), 200
        )

        # 65000 + 3 * 5000 = 80000, the inclusive bottom of the middle bracket.
        # The 72000 net would fall back into the 0.000 penalty bracket, so a
        # penalty of 2400 rather than 0 is what proves the gross keying.
        assert row["gross_cents"] == 80000
        assert row["discount_cents"] == 8000
        assert row["days_late"] == 2
        assert row["late_penalty_cents"] == 2400
        assert row["total_cents"] == 69600
        assert expected_penalty_rate(80000) == 0.015
        assert expected_penalty_rate(80000 - 8000) == 0.000
        assert_billing_matches(row, expected_billing(65000, 3, days_late=2))
        assert panel.read_client(built["client"]["id"])["delivery_sla_credit_cents"] == 2400

    def test_dispatch_at_exactly_due_at_is_not_late_and_carries_no_penalty(
        self, panel: PanelHarness
    ):
        """Delivered on the deadline itself, the same 155000 item totals 131750.

        PRD 3.8: "`days_late` is the elapsed time from the row's `due_at` to the
        current logical clock, divided by 86400 seconds, rounded **up** to a
        whole day and floored at 0."

        Design: Difficulty/combinatorial_formula/deliverable_billing_penalty_bracket_keyed_on_gross_mode_c
        """
        built = _placed_dataset(panel, 18)
        panel.set_clock("2026-08-05T00:00:00Z")

        row = validate_success(
            panel.client.dispatch_deliverable(panel.rep, built["deliverable"]["id"]), 200
        )

        assert row["gross_cents"] == 155000
        assert row["discount_cents"] == 23250
        assert row["days_late"] == 0
        assert row["late_penalty_cents"] == 0
        assert row["total_cents"] == 131750
        assert_billing_matches(row, expected_billing(65000, 18, days_late=0))
        # PRD 3.8: the credit "rises by the `late_penalty_cents` just computed".
        assert panel.read_client(built["client"]["id"])["delivery_sla_credit_cents"] == 0
