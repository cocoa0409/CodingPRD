"""Material draw order, the two costing figures and the mass conservation invariant."""

import pytest

from test_helpers import (
    CLOCK_BASE,
    ApiErrorId,
    TEST_USERS,
    assert_component_draw,
    assert_mass_conserved,
    charge,
    charge_payload,
    create_active_recipe,
    create_active_spec,
    create_batch,
    create_component_lot,
    create_tank,
    list_batch_draws,
    list_lot_draws,
    read_batch,
    read_lot,
    read_tank,
    set_clock,
    setup_charging_batch,
    setup_planned_batch,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["blend_operator_headers"]
QM = TEST_USERS["quality_manager_headers"]


class TestDualCostingVariants:
    def test_charge_prices_the_requirement_at_the_availability_weighted_average(self, api):
        """PRD 3.4: "The mass requirement is derived first. Multiply the requested
        `charge_volume_l` by a fixed blending density of 0.860 kilograms per litre and round
        half up to three decimal places; that is the batch's `charge_mass_kg`."
        PRD 3.3: "The **provisional** figure, `estimated_component_cost_cents`, is written when
        the batch is charged and uses an availability-weighted moving average."
        PRD 3.3: "For each required material code, take the sum over every candidate lot of that
        lot's `available_kg` multiplied by its `unit_cost_cents_per_kg`, and divide by the sum
        over the same lots of their `available_kg`; that quotient is the code's average cost."
        PRD 3.3: "Multiply each code's required mass by its average cost, add those products
        together across all required codes at full precision, and round the total half up to
        whole cents exactly once at the end."

        Design: Difficulty/dual_variant_calc/batch_cost_moving_average_vs_consumption_layer
        """
        world = setup_planned_batch()

        charged = validate_success(
            api.charge_blend_batch(
                world["batch"]["id"], charge_payload(world["tank"]["id"]), OPERATOR
            )
        )
        assert charged["charge_mass_kg"] == pytest.approx(1711.400, abs=0.001)
        assert charged["estimated_component_cost_cents"] == 549918
        assert charged["production_status"] == "CHARGING"
        assert charged["qc_status"] == "PENDING"

    def test_completing_the_blend_freezes_a_lower_consumption_layer_cost(self, api):
        """PRD 3.3: "The **final** figure, `component_cost_cents`, is written when blending
        completes and prices only what was actually consumed."
        PRD 3.3: "Take the sum over this batch's draws whose status is `CONSUMED` of `drawn_kg`
        multiplied by that draw's snapshotted `unit_cost_cents_per_kg`, accumulate at full
        precision, and round half up to whole cents once at the end."
        PRD 3.3: "Where earlier lots are cheaper than later ones, this figure is strictly lower
        than the provisional one, and the difference is real rather than a rounding artefact."
        PRD 3.4: "It is reachable from two originating states: `CHARGING → BLENDED`, which moves
        every `RESERVED` draw on the batch to `CONSUMED` and computes `component_cost_cents` by
        the consumption-layer method of §3.3; and `REWORKED → BLENDED`, permitted only while the
        batch's `qc_status` is `PENDING`, which recomputes `component_cost_cents` over the
        unchanged set of `CONSUMED` draws — the figure comes out identical, because rework
        consumes no additional material — and closes the quarantine-rework loop."

        Design: Difficulty/dual_variant_calc/batch_cost_moving_average_vs_consumption_layer
        """
        world = setup_charging_batch()

        blended = validate_success(api.complete_blend(world["batch"]["id"], OPERATOR))
        assert blended["production_status"] == "BLENDED"
        assert blended["qc_status"] == "PENDING"
        assert blended["estimated_component_cost_cents"] == 549918
        assert blended["component_cost_cents"] == 546024
        assert (
            blended["estimated_component_cost_cents"] - blended["component_cost_cents"] == 3894
        )

        draws = list_batch_draws(world["batch"]["id"])
        assert len(draws) == 4
        for draw in draws:
            assert_component_draw(draw)
            assert draw["status"] == "CONSUMED"

        base_oil_draws = [d for d in draws if d["component_code"] == "GRP2-150N"]
        assert len(base_oil_draws) == 2
        base_oil_draws.sort(key=lambda d: d["created_at"])
        assert base_oil_draws[0]["drawn_kg"] == pytest.approx(400.000, abs=0.001)
        assert base_oil_draws[0]["unit_cost_cents_per_kg"] == 210
        assert base_oil_draws[1]["drawn_kg"] == pytest.approx(1037.576, abs=0.001)
        assert base_oil_draws[1]["unit_cost_cents_per_kg"] == 250

    def test_moving_average_ignores_lots_blocked_from_further_draws(self, api):
        """PRD 3.3: "For each required material code, the candidate lots are those whose
        `component_code` equals the required code **and** whose `status` is `AVAILABLE`."
        PRD 3.3: "Crucially, this average is evaluated over **every** candidate lot of that code
        — including lots the draw never reaches — and it is evaluated **before** any
        availability is decremented by this charge."
        PRD 3.3: "A `QualityManager` may block a lot from further draws, moving it
        `AVAILABLE → QUARANTINED` and recording the supplied `reason` into `quarantine_reason`."

        Design: Corner/calculations/moving_average_cost_excludes_quarantined_lots_from_the_average
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
        expensive = create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=500.0,
            unit_cost_cents_per_kg=900, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        blocked = validate_success(
            api.quarantine_component_lot(expensive["id"], {"reason": "COA_MISMATCH"}, QM)
        )
        assert blocked["status"] == "QUARANTINED"

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
        tank = create_tank()
        batch = create_batch(recipe["id"])

        charged = validate_success(
            api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        )
        assert charged["estimated_component_cost_cents"] == 549918
        assert charged["estimated_component_cost_cents"] != 747112

        refreshed_blocked = read_lot(expensive["id"])
        assert refreshed_blocked["available_kg"] == pytest.approx(500.000, abs=0.001)
        assert refreshed_blocked["status"] == "QUARANTINED"
        assert list_lot_draws(expensive["id"]) == []


class TestMaterialAvailabilityVerdicts:
    def test_shortfall_that_blocked_stock_would_have_covered_reports_blocked_stock(self, api):
        """PRD 3.4: "For each required material code, sum the `available_kg` of the lots of that
        code whose status is `AVAILABLE`."
        PRD 3.4: "If that sum falls short of the requirement, look at whether the quarantined
        lots of the same code would have closed the gap had they been available: if adding them
        in would have covered the requirement, the shortfall is attributable to blocked stock and
        the charge is refused with `ERR_LOT_QUARANTINED`; if even they would not have covered it,
        the charge is refused with `ERR_COMPONENT_SHORTAGE`."
        PRD 3.4: "The blocked-stock verdict sits far higher on the ladder of §2.6 than the plain
        shortage verdict, so blocked stock is always reported in preference to shortage."

        Design: Corner/calculations/quarantined_stock_shortfall_returns_lot_quarantined_not_shortage
        """
        set_clock(CLOCK_BASE)
        lot_b1 = create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=400.0,
            unit_cost_cents_per_kg=210, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        lot_b2 = create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=600.0,
            unit_cost_cents_per_kg=250, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        lot_b3 = create_component_lot(
            component_type="BASE_OIL", component_code="GRP2-150N", received_kg=900.0,
            unit_cost_cents_per_kg=240, kv100_cst=5.200, density_kg_per_l=0.855,
        )
        validate_success(
            api.quarantine_component_lot(lot_b3["id"], {"reason": "AWAITING_RETEST"}, QM)
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
        tank = create_tank()
        batch = create_batch(recipe["id"])

        # 1000.0 kg available against a 1437.576 kg requirement, with 900.0 kg blocked.
        response = api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        error = validate_error(response, ApiErrorId.ERR_LOT_QUARANTINED.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_COMPONENT_SHORTAGE.value

        assert read_batch(batch["id"])["production_status"] == "PLANNED"
        assert read_lot(lot_b1["id"])["available_kg"] == pytest.approx(400.000, abs=0.001)
        assert read_lot(lot_b2["id"])["available_kg"] == pytest.approx(600.000, abs=0.001)

    def test_shortfall_that_blocked_stock_could_not_cover_reports_plain_shortage(self, api):
        """PRD 3.4: "If that sum falls short of the requirement, look at whether the quarantined
        lots of the same code would have closed the gap had they been available: if adding them
        in would have covered the requirement, the shortfall is attributable to blocked stock and
        the charge is refused with `ERR_LOT_QUARANTINED`; if even they would not have covered it,
        the charge is refused with `ERR_COMPONENT_SHORTAGE`."
        PRD 3.4: "The mass requirement is derived first. Multiply the requested
        `charge_volume_l` by a fixed blending density of 0.860 kilograms per litre and round
        half up to three decimal places; that is the batch's `charge_mass_kg`."

        Design: Corner/calculations/component_shortage_when_no_quarantined_stock_can_close_the_gap
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
        # A 10.0 L cross-family heel under a 1990.0 L charge gives exactly 0.005000,
        # so the heel rung passes and the material rung decides.
        tank = create_tank()
        batch = create_batch(recipe["id"])

        response = api.charge_blend_batch(batch["id"], charge_payload(tank["id"]), OPERATOR)
        error = validate_error(response, ApiErrorId.ERR_COMPONENT_SHORTAGE.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_LOT_QUARANTINED.value

        assert read_batch(batch["id"])["production_status"] == "PLANNED"
        assert read_lot(lot_b1["id"])["available_kg"] == pytest.approx(400.000, abs=0.001)


class TestMassConservation:
    def test_charge_draws_lots_down_in_the_declared_order(self, api):
        """PRD 3.3: "Candidates are ordered by `created_at` ascending; ties are broken by
        `received_kg` descending; remaining ties are broken by `unit_cost_cents_per_kg`
        ascending."
        PRD 3.3: "Walking that order, each candidate contributes the smaller of its own
        `available_kg` and the requirement still outstanding, until the outstanding requirement
        reaches zero."
        PRD 3.3: "Availability is never stored as a running counter that is nudged up and down.
        It is always recomputed as the lot's `received_kg` minus the summed `drawn_kg` of every
        draw against that lot whose status is either `RESERVED` or `CONSUMED`, rounded half up
        to three decimal places."
        PRD 3.4: "Each drawn lot's `available_kg` is recomputed downwards, and any lot whose
        availability lands exactly on zero moves `AVAILABLE → DEPLETED`."

        Design: Difficulty/compensating_invariant/cancel_charge_conserves_component_lot_mass
        """
        world = setup_planned_batch()
        charge(world)

        lot_b1 = read_lot(world["lots"]["lot_b1"]["id"])
        assert lot_b1["available_kg"] == pytest.approx(0.000, abs=0.001)
        assert lot_b1["status"] == "DEPLETED"

        assert read_lot(world["lots"]["lot_b2"]["id"])["available_kg"] == pytest.approx(
            462.424, abs=0.001
        )
        assert read_lot(world["lots"]["lot_v1"]["id"])["available_kg"] == pytest.approx(
            197.316, abs=0.001
        )
        assert read_lot(world["lots"]["lot_a1"]["id"])["available_kg"] == pytest.approx(
            228.860, abs=0.001
        )

        for key in ("lot_b1", "lot_b2", "lot_v1", "lot_a1"):
            lot_id = world["lots"][key]["id"]
            assert_mass_conserved(read_lot(lot_id), list_lot_draws(lot_id))

    def test_cancelling_the_charge_restores_every_lot_to_its_pre_charge_mass(self, api):
        """PRD 2.9: "The first is **mass**: for every component lot, its `available_kg` plus the
        summed `drawn_kg` of every draw against it that is still reserved or consumed equals its
        `received_kg`."
        PRD 2.9: "A charge followed by its compensating cancellation must leave `available_kg`
        numerically identical to its pre-charge value."
        PRD 3.3: "Returned draws contribute nothing to the deduction, which is precisely what
        makes the mass conservation of §2.9 hold."
        PRD 3.4: "Cancellation moves the batch `CHARGING → PLANNED`, moves every draw on the
        batch whose status is `RESERVED` to `RETURNED`, restores each affected lot's
        `available_kg` — returning any `DEPLETED` lot to `AVAILABLE` — resets `blend_tank_id`,
        `charge_volume_l`, `charge_mass_kg`, `window_start`, `window_end` and
        `heel_ratio_actual` to null, resets `estimated_component_cost_cents` to 0 and
        `claim_eligible` to false, and hands the vessel back `CHARGED → AVAILABLE` **with its
        heel fields left exactly as they were before the charge**."

        Design: Difficulty/compensating_invariant/cancel_charge_conserves_component_lot_mass
        """
        world = setup_charging_batch()

        cancelled = validate_success(
            api.cancel_charge_blend_batch(
                world["batch"]["id"], {"reason": "OPERATOR_ABORT"}, OPERATOR
            )
        )
        assert cancelled["production_status"] == "PLANNED"
        assert cancelled["estimated_component_cost_cents"] == 0
        assert cancelled["component_cost_cents"] == 0

        lot_b1 = read_lot(world["lots"]["lot_b1"]["id"])
        assert lot_b1["available_kg"] == pytest.approx(400.000, abs=0.001)
        assert lot_b1["status"] == "AVAILABLE"
        assert read_lot(world["lots"]["lot_b2"]["id"])["available_kg"] == pytest.approx(
            1500.000, abs=0.001
        )
        assert read_lot(world["lots"]["lot_v1"]["id"])["available_kg"] == pytest.approx(
            300.000, abs=0.001
        )
        assert read_lot(world["lots"]["lot_a1"]["id"])["available_kg"] == pytest.approx(
            400.000, abs=0.001
        )

        draws = list_batch_draws(world["batch"]["id"])
        assert len(draws) == 4
        assert all(d["status"] == "RETURNED" for d in draws)

        b2_draws = list_lot_draws(world["lots"]["lot_b2"]["id"])
        assert len(b2_draws) == 1
        assert b2_draws[0]["drawn_kg"] == pytest.approx(1037.576, abs=0.001)
        assert b2_draws[0]["status"] == "RETURNED"

        tank = read_tank(world["tank"]["id"])
        assert tank["status"] == "AVAILABLE"
        assert tank["heel_volume_l"] == pytest.approx(10.0, abs=0.001)
        assert tank["heel_additive_family"] == "HDEO_API_CK4"
