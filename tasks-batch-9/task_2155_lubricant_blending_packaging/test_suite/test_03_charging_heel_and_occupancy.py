"""Charging a vessel: heel chemistry, occupancy geometry, capacity and the ladder."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    CLOCK_BASE_ISO,
    ApiErrorId,
    TEST_USERS,
    charge,
    charge_payload,
    complete_blend,
    create_active_recipe,
    create_active_spec,
    create_batch,
    create_component_lot,
    create_tank,
    list_batch_draws,
    read_batch,
    read_lot,
    read_tank,
    set_clock,
    setup_planned_batch,
    setup_released_batch,
    standard_components,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["product_manager_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestHeelRatioCeiling:
    def test_cross_family_heel_ratio_exactly_on_the_limit_is_accepted(self, api):
        """PRD 3.4: "The batch's `heel_ratio_actual` is the vessel's `heel_volume_l` divided by
        the sum of that same `heel_volume_l` and the requested `charge_volume_l`, rounded half
        up to six decimal places."
        PRD 3.4: "A cross-family heel may not exceed a ratio of 0.005000; a same-family heel
        may not exceed 0.020000; a vessel whose heel family is `NONE` is unconstrained on
        ratio."
        PRD 3.4: "Both ceilings are inclusive upper bounds — a ratio landing exactly on the
        limit passes — and the comparison uses the rounded six-decimal figure, so a raw ratio of
        0.0050004 rounds to 0.005000 and is accepted."
        PRD 3.4: "The batch's `claim_eligible` is set true only when all three of the following
        hold: the `heel_ratio_actual` is at or below 0.001000 for a cross-family heel, at or
        below 0.010000 for a same-family heel, or unconstrained where the vessel's heel family
        is `NONE`; every component lot touched by a draw of this charge has
        `coa_viscosity_verified` true; and the recipe's `spec_revision_pinned` equals the
        specification's `revision` at charge time."
        PRD 3.4: "The vessel moves `AVAILABLE → CHARGED`."

        Design: Difficulty/boundary_precision_check/heel_ratio_inclusive_cross_family_limit_on_charge
        """
        world = setup_planned_batch()

        # 10.0 L of HDEO_API_CK4 heel under a 1990.0 L charge of a ZDDP_PCMO product.
        charged = validate_success(
            api.charge_blend_batch(
                world["batch"]["id"], charge_payload(world["tank"]["id"]), OPERATOR
            )
        )
        assert charged["heel_ratio_actual"] == pytest.approx(0.005000, abs=0.0000005)
        assert charged["production_status"] == "CHARGING"
        assert read_tank(world["tank"]["id"])["status"] == "CHARGED"
        assert charged["claim_eligible"] is False, (
            "0.005000 is above the 0.001000 cross-family claim ceiling"
        )

    def test_cross_family_heel_ratio_one_step_above_the_limit_is_refused(self, api):
        """PRD 3.4: "A cross-family heel may not exceed a ratio of 0.005000; a same-family heel
        may not exceed 0.020000; a vessel whose heel family is `NONE` is unconstrained on
        ratio."
        PRD 3.4: "Exceeding the applicable ceiling refuses the charge with
        `ERR_HEEL_CONTAMINATION_EXCEEDED`."
        PRD 3.4: "The batch is born with `production_status` `PLANNED` and `qc_status`
        `PENDING` — two dimensions that evolve entirely independently of one another for the
        rest of the batch's life."

        Design: Difficulty/boundary_precision_check/heel_ratio_inclusive_cross_family_limit_on_charge
        """
        world = setup_planned_batch(
            tank_overrides={"tank_code": "TK-02", "heel_volume_l": 1.510},
            batch_overrides={"batch_code": "B-0002", "planned_volume_l": 300.0},
        )

        # 1.510 / (1.510 + 300.0) rounds to 0.005008, one step above the ceiling.
        response = api.charge_blend_batch(
            world["batch"]["id"],
            charge_payload(world["tank"]["id"], charge_volume_l=300.0),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value, 422)

        refreshed = read_batch(world["batch"]["id"])
        assert refreshed["production_status"] == "PLANNED"
        assert refreshed["heel_ratio_actual"] is None
        assert read_tank(world["tank"]["id"])["status"] == "AVAILABLE"


class TestHeelSafetyOutranksLaterRungs:
    def test_heel_ceiling_is_reported_ahead_of_material_shortage(self, api):
        """PRD 2.6: "18. Heel ratio ceiling — the residue share sits at or below its applicable
        limit; otherwise `ERR_HEEL_CONTAMINATION_EXCEEDED` (422). Guards charging."
        PRD 2.6: "35. Material shortage — the available stock of every required material code
        covers the requirement, with no quarantined lot of that code able to close the gap;
        otherwise `ERR_COMPONENT_SHORTAGE` (422). Guards charging."
        PRD 2.6: "Every check in the system occupies a fixed rung, and the rungs are evaluated
        in strictly ascending order; the **first** check that fails decides the response and no
        later check is consulted."

        Design: Difficulty/priority_pair_validation_conflict/heel_safety_outranks_component_shortage_on_charge
        """
        set_clock(CLOCK_BASE)
        lot_b1 = create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=400.0,
            unit_cost_cents_per_kg=210, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        create_component_lot(
            component_type="VI_IMPROVER", component_code="OCP-VII", received_kg=300.0,
            unit_cost_cents_per_kg=940, kv100_cst=850.000, density_kg_per_l=0.900,
        )
        create_component_lot(
            component_type="ADDITIVE_PACKAGE", component_code="ADD-SN-PLUS", received_kg=400.0,
            unit_cost_cents_per_kg=620, kv100_cst=105.000, density_kg_per_l=0.960,
            additive_family="ZDDP_PCMO",
        )
        spec = create_active_spec()
        recipe = create_active_recipe(spec["id"])
        tank = create_tank(heel_volume_l=11.0)
        batch = create_batch(recipe["id"])

        # Ratio 11.0 / 2001.0 rounds to 0.005497 and the 400.0 kg of base oil on file
        # falls far short of the 1437.576 kg requirement.
        response = api.charge_blend_batch(
            batch["id"], charge_payload(tank["id"]), OPERATOR
        )
        error = validate_error(
            response, ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_COMPONENT_SHORTAGE.value
        assert read_lot(lot_b1["id"])["available_kg"] == pytest.approx(400.000, abs=0.001)

    def test_charge_refused_at_the_heel_rung_leaves_no_draws_behind(self, api):
        """PRD 3.4: "Exceeding the applicable ceiling refuses the charge with
        `ERR_HEEL_CONTAMINATION_EXCEEDED`."
        PRD 3.4: "A charge that clears every gate does a great deal at once. The batch moves
        `PLANNED → CHARGING`, taking `blend_tank_id`, `charge_volume_l`, `window_start` and
        `window_end` from the request and recording `charge_mass_kg`, `heel_ratio_actual`,
        `claim_eligible` and `estimated_component_cost_cents`."
        PRD 3.4: "One component draw is created per consumed lot layer, in the draw order of
        §3.3, each with status `RESERVED`."

        Design: Difficulty/priority_pair_validation_conflict/heel_safety_outranks_component_shortage_on_charge
        """
        set_clock(CLOCK_BASE)
        create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=400.0,
            unit_cost_cents_per_kg=210, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        create_component_lot(
            component_type="VI_IMPROVER", component_code="OCP-VII", received_kg=300.0,
            unit_cost_cents_per_kg=940, kv100_cst=850.000, density_kg_per_l=0.900,
        )
        create_component_lot(
            component_type="ADDITIVE_PACKAGE", component_code="ADD-SN-PLUS", received_kg=400.0,
            unit_cost_cents_per_kg=620, kv100_cst=105.000, density_kg_per_l=0.960,
            additive_family="ZDDP_PCMO",
        )
        spec = create_active_spec()
        recipe = create_active_recipe(spec["id"])
        tank = create_tank(heel_volume_l=11.0)
        batch = create_batch(recipe["id"])

        response = api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        validate_error(response, ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value, 422)

        refreshed = read_batch(batch["id"])
        assert refreshed["production_status"] == "PLANNED"
        assert refreshed["blend_tank_id"] is None

        refreshed_tank = read_tank(tank["id"])
        assert refreshed_tank["status"] == "AVAILABLE"
        assert refreshed_tank["heel_volume_l"] == pytest.approx(11.0, abs=0.001)

        assert list_batch_draws(batch["id"]) == [], "a refused charge reserves nothing"

    def test_same_family_heel_ceiling_is_reported_ahead_of_the_window_collision(self, api):
        """PRD 2.6: "18. Heel ratio ceiling — the residue share sits at or below its applicable
        limit; otherwise `ERR_HEEL_CONTAMINATION_EXCEEDED` (422). Guards charging."
        PRD 2.6: "24. Tank window collision — the requested occupancy window does not collide
        on the same vessel; otherwise `ERR_TANK_WINDOW_CONFLICT` (409). Guards charging."
        PRD 3.5: "Release hands the vessel back `CHARGED → AVAILABLE` and, unlike a cancelled
        charge, **rewrites** the vessel's heel from this batch: `heel_volume_l` becomes the
        batch's `charge_volume_l` multiplied by a heel retention rate of 0.5 percent, rounded
        half up to three decimal places; `heel_additive_family` becomes the released batch's
        specification `additive_family`; and `heel_product_code` becomes that specification's
        `product_code`."

        Design: Difficulty/priority_pair_validation_conflict/heel_safety_outranks_tank_window_conflict_on_recharge
        """
        world = setup_released_batch()
        tank = read_tank(world["tank"]["id"])
        assert tank["heel_volume_l"] == pytest.approx(9.950, abs=0.001)
        assert tank["heel_additive_family"] == "ZDDP_PCMO"

        second = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=400.0
        )
        # 9.950 / 409.950 rounds to 0.024271, above the 0.020000 same-family ceiling,
        # while [10:00, 14:00) also overlaps the released batch's [08:00, 12:00).
        response = api.charge_blend_batch(
            second["id"],
            charge_payload(
                tank["id"],
                charge_volume_l=400.0,
                window_start="2026-08-02T10:00:00Z",
                window_end="2026-08-02T14:00:00Z",
            ),
            OPERATOR,
        )
        error = validate_error(
            response, ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value, 422
        )
        assert error["error_id"] != ApiErrorId.ERR_TANK_WINDOW_CONFLICT.value

    def test_recharge_refused_at_the_heel_rung_leaves_the_vessel_available(self, api):
        """PRD 3.4: "Exceeding the applicable ceiling refuses the charge with
        `ERR_HEEL_CONTAMINATION_EXCEEDED`."
        PRD 3.4: "A cross-family heel may not exceed a ratio of 0.005000; a same-family heel
        may not exceed 0.020000; a vessel whose heel family is `NONE` is unconstrained on
        ratio."
        PRD 3.4: "The vessel moves `AVAILABLE → CHARGED`."

        Design: Difficulty/priority_pair_validation_conflict/heel_safety_outranks_tank_window_conflict_on_recharge
        """
        world = setup_released_batch()
        second = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=400.0
        )

        response = api.charge_blend_batch(
            second["id"],
            charge_payload(
                world["tank"]["id"],
                charge_volume_l=400.0,
                window_start="2026-08-02T10:00:00Z",
                window_end="2026-08-02T14:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value, 422)

        assert read_batch(second["id"])["production_status"] == "PLANNED"
        assert read_tank(world["tank"]["id"])["status"] == "AVAILABLE"


class TestVesselOccupancyGeometry:
    @staticmethod
    def _two_chemistry_world(api):
        """A vessel that started clean, was occupied over [08:00, 12:00) by a ZDDP_PCMO
        batch and released, leaving a 5.000 L same-family heel; plus a second
        specification and recipe on the LOW_SAPS chemistry."""
        world = setup_released_batch(
            tank_overrides={"heel_volume_l": 0.0, "heel_additive_family": "NONE"},
            batch_overrides={"planned_volume_l": 1000.0},
            charge_overrides={"charge_volume_l": 1000.0},
        )
        create_component_lot(
            component_type="ADDITIVE_PACKAGE", component_code="ADD-C4", received_kg=400.0,
            unit_cost_cents_per_kg=660, kv100_cst=105.000, density_kg_per_l=0.960,
            additive_family="LOW_SAPS",
        )
        low_saps_spec = create_active_spec(
            product_code="LUBE-5W30-C4", sae_grade="5W-30", additive_family="LOW_SAPS"
        )
        components = standard_components()
        components[2]["component_code"] = "ADD-C4"
        components[2]["additive_family"] = "LOW_SAPS"
        world["spec_low_saps"] = low_saps_spec
        world["recipe_low_saps"] = create_active_recipe(low_saps_spec["id"], components)
        return world

    def test_same_family_batch_may_start_exactly_where_the_previous_window_ended(self, api):
        """PRD 3.4: "**Occupancy** is adjudicated as a half-open interval. A window runs from
        its start inclusive to its end exclusive, so two batches whose windows merely touch at
        an endpoint do not collide."
        PRD 3.4: "The heel is a *cross-family* heel when the vessel's `heel_additive_family` is
        not `NONE` and differs from the specification's `additive_family`; it is a
        *same-family* heel when the vessel's `heel_additive_family` equals the specification's
        `additive_family`; and when the vessel's `heel_additive_family` is `NONE`, it is
        neither."
        PRD 3.4: "The batch's `heel_ratio_actual` is the vessel's `heel_volume_l` divided by
        the sum of that same `heel_volume_l` and the requested `charge_volume_l`, rounded half
        up to six decimal places."

        Design: Difficulty/resource_temporal_overlap/tank_half_open_adjacency_versus_changeover_buffer
        """
        world = self._two_chemistry_world(api)
        tank = read_tank(world["tank"]["id"])
        assert tank["heel_volume_l"] == pytest.approx(5.000, abs=0.001)
        assert tank["heel_additive_family"] == "ZDDP_PCMO"

        same_family = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=1000.0
        )
        charged = validate_success(
            api.charge_blend_batch(
                same_family["id"],
                charge_payload(
                    tank["id"],
                    charge_volume_l=1000.0,
                    window_start="2026-08-02T12:00:00Z",
                    window_end="2026-08-02T16:00:00Z",
                ),
                OPERATOR,
            )
        )
        assert charged["production_status"] == "CHARGING"
        assert charged["heel_ratio_actual"] == pytest.approx(0.004975, abs=0.0000005)

    def test_cross_family_batch_is_pushed_back_by_the_changeover_buffer(self, api):
        """PRD 3.4: "Where the incoming chemistry is a cross-family heel, and only then, the
        incoming window's left edge is widened backwards by a two-hour changeover buffer to
        force a gap for the changeover; the buffer never widens the right edge and never widens
        the windows of batches already on the vessel."
        PRD 3.4: "A collision exists when some other batch on the same vessel — a different
        batch, with a window recorded, whose `production_status` is `PLANNED`, `CHARGING`,
        `BLENDED` or `RELEASED` — has a window whose end lies strictly after the buffered
        incoming start and whose start lies strictly before the incoming `window_end`."
        PRD 3.4: "A collision refuses the charge with `ERR_TANK_WINDOW_CONFLICT`."
        PRD 3.4: "Cancellation moves the batch `CHARGING → PLANNED`, moves every draw on the
        batch whose status is `RESERVED` to `RETURNED`, restores each affected lot's
        `available_kg` — returning any `DEPLETED` lot to `AVAILABLE` — resets `blend_tank_id`,
        `charge_volume_l`, `charge_mass_kg`, `window_start`, `window_end` and
        `heel_ratio_actual` to null, resets `estimated_component_cost_cents` to 0 and
        `claim_eligible` to false, and hands the vessel back `CHARGED → AVAILABLE` **with its
        heel fields left exactly as they were before the charge**."

        Design: Difficulty/resource_temporal_overlap/tank_half_open_adjacency_versus_changeover_buffer
        """
        world = self._two_chemistry_world(api)
        tank_id = world["tank"]["id"]

        same_family = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=1000.0
        )
        validate_success(
            api.charge_blend_batch(
                same_family["id"],
                charge_payload(
                    tank_id,
                    charge_volume_l=1000.0,
                    window_start="2026-08-02T12:00:00Z",
                    window_end="2026-08-02T16:00:00Z",
                ),
                OPERATOR,
            )
        )
        cancelled = validate_success(
            api.cancel_charge_blend_batch(
                same_family["id"], {"reason": "SCHEDULE_SWAP"}, OPERATOR
            )
        )
        assert cancelled["production_status"] == "PLANNED"
        assert cancelled["window_start"] is None

        cross_family = create_batch(
            world["recipe_low_saps"]["id"], batch_code="B-0003", planned_volume_l=1000.0
        )
        response = api.charge_blend_batch(
            cross_family["id"],
            charge_payload(
                tank_id,
                charge_volume_l=1000.0,
                window_start="2026-08-02T12:00:00Z",
                window_end="2026-08-02T16:00:00Z",
            ),
            OPERATOR,
        )
        error = validate_error(response, ApiErrorId.ERR_TANK_WINDOW_CONFLICT.value, 409)
        # 5.000 / 1005.000 rounds to 0.004975, inside the 0.005000 cross-family ceiling.
        assert error["error_id"] != ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value

        assert read_batch(cross_family["id"])["production_status"] == "PLANNED"
        assert read_tank(tank_id)["status"] == "AVAILABLE"


class TestVesselAvailability:
    def test_charge_is_refused_while_the_vessel_is_charged_by_another_batch(self, api):
        """PRD 3.4: "The batch must be `PLANNED`; the recipe must be `ACTIVE`, or
        `ERR_RECIPE_NOT_ACTIVE` applies; the specification must be `ACTIVE`, or
        `ERR_SPEC_NOT_ACTIVE` applies; the recipe's `spec_revision_pinned` must equal the
        specification's current `revision`, or `ERR_SPEC_REVISION_STALE` applies; the vessel
        must be `AVAILABLE`, or `ERR_TANK_NOT_AVAILABLE` applies; and `window_end` must be
        strictly after `window_start`, or `ERR_INVALID_WINDOW` applies."
        PRD 3.4: "The vessel moves `AVAILABLE → CHARGED`."

        Design: Difficulty/cross_entity_state_dependency/batch_charge_depends_on_blend_tank_status
        """
        world = setup_planned_batch()
        second = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=2000.0
        )
        charge(world)
        assert read_tank(world["tank"]["id"])["status"] == "CHARGED"

        response = api.charge_blend_batch(
            second["id"],
            charge_payload(
                world["tank"]["id"],
                window_start="2026-08-02T14:00:00Z",
                window_end="2026-08-02T18:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_TANK_NOT_AVAILABLE.value, 409)
        assert read_batch(second["id"])["production_status"] == "PLANNED"

    def test_charge_succeeds_once_the_cancelling_batch_hands_the_vessel_back(self, api):
        """PRD 3.4: "Cancellation moves the batch `CHARGING → PLANNED`, moves every draw on the
        batch whose status is `RESERVED` to `RETURNED`, restores each affected lot's
        `available_kg` — returning any `DEPLETED` lot to `AVAILABLE` — resets `blend_tank_id`,
        `charge_volume_l`, `charge_mass_kg`, `window_start`, `window_end` and
        `heel_ratio_actual` to null, resets `estimated_component_cost_cents` to 0 and
        `claim_eligible` to false, and hands the vessel back `CHARGED → AVAILABLE` **with its
        heel fields left exactly as they were before the charge**."
        PRD 3.4: "The vessel's `heel_volume_l`, `heel_additive_family` and `heel_product_code`
        are not rewritten by a cancellation."
        PRD 3.3: "The **provisional** figure, `estimated_component_cost_cents`, is written when
        the batch is charged and uses an availability-weighted moving average."

        Design: Difficulty/cross_entity_state_dependency/batch_charge_depends_on_blend_tank_status
        """
        world = setup_planned_batch()
        second = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=2000.0
        )
        charge(world)

        cancelled = validate_success(
            api.cancel_charge_blend_batch(
                world["batch"]["id"], {"reason": "OPERATOR_ABORT"}, OPERATOR
            )
        )
        assert cancelled["production_status"] == "PLANNED"

        tank = read_tank(world["tank"]["id"])
        assert tank["status"] == "AVAILABLE"
        assert tank["heel_volume_l"] == pytest.approx(10.0, abs=0.001)
        assert tank["heel_additive_family"] == "HDEO_API_CK4"

        charged = validate_success(
            api.charge_blend_batch(
                second["id"],
                charge_payload(
                    tank["id"],
                    window_start="2026-08-02T14:00:00Z",
                    window_end="2026-08-02T18:00:00Z",
                ),
                OPERATOR,
            )
        )
        assert charged["production_status"] == "CHARGING"
        assert charged["heel_ratio_actual"] == pytest.approx(0.005000, abs=0.0000005)
        assert charged["estimated_component_cost_cents"] == 549918


class TestChargeGatesAndVesselHousekeeping:
    def test_zero_length_occupancy_window_is_refused(self, api):
        """PRD 3.4: "The batch must be `PLANNED`; the recipe must be `ACTIVE`, or
        `ERR_RECIPE_NOT_ACTIVE` applies; the specification must be `ACTIVE`, or
        `ERR_SPEC_NOT_ACTIVE` applies; the recipe's `spec_revision_pinned` must equal the
        specification's current `revision`, or `ERR_SPEC_REVISION_STALE` applies; the vessel
        must be `AVAILABLE`, or `ERR_TANK_NOT_AVAILABLE` applies; and `window_end` must be
        strictly after `window_start`, or `ERR_INVALID_WINDOW` applies."
        PRD 2.6: "26. Window sanity — `window_end` is strictly after `window_start`; otherwise
        `ERR_INVALID_WINDOW` (422). Guards charging and packaging-run scheduling."

        Design: Corner/validations/charge_window_end_not_after_start_rejected
        """
        world = setup_planned_batch()

        response = api.charge_blend_batch(
            world["batch"]["id"],
            charge_payload(
                world["tank"]["id"],
                window_start="2026-08-02T08:00:00Z",
                window_end="2026-08-02T08:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_WINDOW.value, 422)

        assert read_batch(world["batch"]["id"])["production_status"] == "PLANNED"
        assert read_tank(world["tank"]["id"])["status"] == "AVAILABLE"

    def test_charge_that_will_not_fit_inside_the_vessel_is_refused(self, api):
        """PRD 3.4: "Finally, the existing `heel_volume_l` plus the requested `charge_volume_l`
        must fit within the vessel's `capacity_l`, or the charge is refused with
        `ERR_TANK_CAPACITY_EXCEEDED`."
        PRD 3.4: "Blending vessels are registered by a `PlatformAdmin` with a `tank_code`
        painted on the shell — unique across every vessel — and a working `capacity_l` in
        litres, greater than zero."

        Design: Corner/validations/tank_capacity_exceeded_blocks_charge
        """
        world = setup_planned_batch(
            tank_overrides={"tank_code": "TK-SMALL", "capacity_l": 500.0}
        )

        response = api.charge_blend_batch(
            world["batch"]["id"], charge_payload(world["tank"]["id"]), OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED.value, 422)

        assert read_batch(world["batch"]["id"])["production_status"] == "PLANNED"
        assert read_tank(world["tank"]["id"])["status"] == "AVAILABLE"
        assert read_lot(world["lots"]["lot_b1"]["id"])["available_kg"] == pytest.approx(
            400.000, abs=0.001
        )

    def test_food_grade_barrier_ignores_the_heel_ratio_entirely(self, api):
        """PRD 3.4: "Food-grade chemistry gets an absolute barrier that ignores quantity
        altogether: if the specification's `additive_family` is `FOOD_GRADE_H1` and the vessel's
        `heel_additive_family` is anything other than `NONE` or `FOOD_GRADE_H1`, the charge is
        refused with `ERR_FLUSH_REQUIRED`; and symmetrically, if the vessel's
        `heel_additive_family` is `FOOD_GRADE_H1` and the specification's `additive_family` is
        anything else, the charge is refused with `ERR_FLUSH_REQUIRED`."
        PRD 3.4: "That barrier holds at any heel ratio, including a vanishingly small one."
        PRD 3.4: "Flushing sets `heel_volume_l` to 0.0, sets `heel_additive_family` to `NONE`,
        clears `heel_product_code` to null, and stamps `last_flush_at` from the logical clock."

        Design: Corner/validations/food_grade_heel_mismatch_returns_flush_required
        """
        set_clock(CLOCK_BASE)
        create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=400.0,
            unit_cost_cents_per_kg=210, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=1500.0,
            unit_cost_cents_per_kg=250, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        create_component_lot(
            component_type="VI_IMPROVER", component_code="OCP-VII", received_kg=300.0,
            unit_cost_cents_per_kg=940, kv100_cst=850.000, density_kg_per_l=0.900,
        )
        create_component_lot(
            component_type="ADDITIVE_PACKAGE", component_code="ADD-H1", received_kg=400.0,
            unit_cost_cents_per_kg=880, kv100_cst=105.000, density_kg_per_l=0.960,
            additive_family="FOOD_GRADE_H1",
        )
        spec = create_active_spec(
            product_code="LUBE-H1-FG",
            base_stock_group="GROUP_IV",
            additive_family="FOOD_GRADE_H1",
        )
        components = standard_components()
        components[2]["component_code"] = "ADD-H1"
        components[2]["additive_family"] = "FOOD_GRADE_H1"
        recipe = create_active_recipe(spec["id"], components)
        tank = create_tank(
            heel_additive_family="ZDDP_PCMO", heel_product_code="LUBE-0W20-SP"
        )
        batch = create_batch(recipe["id"], batch_code="B-H1")

        response = api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        error = validate_error(response, ApiErrorId.ERR_FLUSH_REQUIRED.value, 422)
        # The ratio would have been exactly 0.005000, inside the cross-family ceiling.
        assert error["error_id"] != ApiErrorId.ERR_HEEL_CONTAMINATION_EXCEEDED.value

        flushed = validate_success(api.flush_blend_tank(tank["id"], OPERATOR))
        assert flushed["heel_volume_l"] == pytest.approx(0.0, abs=0.001)
        assert flushed["heel_additive_family"] == "NONE"

        charged = validate_success(
            api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        )
        assert charged["production_status"] == "CHARGING"
        assert charged["heel_ratio_actual"] == pytest.approx(0.0, abs=0.0000005)
        assert charged["claim_eligible"] is True

    def test_charging_against_a_draft_recipe_is_refused(self, api):
        """PRD 3.4: "The batch must be `PLANNED`; the recipe must be `ACTIVE`, or
        `ERR_RECIPE_NOT_ACTIVE` applies; the specification must be `ACTIVE`, or
        `ERR_SPEC_NOT_ACTIVE` applies; the recipe's `spec_revision_pinned` must equal the
        specification's current `revision`, or `ERR_SPEC_REVISION_STALE` applies; the vessel
        must be `AVAILABLE`, or `ERR_TANK_NOT_AVAILABLE` applies; and `window_end` must be
        strictly after `window_start`, or `ERR_INVALID_WINDOW` applies."
        PRD 2.6: "12. Recipe activity — the batch's recipe is `ACTIVE`; otherwise
        `ERR_RECIPE_NOT_ACTIVE` (409). Guards charging."

        Design: Corner/errors/charge_against_draft_recipe_returns_recipe_not_active
        """
        world = setup_planned_batch(activate_recipe=False)

        response = api.charge_blend_batch(
            world["batch"]["id"], charge_payload(world["tank"]["id"]), OPERATOR
        )
        validate_error(response, ApiErrorId.ERR_RECIPE_NOT_ACTIVE.value, 409)

        assert read_batch(world["batch"]["id"])["production_status"] == "PLANNED"
        assert read_tank(world["tank"]["id"])["status"] == "AVAILABLE"

    def test_second_charge_on_a_charging_batch_is_refused_on_its_own_state(self, api):
        """PRD 2.6: "10. Own-state legality — the target resource sits in a declared originating
        state for the requested transition; otherwise `ERR_INVALID_STATE` (409)."
        PRD 3.4: "A charge that clears every gate does a great deal at once. The batch moves
        `PLANNED → CHARGING`, taking `blend_tank_id`, `charge_volume_l`, `window_start` and
        `window_end` from the request and recording `charge_mass_kg`, `heel_ratio_actual`,
        `claim_eligible` and `estimated_component_cost_cents`."
        PRD 3.4: "One component draw is created per consumed lot layer, in the draw order of
        §3.3, each with status `RESERVED`."

        Design: Corner/state_machines/charge_from_charging_returns_invalid_state
        """
        world = setup_planned_batch()
        spare_tank = create_tank(
            tank_code="TK-02", heel_volume_l=0.0, heel_additive_family="NONE"
        )
        charge(world)

        response = api.charge_blend_batch(
            world["batch"]["id"],
            charge_payload(
                spare_tank["id"],
                charge_volume_l=100.0,
                window_start="2026-08-02T14:00:00Z",
                window_end="2026-08-02T16:00:00Z",
            ),
            OPERATOR,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

        refreshed = read_batch(world["batch"]["id"])
        assert refreshed["blend_tank_id"] == world["tank"]["id"]
        assert refreshed["charge_volume_l"] == pytest.approx(1990.0, abs=0.001)
        assert read_tank(spare_tank["id"])["status"] == "AVAILABLE"
        assert len(list_batch_draws(world["batch"]["id"])) == 4

    def test_flushing_a_quarantined_vessel_clears_its_heel_and_returns_it_to_service(self, api):
        """PRD 3.4: "Flushing sets `heel_volume_l` to 0.0, sets `heel_additive_family` to
        `NONE`, clears `heel_product_code` to null, and stamps `last_flush_at` from the logical
        clock."
        PRD 3.4: "It is permitted from `AVAILABLE` — a self-loop that leaves the vessel
        `AVAILABLE` — and from `QUARANTINED`, in which case the vessel returns
        `QUARANTINED → AVAILABLE`."
        PRD 3.5: "Where a failing result lands on a batch whose `production_status` is
        `BLENDED`, cascade B fires in the same operation and the batch also moves
        `BLENDED → QUARANTINED`."

        Design: Corner/state_machines/tank_flush_clears_heel_and_lifts_quarantine
        """
        world = setup_planned_batch()
        charge(world)
        complete_blend(world)
        validate_success(
            api.create_qc_result(
                world["batch"]["id"],
                {"test_type": "KV100", "measured_value": 7.900},
                TEST_USERS["qc_technician_headers"],
            ),
            201,
        )
        validate_success(
            api.dispose_blend_batch(
                world["batch"]["id"], {"reason": "OFF_SPEC_UNRECOVERABLE"}, QM
            )
        )
        assert read_tank(world["tank"]["id"])["status"] == "QUARANTINED"

        flushed = validate_success(api.flush_blend_tank(world["tank"]["id"], OPERATOR))
        assert flushed["status"] == "AVAILABLE"
        assert flushed["heel_volume_l"] == pytest.approx(0.0, abs=0.001)
        assert flushed["heel_additive_family"] == "NONE"
        assert flushed["heel_product_code"] is None
        assert flushed["last_flush_at"] == CLOCK_BASE_ISO

    def test_duplicate_vessel_code_is_refused(self, api):
        """PRD 3.4: "Blending vessels are registered by a `PlatformAdmin` with a `tank_code`
        painted on the shell — unique across every vessel — and a working `capacity_l` in
        litres, greater than zero."
        PRD 2.6: "34. Duplicate code — `product_code`, `tank_code`, `batch_code` and `line_code`
        are globally unique and `retain_code` is unique within its batch; otherwise
        `ERR_DUPLICATE_CODE` (409). Guards specification, tank, batch, filling-line and
        retain-jar creation."

        Design: Corner/validations/duplicate_tank_code_rejected
        """
        set_clock(CLOCK_BASE)
        first = validate_success(
            api.create_blend_tank({"tank_code": "TK-01", "capacity_l": 5000.0}, ADMIN), 201
        )

        response = api.create_blend_tank({"tank_code": "TK-01", "capacity_l": 9000.0}, ADMIN)
        validate_error(response, ApiErrorId.ERR_DUPLICATE_CODE.value, 409)

        _, meta = validate_paginated(api.list_blend_tanks(ADMIN))
        assert meta["total_count"] == 1
        assert read_tank(first["id"])["capacity_l"] == pytest.approx(5000.0, abs=0.001)

    def test_batch_listing_filters_on_the_occupied_vessel(self, api):
        """PRD 2.5: "Reads that traverse a relationship backwards are available throughout: the
        draws taken from a component lot, the components of a recipe, the draws, laboratory
        results and retain jars of a batch, the order lines quoting a package configuration,
        and the recipes, claims, configurations and change requests belonging to a
        specification are all reachable, either as a dedicated sub-collection or through a
        filter on the parent's identifier."
        PRD 2.3: "Filter parameters are additive: supplying several narrows the result set to
        rows matching all of them, and an unrecognised filter value that is not a member of the
        relevant enumeration is an invalid request."
        PRD 3.4: "At creation the recipe's `predicted_kv100_cst` is snapshotted onto the batch,
        `claim_eligible` is initialised to false, both `estimated_component_cost_cents` and
        `component_cost_cents` are initialised to 0, `retain_count` is initialised to 0, and
        `blend_tank_id`, `charge_volume_l`, `charge_mass_kg`, `heel_ratio_actual`,
        `measured_kv100_cst`, `window_start` and `window_end` are all null."

        Design: Corner/endpoints/blend_batches_filtered_list_by_blend_tank_id
        """
        world = setup_planned_batch()
        planned = create_batch(
            world["recipe"]["id"], batch_code="B-0002", planned_volume_l=2000.0
        )
        charge(world)

        by_tank_response = api.list_blend_batches(
            OPERATOR, {"blend_tank_id": world["tank"]["id"]}
        )
        by_tank, _ = validate_paginated(by_tank_response)
        assert len(by_tank) == 1 and by_tank[0]["id"] == world["batch"]["id"]
        assert by_tank_response.json()["response_type"] == "array"

        by_status_response = api.list_blend_batches(
            OPERATOR,
            {"blend_recipe_id": world["recipe"]["id"], "production_status": "PLANNED"},
        )
        by_status, _ = validate_paginated(by_status_response)
        assert len(by_status) == 1 and by_status[0]["id"] == planned["id"]
        assert by_status_response.json()["response_type"] == "array"
