"""Refusals guarding the front of the fastener process route.

This module exercises the gates a request has to clear before material may move:
the plant-wide uniqueness of business identifiers and the separate register that
admits each mill certificate serial exactly once, a verification presenting the
wrong serial and the terminal rejection that follows it, an unverified heat
blocking wire release ahead of the lubrication floor, plating attempted before
heat treatment has passed, relief-bake parameters outside the temperature band or
below the class minimum soak, and an aerospace lot whose die utilisation has
reached the full derated life and can therefore no longer be certified. Every
expectation below is taken from the PRD narratives of §2.10, §3.1, §3.2, §3.6 and
§3.8.
"""

from typing import Any, Dict, Tuple

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    fixtures,
    make_heat_treat_headers,
    make_inspector_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ENGINEER = fixtures.ENGINEER
INSPECTOR = make_inspector_headers("insp-1")
HEAT_TREAT = make_heat_treat_headers("ht-1")
MANAGER = make_manager_headers("qm-1")
MANAGER_ALT = make_manager_headers("qm-2")

CLOCK_AT_SHIFT_START = "2026-09-01T06:00:00Z"

# The unplated reference part of the counterfeit register scenario.
UNPLATED_SPEC = {
    "part_number": "NP-M8-088",
    "thread_designation": "M8x1.25",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 20.0,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.100,
    "plating_spec": "NONE",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 100,
    "pieces_per_kg": 62.5,
    "proof_load_kn": 34.7,
}

# The same routing, zinc plated: CLASS_10_9 + ZINC_CLEAR => he_bake_min_minutes 240.
ZINC_SPEC = dict(UNPLATED_SPEC, part_number="NP-M8-ZN", plating_spec="ZINC_CLEAR")

# An aerospace part whose die is budgeted against its observed history.
AEROSPACE_SPEC = {
    "part_number": "AE-M8-095",
    "thread_designation": "M8x1.25",
    "strength_class": "CLASS_12_9",
    "qualification_program": "AEROSPACE_NADCAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 20.0,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 366,
    "max_core_hardness_hv": 414,
    "max_decarb_depth_mm": 0.100,
    "plating_spec": "NONE",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 100,
    "pieces_per_kg": 62.5,
    "proof_load_kn": 47.0,
}


# ---------------------------------------------------------------------------
# Local setup helpers (composed out of test_helpers.fixtures only)
# ---------------------------------------------------------------------------
def _register_reference_master_data() -> Dict[str, Any]:
    """Part spec, steel heat, die set and furnace each registered exactly once."""
    fixtures.set_clock(CLOCK_AT_SHIFT_START)
    spec = fixtures.register_part_spec(**UNPLATED_SPEC)
    heat = fixtures.register_steel_heat(
        heat_number="H-77410",
        mill_code="MC-A",
        grade="SAE_10B21",
        carbon_pct=0.21,
        boron_ppm=25,
        gross_mass_kg=500.0,
        mill_cert_serial="MC-2026-000481",
    )
    tool = fixtures.register_heading_tool(
        tool_code="DIE-4S-001", station_count=4, rated_life_pieces=120000
    )
    furnace = fixtures.register_furnace(furnace_code="FCE-1", max_charge_mass_kg=400.0)
    return {"spec": spec, "heat": heat, "tool": tool, "furnace": furnace}


def _pending_heat_with_drawn_wire(
    heat_number: str, mill_cert_serial: str, **wire_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A heat left in ``cert_status`` ``PENDING`` with one ``DRAWN`` wire lot on it."""
    fixtures.set_clock(CLOCK_AT_SHIFT_START, INSPECTOR)
    heat = fixtures.register_steel_heat(
        heat_number=heat_number,
        mill_code="MC-A",
        grade="SAE_10B21",
        carbon_pct=0.21,
        boron_ppm=25,
        gross_mass_kg=400.0,
        mill_cert_serial=mill_cert_serial,
    )
    wire = fixtures.register_wire_lot(heat["id"], gross_mass_kg=400.0, **wire_overrides)
    return heat, wire


def _plated_run_awaiting_its_bake() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A zinc-plated CLASS_10_9 lot whose plating run is ``PLATED`` at 22:00.

    The logical clock is left exactly at ``plated_at``, so the relief-bake delay
    the next call measures is 0.000 hours and only the bake parameters can fail.
    """
    env = fixtures.setup_heat_treated_lot(
        spec_overrides=ZINC_SPEC, lot_overrides={"lot_code": "L-2633"}
    )
    run = fixtures.schedule_plating(env["lot"]["id"])
    run = fixtures.complete_plating(run["id"])
    return env, run


def _only_plating_run(lot_id: str) -> Dict[str, Any]:
    items, _ = validate_paginated(api_client.list_lot_plating_runs(lot_id, HEAT_TREAT))
    assert len(items) == 1, f"Expected exactly one plating run, got {len(items)}"
    return items[0]


# ---------------------------------------------------------------------------
# Uniqueness: ERR_DUPLICATE_IDENTIFIER versus ERR_DUPLICATE_MILL_CERT_SERIAL
# ---------------------------------------------------------------------------
class TestDuplicateBusinessIdentifiers:
    """Tier-6 uniqueness collisions, and the register that keeps its own error."""

    def test_duplicate_part_number_is_rejected_and_the_first_spec_is_untouched(self, api):
        """Re-registering a part number already on the books is a 409 that changes nothing.

        PRD: "Every other business identifier collision reports `ERR_DUPLICATE_IDENTIFIER` (409): `part_number` on part-spec registration, `lot_code` on lot opening, `tool_code` on die-set registration, `furnace_code` on furnace registration, `cert_serial` on certificate drafting and on certificate reissue, `label_serial` on pack-unit opening — each unique across the whole plant — and `sequence_no` on secondary-operation queueing, unique within its production lot."

        Design: Corner/errors/duplicate_business_identifiers_and_serials_are_rejected
        """
        env = _register_reference_master_data()

        clash = api.create_part_spec(
            {
                "part_number": "NP-M8-088",
                "thread_designation": "M10x1.5",
                "strength_class": "CLASS_8_8",
                "qualification_program": "NONE",
                "allowed_steel_grades": ["SAE_1038"],
                "blank_mass_g": 32.0,
                "station_count_required": 3,
                "thread_timing": "AFTER_HEAT_TREAT",
                "required_secondary_ops": ["THREAD_ROLL"],
                "min_core_hardness_hv": 242,
                "max_core_hardness_hv": 318,
                "max_decarb_depth_mm": 0.150,
                "plating_spec": "NONE",
                "packaging_mode": "BY_COUNT",
                "nominal_pack_count": 50,
                "pieces_per_kg": 31.25,
                "proof_load_kn": 40.0,
            },
            ENGINEER,
        )
        validate_error(clash, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        stored = fixtures.read_part_spec(env["spec"]["id"])
        assert stored["version"] == 1, (
            f"Expected version 1, got {stored['version']} after a refused re-registration"
        )
        assert stored["thread_designation"] == "M8x1.25", (
            "Expected thread_designation M8x1.25, got "
            f"{stored['thread_designation']} after a refused re-registration"
        )
        assert stored["strength_class"] == "CLASS_10_9", (
            f"Expected strength_class CLASS_10_9, got {stored['strength_class']}"
        )

    def test_duplicate_mill_cert_serial_answers_the_counterfeit_register_error(self, api):
        """A second heat re-using a mill certificate serial gets its own 409, not the generic one.

        PRD: "A steel heat whose `mill_cert_serial` already exists in the register is rejected with `ERR_DUPLICATE_MILL_CERT_SERIAL` (409) — the counterfeit-prevention register admits each mill certificate serial exactly once."

        PRD: "Each steel heat carries a `mill_cert_serial` that no other heat may repeat, so a forged duplicate cannot be quietly registered alongside the genuine article."

        Design: Corner/errors/duplicate_business_identifiers_and_serials_are_rejected
        """
        env = _register_reference_master_data()

        clash = api.create_steel_heat(
            {
                "heat_number": "H-99999",
                "mill_code": "MC-B",
                "grade": "SAE_1038",
                "carbon_pct": 0.38,
                "boron_ppm": 0,
                "gross_mass_kg": 300.0,
                "mill_cert_serial": "MC-2026-000481",
            },
            INSPECTOR,
        )
        error = validate_error(clash, ApiErrorId.ERR_DUPLICATE_MILL_CERT_SERIAL.value)
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value, (
            "The serial register must not collapse into the generic identifier error, "
            f"got {error['error_id']}"
        )

        genuine = fixtures.read_heat(env["heat"]["id"])
        assert genuine["version"] == 1, (
            f"Expected version 1, got {genuine['version']} on the genuine heat"
        )
        assert genuine["mill_code"] == "MC-A", (
            f"Expected mill_code MC-A, got {genuine['mill_code']} on the genuine heat"
        )

    def test_duplicate_tool_code_is_rejected_and_the_die_set_keeps_its_nameplate(self, api):
        """Re-registering a die set code answers the generic identifier collision.

        PRD: "Every other business identifier collision reports `ERR_DUPLICATE_IDENTIFIER` (409): `part_number` on part-spec registration, `lot_code` on lot opening, `tool_code` on die-set registration, `furnace_code` on furnace registration, `cert_serial` on certificate drafting and on certificate reissue, `label_serial` on pack-unit opening — each unique across the whole plant — and `sequence_no` on secondary-operation queueing, unique within its production lot."

        Design: Corner/errors/duplicate_business_identifiers_and_serials_are_rejected
        """
        env = _register_reference_master_data()

        clash = api.create_heading_tool(
            {"tool_code": "DIE-4S-001", "station_count": 3, "rated_life_pieces": 90000},
            ENGINEER,
        )
        validate_error(clash, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        stored = fixtures.read_tool(env["tool"]["id"])
        assert stored["station_count"] == 4, (
            f"Expected station_count 4, got {stored['station_count']} after the refusal"
        )
        assert stored["rated_life_pieces"] == 120000, (
            f"Expected rated_life_pieces 120000, got {stored['rated_life_pieces']}"
        )
        assert stored["version"] == 1, (
            f"Expected version 1, got {stored['version']} after the refusal"
        )

    def test_duplicate_furnace_code_is_rejected_and_the_furnace_keeps_its_capacity(self, api):
        """Re-registering a furnace code answers the generic identifier collision.

        PRD: "Every other business identifier collision reports `ERR_DUPLICATE_IDENTIFIER` (409): `part_number` on part-spec registration, `lot_code` on lot opening, `tool_code` on die-set registration, `furnace_code` on furnace registration, `cert_serial` on certificate drafting and on certificate reissue, `label_serial` on pack-unit opening — each unique across the whole plant — and `sequence_no` on secondary-operation queueing, unique within its production lot."

        Design: Corner/errors/duplicate_business_identifiers_and_serials_are_rejected
        """
        env = _register_reference_master_data()

        clash = api.create_furnace(
            {"furnace_code": "FCE-1", "max_charge_mass_kg": 900.0}, ENGINEER
        )
        validate_error(clash, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        stored = fixtures.read_furnace(env["furnace"]["id"])
        assert stored["max_charge_mass_kg"] == pytest.approx(400.0, abs=0.001), (
            f"Expected max_charge_mass_kg 400.0, got {stored['max_charge_mass_kg']}"
        )
        assert stored["version"] == 1, (
            f"Expected version 1, got {stored['version']} after the refusal"
        )


# ---------------------------------------------------------------------------
# Serial mismatch, then the terminal rejection and its quarantine
# ---------------------------------------------------------------------------
class TestSerialMismatchAndRejection:
    """A wrong serial is a counterfeit signal; the rejection that follows is terminal."""

    def test_mismatched_serial_verification_is_refused_and_moves_nothing(self, api):
        """Attesting a serial the heat does not record is a 422 that leaves the heat PENDING.

        PRD: "A verification must present the same serial the heat already records; presenting a different one is treated as a counterfeit signal rather than a typo and is refused with `ERR_MILL_CERT_SERIAL_MISMATCH`."

        Design: Corner/errors/serial_mismatch_then_rejection_locks_the_heat_and_quarantines_its_wire
        """
        heat, wire = _pending_heat_with_drawn_wire("H-88001", "MC-2026-000900")

        mismatch = api.verify_mill_cert(
            heat["id"],
            {
                "outcome": "VERIFIED",
                "mill_cert_serial": "MC-2026-000901",
                "lab_report_reference": "LAB-0007",
            },
            INSPECTOR,
        )
        validate_error(mismatch, ApiErrorId.ERR_MILL_CERT_SERIAL_MISMATCH.value)

        after_heat = fixtures.read_heat(heat["id"])
        assert after_heat["cert_status"] == "PENDING", (
            f"Expected cert_status PENDING, got {after_heat['cert_status']} after the mismatch"
        )
        assert after_heat["version"] == 1, (
            f"Expected version 1, got {after_heat['version']} after the mismatch"
        )
        assert not after_heat.get("verified_at"), (
            f"verified_at must stay empty, got {after_heat.get('verified_at')!r}"
        )

        after_wire = fixtures.read_wire_lot(wire["id"])
        assert after_wire["status"] == "DRAWN", (
            f"Expected wire status DRAWN, got {after_wire['status']} after the mismatch"
        )
        assert after_wire["version"] == 1, (
            f"Expected wire version 1, got {after_wire['version']} after the mismatch"
        )

    def test_rejection_quarantines_the_wire_and_locks_the_heat_terminally(self, api):
        """A REJECTED verification quarantines the heat's wire and closes every further move.

        PRD: "On an outcome of `REJECTED`, the heat moves `PENDING → REJECTED`, recording `lab_report_reference`, and `REJECTED` is terminal — no path leads out of it."

        PRD: "The first link takes every wire lot drawn from the heat whose `status` is `DRAWN` or `RELEASED`, in ascending `created_at` order, to `QUARANTINED` with `quarantine_source` set to `HEAT_REJECTED`."

        PRD: "A steel heat must be `PENDING` or `SUSPECTED_COUNTERFEIT` to be verified, and `PENDING` or `VERIFIED` to be flagged counterfeit, with `REJECTED` terminal — otherwise `ERR_INVALID_HEAT_STATE` (409)."

        PRD: "A wire lot must be `DRAWN` to be released, so quarantined and already-released lots are refused — otherwise `ERR_INVALID_WIRE_LOT_STATE` (409)."

        Design: Corner/errors/serial_mismatch_then_rejection_locks_the_heat_and_quarantines_its_wire
        """
        heat, wire = _pending_heat_with_drawn_wire("H-88001", "MC-2026-000900")

        rejected = validate_success(
            api.verify_mill_cert(
                heat["id"],
                {
                    "outcome": "REJECTED",
                    "mill_cert_serial": "MC-2026-000900",
                    "lab_report_reference": "LAB-0008",
                },
                INSPECTOR,
            )
        )
        assert rejected["cert_status"] == "REJECTED", (
            f"Expected cert_status REJECTED, got {rejected['cert_status']}"
        )
        assert rejected["version"] == 2, (
            f"Expected heat version 2, got {rejected['version']} after the rejection"
        )
        assert rejected["lab_report_reference"] == "LAB-0008", (
            "Expected lab_report_reference LAB-0008, got "
            f"{rejected['lab_report_reference']}"
        )

        quarantined = fixtures.read_wire_lot(wire["id"])
        assert quarantined["status"] == "QUARANTINED", (
            f"Expected wire status QUARANTINED, got {quarantined['status']}"
        )
        assert quarantined["quarantine_source"] == "HEAT_REJECTED", (
            "Expected quarantine_source HEAT_REJECTED, got "
            f"{quarantined['quarantine_source']}"
        )
        assert quarantined["version"] == 2, (
            f"Expected wire version 2, got {quarantined['version']} after the cascade"
        )

        reverify = api.verify_mill_cert(
            heat["id"],
            {
                "outcome": "VERIFIED",
                "mill_cert_serial": "MC-2026-000900",
                "lab_report_reference": "LAB-0009",
            },
            INSPECTOR,
        )
        validate_error(reverify, ApiErrorId.ERR_INVALID_HEAT_STATE.value)

        flag = api.flag_counterfeit(heat["id"], {"reason": "ANONYMOUS_TIP"}, MANAGER_ALT)
        validate_error(flag, ApiErrorId.ERR_INVALID_HEAT_STATE.value)

        release = api.release_wire_lot(wire["id"], INSPECTOR)
        validate_error(release, ApiErrorId.ERR_INVALID_WIRE_LOT_STATE.value)

        still_rejected = fixtures.read_heat(heat["id"])
        assert still_rejected["cert_status"] == "REJECTED", (
            f"Expected cert_status REJECTED, got {still_rejected['cert_status']}"
        )
        assert still_rejected["version"] == 2, (
            f"Expected heat version 2, got {still_rejected['version']} after three refusals"
        )
        assert fixtures.read_wire_lot(wire["id"])["version"] == 2, (
            "The refused release must not advance the wire lot's version"
        )


# ---------------------------------------------------------------------------
# The unverified heat outranks the lubrication floor at wire release
# ---------------------------------------------------------------------------
class TestUnverifiedHeatBlocksWireRelease:
    """Priority 11 decides the response before the priority 13 lubrication rule runs."""

    def test_pending_heat_outranks_the_lubrication_floor_at_wire_release(self, api):
        """Uncoated wire drawn from a PENDING heat reports the heat, then the lubrication.

        PRD: "The first rule violated decides the response, and no later rule runs."

        PRD: "The steel heat behind the material must have `cert_status` of `VERIFIED` at wire-lot release, at lot opening, at certificate drafting, and at hold release when the hold's `hold_source` is `HEAT_COUNTERFEIT` — otherwise `ERR_STEEL_HEAT_NOT_VERIFIED` (409)."

        PRD: "The wire must actually be lubricated: `lubricant_coating` must be something other than `NONE` and `coating_weight_gsm` must be at least 2.0 grams per square metre, or the release is refused with `ERR_LUBRICATION_INSUFFICIENT`."

        Design: Corner/errors/unverified_heat_blocks_wire_release_ahead_of_the_lubrication_check
        """
        heat, wire = _pending_heat_with_drawn_wire(
            "H-88010",
            "MC-2026-000910",
            lubricant_coating="NONE",
            coating_weight_gsm=0.0,
        )

        first = api.release_wire_lot(wire["id"], INSPECTOR)
        validate_error(first, ApiErrorId.ERR_STEEL_HEAT_NOT_VERIFIED.value)

        fixtures.verify_heat(heat["id"], mill_cert_serial="MC-2026-000910")

        second = api.release_wire_lot(wire["id"], INSPECTOR)
        validate_error(second, ApiErrorId.ERR_LUBRICATION_INSUFFICIENT.value)

        after = fixtures.read_wire_lot(wire["id"])
        assert after["status"] == "DRAWN", (
            f"Expected wire status DRAWN, got {after['status']} after both refusals"
        )
        assert not after.get("inspected_at"), (
            f"inspected_at must stay empty, got {after.get('inspected_at')!r}"
        )
        assert after["version"] == 1, (
            f"Expected wire version 1, got {after['version']} after both refusals"
        )

    def test_suspected_counterfeit_heat_blocks_wire_drawn_after_the_flag(self, api):
        """Wire drawn after the counterfeit flag is still DRAWN, so the heat gate decides.

        PRD: "The steel heat behind the material must have `cert_status` of `VERIFIED` at wire-lot release, at lot opening, at certificate drafting, and at hold release when the hold's `hold_source` is `HEAT_COUNTERFEIT` — otherwise `ERR_STEEL_HEAT_NOT_VERIFIED` (409)."

        PRD: "Flagging a heat whose `cert_status` is `PENDING` or `VERIFIED` moves it to `SUSPECTED_COUNTERFEIT`, records the supplied `reason` as `counterfeit_reason`, and fires the plant's longest chain — four links, each caused by the write the previous link performed rather than by the original request."

        Design: Corner/errors/unverified_heat_blocks_wire_release_ahead_of_the_lubrication_check
        """
        fixtures.set_clock(CLOCK_AT_SHIFT_START, INSPECTOR)
        heat = fixtures.create_verified_heat(
            heat_number="H-88011",
            mill_code="MC-A",
            grade="SAE_10B21",
            carbon_pct=0.21,
            boron_ppm=25,
            gross_mass_kg=400.0,
            mill_cert_serial="MC-2026-000911",
        )
        flagged = fixtures.flag_heat_counterfeit(heat["id"], reason="SERIAL_REUSE_ALERT")
        assert flagged["cert_status"] == "SUSPECTED_COUNTERFEIT", (
            f"Expected cert_status SUSPECTED_COUNTERFEIT, got {flagged['cert_status']}"
        )

        late_wire = fixtures.register_wire_lot(
            heat["id"],
            gross_mass_kg=400.0,
            lubricant_coating="PHOSPHATE",
            coating_weight_gsm=4.5,
        )
        assert late_wire["status"] == "DRAWN", (
            "Wire drawn after the flag is untouched by the cascade, expected DRAWN, got "
            f"{late_wire['status']}"
        )

        release = api.release_wire_lot(late_wire["id"], INSPECTOR)
        validate_error(release, ApiErrorId.ERR_STEEL_HEAT_NOT_VERIFIED.value)

        after = fixtures.read_wire_lot(late_wire["id"])
        assert after["status"] == "DRAWN", (
            f"Expected wire status DRAWN, got {after['status']} after the refusal"
        )
        assert after["version"] == 1, (
            f"Expected wire version 1, got {after['version']} after the refusal"
        )


# ---------------------------------------------------------------------------
# Plating waits for a passing furnace run
# ---------------------------------------------------------------------------
class TestPlatingRequiresPassedHeatTreatment:
    """`POST /plating-runs` reads ``heat_treat_completed``, not the process state."""

    def test_plating_is_refused_until_the_furnace_run_comes_back_passing(self, api):
        """A zinc lot is refused plating at HEADED, at SECONDARY_DONE and mid-run.

        PRD: "Plating is scheduled by a `HeatTreatOperator` or `ProcessEngineer` against a `production_lot_id`, and it may not begin before metallurgy has been proven: the lot's `heat_treat_completed` flag must be true both when the run is scheduled and when plating is completed, or the request is refused with `ERR_HEAT_TREAT_NOT_PASSED`."

        PRD: "On `PASS`, the lot's `heat_treat_completed` flag becomes true and the lot moves `SECONDARY_DONE → HEAT_TREATED`."

        PRD: "Although the payload names `plating_spec` and `load_mass_kg`, both are server-derived on the created run: `plating_spec` is copied from the part specification's own `plating_spec` — one of `ZINC_CLEAR`, `ZINC_NICKEL` or `CADMIUM`, since an unplated part never has a plating run — and `load_mass_kg` is the lot's `available_count` multiplied by the part's `blank_mass_g`, divided by 1000, rounded half up to three decimal places."

        Design: Corner/errors/plating_cannot_be_scheduled_before_heat_treatment_passes
        """
        env = fixtures.setup_headed_lot(
            spec_overrides=ZINC_SPEC, lot_overrides={"lot_code": "L-2631"}
        )
        lot_id = env["lot"]["id"]
        assert env["lot"]["process_state"] == "HEADED", (
            f"Expected process_state HEADED, got {env['lot']['process_state']}"
        )
        assert env["lot"]["heat_treat_completed"] is False, (
            "heat_treat_completed must still be false at HEADED"
        )

        payload = {
            "production_lot_id": lot_id,
            "plating_spec": "ZINC_CLEAR",
            "load_mass_kg": 98.0,
        }
        at_headed = api.create_plating_run(payload, HEAT_TREAT)
        validate_error(at_headed, ApiErrorId.ERR_HEAT_TREAT_NOT_PASSED.value)

        fixtures.run_secondary_op(lot_id, op_type="THREAD_ROLL", sequence_no=1, pieces_out=4850)
        secondary_done = fixtures.read_lot(lot_id)
        assert secondary_done["process_state"] == "SECONDARY_DONE", (
            f"Expected process_state SECONDARY_DONE, got {secondary_done['process_state']}"
        )

        payload["load_mass_kg"] = 97.0
        at_secondary_done = api.create_plating_run(payload, HEAT_TREAT)
        validate_error(at_secondary_done, ApiErrorId.ERR_HEAT_TREAT_NOT_PASSED.value)

        run = fixtures.book_heat_treat(lot_id, env["furnace"]["id"])
        fixtures.start_heat_treat(run["id"], at="2026-09-01T19:00:00Z")

        while_running = api.create_plating_run(payload, HEAT_TREAT)
        validate_error(while_running, ApiErrorId.ERR_HEAT_TREAT_NOT_PASSED.value)
        assert fixtures.read_lot(lot_id)["heat_treat_completed"] is False, (
            "heat_treat_completed must still be false while the furnace run is RUNNING"
        )

        items, pagination = validate_paginated(api.list_lot_plating_runs(lot_id, HEAT_TREAT))
        assert pagination["total_count"] == 0, (
            f"Expected total_count 0, got {pagination['total_count']} after three refusals"
        )
        assert items == [], f"Expected no plating run rows, got {items}"

        results = fixtures.record_heat_treat_results(
            run["id"],
            at="2026-09-01T22:00:00Z",
            core_hardness_hv=330.0,
            surface_decarb_depth_mm=0.020,
        )
        assert results["result"] == "PASS", (
            f"Expected furnace result PASS, got {results['result']}"
        )
        passed_lot = fixtures.read_lot(lot_id)
        assert passed_lot["heat_treat_completed"] is True, (
            "heat_treat_completed must be true after the PASS"
        )
        assert passed_lot["process_state"] == "HEAT_TREATED", (
            f"Expected process_state HEAT_TREATED, got {passed_lot['process_state']}"
        )

        created = validate_success(api.create_plating_run(payload, HEAT_TREAT), 201)
        assert created["status"] == "SCHEDULED", (
            f"Expected status SCHEDULED, got {created['status']}"
        )
        assert created["plating_spec"] == "ZINC_CLEAR", (
            f"Expected plating_spec ZINC_CLEAR, got {created['plating_spec']}"
        )
        assert created["load_mass_kg"] == pytest.approx(97.000, abs=0.001), (
            f"Expected load_mass_kg 97.000 for 4850 blanks of 20.0 g, got {created['load_mass_kg']}"
        )

        _, pagination = validate_paginated(api.list_lot_plating_runs(lot_id, HEAT_TREAT))
        assert pagination["total_count"] == 1, (
            f"Expected total_count 1, got {pagination['total_count']} — the refusals left no rows"
        )


# ---------------------------------------------------------------------------
# Relief-bake parameters
# ---------------------------------------------------------------------------
class TestReliefBakeParameters:
    """One error id covers both temperature bounds and the class minimum soak."""

    def test_bake_below_the_inclusive_temperature_floor_is_rejected(self, api):
        """189 degrees is one degree under the floor, so the bake never starts.

        PRD: "The parameters must be right: `bake_temp_c` must be at least 190 and at most 230 degrees Celsius — both bounds inclusive, so exactly 190 and exactly 230 both pass — and `bake_duration_min` must be at least the part's `he_bake_min_minutes`; either violation is refused with `ERR_HE_BAKE_PARAMS_INVALID`."

        Design: Corner/errors/bake_parameters_are_rejected_outside_the_band_and_below_the_minimum_soak
        """
        env, run = _plated_run_awaiting_its_bake()

        too_cold = api.start_bake(
            run["id"], {"bake_temp_c": 189, "bake_duration_min": 240}, HEAT_TREAT
        )
        validate_error(too_cold, ApiErrorId.ERR_HE_BAKE_PARAMS_INVALID.value)

        after = _only_plating_run(env["lot"]["id"])
        assert after["status"] == "PLATED", (
            f"Expected status PLATED, got {after['status']} after the refused bake start"
        )
        assert after["version"] == 2, (
            f"Expected version 2 (create, complete-plating), got {after['version']}"
        )
        assert not after.get("bake_started_at"), (
            f"bake_started_at must stay empty, got {after.get('bake_started_at')!r}"
        )

    def test_bake_above_the_inclusive_temperature_ceiling_is_rejected(self, api):
        """231 degrees is one degree over the ceiling, so the bake never starts.

        PRD: "The parameters must be right: `bake_temp_c` must be at least 190 and at most 230 degrees Celsius — both bounds inclusive, so exactly 190 and exactly 230 both pass — and `bake_duration_min` must be at least the part's `he_bake_min_minutes`; either violation is refused with `ERR_HE_BAKE_PARAMS_INVALID`."

        Design: Corner/errors/bake_parameters_are_rejected_outside_the_band_and_below_the_minimum_soak
        """
        env, run = _plated_run_awaiting_its_bake()

        too_hot = api.start_bake(
            run["id"], {"bake_temp_c": 231, "bake_duration_min": 240}, HEAT_TREAT
        )
        validate_error(too_hot, ApiErrorId.ERR_HE_BAKE_PARAMS_INVALID.value)

        after = _only_plating_run(env["lot"]["id"])
        assert after["status"] == "PLATED", (
            f"Expected status PLATED, got {after['status']} after the refused bake start"
        )
        assert after["version"] == 2, (
            f"Expected version 2 (create, complete-plating), got {after['version']}"
        )

    def test_bake_shorter_than_the_class_minimum_soak_is_rejected(self, api):
        """239 minutes misses the CLASS_10_9 minimum of 240 by one minute.

        PRD: "The parameters must be right: `bake_temp_c` must be at least 190 and at most 230 degrees Celsius — both bounds inclusive, so exactly 190 and exactly 230 both pass — and `bake_duration_min` must be at least the part's `he_bake_min_minutes`; either violation is refused with `ERR_HE_BAKE_PARAMS_INVALID`."

        PRD: "`he_bake_min_minutes` follows from it: zero when no bake is required; a full eight hours, expressed as 480 minutes, for `CLASS_12_9` and `GRADE_8`; and four hours, expressed as 240 minutes, for `CLASS_10_9`."

        Design: Corner/errors/bake_parameters_are_rejected_outside_the_band_and_below_the_minimum_soak
        """
        env, run = _plated_run_awaiting_its_bake()
        assert env["spec"]["he_bake_min_minutes"] == 240, (
            "A zinc-plated CLASS_10_9 part owes a 240 minute soak, got "
            f"{env['spec']['he_bake_min_minutes']}"
        )

        too_short = api.start_bake(
            run["id"], {"bake_temp_c": 200, "bake_duration_min": 239}, HEAT_TREAT
        )
        validate_error(too_short, ApiErrorId.ERR_HE_BAKE_PARAMS_INVALID.value)

        after = _only_plating_run(env["lot"]["id"])
        assert after["status"] == "PLATED", (
            f"Expected status PLATED, got {after['status']} after the refused bake start"
        )
        assert after["version"] == 2, (
            f"Expected version 2 (create, complete-plating), got {after['version']}"
        )
        assert not after.get("bake_duration_min"), (
            f"bake_duration_min must stay empty, got {after.get('bake_duration_min')!r}"
        )

    def test_bake_at_the_floor_temperature_with_the_exact_minimum_soak_starts(self, api):
        """190 degrees for exactly 240 minutes passes both inclusive checks.

        PRD: "The parameters must be right: `bake_temp_c` must be at least 190 and at most 230 degrees Celsius — both bounds inclusive, so exactly 190 and exactly 230 both pass — and `bake_duration_min` must be at least the part's `he_bake_min_minutes`; either violation is refused with `ERR_HE_BAKE_PARAMS_INVALID`."

        PRD: "The bake must start promptly: `bake_delay_hours` is the elapsed time from `plated_at` to now, expressed in hours — the elapsed seconds divided by three thousand six hundred — rounded half up to three decimal places, and it must be at most 4.0 hours; the bound is inclusive, so a delay of exactly 4.000 hours still passes, while anything longer is refused with `ERR_HE_BAKE_WINDOW_MISSED`."

        PRD: "On success the run moves `PLATED → BAKING`, `bake_started_at` is stamped from the logical clock, `bake_delay_hours` and both bake parameters are recorded, and the run's `version` increments by 1."

        Design: Corner/errors/bake_parameters_are_rejected_outside_the_band_and_below_the_minimum_soak
        """
        env, run = _plated_run_awaiting_its_bake()

        baking = validate_success(
            api.start_bake(
                run["id"], {"bake_temp_c": 190, "bake_duration_min": 240}, HEAT_TREAT
            )
        )
        assert baking["status"] == "BAKING", (
            f"Expected status BAKING, got {baking['status']}"
        )
        assert baking["bake_temp_c"] == pytest.approx(190, abs=0.001), (
            f"Expected bake_temp_c 190, got {baking['bake_temp_c']}"
        )
        assert baking["bake_duration_min"] == 240, (
            f"Expected bake_duration_min 240, got {baking['bake_duration_min']}"
        )
        assert baking["bake_delay_hours"] == pytest.approx(0.000, abs=0.001), (
            "The bake started at the plating instant, so expected bake_delay_hours 0.000, got "
            f"{baking['bake_delay_hours']}"
        )
        assert baking["version"] == 3, (
            "Expected version 3 (create, complete-plating, start-bake), got "
            f"{baking['version']}"
        )
        assert baking["bake_started_at"], "bake_started_at must be stamped from the logical clock"

        stored = _only_plating_run(env["lot"]["id"])
        assert stored["status"] == "BAKING", (
            f"Expected the stored run to read BAKING, got {stored['status']}"
        )
        assert stored["version"] == 3, (
            f"Expected the stored run at version 3, got {stored['version']}"
        )


# ---------------------------------------------------------------------------
# The aerospace die-utilisation ceiling at certificate draft
# ---------------------------------------------------------------------------
class TestAerospaceUtilizationCeiling:
    """The cap bites at draft time, and the traceability read is not gated by it."""

    def test_aerospace_lot_at_full_die_utilization_cannot_be_certified(self, api):
        """A die consumed to exactly 100.00 percent heads, passes and is accepted — but never certifies.

        PRD: "And for a part whose `qualification_program` is `AEROSPACE_NADCAP` only, the lot's snapshotted `tool_utilization_pct` may be at most 80.00 percent of derated die life — the bound is inclusive, so exactly 80.00 passes — or the draft is refused with `ERR_AEROSPACE_TOOL_UTILIZATION_EXCEEDED`."

        PRD: "The certificate's `traceability_chain` is a frozen provenance object projected at draft time (and re-projected on reissue), and the same projection is available as a computed read on the lot itself even before any certificate exists."

        Design: Corner/errors/aerospace_lot_at_full_die_utilization_cannot_be_certified
        """
        env = fixtures.setup_tested_lot(
            unplated=True,
            spec_overrides=AEROSPACE_SPEC,
            tool_overrides={
                "tool_code": "DIE-AE-001",
                "station_count": 4,
                "rated_life_pieces": 5985,
            },
            furnace_overrides={"furnace_code": "FCE-2", "max_charge_mass_kg": 400.0},
            press_code="PRESS-9",
            lot_overrides={"lot_code": "L-AE01"},
            planned_pieces=5700,
            headed_count=5900,
            heading_scrap_count=85,
            ops=[
                {
                    "op_type": "THREAD_ROLL",
                    "sequence_no": 1,
                    "pieces_out": 5850,
                    "machine_code": "TR-2",
                }
            ],
            booking_overrides={"austenitize_temp_c": 880.0, "temper_temp_c": 380.0},
            core_hardness_hv=390.0,
            surface_decarb_depth_mm=0.020,
            min_measured_core_hardness_hv=390.0,
        )
        lot, test = env["lot"], env["lot_test"]

        tool = fixtures.read_tool(env["tool"]["id"])
        assert tool["cumulative_pieces_current_cycle"] == 5985, (
            "Expected 5985 pieces in the open cycle (5900 good + 85 scrapped), got "
            f"{tool['cumulative_pieces_current_cycle']}"
        )
        assert tool["status"] == "WORN", (
            f"Expected the die set WORN at full derated life, got {tool['status']}"
        )
        assert lot["tool_utilization_pct"] == pytest.approx(100.00, abs=0.001), (
            f"Expected tool_utilization_pct 100.00, got {lot['tool_utilization_pct']}"
        )

        run = fixtures.read_heat_treat_run(env["heat_treat_run"]["id"])
        assert run["charge_mass_kg"] == pytest.approx(117.000, abs=0.001), (
            f"Expected charge_mass_kg 117.000 for 5850 blanks, got {run['charge_mass_kg']}"
        )
        assert run["result"] == "PASS", (
            f"Expected furnace result PASS, got {run['result']}"
        )
        assert run["total_decarb_depth_mm"] == pytest.approx(0.020, abs=0.001), (
            f"Expected total_decarb_depth_mm 0.020, got {run['total_decarb_depth_mm']}"
        )

        assert test["result"] == "ACCEPT", (
            f"Expected the destructive test to ACCEPT, got {test['result']}"
        )
        assert lot["achieved_strength_class"] == "CLASS_12_9", (
            "Expected achieved_strength_class CLASS_12_9 so only the die-utilisation gate "
            f"can bite, got {lot['achieved_strength_class']}"
        )
        assert lot["process_state"] == "TESTED", (
            f"Expected process_state TESTED, got {lot['process_state']}"
        )

        refused = api.create_certification_document(
            {
                "production_lot_id": lot["id"],
                "lot_test_id": test["id"],
                "cert_serial": "CERT-AE01",
                "expected_production_lot_version": lot["version"],
            },
            INSPECTOR,
        )
        validate_error(refused, ApiErrorId.ERR_AEROSPACE_TOOL_UTILIZATION_EXCEEDED.value)

        _, pagination = validate_paginated(
            api.list_certification_documents(INSPECTOR, {"production_lot_id": lot["id"]})
        )
        assert pagination["total_count"] == 0, (
            f"Expected total_count 0 certificates, got {pagination['total_count']}"
        )

        chain = validate_success(api.get_lot_traceability(lot["id"], MANAGER))
        assert chain["tool_utilization_pct"] == pytest.approx(100.00, abs=0.001), (
            "The traceability read is not gated by the ceiling, expected "
            f"tool_utilization_pct 100.00, got {chain['tool_utilization_pct']}"
        )
        assert chain["pinned_part_spec_version"] == 1, (
            f"Expected pinned_part_spec_version 1, got {chain['pinned_part_spec_version']}"
        )
