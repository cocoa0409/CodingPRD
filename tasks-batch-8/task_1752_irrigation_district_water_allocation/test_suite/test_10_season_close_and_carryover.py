"""Season close: the FLOWING gate, the two readings of remaining water,
carryover settlement, and over-allocation forfeiture."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_amount,
    create_allocation,
    create_announced_season,
    get_allocation,
    get_order,
    get_season,
    place_order,
    schedule_order,
    set_clock,
    setup_flowing_order,
    setup_open_season_with_allocation,
    start_order,
    submit_measurement,
    validate_error,
    validate_success,
    verify_work_order,
)


def _close(season_id, api):
    return validate_success(api.close_season(season_id, ADMIN), expected_status=200)


class TestSeasonCloseGate:
    def test_close_season_with_flowing_order_rejected(self, api):
        """PRD §3.9: "Closing the season is the district's end-of-year
        settlement, permitted only when no order of the season is still
        `FLOWING` (else `ERR_INVALID_SEASON_STATE`)."

        Design: Corner/state_machines/close_season_with_flowing_order_rejected
        """
        scenario = setup_flowing_order(
            holder_name="Flow F", parcel_number="APN-105",
            clock_at="2026-06-01T09:00:00Z",
        )
        assert scenario["order"]["status"] == "FLOWING"

        resp = api.close_season(scenario["season"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_SEASON_STATE)

        assert get_season(scenario["season"]["id"])["status"] == "OPEN"
        assert get_order(scenario["order"]["id"])["status"] == "FLOWING"


class TestNetVsDeliveredReadings:
    def _setup_pending_plus_delivered(self):
        """Season 2026 OPEN (announced 2.0, cap 50%); account A 5.0 acres
        SENIOR -> 10.00 af base. Order1 REQUESTED 2.48 af (5 cfs x 6 h), never
        delivered; order2 SCHEDULED/FLOWING/DELIVERED with 4.00 af measured
        (4.0 cfs x 12.11 h)."""
        scenario = setup_open_season_with_allocation(
            holder_name="Alice A", parcel_number="APN-100",
            priority_date="1888-03-10T00:00:00Z",
        )
        account_id = scenario["account"]["id"]
        alloc_id = scenario["allocation"]["id"]
        reach_id = scenario["reach"]["id"]

        order1 = place_order(
            account_id, alloc_id, reach_id, requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T14:00:00Z",
        )
        order2 = place_order(
            account_id, alloc_id, reach_id, requested_cfs=5.0,
            start="2026-06-10T08:00:00Z", end="2026-06-10T18:00:00Z",
        )
        order2, wo2 = schedule_order(order2["id"], "rider-1")
        set_clock("2026-06-10T09:00:00Z")
        start_order(order2["id"], "rider-1")
        submit_measurement(wo2["id"], "rider-1", 4.0, 12.11)
        verify_work_order(wo2["id"])
        scenario.update({"order1": order1, "order2": order2})
        return scenario

    def test_net_of_committed_reading_before_close(self, api):
        """PRD §3.2: "`available_af` is the entitlement pool —
        `effective_entitlement_af` plus `carryover_in_af` plus
        `transfers_in_af` minus `transfers_out_af` — with `delivered_af` and
        `committed_af` both subtracted. This net-of-committed reading is the
        balance that order creation and transfer approval/posting are checked
        against."
        With 10.00 af entitlement, 4.00 af delivered, and 2.48 af still
        committed on the pending order, available reads 3.52 af.

        Design: Difficulty/dual_variant_calc/remaining_water_net_of_committed_vs_delivered_only
        """
        scenario = self._setup_pending_plus_delivered()
        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["base_entitlement_af"], 10.00, "base_entitlement_af")
        assert_amount(allocation["delivered_af"], 4.00, "delivered_af")
        assert_amount(allocation["committed_af"], 2.48, "committed_af")
        assert_amount(allocation["available_af"], 3.52,
                      "available_af (net-of-committed reading)")

    def test_delivered_only_carryover_at_close(self, api):
        """PRD §3.2: "A delivered-only reading — which ignores committed water
        and nets the entitlement pool against measured deliveries alone —
        governs the carryover computation at season close, so a season that
        ends with a still-pending order reports a larger unused balance than
        the net-of-committed reading would show for identical data."
        PRD §3.9: "Every order still `REQUESTED` or `SCHEDULED` is moved to
        `CANCELLED`, releasing its `requested_quantity_af` from its
        allocation's `committed_af`..." and "...otherwise `carryover_out_af`
        is the lesser of the settled-unused water and the cap, with an unused
        balance exactly equal to the cap carrying over the full cap amount."
        PRD §3.1: "The allocation's `carryover_in_af` is read from the
        account's allocation in the most recent closed prior season — the
        closed season with the greatest `year` strictly less than the new
        season's year — taking that prior allocation's `carryover_out_af`;
        when no such prior closed allocation exists, `carryover_in_af` is
        0.00."
        Settled unused is 10.00 - 4.00 = 6.00 (ignoring the pending 2.48),
        capped at 50% of 10.00 = 5.00; the 2027 allocation inherits 5.00 —
        larger than the pre-close net-of-committed reading of 3.52.

        Design: Difficulty/dual_variant_calc/remaining_water_net_of_committed_vs_delivered_only
        """
        scenario = self._setup_pending_plus_delivered()
        season2 = create_announced_season(
            year=2027, start_date="2027-04-01T00:00:00Z",
            end_date="2027-09-30T00:00:00Z",
        )

        _close(scenario["season"]["id"], api)

        allocation = get_allocation(scenario["allocation"]["id"])
        assert allocation["status"] == "CLOSED"
        assert_amount(allocation["carryover_out_af"], 5.00,
                      "carryover_out_af (settled 6.00 capped at 5.00)")
        assert get_order(scenario["order1"]["id"])["status"] == "CANCELLED", (
            "The still-REQUESTED order is auto-cancelled by the close"
        )

        next_allocation = create_allocation(
            scenario["account"]["id"], season2["id"],
        )
        assert_amount(next_allocation["carryover_in_af"], 5.00,
                      "carryover_in_af reads the prior closed allocation")


class TestCarryoverBoundaries:
    def test_carryover_inclusive_cap_boundary(self, api):
        """PRD §3.9: "...otherwise `carryover_out_af` is the lesser of the
        settled-unused water and the cap, with an unused balance exactly equal
        to the cap carrying over the full cap amount."
        Delivering exactly 5.00 af (5 cfs x 12.11 h) leaves settled unused of
        5.00, exactly the 50% cap on the 10.00 af base — the full 5.00
        carries over.

        Design: Corner/calculations/carryover_inclusive_cap_boundary
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Cap C", parcel_number="APN-117",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"], requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T20:06:36Z",
        )
        order, work_order = schedule_order(order["id"], "rider-1")
        set_clock("2026-06-01T09:00:00Z")
        start_order(order["id"], "rider-1")
        submit_measurement(work_order["id"], "rider-1", 5.0, 12.11)
        verify_work_order(work_order["id"])

        season2 = create_announced_season(
            year=2027, start_date="2027-04-01T00:00:00Z",
            end_date="2027-09-30T00:00:00Z",
        )
        _close(scenario["season"]["id"], api)

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["delivered_af"], 5.00, "delivered_af")
        assert_amount(allocation["carryover_out_af"], 5.00,
                      "carryover_out_af (5.00 unused == 5.00 cap, inclusive)")

        next_allocation = create_allocation(
            scenario["account"]["id"], season2["id"],
        )
        assert_amount(next_allocation["carryover_in_af"], 5.00,
                      "Next season inherits the full capped carryover")

    def test_over_allocated_account_forfeits_carryover(self, api):
        """PRD §3.9: "An account that closed the season over-allocated —
        delivered water exceeding the entitlement pool — forfeits carryover
        entirely and its `carryover_out_af` is 0.00..."
        PRD §3.2: "`over_allocated_af` is the amount by which `delivered_af`
        exceeds that same entitlement pool (ignoring committed water
        entirely), floored at zero."
        The 1.0-acre account (2.00 af pool) is measured 2.50 af
        (5 cfs x 6.06 h): 0.50 af over-allocated, carryover forfeited.

        Design: Corner/calculations/over_allocated_account_forfeits_carryover
        """
        scenario = setup_open_season_with_allocation(
            irrigated_acres=1.0, holder_name="Over O", parcel_number="APN-118",
        )
        order = place_order(
            scenario["account"]["id"], scenario["allocation"]["id"],
            scenario["reach"]["id"], requested_cfs=5.0,
            start="2026-06-01T08:00:00Z", end="2026-06-01T12:50:00Z",
        )
        order, work_order = schedule_order(order["id"], "rider-1")
        set_clock("2026-06-01T09:00:00Z")
        start_order(order["id"], "rider-1")
        submit_measurement(work_order["id"], "rider-1", 5.0, 6.06)
        verify_work_order(work_order["id"])

        allocation = get_allocation(scenario["allocation"]["id"])
        assert_amount(allocation["over_allocated_af"], 0.50,
                      "over_allocated_af (2.50 delivered vs 2.00 pool)")

        _close(scenario["season"]["id"], api)
        allocation = get_allocation(scenario["allocation"]["id"])
        assert allocation["status"] == "CLOSED"
        assert_amount(allocation["carryover_out_af"], 0.00,
                      "Over-allocation forfeits carryover entirely")
