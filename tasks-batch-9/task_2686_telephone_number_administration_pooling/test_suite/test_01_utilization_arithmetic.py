"""Utilization arithmetic: the two per-filing bases and the pooled aggregate."""
from test_helpers import (
    assert_pct,
    create_eligible_carrier,
    create_submitted_filing,
    create_filing,
    load_held_blocks,
    open_audit_finding,
    read_filing,
    read_rate_center,
    set_clock,
    setup_npa_with_rate_center,
    submit_filing,
)


class TestClaimedVersusStrictUtilization:
    """One filing row yields two percentages over a single shared denominator."""

    def test_one_filing_publishes_both_the_claimed_and_the_strict_basis(self):
        """Submission computes both bases from the same counts.

        Consider a filing reporting 5 blocks held, 2500 assigned, 400
        intermediate, 200 reserved, 300 administrative and 200 aging: the
        denominator is 4500, the claimed numerator is 3100 giving 68.89, and the
        strict numerator is 2500 giving 55.56.

        Design: Difficulty/dual_variant_calc/carrier_utilization_strict_vs_claimed_divergence
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(npa, rate_center, carrier, 5, nxx_code="555")

        filing = create_submitted_filing(
            carrier,
            rate_center,
            numbers_assigned=2500,
            numbers_intermediate=400,
            numbers_reserved=200,
            numbers_aging=200,
            numbers_administrative=300,
            blocks_held_at_period_end=5,
            forecast_quarters=[1800, 1200, 900, 600],
        )

        assert filing["status"] == "SUBMITTED"
        assert_pct(filing["claimed_utilization_pct"], 68.89, "claimed_utilization_pct")
        assert_pct(filing["strict_utilization_pct"], 55.56, "strict_utilization_pct")
        # The strict figure is always at or below the claimed figure for the row.
        assert filing["strict_utilization_pct"] < filing["claimed_utilization_pct"]

    def test_an_overstatement_finding_audits_down_to_the_strict_basis(self):
        """The finding recomputes the strict basis over the adjusted inputs, and the
        13.33 point gap against the claimed figure earns a probation penalty.

        A difference of 20.00 points or more yields `RECLAMATION_REFERRAL`, a
        difference of 5.00 points or more yields `PROBATION`, and anything smaller
        yields `NONE`.

        Design: Difficulty/dual_variant_calc/carrier_utilization_strict_vs_claimed_divergence
        """
        set_clock()
        carrier = create_eligible_carrier("A")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(npa, rate_center, carrier, 5, nxx_code="555")
        filing = create_submitted_filing(
            carrier,
            rate_center,
            numbers_assigned=2500,
            numbers_intermediate=400,
            numbers_reserved=200,
            numbers_aging=200,
            numbers_administrative=300,
            blocks_held_at_period_end=5,
            forecast_quarters=[1800, 1200, 900, 600],
        )

        finding = open_audit_finding(
            filing,
            finding_type="OVERSTATED_UTILIZATION",
            adjusted_numbers_assigned=2500,
            adjusted_numbers_administrative=300,
        )

        assert_pct(finding["adjusted_utilization_pct"], 55.56, "adjusted_utilization_pct")
        assert finding["penalty_action"] == "PROBATION"
        assert finding["status"] == "OPEN"
        assert read_filing(filing["id"])["status"] == "UNDER_AUDIT"
        # The adjusted reading reproduces the strict basis exactly, because the
        # adjusted inputs repeat the filed ones.
        assert_pct(
            finding["adjusted_utilization_pct"],
            filing["strict_utilization_pct"],
            "adjusted against strict",
        )


class TestPooledAggregateUtilization:
    """A rate center's aggregate sums the two totals and rounds once at the end."""

    def test_aggregate_pools_the_two_totals_before_rounding_once(self):
        """Two holders pool into a single ratio.

        Two holders at 3100 over 4500 and 95 over 1000 pool to 3195 over 5500,
        which is 58.09.

        Design: Difficulty/combinatorial_formula/pooled_aggregate_utilization_sum_then_round
        """
        set_clock()
        carrier_a = create_eligible_carrier("A")
        carrier_b = create_eligible_carrier("B")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(npa, rate_center, carrier_a, 1, nxx_code="555")
        load_held_blocks(npa, rate_center, carrier_b, 1, nxx_code="556")

        filing_a = create_submitted_filing(
            carrier_a,
            rate_center,
            numbers_assigned=2500,
            numbers_intermediate=400,
            numbers_reserved=200,
            numbers_aging=200,
            numbers_administrative=300,
            blocks_held_at_period_end=5,
            forecast_quarters=[1800, 1200, 900, 600],
        )
        draft_b = create_filing(
            carrier_b,
            rate_center,
            numbers_assigned=95,
            numbers_intermediate=0,
            numbers_reserved=0,
            numbers_aging=0,
            numbers_administrative=0,
            blocks_held_at_period_end=1,
            forecast_quarters=[200, 200, 200, 200],
        )
        filing_b = submit_filing(carrier_b, draft_b)

        assert_pct(filing_a["claimed_utilization_pct"], 68.89, "filing A claimed")
        assert_pct(filing_b["claimed_utilization_pct"], 9.50, "filing B claimed")
        assert_pct(
            read_rate_center(rate_center["id"])["aggregate_utilization_pct"],
            58.09,
            "aggregate_utilization_pct",
        )

    def test_aggregate_is_not_the_average_of_the_rounded_filing_figures(self):
        """The wrong discipline is observably different.

        Averaging per-filing percentages that have already been rounded is wrong
        and observably different: two holders at 3100 over 4500 and 95 over 1000
        pool to 3195 over 5500, which is 58.09, whereas averaging the rounded
        68.89 and 9.50 would yield 39.20.

        Design: Difficulty/combinatorial_formula/pooled_aggregate_utilization_sum_then_round
        """
        set_clock()
        carrier_a = create_eligible_carrier("A")
        carrier_b = create_eligible_carrier("B")
        npa, rate_center = setup_npa_with_rate_center()
        load_held_blocks(npa, rate_center, carrier_a, 1, nxx_code="555")
        load_held_blocks(npa, rate_center, carrier_b, 1, nxx_code="556")

        create_submitted_filing(
            carrier_a,
            rate_center,
            numbers_assigned=2500,
            numbers_intermediate=400,
            numbers_reserved=200,
            numbers_aging=200,
            numbers_administrative=300,
            blocks_held_at_period_end=5,
            forecast_quarters=[1800, 1200, 900, 600],
        )
        draft_b = create_filing(
            carrier_b,
            rate_center,
            numbers_assigned=95,
            numbers_intermediate=0,
            numbers_reserved=0,
            numbers_aging=0,
            numbers_administrative=0,
            blocks_held_at_period_end=1,
            forecast_quarters=[200, 200, 200, 200],
        )

        # Before carrier B's filing is effective only carrier A pools in.
        assert_pct(
            read_rate_center(rate_center["id"])["aggregate_utilization_pct"],
            68.89,
            "aggregate over one holder",
        )

        submit_filing(carrier_b, draft_b)

        aggregate = read_rate_center(rate_center["id"])["aggregate_utilization_pct"]
        assert_pct(aggregate, 58.09, "aggregate_utilization_pct")
        assert abs(aggregate - 39.20) > 0.01, (
            "the aggregate must not be the average of the two rounded figures"
        )
