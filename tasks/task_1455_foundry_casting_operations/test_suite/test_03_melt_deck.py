"""Melt deck: charge chemistry, spectro certification, AUTO_CORRECT, tap gates,
furnace daily capacity, and maintenance windows."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_charges,
    auto_correct,
    create_assayed_lot,
    create_certified_heat,
    create_foundry,
    create_furnace,
    create_heat,
    create_return_lot,
    get_heat,
    get_return_lot,
    pour_molds,
    record_sample,
    return_lot_addition,
    run_ops,
    set_clock,
    setup_shop,
    tap,
    validate_error,
    validate_success,
    virgin_addition,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
MELT = TEST_USERS["melt_supervisor_headers"]
SPECTRO_1 = TEST_USERS["spectro_1_headers"]


def _setup_foundry_furnace(api, tap_capacity=5000):
    set_clock("2026-08-10T08:00:00Z")
    foundry = create_foundry()
    furnace = create_furnace(foundry["id"], daily_tap_capacity_kg=tap_capacity)
    return foundry, furnace


class TestSpectroCertification:
    def test_spectro_ce_failure_with_passing_elements(self, api):
        """PRD §3.4: "every element's measured value must lie between its
        specified minimum and maximum with both bounds inclusive, and if the
        spec carries `ce_max`, the carbon equivalent — the carbon value plus the
        silicon value divided by three plus the phosphorus value divided by two
        — must not exceed it."

        Design: Corner/calculations/spectro_ce_failure_with_passing_elements
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 3.55, "Si": 2.55, "P": 0.02})])
        # All elements in band, but CE = 3.55 + 2.55/3 + 0.02/2 = 4.41 > 4.30.
        after = record_sample(heat, {"C": 3.55, "Si": 2.55, "P": 0.02})
        assert after["status"] == "SAMPLED"
        assert after["last_sample_passed"] is False

    def test_spectro_inclusive_bounds_pass_at_min_and_max(self, api):
        """PRD §3.4: "every element's measured value must lie between its
        specified minimum and maximum with both bounds inclusive" and "A passing
        reading moves the heat to `CERTIFIED`, stamps `certified_by_user_id`
        with the caller's `X-User-ID`".

        Design: Corner/calculations/spectro_inclusive_bounds_pass_at_min_and_max
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 3.20, "Si": 2.60, "P": 0.05})])
        # Min/max inclusive: CE = 3.20 + 0.8667 + 0.025 = 4.0917 <= 4.30.
        after = record_sample(heat, {"C": 3.20, "Si": 2.60, "P": 0.05})
        assert after["status"] == "CERTIFIED"
        assert after["certified_by_user_id"] == "spectro_1"


class TestProjectedChemistry:
    def test_projected_chemistry_weighted_average(self, api):
        """PRD §3.4: "each element's projected percentage is the weight-weighted
        average over all recorded additions — the sum over additions of each
        addition's weight multiplied by its element percentage, divided by the
        sum of addition weights — rounded half-up to four decimal places, with
        elements absent from an addition counting as zero for that addition."

        Design: Corner/calculations/projected_chemistry_weighted_average
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6}}}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(800, {"C": 2.80, "Si": 2.00})])
        heat = add_charges(heat, [virgin_addition(200, {"C": 3.80, "Si": 2.80})])
        assert heat["charge_total_kg"] == pytest.approx(1000, abs=1e-9)
        # C: (800*2.80 + 200*3.80)/1000 = 3.0; Si: (800*2.00 + 200*2.80)/1000 = 2.16
        assert heat["charge_composition"]["C"] == pytest.approx(3.0, abs=1e-9)
        assert heat["charge_composition"]["Si"] == pytest.approx(2.16, abs=1e-9)


class TestAutoCorrectFrozenBaseline:
    def test_auto_correct_mass_uses_frozen_baseline(self, api):
        """PRD §3.4: "The corrective mass for the element, in kilograms, is the
        deficit divided by 100, multiplied by the frozen pre-correction charge
        weight, divided by the difference between the additive purity (a
        perfectly pure additive, 1.00) and the target share divided by 100;
        each element's mass is rounded half-up to two decimal places, and the
        frozen weight is used for every element without iteration."

        Design: Difficulty/combinatorial_formula/corrective_charge_frozen_baseline_order
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 3.00, "Si": 2.40, "P": 0.02})])
        heat = record_sample(heat, {"C": 3.00, "Si": 2.40, "P": 0.02})
        assert heat["status"] == "SAMPLED"

        after = auto_correct(heat)
        # target C = (3.2+3.6)/2 = 3.40; deficit 0.40; 0.004*1000/(1.00-0.034) = 4.14
        assert after["last_correction_masses"]["C"] == pytest.approx(4.14, abs=1e-9)

    def test_auto_correct_only_under_range_elements_and_loops_back(self, api):
        """PRD §3.4: "For each element whose frozen projected share is below its
        specification minimum — only under-range elements are corrected" and
        "Elements already within range produce no addition." and "From
        `SAMPLED`, a re-sample that passes certifies the heat, and a corrective
        charge loops the heat back to `CHARGING`".

        Design: Difficulty/combinatorial_formula/corrective_charge_frozen_baseline_order
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 3.00, "Si": 2.40, "P": 0.02})])
        heat = record_sample(heat, {"C": 3.00, "Si": 2.40, "P": 0.02})

        after = auto_correct(heat)
        # Si 2.40 is within [2.2, 2.6] and P 0.02 within [0, 0.05]: no additions.
        assert "Si" not in (after["last_correction_masses"] or {})
        assert "P" not in (after["last_correction_masses"] or {})
        assert after["charge_total_kg"] == pytest.approx(1004.14, abs=1e-9)
        assert after["status"] == "CHARGING"


class TestMeltHeatCorrectionCycle:
    def test_correction_cycle_fail_correct_certify(self, api):
        """PRD §3.4: "A failing reading moves the heat `CHARGING → SAMPLED`, or
        keeps a `SAMPLED` heat in `SAMPLED`, recording `last_sample_reading` and
        setting `last_sample_passed` false; each new sample supersedes the
        previous reading outright."

        Design: Difficulty/non_linear_state_machine/melt_heat_correction_cycle
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 2.90, "Si": 2.40, "P": 0.02})])
        sampled = record_sample(heat, {"C": 2.90, "Si": 2.40, "P": 0.02})
        assert sampled["status"] == "SAMPLED"
        assert sampled["last_sample_passed"] is False

        corrected = auto_correct(sampled)
        # target C 3.40; deficit 0.50; 0.005*1000/0.966 = 5.18
        assert corrected["status"] == "CHARGING"
        assert corrected["last_correction_masses"]["C"] == pytest.approx(5.18, abs=1e-9)

    def test_correction_cycle_version_advances_each_hop(self, api):
        """PRD §3.4: "Every sample write increments the heat's `version` by
        one." and "Every charge write increments the heat's `version` by one."
        and "From `SAMPLED`, a re-sample that passes certifies the heat".

        Design: Difficulty/non_linear_state_machine/melt_heat_correction_cycle
        """
        foundry, furnace = _setup_foundry_furnace(api)
        spec = {"elements": {"C": {"min": 3.2, "max": 3.6},
                             "Si": {"min": 2.2, "max": 2.6},
                             "P": {"min": 0.0, "max": 0.05}},
                "ce_max": 4.30}
        heat = create_heat(foundry["id"], furnace["id"], chemistry_spec=spec)
        v0 = heat["version"]
        heat = add_charges(heat, [virgin_addition(
            1000, {"C": 2.90, "Si": 2.40, "P": 0.02})])
        heat = record_sample(heat, {"C": 2.90, "Si": 2.40, "P": 0.02})
        heat = auto_correct(heat)
        certified = record_sample(heat, {"C": 3.45, "Si": 2.40, "P": 0.02})
        assert certified["status"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == "spectro_1"
        # create -> charge -> sample -> correct -> sample: four writes
        assert certified["version"] == v0 + 4


class TestFurnaceDailyCapacity:
    def test_taps_up_to_capacity_succeed(self, api):
        """PRD §3.4: "the sum of `tapped_weight_kg` over all heats of the same
        furnace whose `tapped_date` equals the current UTC date, plus the new
        tap weight, must not exceed the furnace's `daily_tap_capacity_kg` — a
        total landing exactly on capacity passes, and anything above is
        `ERR_FURNACE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/furnace_daily_capacity_equality_then_overflow
        """
        foundry, furnace = _setup_foundry_furnace(api, tap_capacity=5000)
        h1 = create_certified_heat(foundry["id"], furnace["id"],
                                   charge_weight_kg=3000)
        h2 = create_certified_heat(foundry["id"], furnace["id"],
                                   charge_weight_kg=2000)
        t1 = tap(h1, 3000)
        assert t1["status"] == "TAPPED"
        # Cumulative 3000 + 2000 == 5000: equality passes.
        t2 = tap(h2, 2000)
        assert t2["status"] == "TAPPED"

    def test_tap_one_cent_over_capacity_rejected(self, api):
        """PRD §3.4: "the sum of `tapped_weight_kg` over all heats of the same
        furnace whose `tapped_date` equals the current UTC date, plus the new
        tap weight, must not exceed the furnace's `daily_tap_capacity_kg` — a
        total landing exactly on capacity passes, and anything above is
        `ERR_FURNACE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/furnace_daily_capacity_equality_then_overflow
        """
        foundry, furnace = _setup_foundry_furnace(api, tap_capacity=5000)
        h1 = create_certified_heat(foundry["id"], furnace["id"],
                                   charge_weight_kg=3000)
        h2 = create_certified_heat(foundry["id"], furnace["id"],
                                   charge_weight_kg=2000)
        h3 = create_certified_heat(foundry["id"], furnace["id"],
                                   charge_weight_kg=100)
        tap(h1, 3000)
        tap(h2, 2000)
        res = api.tap_heat(h3["id"], {"tap_weight_kg": 0.01}, MELT)
        validate_error(res, "ERR_FURNACE_CAPACITY_EXCEEDED", expected_status=422)
        assert get_heat(h3["id"])["status"] == "CERTIFIED"


class TestTapGates:
    def test_tap_from_charging_heat_rejected_not_certified(self, api):
        """PRD §3.4: "The heat must be `CERTIFIED`: tapping from `CHARGING` or
        `SAMPLED` is rejected with `ERR_HEAT_NOT_CERTIFIED`, tapping an already
        `TAPPED` heat is `ERR_INVALID_STATE`, and tapping a `POURED_OUT` heat is
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/errors/tap_from_charging_heat_rejected_not_certified
        """
        foundry, furnace = _setup_foundry_furnace(api)
        heat = create_heat(foundry["id"], furnace["id"])
        heat = add_charges(heat, [virgin_addition(1000, {"C": 3.40})])
        assert heat["status"] == "CHARGING"
        res = api.tap_heat(heat["id"], {"tap_weight_kg": 500}, MELT)
        validate_error(res, "ERR_HEAT_NOT_CERTIFIED", expected_status=409)
        assert get_heat(heat["id"])["status"] == "CHARGING"

    def test_tap_inside_maintenance_window_rejected(self, api):
        """PRD §3.4: "And the logical now must not fall inside any of the
        furnace's maintenance windows, which are closed intervals whose touching
        endpoints count as inside; a tap during a window is `ERR_INVALID_STATE`."

        Design: Corner/errors/tap_inside_maintenance_window_rejected
        """
        foundry, furnace = _setup_foundry_furnace(api)
        validate_success(api.add_equipment_window(
            furnace["id"],
            {"start_iso": "2026-08-10T09:00:00Z", "end_iso": "2026-08-10T12:00:00Z"},
            ADMIN), expected_status=201)
        heat = create_certified_heat(foundry["id"], furnace["id"])

        set_clock("2026-08-10T10:00:00Z")
        res = api.tap_heat(heat["id"], {"tap_weight_kg": 500}, MELT)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

        set_clock("2026-08-10T12:00:01Z")
        tapped = validate_success(api.tap_heat(
            heat["id"], {"tap_weight_kg": 500}, MELT))
        assert tapped["status"] == "TAPPED"


class TestReturnLotConsumption:
    def test_charge_collected_lot_not_assayed(self, api):
        """PRD §3.4: "A return-lot addition is rejected with
        `ERR_RETURN_LOT_NOT_ASSAYED` unless the lot is `ASSAYED`".

        Design: Corner/errors/charge_collected_lot_not_assayed
        """
        foundry, furnace = _setup_foundry_furnace(api)
        lot = create_return_lot(foundry["id"], collected_weight_kg=500.0)
        assert lot["status"] == "COLLECTED"
        heat = create_heat(foundry["id"], furnace["id"])
        res = api.add_heat_charges(
            heat["id"],
            {"expected_heat_version": heat["version"],
             "additions": [return_lot_addition(lot["id"], 100.0)]},
            MELT)
        validate_error(res, "ERR_RETURN_LOT_NOT_ASSAYED", expected_status=409)
        after = get_heat(heat["id"])
        assert after["status"] == "CHARGING"
        assert after["charge_total_kg"] == pytest.approx(0, abs=1e-9)

    def test_charge_exceeds_lot_remaining(self, api):
        """PRD §3.4: "and with `ERR_RETURN_LOT_INSUFFICIENT` if the requested
        weight exceeds the lot's `remaining_weight_kg`."

        Design: Corner/errors/charge_exceeds_lot_remaining
        """
        foundry, furnace = _setup_foundry_furnace(api)
        lot = create_assayed_lot(foundry["id"], collected_weight_kg=500.0)
        heat = create_heat(foundry["id"], furnace["id"])
        res = api.add_heat_charges(
            heat["id"],
            {"expected_heat_version": heat["version"],
             "additions": [return_lot_addition(lot["id"], 600.0)]},
            MELT)
        validate_error(res, "ERR_RETURN_LOT_INSUFFICIENT", expected_status=422)
        assert get_return_lot(lot["id"])["remaining_weight_kg"] == pytest.approx(
            500.0, abs=1e-9)


class TestTerminalHeat:
    def test_terminal_poured_out_heat_rejects_tap(self, api):
        """PRD §3.4: "tapping a `POURED_OUT` heat is `ERR_ALREADY_TERMINAL`."
        and PRD §3.1: "every `TAPPED` heat with no `BOOKED` slot referencing it
        transitions `TAPPED → POURED_OUT`".

        Design: Corner/state_machines/terminal_poured_out_heat_rejects_tap
        """
        ctx = setup_shop()
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        # Slot COMPLETED -> heat has no BOOKED slots; run-ops pours it out.
        run_ops(ctx["foundry"]["id"])
        heat_after = get_heat(ctx["heat"]["id"])
        assert heat_after["status"] == "POURED_OUT"

        res = api.tap_heat(ctx["heat"]["id"], {"tap_weight_kg": 100}, MELT)
        validate_error(res, "ERR_ALREADY_TERMINAL", expected_status=409)
