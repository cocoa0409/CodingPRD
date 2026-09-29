"""Pre-season pallet space: the two billing bases, peak-day capacity, and the
occupancy identity a release restores."""

import pytest

from test_helpers import (
    assert_four_decimals,
    assert_instant_equals,
    assert_warehouse,
    assert_warehouse_pallet_identity,
    assert_warehouse_reservation,
    create_reservation,
    create_warehouse_reservation_payload,
    read_build_order,
    read_reservation,
    read_warehouse,
    release_reservation_payload,
    set_clock,
    setup_preseason_lot_with_reservation,
    setup_two_preseason_reservations_for_cost,
    setup_warehouse_with_one_large_reservation,
    validate_error,
    validate_paginated,
    validate_success,
)

COST_WINDOW = {"window_start": "2026-11-02", "window_end": "2026-11-22"}


class TestCarryingCostBases:
    """The same pallet-weeks bill one cent apart under the two bases."""

    def test_per_reservation_basis_rounds_each_line_before_adding(
        self, api, production_planner_headers
    ):
        """Under PER_RESERVATION, each reservation is invoiced as its own line:
        multiply the reservation's pallet_units by its occupied days, divide by
        seven, multiply by the 1165-cent weekly rate, round that line to a whole
        cent, and only then add the lines together.

        Design: Difficulty/boundary_precision_check/carrying_cost_per_reservation_is_one_cent_below_pooled
        """
        scenario = setup_two_preseason_reservations_for_cost()
        params = dict(COST_WINDOW, basis="PER_RESERVATION")

        cost = validate_success(
            api.get_warehouse_carrying_cost(
                scenario["warehouse"]["id"], production_planner_headers, params=params
            )
        )

        assert cost["reservation_count"] == 2, "both active reservations intersect"
        assert_four_decimals(cost["pallet_week_total"], "pallet_week_total")
        assert float(cost["pallet_week_total"]) == pytest.approx(
            14.2857, abs=0.00005
        ), "two lines of five pallets over ten days is 100 pallet-days over seven"
        assert cost["carrying_cost_cents"] == 16642, (
            "each line rounds to 8321 cents before the two are added, got "
            f"{cost['carrying_cost_cents']}"
        )

    def test_pooled_basis_rounds_once_at_the_end(self, api, production_planner_headers):
        """Under POOLED, the pallet-weeks are pooled first: add up each
        reservation's pallet_units multiplied by its occupied days and divided by
        seven across all of them, multiply that single pooled figure by the
        1165-cent weekly rate, and round once at the end.

        Design: Difficulty/boundary_precision_check/carrying_cost_per_reservation_is_one_cent_below_pooled
        """
        scenario = setup_two_preseason_reservations_for_cost()
        params = dict(COST_WINDOW, basis="POOLED")

        cost = validate_success(
            api.get_warehouse_carrying_cost(
                scenario["warehouse"]["id"], production_planner_headers, params=params
            )
        )

        assert cost["reservation_count"] == 2
        assert float(cost["pallet_week_total"]) == pytest.approx(14.2857, abs=0.00005), (
            "that figure is reported identically under both bases"
        )
        assert cost["carrying_cost_cents"] == 16643, (
            f"the pooled remainder rounds up, got {cost['carrying_cost_cents']}"
        )

    def test_the_two_bases_differ_by_exactly_one_cent(
        self, api, production_planner_headers
    ):
        """The two bases can differ by a cent on the very same set of
        reservations, whenever the individual line remainders and the pooled
        remainder round in opposite directions.

        Design: Difficulty/boundary_precision_check/carrying_cost_per_reservation_is_one_cent_below_pooled
        """
        scenario = setup_two_preseason_reservations_for_cost()
        warehouse_id = scenario["warehouse"]["id"]

        per_reservation = validate_success(
            api.get_warehouse_carrying_cost(
                warehouse_id,
                production_planner_headers,
                params=dict(COST_WINDOW, basis="PER_RESERVATION"),
            )
        )
        pooled = validate_success(
            api.get_warehouse_carrying_cost(
                warehouse_id,
                production_planner_headers,
                params=dict(COST_WINDOW, basis="POOLED"),
            )
        )

        assert (
            pooled["carrying_cost_cents"] - per_reservation["carrying_cost_cents"] == 1
        ), "the per-reservation invoice sits one cent below the pooled figure"
        assert float(per_reservation["pallet_week_total"]) == pytest.approx(
            float(pooled["pallet_week_total"]), abs=0.00005
        )

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-11-12"}
            )
        )
        assert occupancy["on_date"] == "2026-11-12"
        assert occupancy["occupancy_units"] == 5, (
            "a reservation that ends on the day another begins does not overlap it"
        )

        warehouse = read_warehouse(warehouse_id)
        assert_warehouse(warehouse)
        assert warehouse["pallets_reserved_current"] == 0, (
            "neither November window covers the clock's own date"
        )


class TestPeakDayCapacity:
    """Capacity is judged day by day, at the peak of the candidate's interval."""

    def test_overlapping_candidate_that_peaks_above_capacity_is_refused(
        self, api, production_planner_headers
    ):
        """For a candidate reservation, the peak occupancy is the largest value,
        taken across every day in the candidate's own interval, of that day's
        existing occupancy plus the candidate's pallet_units. Acceptance requires
        that peak to be at or below the warehouse's pallet_capacity; a peak
        exactly equal to capacity is accepted, and any excess is refused with
        ERR_WAREHOUSE_CAPACITY_EXCEEDED.

        Design: Difficulty/resource_temporal_overlap/warehouse_peak_overlap_refuses_25_pallets_that_adjacency_would_admit
        """
        scenario = setup_warehouse_with_one_large_reservation()
        warehouse_id = scenario["warehouse"]["id"]
        assert scenario["warehouse"]["pallet_capacity"] == 50

        response = api.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                warehouse_id,
                scenario["build_order_2"]["id"],
                start_date="2026-11-10",
                end_date="2026-11-20",
                pallet_units=25,
            ),
            production_planner_headers,
        )
        validate_error(response, "ERR_WAREHOUSE_CAPACITY_EXCEEDED", 409)

        _, meta = validate_paginated(
            api.list_warehouse_reservations(warehouse_id, production_planner_headers)
        )
        assert meta["total_count"] == 1, "the refused booking stored nothing"

    def test_adjacent_candidate_shares_the_last_pallet_of_capacity(
        self, api, production_planner_headers
    ):
        """A reservation occupies day D when its start_date is at or before D and
        its end_date is strictly after D, so a reservation that ends on the day
        another begins does not overlap it and the two may share the last pallet
        of capacity.

        Design: Difficulty/resource_temporal_overlap/warehouse_peak_overlap_refuses_25_pallets_that_adjacency_would_admit
        """
        scenario = setup_warehouse_with_one_large_reservation()
        warehouse_id = scenario["warehouse"]["id"]

        booked = validate_success(
            api.create_warehouse_reservation(
                create_warehouse_reservation_payload(
                    warehouse_id,
                    scenario["build_order_2"]["id"],
                    start_date="2026-11-12",
                    end_date="2026-11-20",
                    pallet_units=25,
                ),
                production_planner_headers,
            ),
            201,
        )
        assert_warehouse_reservation(booked)
        assert booked["status"] == "ACTIVE"
        assert booked["released_at"] is None
        assert booked["release_reason"] is None

        last_shared_day = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-11-11"}
            )
        )
        assert last_shared_day["occupancy_units"] == 30

        first_new_day = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-11-12"}
            )
        )
        assert first_new_day["occupancy_units"] == 25, (
            "the earlier window has already ended on the 12th"
        )

    def test_the_two_windows_never_stack_into_a_single_day(
        self, api, production_planner_headers
    ):
        """The occupancy of a warehouse on day D is the summed pallet_units of
        that warehouse's reservations whose status is ACTIVE and which occupy D;
        released reservations are excluded from every day, including days already
        elapsed.

        Design: Difficulty/resource_temporal_overlap/warehouse_peak_overlap_refuses_25_pallets_that_adjacency_would_admit
        """
        scenario = setup_warehouse_with_one_large_reservation()
        warehouse_id = scenario["warehouse"]["id"]
        payload_fields = dict(
            warehouse_id=warehouse_id,
            build_order_id=scenario["build_order_2"]["id"],
            pallet_units=25,
        )

        overlapping = api.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                start_date="2026-11-10", end_date="2026-11-20", **payload_fields
            ),
            production_planner_headers,
        )
        validate_error(overlapping, "ERR_WAREHOUSE_CAPACITY_EXCEEDED", 409)

        adjacent = validate_success(
            api.create_warehouse_reservation(
                create_warehouse_reservation_payload(
                    start_date="2026-11-12", end_date="2026-11-20", **payload_fields
                ),
                production_planner_headers,
            ),
            201,
        )
        assert adjacent["pallet_units"] == 25

        window = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id,
                production_planner_headers,
                params={"window_start": "2026-11-02", "window_end": "2026-11-22"},
            )
        )
        assert window["pallet_capacity"] == 50
        assert window["peak_occupancy_units"] == 30, (
            "the busiest single day carries the first reservation alone, got "
            f"{window['peak_occupancy_units']}"
        )


class TestReleaseRestoresOccupancy:
    """Releasing space restores the pallet identity and frees it for re-booking."""

    def test_release_returns_the_pallets_to_the_clock_date_occupancy(
        self, api, production_planner_headers
    ):
        """On success status becomes RELEASED, released_at is stamped from the
        logical clock, release_reason is recorded, and the reservation's version
        increments; the warehouse then recomputes pallets_reserved_current,
        increments its own version, and the conserved occupancy identity of §2.9
        holds again.

        Design: Difficulty/compensating_invariant/reservation_release_restores_warehouse_pallet_identity
        """
        scenario = setup_preseason_lot_with_reservation(
            pallet_capacity=50,
            quantity_units=80,
            pallet_units=40,
            scheduled_start_utc="2026-11-02T08:00:00Z",
            start_date="2026-11-02",
            end_date="2026-11-12",
        )
        warehouse_id = scenario["warehouse"]["id"]
        set_clock("2026-11-05T00:00:00Z")

        occupied = read_warehouse(warehouse_id)
        assert occupied["pallets_reserved_current"] == 40
        assert_warehouse_pallet_identity(occupied, [scenario["reservation"]])

        released = validate_success(
            api.release_warehouse_reservation(
                scenario["reservation"]["id"],
                release_reservation_payload("Pre-season plan rebalanced"),
                production_planner_headers,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "Pre-season plan rebalanced"
        assert_instant_equals(
            released["released_at"], "2026-11-05T00:00:00Z", "released_at"
        )

        warehouse = read_warehouse(warehouse_id)
        assert warehouse["pallets_reserved_current"] == 0
        assert_warehouse_pallet_identity(warehouse, [])

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-11-05"}
            )
        )
        assert occupancy["occupancy_units"] == 0
        assert read_build_order(scenario["build_order"]["id"])["status"] == "DRAFT", (
            "giving the space back does not disturb the lot"
        )

    def test_freed_space_can_be_re_booked_up_to_the_full_capacity(
        self, api, production_planner_headers
    ):
        """RELEASED is terminal — space is re-booked by creating a new
        reservation, never by reviving an old one.

        Design: Difficulty/compensating_invariant/reservation_release_restores_warehouse_pallet_identity
        """
        scenario = setup_preseason_lot_with_reservation(
            pallet_capacity=50,
            quantity_units=80,
            pallet_units=40,
            scheduled_start_utc="2026-11-02T08:00:00Z",
            start_date="2026-11-02",
            end_date="2026-11-12",
        )
        warehouse_id = scenario["warehouse"]["id"]
        set_clock("2026-11-05T00:00:00Z")
        validate_success(
            api.release_warehouse_reservation(
                scenario["reservation"]["id"],
                release_reservation_payload("Pre-season plan rebalanced"),
                production_planner_headers,
            )
        )

        rebooked = create_reservation(
            warehouse_id,
            scenario["build_order"]["id"],
            start_date="2026-11-02",
            end_date="2026-11-12",
            pallet_units=50,
        )
        assert rebooked["status"] == "ACTIVE"
        assert rebooked["pallet_units"] == 50

        warehouse = read_warehouse(warehouse_id)
        assert warehouse["pallets_reserved_current"] == 50, (
            "a peak exactly equal to capacity is accepted"
        )
        assert_warehouse_pallet_identity(warehouse, [rebooked])

        occupancy = validate_success(
            api.get_warehouse_occupancy(
                warehouse_id, production_planner_headers, params={"on_date": "2026-11-05"}
            )
        )
        assert occupancy["occupancy_units"] == 50

        active, meta = validate_paginated(
            api.list_warehouse_reservations(
                warehouse_id, production_planner_headers, params={"status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1, "the released row is not revived"
        assert active[0]["id"] == rebooked["id"]
        assert read_reservation(scenario["reservation"]["id"])["status"] == "RELEASED"
