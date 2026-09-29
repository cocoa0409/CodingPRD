"""Harvest reservation: the nested revenue clamps, the tonnage boundary and the re-entry buffer."""

from test_helpers import (
    ApiErrorId,
    assert_fund_cash,
    assert_money,
    assert_stand_partition,
    assert_tons,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import harvest_block_payload
from test_helpers.fixtures import (
    cruised_stand,
    read_fund,
    read_stand,
    reserve_block,
    stand_version,
)
from test_helpers.test_users import make_forest_manager_headers

BLOCK_X = {
    "planned_start_date": "2027-06-01",
    "planned_end_date": "2027-09-30",
    "planned_tons": 1000.00,
    "product_mix": "MIXED",
    "expected_stumpage_price_usd_per_ton": 58.00,
    "price_index_factor": 1.05,
    "expected_haul_distance_miles": 140,
}
BLOCK_Y = {
    "planned_start_date": "2029-10-01",
    "planned_end_date": "2029-12-31",
    "planned_tons": 150.00,
    "product_mix": "PULPWOOD",
    "expected_stumpage_price_usd_per_ton": 60.50,
    "price_index_factor": 1.00,
    "expected_haul_distance_miles": 45,
}


class TestNestedRevenueClamps:
    """One net-revenue formula with two different clamps active on two blocks of one stand."""

    def test_the_haul_cost_bills_only_ninety_of_the_hundred_and_forty_miles(self, api):
        """A 140-mile block is billed at the ninety-mile cap, so net revenue is 22889.55.

        PRD: "the billable mileage is the lesser of `expected_haul_distance_miles` and ninety miles, with any distance beyond ninety absorbed by the contractor"

        Design: Difficulty/combinatorial_formula/harvest_revenue_nests_haul_mile_cap_inside_severance_floor
        """
        ctx = cruised_stand(api)

        block = reserve_block(api, ctx.stand_id, **BLOCK_X)

        assert_money(
            block["provisional_net_revenue_usd"], 22889.55, "provisional_net_revenue_usd"
        )
        assert abs(float(block["provisional_net_revenue_usd"]) - 15639.55) > 0.01, (
            "an uncapped 140-mile haul would have produced 15639.55"
        )
        assert_money(block["severance_tax_usd"], 1248.45, "severance_tax_usd")
        assert block["years_to_start"] == 0
        assert_tons(block["projected_available_tons"], 4647.12, "projected_available_tons")

    def test_the_severance_tax_is_lifted_to_the_floor_on_a_small_pulpwood_block(self, api):
        """A block whose two-and-a-half percent tax falls short pays the 250.00 floor instead.

        PRD: "it is the greater of two hundred fifty dollars and gross revenue multiplied by two and one half percent rounded half-up to two decimals"

        Design: Difficulty/combinatorial_formula/harvest_revenue_nests_haul_mile_cap_inside_severance_floor
        """
        ctx = cruised_stand(api)
        reserve_block(api, ctx.stand_id, **BLOCK_X)

        block = reserve_block(api, ctx.stand_id, **BLOCK_Y)

        assert_money(block["severance_tax_usd"], 250.00, "severance_tax_usd")
        assert_money(
            block["provisional_net_revenue_usd"], 2394.50, "provisional_net_revenue_usd"
        )
        assert block["years_to_start"] == 3
        assert_tons(block["projected_available_tons"], 4257.59, "projected_available_tons")

    def test_the_provisional_figures_never_reach_fund_cash(self, api):
        """Two reservations accumulate against the stand and leave the fund's cash alone.

        PRD: "At creation the tonnage is `planned_tons` and the index is `price_index_factor`, and the result is written to `provisional_net_revenue_usd`; the provisional figure never touches fund cash."

        Design: Difficulty/combinatorial_formula/harvest_revenue_nests_haul_mile_cap_inside_severance_floor
        """
        ctx = cruised_stand(api)
        reserve_block(api, ctx.stand_id, **BLOCK_X)
        reserve_block(api, ctx.stand_id, **BLOCK_Y)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=1150.00,
            available_tons=3497.12,
        )
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=400000.00,
            net_operating_cash_usd=0.00,
        )


class TestAvailableTonsBoundary:
    """Equality with available tons is permitted; one hundredth beyond it is not."""

    def test_one_hundredth_beyond_available_tons_is_refused(self, api):
        """Reserving 4647.13 against 4647.12 of headroom is an over-reservation.

        PRD: "Finally, `planned_tons` must be no greater than the stand's `available_tons`, with equality permitted; an over-reservation is refused with `ERR_INSUFFICIENT_AVAILABLE_TONS`."

        Design: Difficulty/boundary_precision_check/available_tons_boundary_allows_exact_4647_12_and_rejects_4647_13
        """
        ctx = cruised_stand(api)
        version = stand_version(api, ctx.stand_id)

        response = api.create_harvest_block(
            harvest_block_payload(
                ctx.stand_id,
                version,
                planned_tons=4647.13,
                product_mix="SAWTIMBER",
                expected_haul_distance_miles=62,
            ),
            make_forest_manager_headers(),
        )
        validate_error(response, ApiErrorId.INSUFFICIENT_AVAILABLE_TONS.value, 422)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            reserved_tons=0.00,
            available_tons=4647.12,
        )

    def test_a_reservation_exactly_at_available_tons_is_accepted(self, api):
        """Reserving the whole 4647.12 empties the headroom and leaves the pool intact.

        PRD: "On acceptance the block is created in `RESERVED`, its `planned_tons` is added to the stand's `reserved_tons` and subtracted from `available_tons`, and the stand's `version` is incremented."

        Design: Difficulty/boundary_precision_check/available_tons_boundary_allows_exact_4647_12_and_rejects_4647_13
        """
        ctx = cruised_stand(api)
        version = stand_version(api, ctx.stand_id)

        response = api.create_harvest_block(
            harvest_block_payload(
                ctx.stand_id,
                version,
                planned_tons=4647.12,
                product_mix="SAWTIMBER",
                expected_haul_distance_miles=62,
            ),
            make_forest_manager_headers(),
        )
        block = validate_success(response, 201)

        assert block["status"] == "RESERVED"
        assert_tons(block["planned_tons"], 4647.12, "planned_tons")
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=4647.12,
            available_tons=0.00,
        )

    def test_the_refused_attempt_leaves_the_block_list_empty(self, api):
        """The over-reservation created nothing, so the accepted block is the stand's first.

        PRD: "with equality permitted; an over-reservation is refused with `ERR_INSUFFICIENT_AVAILABLE_TONS`"

        Design: Difficulty/boundary_precision_check/available_tons_boundary_allows_exact_4647_12_and_rejects_4647_13
        """
        ctx = cruised_stand(api)
        version = stand_version(api, ctx.stand_id)

        api.create_harvest_block(
            harvest_block_payload(ctx.stand_id, version, planned_tons=4647.13),
            make_forest_manager_headers(),
        )
        reserve_block(api, ctx.stand_id, planned_tons=4647.12, product_mix="SAWTIMBER")

        blocks, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, headers=make_forest_manager_headers())
        )
        assert meta["total_count"] == 1
        assert len(blocks) == 1


class TestReentryBufferBoundary:
    """The twenty-four-month boundary date is itself a conflict; the following day is clear."""

    def test_a_start_date_on_the_buffer_boundary_is_itself_a_conflict(self, api):
        """A prior window ending 2027-09-30 blocks a start on 2029-09-30 exactly.

        PRD: "the new block's `planned_start_date` must fall strictly after that prior block's `planned_end_date` advanced by twenty-four months — two full growing years — and a start date landing exactly on that buffer boundary is itself a conflict, refused with `ERR_REENTRY_BUFFER_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/reentry_buffer_endpoint_itself_conflicts_one_day_later_allowed
        """
        ctx = cruised_stand(api)
        block_a = reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2027-06-01",
            planned_end_date="2027-09-30",
            planned_tons=500.00,
            product_mix="SAWTIMBER",
            expected_haul_distance_miles=62,
        )
        assert block_a["years_to_start"] == 0
        assert_tons(block_a["projected_available_tons"], 4647.12, "projected_available_tons")

        response = api.create_harvest_block(
            harvest_block_payload(
                ctx.stand_id,
                stand_version(api, ctx.stand_id),
                planned_start_date="2029-09-30",
                planned_end_date="2029-12-31",
                planned_tons=500.00,
                product_mix="SAWTIMBER",
                expected_haul_distance_miles=62,
            ),
            make_forest_manager_headers(),
        )
        validate_error(response, ApiErrorId.REENTRY_BUFFER_CONFLICT.value, 409)

    def test_a_start_date_one_day_past_the_boundary_is_accepted(self, api):
        """Moving the start to 2029-10-01 clears the buffer and reserves a second block.

        PRD: "The **re-entry buffer** forbids returning to the same ground too soon: for every block on the same stand whose `status` is `RESERVED`, `COMMITTED` or `COMPLETED`"

        Design: Difficulty/resource_temporal_overlap/reentry_buffer_endpoint_itself_conflicts_one_day_later_allowed
        """
        ctx = cruised_stand(api)
        reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2027-06-01",
            planned_end_date="2027-09-30",
            planned_tons=500.00,
            product_mix="SAWTIMBER",
            expected_haul_distance_miles=62,
        )

        block_b = reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2029-10-01",
            planned_end_date="2029-12-31",
            planned_tons=500.00,
            product_mix="SAWTIMBER",
            expected_haul_distance_miles=62,
        )

        assert block_b["status"] == "RESERVED"
        assert_tons(block_b["planned_tons"], 500.00, "planned_tons")
        assert block_b["years_to_start"] == 3
        assert_tons(block_b["projected_available_tons"], 4757.59, "projected_available_tons")

    def test_the_two_cleared_reservations_share_the_stand_pool(self, api):
        """Both blocks draw on one unchanged pool of net merchantable tons.

        PRD: "That snapshot is taken **before** this block's own reservation is applied."

        Design: Difficulty/resource_temporal_overlap/reentry_buffer_endpoint_itself_conflicts_one_day_later_allowed
        """
        ctx = cruised_stand(api)
        reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2027-06-01",
            planned_end_date="2027-09-30",
            planned_tons=500.00,
            product_mix="SAWTIMBER",
            expected_haul_distance_miles=62,
        )
        reserve_block(
            api,
            ctx.stand_id,
            planned_start_date="2029-10-01",
            planned_end_date="2029-12-31",
            planned_tons=500.00,
            product_mix="SAWTIMBER",
            expected_haul_distance_miles=62,
        )

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=1000.00,
            available_tons=3647.12,
        )
        _, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, headers=make_forest_manager_headers())
        )
        assert meta["total_count"] == 2
