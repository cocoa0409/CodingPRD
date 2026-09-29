"""Entitlement ceilings, the utilization tier boundary and the pool draw."""
from test_helpers import (
    APPROVER_HEADERS,
    ApiErrorId,
    api_client,
    approve_request,
    assert_pct,
    create_eligible_carrier,
    create_submitted_filing,
    file_allocation_request,
    load_block,
    load_pool_blocks,
    make_rate_center_pooled,
    read_block,
    read_rate_center,
    read_request,
    set_clock,
    setup_npa_with_rate_center,
    validate_error,
)


def _two_carriers_over_a_six_block_pool():
    """Carrier A at 68.89 asking 4 blocks, carrier C at 93.33 asking 2, pool of six."""
    set_clock()
    carrier_a = create_eligible_carrier("A")
    carrier_c = create_eligible_carrier("C")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 6, nxx_code="556")
    load_block(
        npa, rate_center, nxx_code="555", thousands_digit=0, contaminated_count=0,
        holder_carrier_id=carrier_a["id"], mark_activated=True,
    )
    load_block(
        npa, rate_center, nxx_code="554", thousands_digit=0, contaminated_count=0,
        holder_carrier_id=carrier_c["id"], mark_activated=True,
    )
    create_submitted_filing(
        carrier_a, rate_center,
        numbers_assigned=2500, numbers_intermediate=400, numbers_reserved=200,
        numbers_aging=200, numbers_administrative=300,
        blocks_held_at_period_end=5, forecast_quarters=[3600, 2400, 1200, 600],
    )
    create_submitted_filing(
        carrier_c, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[3600, 2400, 1200, 600],
    )
    request_a = file_allocation_request(
        carrier_a, rate_center, request_type="GROWTH", requested_block_count=4,
        justification="four blocks requested",
    )
    request_c = file_allocation_request(
        carrier_c, rate_center, request_type="GROWTH", requested_block_count=2,
        justification="two blocks requested",
    )
    return {
        "carrier_a": carrier_a,
        "carrier_c": carrier_c,
        "npa": npa,
        "rate_center": rate_center,
        "pool_blocks": pool_blocks,
        "request_a": request_a,
        "request_c": request_c,
    }


class TestNestedMinimumEntitlement:
    """The grant is the smallest of the ask, the tier, the demand and the pool."""

    def test_tier_cap_of_one_beats_a_four_block_ask_and_a_six_block_pool(self):
        """At 68.89 the tier caps the grant at one block, whatever else is available.

        The entitlement itself is the smallest of four independent ceilings, none of
        which predicts the answer on its own.

        Design: Difficulty/combinatorial_formula/growth_grant_size_nested_min_with_tier_cap
        """
        scenario = _two_carriers_over_a_six_block_pool()

        approve_request(scenario["request_a"])

        decided = read_request(scenario["request_a"]["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert_pct(
            decided["utilization_pct_at_submission"], 68.89, "utilization_pct_at_submission"
        )
        assert decided["assigned_block_ids"] == [scenario["pool_blocks"][0]["id"]]
        assert read_rate_center(scenario["rate_center"]["id"])["available_block_count"] == 5

    def test_a_higher_tier_on_the_same_pool_grants_two_blocks_in_ranking_order(self):
        """Carrier C reads 93.33, so its tier cap of three lets its full ask through,
        and the draw hands out the next two blocks in ranking order.

        Candidates are ordered by `contaminated_count` ascending, then `nxx_code`
        ascending, then `thousands_digit` ascending, then `created_at` ascending.

        Design: Difficulty/combinatorial_formula/growth_grant_size_nested_min_with_tier_cap
        """
        scenario = _two_carriers_over_a_six_block_pool()

        approve_request(scenario["request_a"])
        approve_request(scenario["request_c"])

        decided_a = read_request(scenario["request_a"]["id"])
        decided_c = read_request(scenario["request_c"]["id"])
        assert decided_c["status"] == "APPROVED"
        assert decided_c["granted_block_count"] == 2
        assert_pct(
            decided_c["utilization_pct_at_submission"], 93.33, "utilization_pct_at_submission"
        )
        assert decided_c["assigned_block_ids"] == [
            scenario["pool_blocks"][1]["id"],
            scenario["pool_blocks"][2]["id"],
        ]
        # Neither grant equals carrier A's ask of 4 nor the demand ceiling of 6.
        assert decided_a["granted_block_count"] == 1
        assert decided_a["requested_block_count"] == 4
        assert read_rate_center(scenario["rate_center"]["id"])["available_block_count"] == 3


def _two_carriers_either_side_of_the_tier_boundary():
    """Carrier A computes to exactly 60.00 and carrier B to 59.99 on the same shape."""
    set_clock()
    carrier_a = create_eligible_carrier("A")
    carrier_b = create_eligible_carrier("B")
    npa, rate_center = setup_npa_with_rate_center()
    pool_blocks = load_pool_blocks(npa, rate_center, 2, nxx_code="556")
    filing_a = create_submitted_filing(
        carrier_a, rate_center,
        numbers_assigned=6000, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=10, forecast_quarters=[1200, 800, 600, 400],
    )
    filing_b = create_submitted_filing(
        carrier_b, rate_center,
        numbers_assigned=5999, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=10, forecast_quarters=[1200, 800, 600, 400],
    )
    request_a = file_allocation_request(
        carrier_a, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="at the threshold exactly",
    )
    request_b = file_allocation_request(
        carrier_b, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one number under the threshold",
    )
    return {
        "rate_center": rate_center,
        "pool_blocks": pool_blocks,
        "filing_a": filing_a,
        "filing_b": filing_b,
        "request_a": request_a,
        "request_b": request_b,
    }


class TestUtilizationTierBoundary:
    """The lowest tier is entered inclusively at 60.00."""

    def test_exactly_sixty_percent_earns_the_lowest_tier_and_one_block(self):
        """6000 assigned over 10 blocks held is 60.00 exactly, which is inside the tier.

        3 blocks when that figure is at or above 90.00, 2 blocks when it is at or
        above 75.00, 1 block when it is at or above 60.00, and 0 blocks below that.

        Design: Difficulty/boundary_precision_check/utilization_exactly_sixty_pct_grants_while_fifty_nine_ninety_nine_fails
        """
        scenario = _two_carriers_either_side_of_the_tier_boundary()

        assert_pct(
            scenario["filing_a"]["claimed_utilization_pct"], 60.00, "filing A claimed"
        )

        approve_request(scenario["request_a"])

        decided = read_request(scenario["request_a"]["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert decided["assigned_block_ids"] == [scenario["pool_blocks"][0]["id"]]

    def test_fifty_nine_ninety_nine_falls_below_the_tier_and_is_refused(self):
        """One number short of the boundary reads 59.99, which is a tier cap of zero.

        A tier cap of zero — an effective utilization below 60.00 on a `GROWTH` or
        `POOL_REPLENISH` request — is refused with `ERR_UTILIZATION_THRESHOLD_NOT_MET`

        Design: Difficulty/boundary_precision_check/utilization_exactly_sixty_pct_grants_while_fifty_nine_ninety_nine_fails
        """
        scenario = _two_carriers_either_side_of_the_tier_boundary()
        assert_pct(
            scenario["filing_b"]["claimed_utilization_pct"], 59.99, "filing B claimed"
        )

        approve_request(scenario["request_a"])

        validate_error(
            api_client.create_review(
                scenario["request_b"]["id"], {"action": "APPROVE"}, APPROVER_HEADERS
            ),
            ApiErrorId.ERR_UTILIZATION_THRESHOLD_NOT_MET,
            422,
        )

        assert read_request(scenario["request_b"]["id"])["status"] == "PENDING_REVIEW"
        second = read_block(scenario["pool_blocks"][1]["id"])
        assert second["allocation_status"] == "POOL_AVAILABLE"
        assert second["holder_carrier_id"] is None
        assert read_rate_center(scenario["rate_center"]["id"])["available_block_count"] == 1


def _pooled_rate_center_with_two_contaminated_blocks():
    """A POOLED rate center holding one block at 100 contaminated and one at 101."""
    set_clock()
    carrier = create_eligible_carrier("A")
    npa, rate_center = setup_npa_with_rate_center()
    make_rate_center_pooled(rate_center)
    block_at_100 = load_block(
        npa, rate_center, nxx_code="557", thousands_digit=0, contaminated_count=100
    )
    block_at_101 = load_block(
        npa, rate_center, nxx_code="557", thousands_digit=1, contaminated_count=101
    )
    create_submitted_filing(
        carrier, rate_center,
        numbers_assigned=2800, numbers_intermediate=0, numbers_reserved=0,
        numbers_aging=0, numbers_administrative=0,
        blocks_held_at_period_end=3, forecast_quarters=[1200, 800, 600, 400],
    )
    request = file_allocation_request(
        carrier, rate_center, request_type="GROWTH", requested_block_count=1,
        justification="one contaminated block is acceptable",
    )
    return {
        "carrier": carrier,
        "rate_center": rate_center,
        "block_at_100": block_at_100,
        "block_at_101": block_at_101,
        "request": request,
    }


class TestContaminationCeiling:
    """The pooling eligibility ceiling is inclusive at one hundred."""

    def test_one_hundred_contaminated_numbers_is_still_pooling_eligible(self):
        """One hundred is inside the ceiling and one hundred and one is outside it.

        A block's `is_pooling_eligible` is true when its `contaminated_count` is at
        most 100

        Design: Difficulty/boundary_precision_check/contamination_exactly_one_hundred_stays_pooling_eligible
        """
        scenario = _pooled_rate_center_with_two_contaminated_blocks()

        assert scenario["block_at_100"]["contaminated_count"] == 100
        assert scenario["block_at_100"]["is_pooling_eligible"] is True
        assert scenario["block_at_101"]["contaminated_count"] == 101
        assert scenario["block_at_101"]["is_pooling_eligible"] is False

    def test_the_pooled_draw_takes_the_eligible_block_and_leaves_the_other_behind(self):
        """A pooled rate center hands out the block at the ceiling and never the one
        above it.

        A `POOLED` rate center may hand out contaminated blocks, because the pool-draw
        candidate test drops its pristine-only requirement once `pooling_status` reads
        `POOLED`

        Design: Difficulty/boundary_precision_check/contamination_exactly_one_hundred_stays_pooling_eligible
        """
        scenario = _pooled_rate_center_with_two_contaminated_blocks()

        approve_request(scenario["request"])

        decided = read_request(scenario["request"]["id"])
        assert decided["status"] == "APPROVED"
        assert decided["granted_block_count"] == 1
        assert decided["assigned_block_ids"] == [scenario["block_at_100"]["id"]]

        drawn = read_block(scenario["block_at_100"]["id"])
        assert drawn["allocation_status"] == "RESERVED"
        assert drawn["holder_carrier_id"] == scenario["carrier"]["id"]

        left_behind = read_block(scenario["block_at_101"]["id"])
        assert left_behind["allocation_status"] == "POOL_AVAILABLE"
        assert left_behind["holder_carrier_id"] is None

        rate_center = read_rate_center(scenario["rate_center"]["id"])
        assert rate_center["available_block_count"] == 1
        assert rate_center["pooling_status"] == "POOLED"
