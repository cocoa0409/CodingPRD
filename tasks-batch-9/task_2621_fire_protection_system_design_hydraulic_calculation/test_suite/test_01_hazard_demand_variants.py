"""Hazard classification and the two demand derivation methods."""
import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import make_design_engineer_headers
from test_helpers.assertions import (
    assert_calculation_demand_snapshot,
    assert_classification,
    assert_flow,
)
from test_helpers.fixtures import (
    create_calculation,
    create_hazard_area,
    build_project_stage,
)

# A light industrial project with no underground lead-in allowance, so the
# hazard arithmetic is not obscured by a pressure adder.
FP2602 = dict(
    project_number="FP-2602",
    building_name="Balcones Light Industrial",
    occupancy_type="INDUSTRIAL",
    building_height_ft=24.0,
    underground_lead_in_loss_psi=0.0,
)

ROOM_140 = dict(
    label="Assembly Room 140",
    hazard_class="ORDINARY_1",
    commodity_class="CLASS_III",
    storage_height_ft=8.0,
    ceiling_height_ft=12.0,
    area_sqft=1800.0,
    sprinkler_system_type="WET",
    ceiling_slope_pct=4.0,
    room_area_sqft=1200.0,
    enclosure_rating_hours=2.0,
    room_has_unprotected_opening=False,
)


def _fp2602(client):
    return build_project_stage(client, **FP2602)


class TestHazardDemandMethodDivergence:
    def test_01_area_density_and_room_design_diverge_on_one_identical_density(self, client):
        """Under `AREA_DENSITY`, the basis area is the hazard area's `design_area_sqft`
        and `room_design_penalty_gpm` is 0.0; neither the enclosure requirement nor the
        opening penalty applies.

        Design: Difficulty/dual_variant_calc/hazard_demand_area_density_versus_room_design_divergence
        """
        ctx = _fp2602(client)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]
        area = create_hazard_area(client, project_id, engineer_id, **ROOM_140)
        assert_classification(area, "ORDINARY_1", 0.150, 1500, 250.0)

        by_area = create_calculation(
            client, project_id, area["id"], engineer_id, method="AREA_DENSITY", k_factor=5.6
        )
        by_room = create_calculation(
            client, project_id, area["id"], engineer_id, method="ROOM_DESIGN", k_factor=5.6
        )

        assert_calculation_demand_snapshot(by_area, 247.5, 250.0, 497.5, 0.0)
        assert_calculation_demand_snapshot(by_room, 198.0, 250.0, 448.0, 0.0)
        assert_flow(
            by_area["hazard_total_demand_gpm"] - by_room["hazard_total_demand_gpm"], 49.5
        )

    def test_02_unprotected_room_opening_adds_the_quarter_density_penalty(self, client):
        """When the method is admissible and `room_has_unprotected_opening` is true,
        `room_design_penalty_gpm` is the hazard area's `design_density` multiplied by an
        opening penalty factor of 0.25 and by `room_area_sqft`, rounded to 1 decimal
        place.

        Design: Difficulty/dual_variant_calc/hazard_demand_area_density_versus_room_design_divergence
        """
        ctx = _fp2602(client)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]
        sealed_room = dict(ROOM_140, label="Assembly Room 140")
        open_room = dict(ROOM_140, label="Assembly Room 142", room_has_unprotected_opening=True)

        closed_area = create_hazard_area(client, project_id, engineer_id, **sealed_room)
        opened_area = create_hazard_area(client, project_id, engineer_id, **open_room)
        assert closed_area["design_density"] == pytest.approx(0.150, abs=0.0005)
        assert opened_area["design_density"] == pytest.approx(0.150, abs=0.0005)

        without_opening = create_calculation(
            client, project_id, closed_area["id"], engineer_id, method="ROOM_DESIGN", k_factor=5.6
        )
        with_opening = create_calculation(
            client, project_id, opened_area["id"], engineer_id, method="ROOM_DESIGN", k_factor=5.6
        )

        assert_calculation_demand_snapshot(without_opening, 198.0, 250.0, 448.0, 0.0)
        assert_calculation_demand_snapshot(with_opening, 243.0, 250.0, 493.0, 45.0)

    def test_03_the_three_variants_read_back_unchanged_from_their_own_endpoint(self, client):
        """`hazard_total_demand_gpm` is `design_flow_gpm` plus `hose_allowance_gpm`,
        rounded to 1 decimal place; this is the single figure the project ledger ranks
        calculations by.

        Design: Difficulty/dual_variant_calc/hazard_demand_area_density_versus_room_design_divergence
        """
        ctx = _fp2602(client)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]
        headers = make_design_engineer_headers(engineer_id)
        closed_area = create_hazard_area(client, project_id, engineer_id, **ROOM_140)
        opened_area = create_hazard_area(
            client,
            project_id,
            engineer_id,
            **dict(ROOM_140, label="Assembly Room 142", room_has_unprotected_opening=True),
        )
        expected = {}
        for area_id, method, demand in (
            (closed_area["id"], "AREA_DENSITY", 497.5),
            (closed_area["id"], "ROOM_DESIGN", 448.0),
            (opened_area["id"], "ROOM_DESIGN", 493.0),
        ):
            row = create_calculation(
                client, project_id, area_id, engineer_id, method=method, k_factor=5.6
            )
            expected[row["id"]] = demand

        for calculation_id, demand in expected.items():
            fetched = validate_success(
                client.get_hydraulic_calculation(calculation_id, headers)
            )
            assert_flow(fetched["hazard_total_demand_gpm"], demand)
            assert_flow(
                fetched["design_flow_gpm"] + fetched["hose_allowance_gpm"], demand
            )


FP2603 = dict(
    project_number="FP-2603",
    building_name="Pecan Creek Cold Storage",
    occupancy_type="INDUSTRIAL",
    building_height_ft=30.0,
    underground_lead_in_loss_psi=0.0,
)

# Both stores are DRY under a 20.0 pct slope at a 32.0 ft ceiling, so both
# design-area multipliers apply and the ceiling earns no whole 5 ft step.
PLASTIC_STORE = dict(
    hazard_class="ORDINARY_2",
    commodity_class="GROUP_A_PLASTIC",
    ceiling_height_ft=32.0,
    area_sqft=40000.0,
    sprinkler_system_type="DRY",
    ceiling_slope_pct=20.0,
    room_area_sqft=None,
    enclosure_rating_hours=None,
    room_has_unprotected_opening=None,
)


class TestFourFactorClassification:
    def test_04_plastic_escalation_above_twelve_feet_moves_density_area_and_hose_together(
        self, client
    ):
        """Stored plastics are tested first: when `commodity_class` is `GROUP_A_PLASTIC`
        and `storage_height_ft` is strictly greater than 12 feet, the effective class is
        one position higher in that order than the declared `hazard_class`.

        Design: Difficulty/combinatorial_formula/hazard_classification_plastic_dry_slope_ceiling_four_factor_combination
        """
        ctx = build_project_stage(client, **FP2603)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]

        escalated = create_hazard_area(
            client,
            project_id,
            engineer_id,
            label="Plastic Pallet Store 12.5 ft",
            storage_height_ft=12.5,
            **PLASTIC_STORE,
        )
        not_escalated = create_hazard_area(
            client,
            project_id,
            engineer_id,
            label="Plastic Pallet Store 12.0 ft",
            storage_height_ft=12.0,
            **PLASTIC_STORE,
        )

        assert_classification(escalated, "EXTRA_1", 0.300, 4225, 500.0)
        assert_classification(not_escalated, "ORDINARY_2", 0.200, 2535, 250.0)

    def test_05_both_design_area_multipliers_are_visible_in_the_stored_value(self, client):
        """When `sprinkler_system_type` is `DRY` or `PREACTION` the area is multiplied by
        1.30, because a dry or preaction system's water delivery delay widens the
        expected area of operation.

        Design: Difficulty/combinatorial_formula/hazard_classification_plastic_dry_slope_ceiling_four_factor_combination
        """
        ctx = build_project_stage(client, **FP2603)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]

        area = create_hazard_area(
            client,
            project_id,
            engineer_id,
            label="Plastic Pallet Store 12.5 ft",
            storage_height_ft=12.5,
            **PLASTIC_STORE,
        )
        # EXTRA_1 opens at 2500 sqft; the DRY multiplier takes it to 3250 and the
        # 20.0 pct slope multiplier to 4225, well under the 40000 sqft gross cap.
        assert area["design_area_sqft"] == pytest.approx(4225, abs=0.5)
        assert area["design_area_sqft"] < area["area_sqft"]
        assert area["design_density"] == pytest.approx(0.300, abs=0.0005)

    def test_06_the_two_stores_snapshot_different_demands_from_one_half_foot_of_storage(
        self, client
    ):
        """Under either method, `design_flow_gpm` is the hazard area's `design_density`
        multiplied by a basis area, multiplied by an overdischarge factor of 1.10 to
        allow for the hose and end-head overdischarge the trade assumes, plus the
        room-design opening penalty, with the result rounded to 1 decimal place.

        Design: Difficulty/combinatorial_formula/hazard_classification_plastic_dry_slope_ceiling_four_factor_combination
        """
        ctx = build_project_stage(client, **FP2603)
        project_id = ctx["project_id"]
        engineer_id = ctx["lead_id"]

        escalated = create_hazard_area(
            client,
            project_id,
            engineer_id,
            label="Plastic Pallet Store 12.5 ft",
            storage_height_ft=12.5,
            **PLASTIC_STORE,
        )
        not_escalated = create_hazard_area(
            client,
            project_id,
            engineer_id,
            label="Plastic Pallet Store 12.0 ft",
            storage_height_ft=12.0,
            **PLASTIC_STORE,
        )

        high = create_calculation(
            client, project_id, escalated["id"], engineer_id, k_factor=11.2
        )
        low = create_calculation(
            client, project_id, not_escalated["id"], engineer_id, k_factor=11.2
        )

        assert_calculation_demand_snapshot(high, 1394.3, 500.0, 1894.3, 0.0)
        assert_calculation_demand_snapshot(low, 557.7, 250.0, 807.7, 0.0)
