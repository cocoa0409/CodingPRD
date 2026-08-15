"""Water chemistry: cycles-of-concentration recomputation, the out-of-spec
gate on bring-online, and the water mass balance."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_and_verify_log_entry,
    create_boiler,
    deliver_fuel,
    get_boiler,
    make_operator_headers,
    record_chemistry_log,
    record_in_spec_chemistry,
    setup_plant_with_operators,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCyclesRecomputation:
    def test_cycles_of_concentration_from_latest_log(
        self, api, plant_manager_headers
    ):
        """PRD §3.3: "Recording a log immediately recomputes the boiler's
        `cycles_of_concentration` — the boiler-water conductivity divided by
        the feedwater conductivity, taken from the latest non-`VOIDED`
        chemistry log". A reading of 11500/1000 lands at cycles 11.5 (beyond
        the 10.0 maximum, on the documented rounding-chain path of the
        blowdown recommendation).

        Design: Difficulty/combinatorial_formula/blowdown_volume_rounding_order_trap_mode_b
        """
        plant, ops = setup_plant_with_operators(name="BD Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-BD")
        deliver_fuel(plant["id"], 1000)
        create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=8400, fuel_burned_gal=70,
            feedwater_intake_gal=1100, blowdown_gal=100,
        )

        resp = api.create_chemistry_log(
            plant["id"], boiler["id"],
            {
                "recorded_by_operator_id": ops[0]["id"],
                "recorded_at": "2026-08-06T08:00:00Z",
                "conductivity_boiler_umho": 11500,
                "conductivity_feedwater_umho": 1000,
                "sulfite_residual_ppm": 30,
                "phosphate_residual_ppm": 40,
            },
            make_operator_headers(ops[0]["id"]),
        )
        validate_success(resp, expected_status=201)
        state = get_boiler(plant["id"], boiler["id"])
        assert state["cycles_of_concentration"] == pytest.approx(11.5)

    def test_cycles_recomputed_from_latest_non_voided_log_after_void(
        self, api, plant_manager_headers
    ):
        """PRD §3.3: "A `PlantManager` may void a chemistry log; voiding
        recomputes `water_status` from the remaining logs, recomputes
        `cycles_of_concentration` from the latest non-`VOIDED` log, and resets
        `water_status` to `IN_SPEC` outright if no non-`VOIDED` logs remain."

        Design: Difficulty/combinatorial_formula/blowdown_volume_rounding_order_trap_mode_b
        """
        plant, ops = setup_plant_with_operators(name="BD2 Plant", count=1)
        boiler = create_boiler(plant["id"], tag="B-BD2")
        log_a = record_chemistry_log(
            plant["id"], boiler["id"], ops[0]["id"],
            recorded_at="2026-08-05T08:00:00Z",
            conductivity_boiler_umho=5000, conductivity_feedwater_umho=1000,
        )
        log_b = record_chemistry_log(
            plant["id"], boiler["id"], ops[0]["id"],
            recorded_at="2026-08-05T09:00:00Z",
            conductivity_boiler_umho=11500, conductivity_feedwater_umho=1000,
        )
        state = get_boiler(plant["id"], boiler["id"])
        assert state["cycles_of_concentration"] == pytest.approx(11.5), (
            "latest log drives cycles (11500/1000)"
        )

        resp = api.void_chemistry_log(
            plant["id"], boiler["id"], log_b["id"], plant_manager_headers
        )
        validate_success(resp, expected_status=200)
        after = get_boiler(plant["id"], boiler["id"])
        assert after["cycles_of_concentration"] == pytest.approx(5.0), (
            "after voiding the latest log, cycles recompute from the remaining "
            "non-VOIDED log (5000/1000)"
        )


class TestOutOfSpecGate:
    def test_err_water_out_of_spec_blocks_bring_online(
        self, api, plant_manager_headers
    ):
        """PRD §2.7: "bringing online rejects a boiler whose `water_status` is
        anything other than `IN_SPEC` with `ERR_WATER_OUT_OF_SPEC` (422)."
        PRD §3.3: "A recorded log drives `IN_SPEC` to `OUT_OF_SPEC` when the
        cycles of concentration exceed the maximum of 10.0".

        Design: Corner/errors/err_water_out_of_spec_blocks_bring_online
        """
        plant, ops = setup_plant_with_operators(name="WOS Plant", count=1)
        op = ops[0]
        boiler = create_boiler(plant["id"], tag="B-WOS")
        headers = make_operator_headers(op["id"])
        record_in_spec_chemistry(plant["id"], boiler["id"], op["id"])
        validate_success(api.warm_boiler(plant["id"], boiler["id"], headers))
        # cycles 15000/1000 = 15 > 10.0 -> leaves IN_SPEC
        record_chemistry_log(
            plant["id"], boiler["id"], op["id"],
            recorded_at="2026-08-05T09:00:00Z",
            conductivity_boiler_umho=15000, conductivity_feedwater_umho=1000,
        )
        assert get_boiler(plant["id"], boiler["id"])["water_status"] != "IN_SPEC"

        resp = api.bring_boiler_online(plant["id"], boiler["id"], headers)
        validate_error(resp, ApiErrorId.ERR_WATER_OUT_OF_SPEC)


class TestWaterMassBalance:
    def test_feedwater_mass_balance_conservation(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "`total_feedwater_gal` must equal `total_blowdown_gal`
        plus `total_steam_lb` divided by 8.345 pounds per gallon, with the
        comparison pinned to 2 decimal places, round-half-up. The balance is
        re-evaluated whenever a log entry is verified or a verified entry is
        voided." A verify-then-void pair returns every total to zero.

        Design: Difficulty/compensating_invariant/feedwater_mass_balance_conservation
        """
        plant, ops = setup_plant_with_operators(name="WB Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-WB")
        deliver_fuel(plant["id"], 1000)
        entry = create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=8350, fuel_burned_gal=60,
            feedwater_intake_gal=1200, blowdown_gal=200,
        )
        mid = get_boiler(plant["id"], boiler["id"])
        assert mid["total_steam_lb"] == pytest.approx(8350)
        # drift = |1200 - (200 + 8350/8.345)| = 0.6 gal, within the 25.0
        # tolerance, so no chemistry-excursion incident is raised.
        incidents, _ = validate_paginated(
            api.list_incidents(
                plant["id"], plant_manager_headers,
                params={"severity": "MEDIUM"},
            )
        )
        assert not any(i["kind"] == "CHEMISTRY_EXCURSION" for i in incidents)

        validate_success(
            api.void_log_entry(
                plant["id"], boiler["id"], entry["id"], plant_manager_headers
            )
        )
        after = get_boiler(plant["id"], boiler["id"])
        assert after["total_feedwater_gal"] == pytest.approx(0)
        assert after["total_blowdown_gal"] == pytest.approx(0)
        assert after["total_steam_lb"] == pytest.approx(0)
        # Compensating pair leaves the boiler at its initial state: 0 == 0 + 0.

    def test_drift_beyond_tolerance_raises_chemistry_excursion_incident(
        self, api, plant_manager_headers
    ):
        """PRD §2.10: "If the absolute drift between the two sides exceeds
        25.0 gallons, the system automatically raises an Incident of `kind`
        `CHEMISTRY_EXCURSION` at `severity` `MEDIUM`, so that unexplained
        water loss is investigated rather than silently absorbed."
        Here drift = |1200 - (0 + 8350/8.345)| = 199.4 gal > 25.0.

        Design: Difficulty/compensating_invariant/feedwater_mass_balance_conservation
        """
        plant, ops = setup_plant_with_operators(name="WB2 Plant", count=2)
        boiler = create_boiler(plant["id"], tag="B-WB2")
        deliver_fuel(plant["id"], 1000)
        create_and_verify_log_entry(
            plant["id"], boiler["id"], ops[0]["id"], ops[1]["id"],
            steam_generated_lb=8350, fuel_burned_gal=60,
            feedwater_intake_gal=1200, blowdown_gal=0,
        )

        incidents, meta = validate_paginated(
            api.list_incidents(
                plant["id"], plant_manager_headers,
                params={"severity": "MEDIUM"},
            )
        )
        matches = [i for i in incidents if i["kind"] == "CHEMISTRY_EXCURSION"]
        assert len(matches) >= 1, (
            "a MEDIUM CHEMISTRY_EXCURSION incident must be auto-raised when the "
            "water mass balance drift exceeds 25.0 gallons"
        )
        assert all(i["severity"] == "MEDIUM" for i in matches)
