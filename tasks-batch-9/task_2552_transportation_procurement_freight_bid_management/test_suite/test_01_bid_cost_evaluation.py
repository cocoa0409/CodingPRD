"""Evaluated cost of a lane bid: the two cost bases and the pinned rounding order."""

from test_helpers import (
    read_lane_bid,
    second_carrier_overrides,
    setup_open_round_with_bidder,
    submit_bid,
)

LANE_A = {"seasonality_peak_index": 1.20}
BID_A = {
    "rate_per_mile": 2.1152,
    "fuel_surcharge_included": True,
    "committed_volume_loads": 600,
    "transit_days_offered": 3,
}


def _bid_on_basis(cost_basis: str, carrier_overrides=None):
    """One qualified bidder, one 1147-mile lane, one bid, on the given cost basis.

    `scac_code` is unique across all carriers, so a test that walks this chain
    twice must register the second bidder under its own SCAC.
    """
    ctx = setup_open_round_with_bidder(
        carrier_overrides=carrier_overrides,
        lane_overrides=[LANE_A],
        cost_basis=cost_basis,
        rounds_allowed=2,
    )
    bid = submit_bid(
        ctx["bid_round"]["id"], ctx["lane"]["id"], ctx["carrier"]["id"], **BID_A
    )
    return ctx, bid


class TestCostBasisVariants:
    """The FORECAST and HISTORICAL variants of the evaluated-cost rule."""

    def test_forecast_basis_inflates_accessorials_and_grows_the_volume_basis(self):
        """A FORECAST event inflates the accessorial term and grows the volume basis.

        PRD §3.5: "Under the `FORECAST` variant, multiply the lane's
        `accessorial_history_usd_per_load` by the event's
        `accessorial_inflation_factor` and round to 2 decimal places."
        PRD §3.5: "Under the `FORECAST` variant, multiply the lane's
        `annual_volume_loads` by the forecast growth factor of `1.20` and round to a
        whole number of loads." and "Then take `awardable_volume_loads` as the smaller
        of the carrier's `committed_volume_loads` and that volume basis".
        PRD §3.5: "The bid records which variant was applied in its own
        `evaluated_basis` field, so a bid always carries the evidence of how it was
        scored."

        Design: Difficulty/dual_variant_calc/lane_evaluated_cost_forecast_versus_historical_basis
        """
        _, bid = _bid_on_basis("FORECAST")

        assert bid["evaluated_basis"] == "FORECAST", (
            f"a FORECAST event must score its bids on the FORECAST variant, "
            f"got {bid['evaluated_basis']}"
        )
        assert bid["linehaul_per_load_usd"] == 2426.13, (
            f"1147 miles at 2.1152 is 2426.13 per load, got {bid['linehaul_per_load_usd']}"
        )
        assert bid["accessorial_per_load_usd"] == 158.18, (
            f"137.55 inflated by 1.15 is 158.18, got {bid['accessorial_per_load_usd']}"
        )
        assert bid["cost_per_load_usd"] == 2584.31, (
            f"2426.13 + 158.18 is 2584.31, got {bid['cost_per_load_usd']}"
        )
        assert bid["awardable_volume_loads"] == 600, (
            f"min(600 committed, 660 grown basis) is 600, "
            f"got {bid['awardable_volume_loads']}"
        )
        assert bid["evaluated_total_cost_usd"] == 1550586.00, (
            f"2584.31 x 600 is 1550586.00, got {bid['evaluated_total_cost_usd']}"
        )

    def test_historical_basis_takes_accessorials_unchanged_and_trailing_volume(self):
        """A HISTORICAL event applies no inflation and reads the trailing volume.

        PRD §3.5: "Under the `HISTORICAL` variant, take
        `accessorial_history_usd_per_load` unchanged, with no inflation applied at
        all."
        PRD §3.5: "Under the `HISTORICAL` variant, the volume basis is the lane's
        `trailing_12m_actual_loads` as recorded."
        PRD §3.5: "Multiply `cost_per_load_usd` by `awardable_volume_loads` and round
        to 2 decimal places, giving `evaluated_total_cost_usd`."

        Design: Difficulty/dual_variant_calc/lane_evaluated_cost_forecast_versus_historical_basis
        """
        _, bid = _bid_on_basis("HISTORICAL")

        assert bid["evaluated_basis"] == "HISTORICAL", (
            f"a HISTORICAL event must score its bids on the HISTORICAL variant, "
            f"got {bid['evaluated_basis']}"
        )
        assert bid["linehaul_per_load_usd"] == 2426.13, (
            f"the linehaul term is basis-independent at 2426.13, "
            f"got {bid['linehaul_per_load_usd']}"
        )
        assert bid["accessorial_per_load_usd"] == 137.55, (
            f"the accessorial history is taken unchanged at 137.55, "
            f"got {bid['accessorial_per_load_usd']}"
        )
        assert bid["cost_per_load_usd"] == 2563.68, (
            f"2426.13 + 137.55 is 2563.68, got {bid['cost_per_load_usd']}"
        )
        assert bid["awardable_volume_loads"] == 480, (
            f"min(600 committed, 480 trailing) is 480, "
            f"got {bid['awardable_volume_loads']}"
        )
        assert bid["evaluated_total_cost_usd"] == 1230566.40, (
            f"2563.68 x 480 is 1230566.40, got {bid['evaluated_total_cost_usd']}"
        )

    def test_identical_bids_diverge_between_a_forecast_and_a_historical_event(self):
        """Byte-identical bid data scores differently under the two cost bases.

        PRD §3.5: "This is the only step where the two variants differ in their
        treatment of accessorials, and it is the reason the same bid scores
        differently in a forecast event and a historical one."

        Design: Difficulty/dual_variant_calc/lane_evaluated_cost_forecast_versus_historical_basis
        """
        _, forecast_bid = _bid_on_basis("FORECAST")
        _, historical_bid = _bid_on_basis(
            "HISTORICAL", carrier_overrides=second_carrier_overrides()
        )

        assert forecast_bid["rate_per_mile"] == historical_bid["rate_per_mile"], (
            "the two bids must be identical in their inputs for the comparison to mean "
            "anything"
        )
        assert (
            forecast_bid["evaluated_total_cost_usd"]
            != historical_bid["evaluated_total_cost_usd"]
        ), (
            "the same bid must not evaluate to the same annual cost under both bases, "
            f"got {forecast_bid['evaluated_total_cost_usd']} twice"
        )
        assert forecast_bid["evaluated_total_cost_usd"] == 1550586.00
        assert historical_bid["evaluated_total_cost_usd"] == 1230566.40


class TestPinnedRoundingOrder:
    """Round-then-sum is normative: the components are rounded before they are added."""

    def test_cost_per_load_sums_two_already_rounded_components(self):
        """2426.1344 and 158.1825 are each rounded before they are added.

        PRD §3.5: "Add `linehaul_per_load_usd` and `accessorial_per_load_usd`. Both
        are already rounded to 2 decimal places, and `cost_per_load_usd` is the sum of
        those two already-rounded figures. Computing the unrounded linehaul plus the
        unrounded accessorial and rounding once at the end is **wrong** and can differ
        by a cent, which propagates into every downstream total."

        Design: Difficulty/combinatorial_formula/lane_evaluated_cost_pinned_rounding_order
        """
        _, bid = _bid_on_basis("FORECAST")

        assert bid["linehaul_per_load_usd"] == 2426.13, (
            f"the raw 2426.1344 must be rounded before summation, "
            f"got {bid['linehaul_per_load_usd']}"
        )
        assert bid["accessorial_per_load_usd"] == 158.18, (
            f"the raw 158.1825 must be rounded before summation, "
            f"got {bid['accessorial_per_load_usd']}"
        )
        assert bid["cost_per_load_usd"] == 2584.31, (
            f"the sum of the two rounded terms is 2584.31, "
            f"got {bid['cost_per_load_usd']}"
        )
        assert bid["cost_per_load_usd"] != 2584.32, (
            "2584.32 is the sum-then-round answer and is rejected by the pinned "
            "rounding order"
        )

    def test_evaluated_total_multiplies_the_already_rounded_per_load_figure(self):
        """The annual total is built from the rounded per-load cost, not the raw one.

        PRD §3.5: "Multiply `cost_per_load_usd` by `awardable_volume_loads` and round
        to 2 decimal places, giving `evaluated_total_cost_usd`."
        PRD §2.7: "where a rule rounds two components separately and then adds them,
        the sum of the two already-rounded components is the answer, and rounding once
        at the end of the unrounded expression is wrong."

        Design: Difficulty/combinatorial_formula/lane_evaluated_cost_pinned_rounding_order
        """
        _, bid = _bid_on_basis("FORECAST")

        assert bid["evaluated_total_cost_usd"] == 1550586.00, (
            f"2584.31 x 600 loads is 1550586.00, "
            f"got {bid['evaluated_total_cost_usd']}"
        )
        assert bid["evaluated_total_cost_usd"] != 1550592.00, (
            "1550592.00 is the raw-product answer and is rejected by the pinned "
            "rounding order"
        )
        refreshed = read_lane_bid(bid["id"])
        assert refreshed["evaluated_total_cost_usd"] == 1550586.00, (
            "the stored figure must match the figure returned at submission"
        )
