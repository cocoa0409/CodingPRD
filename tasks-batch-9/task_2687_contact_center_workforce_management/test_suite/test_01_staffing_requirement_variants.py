"""Both staffing variants, and which of the two the cycle makes authoritative."""

from test_helpers.assertions import assert_interval_forecast
from test_helpers.constants import (
    REQUIREMENT_BASIS_MAX_OF_BOTH,
    REQUIREMENT_BASIS_OCCUPANCY,
    REQUIREMENT_BASIS_SERVICE_LEVEL,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    generate_grid,
    make_forecast_group,
    make_labor_agreement,
    make_planning_cycle,
    read_interval,
    set_clock,
)


class TestRequirementBasisSelection:
    """Identical demand inputs, two different authoritative requirements."""

    def test_service_level_basis_binds_the_service_level_variant(self, api):
        """A cycle on the service-level basis reports the service-level agent count.

        "which one is authoritative is decided by the cycle's `requirement_basis`:
        `SERVICE_LEVEL` selects `required_service_level`, `OCCUPANCY` selects
        `required_occupancy_capped`, and `MAX_OF_BOTH` selects whichever of the
        two is larger."

        Design: Difficulty/dual_variant_calc/staffing_requirement_sl_vs_occupancy_divergence
        """
        set_clock(api, CANONICAL_CLOCK)
        make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(
            api, name="W37-SL", requirement_basis=REQUIREMENT_BASIS_SERVICE_LEVEL
        )
        group = make_forecast_group(api, cycle["id"])

        intervals = generate_grid(api, group["id"], "2026-09-07")

        first = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            first,
            volume_forecast=480,
            aht_forecast_seconds=300,
            required_service_level=140,
            required_occupancy_capped=135,
            required_agents=140,
        )

    def test_occupancy_basis_binds_the_occupancy_variant(self, api):
        """A cycle on the occupancy basis reports the occupancy-capped agent count.

        "The occupancy variant, stored in `required_occupancy_capped`, ignores
        the service-level band entirely: it divides the raw workload by the
        group's `occupancy_target_pct`, divides that by one minus
        `shrinkage_pct`, and likewise rounds **up** to the next whole agent."

        Design: Difficulty/dual_variant_calc/staffing_requirement_sl_vs_occupancy_divergence
        """
        set_clock(api, CANONICAL_CLOCK)
        make_labor_agreement(api, code="LA-CORE")
        cycle = make_planning_cycle(
            api, name="W37-OCC", requirement_basis=REQUIREMENT_BASIS_OCCUPANCY
        )
        group = make_forecast_group(api, cycle["id"])

        intervals = generate_grid(api, group["id"], "2026-09-07")

        first = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            first,
            volume_forecast=480,
            aht_forecast_seconds=300,
            required_service_level=140,
            required_occupancy_capped=135,
            required_agents=135,
        )

    def test_the_two_bases_diverge_by_five_agents_on_identical_inputs(self, api):
        """Byte-identical demand inputs give 140 agents on one basis and 135 on the other.

        "The two variants genuinely disagree — the service-level variant
        dominates when the answer-rate target is aggressive relative to the
        occupancy target, the occupancy variant dominates when the occupancy
        ceiling is tight — and which one is authoritative is decided by the
        cycle's `requirement_basis`"

        Design: Difficulty/dual_variant_calc/staffing_requirement_sl_vs_occupancy_divergence
        """
        set_clock(api, CANONICAL_CLOCK)
        make_labor_agreement(api, code="LA-CORE")
        sl_cycle = make_planning_cycle(
            api, name="W37-SL", requirement_basis=REQUIREMENT_BASIS_SERVICE_LEVEL
        )
        occ_cycle = make_planning_cycle(
            api, name="W37-OCC", requirement_basis=REQUIREMENT_BASIS_OCCUPANCY
        )
        sl_group = make_forecast_group(api, sl_cycle["id"])
        occ_group = make_forecast_group(api, occ_cycle["id"])

        sl_intervals = generate_grid(api, sl_group["id"], "2026-09-07")
        occ_intervals = generate_grid(api, occ_group["id"], "2026-09-07")

        sl_first = read_interval(api, sl_intervals[0]["id"])
        occ_first = read_interval(api, occ_intervals[0]["id"])
        assert sl_first["required_agents"] - occ_first["required_agents"] == 5

        sl_second = read_interval(api, sl_intervals[1]["id"])
        occ_second = read_interval(api, occ_intervals[1]["id"])
        assert sl_second["required_agents"] == 105
        assert occ_second["required_agents"] == 101

    def test_both_variants_are_stored_on_every_interval_whatever_the_basis(self, api):
        """Both variants are computed and stored even when only one is authoritative.

        "From it the system always computes and stores *both* staffing variants."

        Design: Difficulty/dual_variant_calc/staffing_requirement_sl_vs_occupancy_divergence
        """
        set_clock(api, CANONICAL_CLOCK)
        occ_cycle = make_planning_cycle(
            api, name="W37-OCC", requirement_basis=REQUIREMENT_BASIS_OCCUPANCY
        )
        occ_group = make_forecast_group(api, occ_cycle["id"])

        intervals = generate_grid(api, occ_group["id"], "2026-09-07")

        second = read_interval(api, intervals[1]["id"])
        assert_interval_forecast(
            second,
            volume_forecast=360,
            required_service_level=105,
            required_occupancy_capped=101,
            required_agents=101,
        )


class TestServiceLevelBandBoundary:
    """The 0.80 edge of the service-level uplift band."""

    def test_target_exactly_at_eighty_percent_takes_the_twenty_two_percent_band(self, api):
        """A target of exactly 0.80 takes the 0.22 uplift and the service-level variant binds.

        "otherwise a target of 0.80 or higher takes 0.22; otherwise a target of
        0.70 or higher takes 0.12"

        Design: Difficulty/boundary_precision_check/service_level_band_boundary_80_flips_binding_variant
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(
            api, name="W37-BAND-80", requirement_basis=REQUIREMENT_BASIS_MAX_OF_BOTH
        )
        group = make_forecast_group(api, cycle["id"], service_level_target_pct=0.8000)

        intervals = generate_grid(api, group["id"], "2026-09-07")

        first = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            first,
            volume_forecast=480,
            required_service_level=140,
            required_occupancy_capped=135,
            required_agents=140,
        )

    def test_target_one_hundredth_below_the_boundary_flips_the_binding_variant(self, api):
        """Dropping the target to 0.79 drops the band to 0.12, so the occupancy variant binds.

        "otherwise a target of 0.70 or higher takes 0.12; otherwise the uplift is 0.05."

        Design: Difficulty/boundary_precision_check/service_level_band_boundary_80_flips_binding_variant
        """
        set_clock(api, CANONICAL_CLOCK)
        cycle = make_planning_cycle(
            api, name="W37-BAND-79", requirement_basis=REQUIREMENT_BASIS_MAX_OF_BOTH
        )
        group = make_forecast_group(api, cycle["id"], service_level_target_pct=0.7900)

        intervals = generate_grid(api, group["id"], "2026-09-07")

        first = read_interval(api, intervals[0]["id"])
        assert_interval_forecast(
            first,
            volume_forecast=480,
            required_service_level=128,
            required_occupancy_capped=135,
            required_agents=135,
        )

    def test_the_band_edge_does_not_move_the_forecast_volume(self, api):
        """The band selects staffing only: volume is identical either side of the edge.

        "`service_level_target_pct` is the share of contacts to be answered
        within the answer-time target, strictly greater than 0 and at most 1, at
        four decimal places; it is the field that selects the service-level
        uplift band in the staffing formula."

        Design: Difficulty/boundary_precision_check/service_level_band_boundary_80_flips_binding_variant
        """
        set_clock(api, CANONICAL_CLOCK)
        at_edge_cycle = make_planning_cycle(api, name="W37-EDGE-AT")
        below_edge_cycle = make_planning_cycle(api, name="W37-EDGE-BELOW")
        at_edge_group = make_forecast_group(
            api, at_edge_cycle["id"], service_level_target_pct=0.8000
        )
        below_edge_group = make_forecast_group(
            api, below_edge_cycle["id"], service_level_target_pct=0.7900
        )

        at_edge = generate_grid(api, at_edge_group["id"], "2026-09-07")
        below_edge = generate_grid(api, below_edge_group["id"], "2026-09-07")

        assert read_interval(api, at_edge[0]["id"])["volume_forecast"] == 480
        assert read_interval(api, below_edge[0]["id"])["volume_forecast"] == 480
