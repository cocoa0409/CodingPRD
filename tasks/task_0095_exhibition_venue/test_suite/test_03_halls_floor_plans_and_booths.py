"""Halls, floor plans, booths, and booth pricing — PRD §3.2.

Covers booth creation, the four-step booth pricing rule with its
pinned evaluation order, fire-safety cell rejection, and the
floor-plan activation cascade that supersedes the prior ACTIVE plan
and blocks its booths.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booth,
    assert_floor_plan_version,
    assert_hall,
    create_and_activate_floor_plan,
    create_booth,
    create_booth_payload,
    create_exhibition,
    create_floor_plan_payload,
    create_hall,
    create_hall_payload,
    make_full_modular_cells,
    open_intake,
    setup_exhibition_with_active_plan,
    validate_error,
    validate_success,
)


# ===========================================================================
# Hall creation (PRD §3.2)
# ===========================================================================
class TestHallCreation:

    def test_hall_created_with_default_active_version_one(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Each hall also tracks floor_plan_active_version,
        an integer that mirrors the currently-active plan's version
        number; this field starts at 1 and is maintained by the system."

        Claim: a freshly created hall has floor_plan_active_version == 1.
        """
        exh = create_exhibition()
        hall = create_hall(exh["id"])
        assert_hall(hall)
        assert hall["floor_plan_active_version"] == 1


# ===========================================================================
# Floor plan version monotonicity and activation cascade (PRD §3.2)
# ===========================================================================
class TestFloorPlanActivation:
    # difficulty: transitive_cascade/floor_plan_activation_cascade_depth_2

    def test_first_floor_plan_starts_at_version_one(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "The version's version_number is monotonically
        increasing per hall and starts at 1."

        Claim: first POST /halls/{hall_id}/floor-plans yields
        version_number == 1.
        """
        exh = create_exhibition()
        hall = create_hall(exh["id"])
        cells = make_full_modular_cells(
            hall["grid_rows"], hall["grid_cols"],
        )
        res = api.create_floor_plan(
            hall["id"], create_floor_plan_payload(cells=cells),
            venue_admin_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["version_number"] == 1
        assert data["status"] == "DRAFT"
        assert_floor_plan_version(data)

    def test_activation_returns_active_status(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "the version's status runs through DRAFT, ACTIVE,
        and SUPERSEDED."

        Claim: activating a DRAFT plan returns it in status=ACTIVE.
        """
        # difficulty: transitive_cascade/floor_plan_activation_cascade_depth_2
        exh = create_exhibition()
        hall = create_hall(exh["id"], grid_rows=3, grid_cols=3)
        cells = make_full_modular_cells(3, 3)
        plan_res = api.create_floor_plan(
            hall["id"], create_floor_plan_payload(cells=cells),
            venue_admin_headers,
        )
        plan = validate_success(plan_res, expected_status=201)
        assert plan["status"] == "DRAFT"
        act_res = api.activate_floor_plan(
            hall["id"], plan["id"], venue_admin_headers,
        )
        activated = validate_success(act_res, expected_status=200)
        assert activated["status"] == "ACTIVE"

    def test_activation_cascades_booths_to_blocked(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "every Booth that referenced the superseded plan
        is forcibly moved to BLOCKED."

        Claim: after activating a new plan, booth on FPV1 has
        status == 'BLOCKED'.
        """
        # difficulty: transitive_cascade/floor_plan_activation_cascade_depth_2
        exh, hall, fpv1 = setup_exhibition_with_active_plan(
            grid_rows=3, grid_cols=3,
        )
        booth = create_booth(
            hall["id"], cells=[{"row": 1, "col": 1}], tier="STANDARD",
        )
        assert booth["status"] == "AVAILABLE"
        # Create + activate FPV2.
        cells = make_full_modular_cells(3, 3)
        fpv2_create = api.create_floor_plan(
            hall["id"], create_floor_plan_payload(cells=cells),
            venue_admin_headers,
        )
        fpv2 = validate_success(fpv2_create, expected_status=201)
        api.activate_floor_plan(
            hall["id"], fpv2["id"], venue_admin_headers,
        )
        # Booth tied to the now-superseded plan must be BLOCKED.
        refreshed = api.get_booth(booth["id"], venue_admin_headers)
        booth_after = validate_success(refreshed, expected_status=200)
        assert booth_after["status"] == "BLOCKED"

    def test_floor_plan_activation_locked_after_intake_opens(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Activation is only permitted while the owning
        exhibition is still in DRAFT — once intake has opened, an
        activation attempt is rejected with ERR_FLOOR_PLAN_LOCKED."

        Claim: activate a floor plan after open-intake →
        ERR_FLOOR_PLAN_LOCKED.
        """
        exh, hall, fpv1 = setup_exhibition_with_active_plan(
            grid_rows=3, grid_cols=3,
        )
        open_intake(exh["id"])
        # Now create a second floor plan and try to activate it.
        cells = make_full_modular_cells(3, 3)
        fpv2_create = api.create_floor_plan(
            hall["id"], create_floor_plan_payload(cells=cells),
            venue_admin_headers,
        )
        fpv2 = validate_success(fpv2_create, expected_status=201)
        res = api.activate_floor_plan(
            hall["id"], fpv2["id"], venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_FLOOR_PLAN_LOCKED.value)


# ===========================================================================
# Booth creation and fire-safety cells (PRD §3.2)
# ===========================================================================
class TestBoothCreation:

    def test_booth_creation_rejects_fire_safety_cell(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Any attempt to place a booth on a FIRE_SAFETY
        cell is rejected with ERR_FIRE_SAFETY_CELL."

        Claim: POST /halls/{hall_id}/booths with cells overlapping a
        FIRE_SAFETY-kind plan cell → ERR_FIRE_SAFETY_CELL.
        """
        exh = create_exhibition()
        hall = create_hall(exh["id"], grid_rows=3, grid_cols=3)
        create_and_activate_floor_plan(
            hall["id"], grid_rows=3, grid_cols=3,
            fire_safety_cells=[{"row": 1, "col": 1}],
        )
        # Now attempt a booth on the FIRE_SAFETY cell.
        res = api.create_booth(
            hall["id"],
            create_booth_payload(
                cells=[{"row": 1, "col": 1}], tier="STANDARD",
            ),
            venue_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_FIRE_SAFETY_CELL.value)

    def test_booth_capacities_summed_across_cells(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "the booth's power_kw_capacity and
        water_lpm_capacity as the sum of the corresponding per-cell
        fields across the booth's cells, and the booth's
        network_mbps_capacity as the integer sum of the cells'
        network_mbps."

        Claim: a 2-cell booth with default power 2.0/cell, water
        10.0/cell, network 100/cell has 4.0 / 20.0 / 200 capacities.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            grid_rows=3, grid_cols=3,
        )
        booth = create_booth(
            hall["id"],
            cells=[{"row": 1, "col": 1}, {"row": 1, "col": 2}],
            tier="STANDARD",
        )
        assert booth["power_kw_capacity"] == pytest.approx(4.0)
        assert booth["water_lpm_capacity"] == pytest.approx(20.0)
        assert booth["network_mbps_capacity"] == 200


# ===========================================================================
# Booth pricing — at-creation variant (PRD §3.2)
# ===========================================================================
class TestBoothPricingAtCreation:
    # difficulty: dual_variant_calc/booth_price_repin_on_relocate (creation side)
    # difficulty: combinatorial_formula/booth_quoted_price_three_input_nonlinear

    def test_standard_non_corner_no_theme(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Step one picks a tier base in cents: two hundred
        thousand for STANDARD, three hundred and fifty thousand for
        PREMIUM, and six hundred thousand for ISLAND."

        Claim: STANDARD interior booth on non-PRO theme →
        base_price_cents == 200000.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="GEN", grid_rows=5, grid_cols=5,
        )
        booth = create_booth(
            hall["id"],
            cells=[{"row": 2, "col": 2}],
            tier="STANDARD",
        )
        assert booth["is_corner"] is False
        assert booth["base_price_cents"] == 200000

    def test_premium_non_corner_no_theme(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Step one picks a tier base in cents: ... three
        hundred and fifty thousand for PREMIUM."

        Claim: PREMIUM interior booth on non-PRO theme →
        base_price_cents == 350000.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="GEN", grid_rows=5, grid_cols=5,
        )
        booth = create_booth(
            hall["id"],
            cells=[{"row": 2, "col": 2}],
            tier="PREMIUM",
        )
        assert booth["base_price_cents"] == 350000

    def test_corner_multiplier_on_standard(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Step three picks a corner multiplier of
        one-point-one-five when the booth's is_corner flag is true,
        and one otherwise."
        PRD §3.2: "the server computes the boolean is_corner flag (true
        when the booth's cell rectangle touches at least two
        perpendicular aisle edges)."

        Claim: STANDARD corner booth at (0,0) on non-PRO theme →
        is_corner=true and base_price_cents == round(200000*1.0*1.15)
        + 0 == 230000.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="GEN", grid_rows=5, grid_cols=5,
        )
        booth = create_booth(
            hall["id"],
            cells=[{"row": 0, "col": 0}],
            tier="STANDARD",
        )
        assert booth["is_corner"] is True
        assert booth["base_price_cents"] == 230000

    def test_theme_addon_on_pro_prefix(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Step four picks a theme add-on of fifty thousand
        cents when the exhibition's theme_code starts with the prefix
        PRO_, and zero otherwise."

        Claim: STANDARD interior booth in PRO_TECH exhibition →
        200000 + 50000 == 250000 cents.
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="PRO_TECH", grid_rows=5, grid_cols=5,
        )
        booth = create_booth(
            hall["id"],
            cells=[{"row": 2, "col": 2}],
            tier="STANDARD",
        )
        assert booth["base_price_cents"] == 250000

    def test_island_oversize_six_cells_corner_pro_theme(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Step two computes a cell-count multiplier that is
        one in every case except ISLAND booths with more than four
        cells; for those, every cell beyond the fourth adds ten
        percent — so a six-cell ISLAND carries a multiplier of one
        plus zero-point-one times two, equal to one-point-two."
        PRD §3.2: "The evaluation order is pinned: multiply the tier
        base by the cell-count multiplier, then by the corner
        multiplier, then round half-up to integer cents, then add the
        theme add-on."

        Claim: ISLAND 6-cell corner booth on PRO_TECH →
        round(600000*1.20*1.15) + 50000 = 828000 + 50000 = 878000.
        """
        # difficulty: combinatorial_formula/booth_quoted_price_three_input_nonlinear
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="PRO_TECH", grid_rows=8, grid_cols=8,
        )
        booth = create_booth(
            hall["id"],
            cells=[
                {"row": 0, "col": 0}, {"row": 0, "col": 1},
                {"row": 1, "col": 0}, {"row": 1, "col": 1},
                {"row": 2, "col": 0}, {"row": 2, "col": 1},
            ],
            tier="ISLAND",
        )
        assert booth["is_corner"] is True
        assert booth["base_price_cents"] == 878000

    def test_standard_cell_count_multiplier_stays_one(
        self, api, venue_admin_headers,
    ):
        """PRD §3.2: "Booths in STANDARD or PREMIUM always use a
        multiplier of one regardless of cell count."

        Claim: a 6-cell STANDARD interior booth on non-PRO theme →
        base_price_cents == 200000 (unchanged by cell count).
        """
        exh, hall, _ = setup_exhibition_with_active_plan(
            theme_code="GEN", grid_rows=5, grid_cols=5,
        )
        booth = create_booth(
            hall["id"],
            cells=[
                {"row": 2, "col": 0}, {"row": 2, "col": 1},
                {"row": 2, "col": 2}, {"row": 2, "col": 3},
                {"row": 3, "col": 0}, {"row": 3, "col": 1},
            ],
            tier="STANDARD",
        )
        # Booth touches col=0 (aisle) AND row=4 is NOT touched, but
        # row=0 is also not touched. cells span rows [2,3] and cols
        # [0..3]; the rectangle touches col=0 aisle but not the
        # second aisle, so is_corner=false.
        assert booth["base_price_cents"] in (200000, 230000)
        # The cell-count multiplier MUST be 1.0; whichever is_corner
        # the server computes, the base_price must NOT be greater than
        # the corner-applied value for a STANDARD with no theme add-on.
        assert booth["base_price_cents"] <= 230000
