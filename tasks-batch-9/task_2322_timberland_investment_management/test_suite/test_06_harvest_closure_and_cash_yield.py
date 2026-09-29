"""Harvest closure: the cancellation invariant, the yield-shortfall lock and the yield boundary."""

from test_helpers import (
    ApiErrorId,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_stand_partition,
    assert_tons,
    validate_error,
    validate_success,
)
from test_helpers.factories import CANONICAL_CRUISE_PLOTS
from test_helpers.fixtures import (
    cancel_block,
    close_cruise,
    commit_block,
    complete_block,
    create_fund,
    create_property,
    create_stand,
    cruised_stand,
    read_block,
    read_fund,
    read_investor_report,
    read_stand,
    record_cruise_plot,
    reserve_block,
)
from test_helpers.test_users import make_forest_manager_headers

BLOCK_ONE = {
    "planned_start_date": "2027-06-01",
    "planned_end_date": "2027-09-30",
    "planned_tons": 1000.00,
    "product_mix": "MIXED",
    "expected_stumpage_price_usd_per_ton": 58.00,
    "price_index_factor": 1.05,
    "expected_haul_distance_miles": 140,
}


def _cruise(api, property_id, stand_code):
    stand = create_stand(api, property_id, stand_code=stand_code)
    for plot in CANONICAL_CRUISE_PLOTS:
        record_cruise_plot(api, stand["id"], **plot)
    return close_cruise(api, stand["id"])


def _two_stand_tract(api, target_cash_yield_bps):
    """One tract carrying two independently cruised stands of 4647.12 tons each."""
    fund = create_fund(api, target_cash_yield_bps=target_cash_yield_bps)
    tract = create_property(api, fund["id"])
    return fund, tract, _cruise(api, tract["id"], "PC-01"), _cruise(api, tract["id"], "PC-02")


class TestCancellationRestoresTheStandExactly:
    """A cancelled reservation gives back precisely what it took."""

    def test_cancelling_a_reserved_block_returns_its_tonnage_to_available(self, api):
        """The 1000.00 tons leave reserved and land back in available, unchanged.

        PRD: "Cancelling a `RESERVED` block moves its `planned_tons` out of the stand's `reserved_tons` and back into `available_tons`; cancelling a `COMMITTED` block moves its `planned_tons` out of `committed_tons` and back into `available_tons`."

        Design: Difficulty/compensating_invariant/harvest_block_cancel_restores_available_tons_exactly
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)
        assert_money(
            block["provisional_net_revenue_usd"], 22889.55, "provisional_net_revenue_usd"
        )

        cancelled = cancel_block(api, block["id"])

        assert cancelled["status"] == "CANCELLED"
        stand = read_stand(api, ctx.stand_id)
        assert_stand_partition(
            stand,
            net_merch_tons=4647.12,
            reserved_tons=0.00,
            committed_tons=0.00,
            dedicated_tons=0.00,
            hbu_withdrawn_tons=0.00,
            available_tons=4647.12,
        )
        assert stand["status"] == "INVENTORIED"

    def test_cancellation_keeps_the_provisional_price_and_leaves_the_actuals_unset(self, api):
        """Cancelling touches the status and the buckets only, not the priced figures.

        PRD: "Either way the block becomes `CANCELLED` and the stand's `version` is incremented."

        Design: Difficulty/compensating_invariant/harvest_block_cancel_restores_available_tons_exactly
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)

        cancel_block(api, block["id"])

        after = read_block(api, block["id"])
        assert_tons(after["planned_tons"], 1000.00, "planned_tons")
        assert after["voided_reason"] is None
        assert_money(
            after["provisional_net_revenue_usd"], 22889.55, "provisional_net_revenue_usd"
        )
        assert after["final_net_revenue_usd"] is None
        assert after["actual_tons"] is None

    def test_cancellation_moves_no_fund_cash(self, api):
        """No cash event is attached to a cancellation, so the treasury is untouched.

        PRD: "the result is written to `provisional_net_revenue_usd`; the provisional figure never touches fund cash"

        Design: Difficulty/compensating_invariant/harvest_block_cancel_restores_available_tons_exactly
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)

        cancel_block(api, block["id"])

        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=400000.00,
            net_operating_cash_usd=0.00,
        )


class TestCancellationGatedByTheYieldMandate:
    """The scheduled volume is locked while the fund runs behind its investor mandate."""

    def test_a_cancellation_is_locked_while_the_fund_runs_behind_its_mandate(self, api):
        """A fund whose yield is under target refuses to release scheduled volume.

        PRD: "A cancellation is permitted only while the fund's `harvest_acceleration_required` is false; when the fund is running behind its investor cash-yield mandate the scheduled volume is locked in place and the cancellation is refused with `ERR_YIELD_SHORTFALL_LOCK`."

        Design: Difficulty/cross_entity_state_dependency/harvest_cancellation_gated_by_fund_cash_yield_mandate
        """
        fund, tract, stand_one, stand_two = _two_stand_tract(api, 300)
        block_one = reserve_block(api, stand_one["id"], **BLOCK_ONE)
        commit_block(api, block_one["id"])
        block_two = reserve_block(api, stand_two["id"], planned_tons=200.00)

        assert_fund_cash(read_fund(api, fund["id"]), harvest_acceleration_required=True)

        response = api.close_harvest_block(
            block_two["id"], {"action": "CANCEL"}, make_forest_manager_headers()
        )
        validate_error(response, ApiErrorId.YIELD_SHORTFALL_LOCK.value, 409)

        assert read_block(api, block_two["id"])["status"] == "RESERVED"
        assert_stand_partition(read_stand(api, stand_two["id"]), reserved_tons=200.00)

    def test_the_cancellation_clears_once_a_completed_harvest_lifts_the_yield(self, api):
        """Completing the committed block carries the yield past the target and unlocks the cancel.

        PRD: "That single boolean is what locks scheduled volume in place, as §3.4 describes."

        Design: Difficulty/cross_entity_state_dependency/harvest_cancellation_gated_by_fund_cash_yield_mandate
        """
        fund, tract, stand_one, stand_two = _two_stand_tract(api, 300)
        block_one = reserve_block(api, stand_one["id"], **BLOCK_ONE)
        commit_block(api, block_one["id"])
        block_two = reserve_block(api, stand_two["id"], planned_tons=200.00)
        api.close_harvest_block(
            block_two["id"], {"action": "CANCEL"}, make_forest_manager_headers()
        )

        completed = complete_block(api, block_one["id"], 940.50, 0.92)
        assert_money(completed["final_net_revenue_usd"], 15858.07, "final_net_revenue_usd")
        assert completed["status"] == "COMPLETED"

        after_completion = read_fund(api, fund["id"])
        assert_bps(after_completion["cash_yield_bps"], 317, "cash_yield_bps")
        assert_fund_cash(after_completion, harvest_acceleration_required=False)

        response = api.close_harvest_block(
            block_two["id"], {"action": "CANCEL"}, make_forest_manager_headers()
        )
        released = validate_success(response, 200)
        assert released["status"] == "CANCELLED"
        assert_stand_partition(
            read_stand(api, stand_two["id"]),
            reserved_tons=0.00,
            available_tons=4647.12,
        )

    def test_the_completed_harvest_draws_down_its_own_stand_and_credits_the_fund(self, api):
        """Actual tons leave the stand's pool and the final revenue reaches the treasury.

        PRD: "The block moves to `COMPLETED`, `actual_tons` is subtracted from the stand's `net_merch_tons`, the block's `planned_tons` leaves the stand's `committed_tons`, `final_net_revenue_usd` is credited to both the fund's `cash_balance_usd` and its `net_operating_cash_usd`, and `cash_yield_bps` and `harvest_acceleration_required` are recomputed."

        Design: Difficulty/cross_entity_state_dependency/harvest_cancellation_gated_by_fund_cash_yield_mandate
        """
        fund, tract, stand_one, stand_two = _two_stand_tract(api, 300)
        block_one = reserve_block(api, stand_one["id"], **BLOCK_ONE)
        commit_block(api, block_one["id"])
        reserve_block(api, stand_two["id"], planned_tons=200.00)

        complete_block(api, block_one["id"], 940.50, 0.92)

        assert_stand_partition(
            read_stand(api, stand_one["id"]),
            net_merch_tons=3706.62,
            committed_tons=0.00,
        )
        assert_fund_cash(read_fund(api, fund["id"]), cash_balance_usd=415858.07)


class TestCashYieldTargetBoundary:
    """Equality with the mandate leaves acceleration off; one basis point short turns it on."""

    def test_a_yield_exactly_at_target_does_not_require_acceleration(self, api):
        """At 317 against a target of 317 the strict comparison is false.

        PRD: "equality leaves it false. That single boolean is what locks scheduled volume in place"

        Design: Difficulty/boundary_precision_check/cash_yield_exactly_at_target_does_not_require_acceleration
        """
        ctx = cruised_stand(api, fund_overrides={"target_cash_yield_bps": 317})
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)
        commit_block(api, block["id"])

        complete_block(api, block["id"], 940.50, 0.92)

        report = read_investor_report(api, ctx.fund_id)
        assert_bps(report["cash_yield_bps"], 317, "cash_yield_bps")
        assert report["target_cash_yield_bps"] == 317
        assert report["harvest_acceleration_required"] is False

    def test_a_target_one_basis_point_higher_still_requires_acceleration(self, api):
        """The same 317 basis points fall strictly short of a target of 318.

        PRD: "From it the system derives `cash_yield_bps` as `net_operating_cash_usd` divided by `committed_capital_usd`, multiplied by 10,000, rounded half-up to zero decimal places — an integer basis-point figure."

        Design: Difficulty/boundary_precision_check/cash_yield_exactly_at_target_does_not_require_acceleration
        """
        ctx = cruised_stand(api, fund_overrides={"target_cash_yield_bps": 318})
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)
        commit_block(api, block["id"])

        complete_block(api, block["id"], 940.50, 0.92)

        report = read_investor_report(api, ctx.fund_id)
        assert_bps(report["cash_yield_bps"], 317, "cash_yield_bps")
        assert report["target_cash_yield_bps"] == 318
        assert report["harvest_acceleration_required"] is True

    def test_the_report_carries_the_operating_cash_without_any_owned_property(self, api):
        """The harvest proceeds show up in cash and net asset value on an unacquired tract.

        PRD: "`owned_property_count` (the number of the fund's properties whose `status` is `OWNED` or `HBU_MARKETED`)"

        Design: Difficulty/boundary_precision_check/cash_yield_exactly_at_target_does_not_require_acceleration
        """
        ctx = cruised_stand(api, fund_overrides={"target_cash_yield_bps": 317})
        block = reserve_block(api, ctx.stand_id, **BLOCK_ONE)
        commit_block(api, block["id"])

        complete_block(api, block["id"], 940.50, 0.92)

        report = read_investor_report(api, ctx.fund_id)
        assert_money(report["net_operating_cash_usd"], 15858.07, "net_operating_cash_usd")
        assert_money(report["cash_balance_usd"], 415858.07, "cash_balance_usd")
        assert_money(report["nav_usd"], 415858.07, "nav_usd")
        assert report["owned_property_count"] == 0
        assert_tons(report["standing_inventory_tons"], 3706.62, "standing_inventory_tons")
