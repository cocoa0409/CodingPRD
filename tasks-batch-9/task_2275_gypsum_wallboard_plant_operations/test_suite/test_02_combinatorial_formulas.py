"""Formulas whose answer is the product of several independently chosen inputs:
the kiln energy model, the per-bundle freight build-up, and the six-step capacity
and reservation chain that scheduling runs.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    RunStatus,
    assert_production_run,
    fixtures,
)


class TestKilnEnergyModel:
    """Energy is a product of a dwell-tiered efficiency, a thickness multiplier, a
    speed penalty and a formulation adder, all scaled by the effective MSF."""

    def test_regular_half_inch_run_at_four_hundred_fpm_burns_518_018_mmbtu(
        self, api: ApiClient
    ) -> None:
        """A 40-minute dwell picks the 0.81 tier and 400 fpm a 1.02 speed factor.

        PRD: "`kiln_energy_mmbtu` is then the unrounded base energy multiplied by the thickness multiplier and by the speed penalty factor, plus the formulation adder, plus the hold term, with that whole sum rounded half-up to three decimals — the base energy and the drying capacity are the two intermediates that must be left unrounded."

        Design: Difficulty/combinatorial_formula/kiln_energy_tier_thickness_speed_product
        """
        world = fixtures.scheduled_run(api)
        run = world.read_run()

        assert_production_run(run)
        assert run["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005)
        assert run["kiln_energy_mmbtu"] == pytest.approx(518.018, abs=0.0005), (
            "1192 pounds of evaporation per MSF over 300 MSF at 0.81 efficiency, "
            "times a 1.02 speed factor, plus a 0.160 hold term"
        )
        assert run["kiln_energy_cost_usd"] == pytest.approx(2175.68, abs=0.005), (
            "518.018 MMBtu at 4.20 dollars each is 2175.68"
        )

    def test_five_eighths_type_x_run_multiplies_thickness_speed_and_formulation(
        self, api: ApiClient
    ) -> None:
        """A 0.625-inch TYPE_X SKU adds a 1.075 multiplier and a 0.018 per-MSF adder.

        PRD: "A thickness multiplier is one plus the quantity of `thickness_in` less 0.5 multiplied by 0.6, capped at 1.35; because the thinnest board is 0.375 inches, a thin-board run gets a multiplier below one, and the cap never binds at these thicknesses."

        Design: Difficulty/combinatorial_formula/kiln_energy_tier_thickness_speed_product
        """
        world = fixtures.baseline_with_stucco(api)
        batch_2 = fixtures.second_batch_completed(api, world)
        world = fixtures.scheduled_run(api, world)

        tx_run = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            batch_id=batch_2["id"],
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=42.0,
            kiln_dwell_minutes=50,
            kiln_exit_moisture_target_pct=0.5,
        )
        scheduled = fixtures.schedule(api, tx_run["id"], world.plant_id)

        assert scheduled["effective_planned_msf"] == pytest.approx(100.000, abs=0.0005)
        assert scheduled["kiln_energy_mmbtu"] == pytest.approx(214.321, abs=0.0005), (
            "1459.50 pounds of evaporation over 100 MSF at 0.86 efficiency, times 1.075 "
            "for thickness and 1.012 for speed, plus 1.8 of adder and 0.200 of hold"
        )
        assert scheduled["kiln_energy_cost_usd"] == pytest.approx(900.15, abs=0.005), (
            "214.321 MMBtu at 4.20 dollars each is 900.15"
        )
        assert scheduled["projected_exit_moisture_pct"] == pytest.approx(0.00, abs=0.005), (
            "a 50-minute dwell at 0.86 efficiency removes all the slurry water"
        )

    def test_energy_is_stamped_on_the_capped_msf_not_the_requested_msf(
        self, api: ApiClient
    ) -> None:
        """A request for 400 MSF in a 312-MSF window burns the energy of 312 MSF.

        PRD: "Only after all six steps succeed is the kiln energy figure stamped, using `effective_planned_msf` rather than the requested figure."

        Design: Difficulty/combinatorial_formula/kiln_energy_tier_thickness_speed_product
        """
        world = fixtures.baseline_with_stucco(api)
        fixtures.second_batch_completed(api, world)
        world = fixtures.scheduled_run(api, world, requested_planned_msf=400.0)
        run = world.read_run()

        assert run["requested_planned_msf"] == pytest.approx(400.000, abs=0.0005)
        assert run["effective_planned_msf"] == pytest.approx(312.000, abs=0.0005)
        assert run["kiln_energy_mmbtu"] == pytest.approx(538.732, abs=0.0005), (
            "the same envelope over 312 MSF instead of 300 burns 538.732 MMBtu"
        )
        assert run["kiln_energy_cost_usd"] == pytest.approx(2262.67, abs=0.005)


class TestFreightRoundingOrder:
    """The per-bundle charge is rounded to cents before the bundle count multiplies
    it, which is not the same number as rounding the product."""

    def test_twelve_bundles_bill_the_rounded_per_bundle_charge(self, api: ApiClient) -> None:
        """Twelve bundles bill 12 x 53.22, not the 638.66 an unrounded rate would give.

        PRD: "Freight is computed by one routine in two variants, and the order in which it rounds is pinned because it changes the answer in cents."

        Design: Difficulty/combinatorial_formula/freight_per_bundle_rounding_order
        """
        world = fixtures.released_run_with_load(api)
        load = world.read_load()

        assert load["bundle_msf"] == pytest.approx(2.3040, abs=0.00005)
        assert load["quoted_freight_usd"] == pytest.approx(756.79, abs=0.005), (
            "2.3040 MSF at 23.10 dollars rounds to 53.22 a bundle, giving 638.64 plus "
            "118.15 of fuel"
        )
        assert load["quoted_freight_usd"] != pytest.approx(756.82, abs=0.005), (
            "756.82 is what rounding after the multiplication would produce"
        )

    def test_thirteen_bundles_scale_the_same_rounded_per_bundle_charge(
        self, api: ApiClient
    ) -> None:
        """Thirteen bundles bill 13 x 53.22 plus fuel, landing on 819.85.

        PRD: "The charge is then built up in this exact sequence: first, a per-bundle charge equal to `bundle_msf` multiplied by `base_rate_per_msf`, rounded half-up to two decimals; second, a subtotal equal to that already-rounded per-bundle charge multiplied by the billable bundle count — the rounding happens per bundle and *then* the multiplication happens, never the other way round; third, a fuel component equal to the subtotal multiplied by the market's `fuel_surcharge_pct` divided by 100, rounded half-up to two decimals; fourth, an overweight accessorial equal to the excess of `trailer_weight_lb` over 44000 pounds, floored at zero, multiplied by 0.02 dollars per pound and rounded half-up to two decimals; fifth, a backhaul credit equal to the market's `backhaul_credit_usd`; and last, the charge itself, which is the subtotal plus fuel plus the overweight accessorial less the credit, rounded half-up to two decimals, and then raised to the market's `min_charge_usd` if it falls below that floor."

        Design: Difficulty/combinatorial_formula/freight_per_bundle_rounding_order
        """
        world = fixtures.released_run(api)
        load = fixtures.stage_load(api, world, bundles_count=13, boards_per_bundle=48)

        assert load["bundle_weight_lb"] == pytest.approx(3686.40, abs=0.005)
        assert load["trailer_weight_lb"] == pytest.approx(47923.20, abs=0.005), (
            "thirteen bundles weigh 47923.20 pounds, still inside the 48000-pound ceiling"
        )
        assert load["total_msf"] == pytest.approx(29.952, abs=0.0005)
        assert load["quoted_freight_usd"] == pytest.approx(819.85, abs=0.005), (
            "691.86 of line haul plus 127.99 of fuel is 819.85"
        )

        run = world.read_run()
        assert run["available_msf"] == pytest.approx(260.048, abs=0.0005), (
            "290.000 net good less the 29.952 now committed to freight"
        )


class TestCapacityAndReservationChain:
    """Scheduling resolves predecessor, changeover, gap, available minutes, capacity
    and reservation in that order, each step reading only earlier outputs."""

    def test_cold_start_absorbs_forty_five_minutes_inside_its_own_window(
        self, api: ApiClient
    ) -> None:
        """The first run on a line loses 45 of its 240 minutes to changeover.

        PRD: "`in_window_changeover_minutes` is 45 on a cold start and 0 otherwise — a cold start is the only case where changeover is absorbed inside the run's own window."

        Design: Difficulty/combinatorial_formula/run_capacity_reservation_pinned_step_order
        """
        world = fixtures.scheduled_run(api)
        run = world.read_run()

        assert run["status"] == RunStatus.SCHEDULED.value
        assert run["prior_run_id"] is None, "there is no earlier run on this line"
        assert run["changeover_minutes"] == 45
        assert run["gap_minutes"] is None, "a cold start has no predecessor to measure from"
        assert run["in_window_changeover_minutes"] == 45
        assert run["available_minutes"] == 195, "240 window minutes less 45 of changeover"
        assert run["capacity_msf"] == pytest.approx(312.000, abs=0.0005), (
            "195 minutes at 1.600000 MSF a minute is 312.000"
        )
        assert run["effective_planned_msf"] == pytest.approx(300.000, abs=0.0005), (
            "the 300.000 requested fits inside the 312.000 the window can produce"
        )
        assert run["stucco_reserved_tons"] == pytest.approx(202.500, abs=0.0005), (
            "300.000 MSF at 1350 pounds each is 202.500 tons"
        )

    def test_request_above_capacity_is_capped_and_the_reservation_follows_the_cap(
        self, api: ApiClient
    ) -> None:
        """A request for 400 MSF is silently capped at the window's 312.000.

        PRD: "Otherwise `effective_planned_msf` is the smaller of `requested_planned_msf` and `capacity_msf`; a scheduler who asks for more board than the window can produce silently gets the window's worth."

        Design: Difficulty/combinatorial_formula/run_capacity_reservation_pinned_step_order
        """
        world = fixtures.baseline_with_stucco(api)
        fixtures.second_batch_completed(api, world)
        world = fixtures.scheduled_run(api, world, requested_planned_msf=400.0)
        run = world.read_run()

        assert run["capacity_msf"] == pytest.approx(312.000, abs=0.0005)
        assert run["effective_planned_msf"] == pytest.approx(312.000, abs=0.0005)
        assert run["stucco_reserved_tons"] == pytest.approx(210.600, abs=0.0005), (
            "312.000 MSF at 1350 pounds each is 210.600 tons"
        )

        plant = world.read_plant()
        assert plant["stucco_committed_tons"] == pytest.approx(210.600, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(86.677, abs=0.0005), (
            "297.277 tons on hand less the 210.600 now committed"
        )

    def test_warm_start_pays_its_changeover_in_the_gap_between_windows(
        self, api: ApiClient
    ) -> None:
        """A fire-rated run following a standard one needs 135 minutes and has 1200.

        PRD: "The consequence is that on a warm start the changeover happens in the dead time *between* windows and costs the run no production minutes at all."

        Design: Difficulty/combinatorial_formula/run_capacity_reservation_pinned_step_order
        """
        world = fixtures.baseline_with_stucco(api)
        batch_2 = fixtures.second_batch_completed(api, world)
        world = fixtures.scheduled_run(api, world)

        tx_run = fixtures.draft_run(
            api,
            world,
            spec_id=world.spec_tx_id,
            batch_id=batch_2["id"],
            window_start="2026-08-04T06:00:00Z",
            window_end="2026-08-04T10:00:00Z",
            requested_planned_msf=100.0,
            line_speed_fpm=380,
            paper_tension_lb=42.0,
            kiln_dwell_minutes=50,
        )
        scheduled = fixtures.schedule(api, tx_run["id"], world.plant_id)

        assert scheduled["prior_run_id"] == world.run_id, "the standard run precedes it"
        assert scheduled["changeover_minutes"] == 135, (
            "neither thickness nor family matches, which is 110, plus 25 of fire-rated purge"
        )
        assert scheduled["gap_minutes"] == 1200, "20 hours separate the two windows"
        assert scheduled["in_window_changeover_minutes"] == 0
        assert scheduled["available_minutes"] == 240, "the whole window is available for board"
        assert scheduled["capacity_msf"] == pytest.approx(364.800, abs=0.0005), (
            "240 minutes at 1.520000 MSF a minute is 364.800"
        )
        assert scheduled["effective_planned_msf"] == pytest.approx(100.000, abs=0.0005)
        assert scheduled["stucco_reserved_tons"] == pytest.approx(91.000, abs=0.0005), (
            "100.000 MSF at 1820 pounds each is 91.000 tons"
        )
