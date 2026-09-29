"""The numbers the plant's quality gate turns on.

This module exercises the arithmetic and the frozen snapshots that decide whether a
fastener lot may be certified: the unplated route that reaches ``BAKED`` without any
relief bake at all, the normal-inspection sampling floor that makes a nearly exhausted
lot unsamplable, the four-term risk score that is rounded exactly once at the very end,
the exact strength-class band match a certificate draft demands, the carton count
tolerance derived from the nominal pack, and the provenance projection that replays the
lot's own snapshotted die wear rather than the die set's live counter.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_lot_piece_ledger,
    assert_traceability_projection,
    expected_normal_sample_size,
    fixtures,
    round_half_up,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_clerk_headers, make_inspector_headers

# The CLASS_8_8 / ZINC_CLEAR part: plated, but not embrittlement-prone.
NO_BAKE_SPEC = {
    "part_number": "NP-M8-088Z",
    "strength_class": "CLASS_8_8",
    "plating_spec": "ZINC_CLEAR",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "blank_mass_g": 20.0,
    "min_core_hardness_hv": 242,
    "max_core_hardness_hv": 318,
    "max_decarb_depth_mm": 0.100,
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 100,
    "pieces_per_kg": 62.5,
}

# The unplated reference part: plating_spec NONE, so a lot test is entered without a bake.
UNPLATED_SPEC = {
    "part_number": "NP-M8-088",
    "strength_class": "CLASS_10_9",
    "plating_spec": "NONE",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "blank_mass_g": 20.0,
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.100,
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 100,
    "count_tolerance_pct": 0.02,
    "pieces_per_kg": 62.5,
}


class TestNoBakePartReachesBaked:
    """A ZINC_CLEAR CLASS_8_8 part is plated yet owes no relief bake."""

    def test_start_bake_is_refused_on_a_part_that_owes_no_bake(self):
        """A plated CLASS_8_8 lot derives no bake duty, so starting a bake is refused.

        PRD: "`he_bake_required` is true exactly when the part is plated with something — that is, `plating_spec` is not `NONE` — *and* its `strength_class` is one of the three embrittlement-prone classes `CLASS_10_9`, `CLASS_12_9` and `GRADE_8`; in every other combination it is false."

        PRD: "The part must actually need a bake: `he_bake_required` must be true, or the request is refused with `ERR_BAKE_NOT_REQUIRED`."

        Design: Corner/calculations/no_bake_part_reaches_baked_and_start_bake_is_rejected
        """
        env = fixtures.setup_heat_treated_lot(
            spec_overrides=dict(NO_BAKE_SPEC),
            core_hardness_hv=280.0,
            surface_decarb_depth_mm=0.020,
        )
        spec = fixtures.read_part_spec(env["spec"]["id"])
        assert spec["he_bake_required"] is False, (
            "Expected he_bake_required False for a ZINC_CLEAR CLASS_8_8 part, got "
            f"{spec['he_bake_required']}"
        )
        assert spec["he_bake_min_minutes"] == 0, (
            f"Expected he_bake_min_minutes 0, got {spec['he_bake_min_minutes']}"
        )

        run = fixtures.schedule_plating(env["lot"]["id"])
        assert run["load_mass_kg"] == pytest.approx(97.000, abs=0.001), (
            "load_mass_kg is derived from available_count 4850 * 20.0 g, expected "
            f"97.000, got {run['load_mass_kg']}"
        )
        fixtures.complete_plating(run["id"], at="2026-09-02T02:00:00Z")

        resp = api_client.start_bake(
            run["id"],
            {"bake_temp_c": 200.0, "bake_duration_min": 240},
            fixtures.HEAT_TREAT,
        )
        validate_error(resp, ApiErrorId.ERR_BAKE_NOT_REQUIRED.value)

        runs, _ = validate_paginated(
            api_client.list_lot_plating_runs(env["lot"]["id"], fixtures.HEAT_TREAT)
        )
        current = next(r for r in runs if r["id"] == run["id"])
        assert current["status"] == "PLATED", (
            f"Expected the run to stay PLATED after the refused bake, got {current['status']}"
        )
        assert current["bake_started_at"] is None, (
            f"Expected bake_started_at empty, got {current['bake_started_at']}"
        )
        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "PLATED", (
            f"Expected the lot to stay PLATED, got {lot['process_state']}"
        )

    def test_complete_bake_takes_the_no_bake_run_straight_to_bake_complete(self):
        """Closing a no-bake run jumps PLATED to BAKE_COMPLETE and scores the lot.

        PRD: "For a part whose `he_bake_required` is false, there is no soak to wait for: the run is still in `status` `PLATED` and moves `PLATED → BAKE_COMPLETE` directly, stamping `bake_completed_at` while `bake_delay_hours` stays empty and no bake parameters are recorded at all."

        PRD: "In both branches the lot moves `PLATED → BAKED`, the lot's pre-test risk score is computed, and the run's `version` and the lot's `version` each increment by 1."

        PRD: "The **bake term** is 0 for a part whose `he_bake_required` is false; otherwise it depends on `bake_delay_hours`: 0 when that delay is at most 2.0 hours, and otherwise the excess over 2.0 hours multiplied by 40, capped at 100 — so a bake started 3.5 hours after plating contributes 60."

        Design: Corner/calculations/no_bake_part_reaches_baked_and_start_bake_is_rejected
        """
        env = fixtures.setup_heat_treated_lot(
            spec_overrides=dict(NO_BAKE_SPEC),
            core_hardness_hv=280.0,
            surface_decarb_depth_mm=0.020,
        )
        lot_before = fixtures.read_lot(env["lot"]["id"])
        assert lot_before["tool_utilization_pct"] == pytest.approx(4.13, abs=0.001), (
            "The lot snapshotted 4960 pieces against a 120000-piece derated budget, "
            f"expected tool_utilization_pct 4.13, got {lot_before['tool_utilization_pct']}"
        )

        run = fixtures.schedule_plating(env["lot"]["id"])
        plated = fixtures.complete_plating(run["id"], at="2026-09-02T02:00:00Z")
        assert plated["status"] == "PLATED", (
            f"Expected PLATED after completing plating, got {plated['status']}"
        )
        # Completing plating already advanced the lot's version by 1 of its own accord,
        # so the bake-close increment is measured from here.
        lot_before_bake = fixtures.read_lot(env["lot"]["id"])

        closed = fixtures.complete_bake(run["id"], at="2026-09-02T03:00:00Z")
        assert closed["status"] == "BAKE_COMPLETE", (
            f"Expected BAKE_COMPLETE on the no-bake branch, got {closed['status']}"
        )
        assert closed["bake_completed_at"] is not None and closed[
            "bake_completed_at"
        ].startswith("2026-09-02T03:00:00"), (
            "bake_completed_at is stamped from the logical clock, expected "
            f"2026-09-02T03:00:00, got {closed['bake_completed_at']}"
        )
        for field in ("bake_started_at", "bake_delay_hours", "bake_temp_c", "bake_duration_min"):
            assert closed[field] is None, (
                f"Expected {field} to stay empty on a no-bake run, got {closed[field]}"
            )

        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "BAKED", (
            f"Expected the lot to reach BAKED, got {lot['process_state']}"
        )
        # heat term 0 (VERIFIED) + 0.20 * 4.13 + bake term 0 + 0.25 * 20.00 = 5.826 -> 5.83
        assert lot["risk_score_pre_test"] == pytest.approx(5.83, abs=0.001), (
            "Expected risk_score_pre_test 5.83 with a zero bake term, got "
            f"{lot['risk_score_pre_test']}"
        )
        assert lot["version"] == lot_before_bake["version"] + 1, (
            f"Expected the lot version to advance to {lot_before_bake['version'] + 1} on "
            f"the bake close, got {lot['version']}"
        )


def test_sampling_floor_of_eight_makes_a_tiny_lot_unsamplable():
    """A lot holding only five pieces cannot meet the normal plan's floor of eight.

    PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

    PRD: "The lot must hold at least `sample_size` available pieces, or the request is refused with `ERR_INSUFFICIENT_SAMPLE_PIECES`."

    Design: Corner/calculations/sampling_floor_of_eight_makes_a_tiny_lot_unsamplable
    """
    tiny_spec = dict(UNPLATED_SPEC)
    tiny_spec.update(
        {
            "part_number": "NP-M4-TINY",
            "thread_designation": "M4x0.7",
            "blank_mass_g": 2.0,
            "pieces_per_kg": 500.0,
            "proof_load_kn": 8.0,
        }
    )
    env = fixtures.setup_secondary_done_lot(
        planned_pieces=10,
        headed_count=9,
        heading_scrap_count=1,
        ops=[
            {
                "op_type": "THREAD_ROLL",
                "sequence_no": 1,
                "pieces_out": 5,
                "machine_code": "TR-1",
            }
        ],
        unplated=True,
        spec_overrides=tiny_spec,
        lot_overrides={
            "lot_code": "L-2609",
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T07:00:00Z",
        },
    )
    lot_before = fixtures.read_lot(env["lot"]["id"])
    assert lot_before["available_count"] == 5, (
        f"Expected 5 available pieces before the test, got {lot_before['available_count']}"
    )
    assert lot_before["process_state"] == "SECONDARY_DONE", (
        "An unplated part is tested straight from SECONDARY_DONE, but the lot reads "
        f"{lot_before['process_state']}"
    )
    assert expected_normal_sample_size(5) == 8, (
        "max(8, ceil(sqrt(5))) must be 8 — the floor, not the square-root branch"
    )

    resp = api_client.create_lot_test(
        {"production_lot_id": env["lot"]["id"]}, make_inspector_headers("insp-1")
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SAMPLE_PIECES.value)

    lot_after = fixtures.read_lot(env["lot"]["id"])
    assert lot_after["available_count"] == 5, (
        "The refused call books nothing, expected available_count still 5, got "
        f"{lot_after['available_count']}"
    )
    assert lot_after["destructive_test_count"] == 0, (
        "The refused call consumes no sample, expected destructive_test_count 0, got "
        f"{lot_after['destructive_test_count']}"
    )
    assert lot_after["inspection_severity"] is None, (
        "No severity is frozen by a refused test, got "
        f"{lot_after['inspection_severity']}"
    )
    assert lot_after["process_state"] == "SECONDARY_DONE", (
        f"Expected the lot to stay SECONDARY_DONE, got {lot_after['process_state']}"
    )
    assert_lot_piece_ledger(lot_after)

    tests, pagination = validate_paginated(
        api_client.list_lot_tests(env["lot"]["id"], make_inspector_headers("insp-1"))
    )
    assert pagination["total_count"] == 0, (
        f"Expected no lot test rows, got total_count {pagination['total_count']}"
    )
    assert tests == [], f"Expected no lot test rows, got {tests}"


def test_risk_score_rounds_once_at_the_end_not_term_by_term():
    """A decarb term of 20.67 weighted with 4.13 rounds once to 5.99, never to 6.00.

    PRD: "Their weighted sum is rounded exactly once, at the end, after all four terms have been weighted and added; the individual weighted terms are never rounded on their own."

    PRD: "The **decarburization term** is 100 multiplied by the governing run's `total_decarb_depth_mm`, divided by the part's `max_decarb_depth_mm`, rounded half up to two decimal places and then capped at 100."

    PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

    PRD: "`risk_score_final` adds test evidence to the frozen pre-test value: it is `risk_score_pre_test` plus 12.5 points for each failure counted in `total_failures`, capped at 100, and rounded half up to two decimal places."

    Design: Corner/calculations/risk_score_rounds_once_at_the_end_not_term_by_term
    """
    spec_overrides = dict(UNPLATED_SPEC)
    spec_overrides.update({"part_number": "NP-M8-150", "max_decarb_depth_mm": 0.150})
    env = fixtures.setup_heat_treated_lot(
        unplated=True,
        spec_overrides=spec_overrides,
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.031,
        booking_overrides={"carbon_potential_pct": 0.42},
        lot_overrides={"lot_code": "L-2610"},
    )
    run = fixtures.read_heat_treat_run(env["heat_treat_run"]["id"])
    assert run["total_decarb_depth_mm"] == pytest.approx(0.031, abs=0.0005), (
        "A carbon potential of 0.42 leaves no deficit, so total_decarb_depth_mm is the "
        f"measured 0.031, got {run['total_decarb_depth_mm']}"
    )
    assert run["result"] == "PASS", (
        f"0.031 mm is inside a 0.150 mm ceiling, expected PASS, got {run['result']}"
    )

    # decarb term = round_half_up(100 * 0.031 / 0.150, 2) = 20.67
    decarb_term = round_half_up(100.0 * 0.031 / 0.150, 2)
    assert decarb_term == pytest.approx(20.67, abs=0.001), (
        f"Expected a decarb term of 20.67, computed {decarb_term}"
    )
    term_by_term = round_half_up(0.20 * 4.13, 2) + round_half_up(0.25 * decarb_term, 2)

    test = fixtures.open_lot_test(env["lot"]["id"], inspector_user_id="insp-1")
    lot_after_open = fixtures.read_lot(env["lot"]["id"])
    assert lot_after_open["risk_score_pre_test"] == pytest.approx(5.99, abs=0.001), (
        "0.20 * 4.13 + 0.25 * 20.67 is 5.9935 and must be rounded once to 5.99, got "
        f"{lot_after_open['risk_score_pre_test']}"
    )
    assert lot_after_open["risk_score_pre_test"] != pytest.approx(term_by_term, abs=0.001), (
        "Rounding each weighted term first would report "
        f"{term_by_term}; the score must not equal that"
    )
    assert test["sample_size"] == 70, (
        f"ceil(sqrt(4850)) is 70, got sample_size {test['sample_size']}"
    )
    assert test["acceptance_number"] == 1, (
        f"A sample of 70 tolerates one failure, got {test['acceptance_number']}"
    )
    assert lot_after_open["inspection_severity"] == "NORMAL", (
        "A pre-test score under 40.0 with no prior rejection is NORMAL, got "
        f"{lot_after_open['inspection_severity']}"
    )

    closed = fixtures.record_lot_test_results(
        test["id"],
        inspector_user_id="insp-1",
        proof_load_failures=1,
        tensile_failures=0,
        min_measured_core_hardness_hv=322.0,
    )
    assert closed["total_failures"] == 1, (
        f"Expected total_failures 1, got {closed['total_failures']}"
    )
    assert closed["result"] == "ACCEPT", (
        f"One failure against an acceptance number of 1 accepts, got {closed['result']}"
    )

    lot = fixtures.read_lot(env["lot"]["id"])
    assert lot["risk_score_final"] == pytest.approx(18.49, abs=0.001), (
        f"Expected risk_score_final 5.99 + 12.5 = 18.49, got {lot['risk_score_final']}"
    )
    assert lot["risk_score_pre_test"] == pytest.approx(5.99, abs=0.001), (
        "The pre-test score is frozen by the second pass, expected 5.99, got "
        f"{lot['risk_score_pre_test']}"
    )
    assert lot["achieved_strength_class"] == "CLASS_10_9", (
        f"322 HV sits inside the CLASS_10_9 band, got {lot['achieved_strength_class']}"
    )
    assert lot["process_state"] == "TESTED", (
        f"An accepted test takes the lot to TESTED, got {lot['process_state']}"
    )


def test_overachieved_hardness_still_fails_the_exact_class_match():
    """A GRADE_5 lot measured at 310 HV is awarded CLASS_10_9 and cannot be certified.

    PRD: "The achieved strength class is read out of the sample's weakest piece — `min_measured_core_hardness_hv` — against five overlapping hardness bands, each stated in Vickers with both bounds inclusive: `CLASS_8_8` spans 242 to 318, `CLASS_10_9` spans 304 to 361, `CLASS_12_9` spans 366 to 414, `GRADE_5` spans 241 to 302, and `GRADE_8` spans 321 to 352."

    PRD: "Only when it does not are the bands scanned in a fixed order — `CLASS_12_9` first, then `CLASS_10_9`, then `GRADE_8`, then `CLASS_8_8`, then `GRADE_5` — and the first band containing the hardness wins."

    PRD: "The lot's `achieved_strength_class` must equal the part's specified `strength_class`, or the draft is refused with `ERR_STRENGTH_CLASS_NOT_ACHIEVED`; a lot that came out one grade low may not be certified to the grade the customer ordered."

    Design: Corner/calculations/overachieved_hardness_still_fails_the_exact_class_match
    """
    spec_overrides = dict(UNPLATED_SPEC)
    spec_overrides.update(
        {
            "part_number": "NP-M8-G5",
            "strength_class": "GRADE_5",
            "min_core_hardness_hv": 241,
            "max_core_hardness_hv": 361,
            "proof_load_kn": 27.0,
        }
    )
    env = fixtures.setup_tested_lot(
        unplated=True,
        spec_overrides=spec_overrides,
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.020,
        min_measured_core_hardness_hv=310.0,
        proof_load_failures=0,
        tensile_failures=0,
        lot_overrides={"lot_code": "L-2611"},
    )
    assert env["lot_test"]["result"] == "ACCEPT", (
        f"Zero failures must accept, got {env['lot_test']['result']}"
    )
    lot_before = fixtures.read_lot(env["lot"]["id"])
    assert lot_before["achieved_strength_class"] == "CLASS_10_9", (
        "310 HV misses the GRADE_5 band 241-302, so the fixed scan order awards "
        f"CLASS_10_9, got {lot_before['achieved_strength_class']}"
    )
    assert lot_before["process_state"] == "TESTED", (
        f"Expected the lot in TESTED before the draft, got {lot_before['process_state']}"
    )

    resp = api_client.create_certification_document(
        {
            "production_lot_id": env["lot"]["id"],
            "lot_test_id": env["lot_test"]["id"],
            "cert_serial": "CERT-0011",
            "expected_production_lot_version": lot_before["version"],
        },
        make_inspector_headers("insp-1"),
    )
    validate_error(resp, ApiErrorId.ERR_STRENGTH_CLASS_NOT_ACHIEVED.value)

    certs, pagination = validate_paginated(
        api_client.list_certification_documents(
            make_inspector_headers("insp-1"),
            params={"production_lot_id": env["lot"]["id"]},
        )
    )
    assert pagination["total_count"] == 0, (
        f"The refused draft must persist nothing, got total_count {pagination['total_count']}"
    )
    assert certs == [], f"Expected no certificate rows, got {certs}"

    lot_after = fixtures.read_lot(env["lot"]["id"])
    assert lot_after["process_state"] == "TESTED", (
        f"Expected the lot to stay TESTED, got {lot_after['process_state']}"
    )
    assert lot_after["version"] == lot_before["version"], (
        f"Expected the lot version to stay {lot_before['version']} after a refused "
        f"draft, got {lot_after['version']}"
    )


class TestPackCountTolerance:
    """A nominal pack of 100 at a tolerance of 0.02 admits exactly two pieces of drift."""

    def test_a_pack_three_pieces_over_nominal_cannot_seal(self):
        """Declaring 103 pieces against a two-piece tolerance is refused at the seal.

        PRD: "`count_tolerance_pieces` is the part's `nominal_pack_count` multiplied by its `count_tolerance_pct`, truncated downward to a whole number of pieces — so a nominal pack of 500 at a `count_tolerance_pct` of 0.02 tolerates 10 pieces of deviation, and a nominal pack of 40 at the same tolerance tolerates none at all, because 0.8 of a piece truncates downward to 0."

        PRD: "The pack must be `OPEN`, the lot must be in `process_state` `CERTIFIED` or already `PACKED` with `disposition` `IN_PROCESS`, the pack's `declared_count` must sit within `count_tolerance_pieces` of the part's `nominal_pack_count` in either direction — a deviation larger than the tolerance in absolute terms is refused with `ERR_PACK_COUNT_OUT_OF_TOLERANCE` — and `declared_count` may not exceed the lot's `available_count`, or the seal is refused with `ERR_PIECE_COUNT_INVALID`."

        Design: Corner/calculations/pack_count_tolerance_is_two_pieces_and_seal_updates_the_ledger
        """
        env = fixtures.setup_certified_lot(
            unplated=True,
            spec_overrides=dict(UNPLATED_SPEC),
            core_hardness_hv=330.0,
            surface_decarb_depth_mm=0.020,
            min_measured_core_hardness_hv=322.0,
            lot_overrides={"lot_code": "L-2601"},
            cert_serial="CERT-0001",
        )
        pack = fixtures.open_pack(
            env["lot"]["id"],
            env["certificate"]["id"],
            label_serial="PK-0001",
            actual_count=103,
            label_fields_complete=True,
        )
        assert pack["count_tolerance_pieces"] == 2, (
            "floor(100 * 0.02) is 2, got count_tolerance_pieces "
            f"{pack['count_tolerance_pieces']}"
        )
        assert pack["declared_count"] == 103, (
            "A BY_COUNT pack copies actual_count verbatim, expected 103, got "
            f"{pack['declared_count']}"
        )

        lot_before = fixtures.read_lot(env["lot"]["id"])
        resp = api_client.seal_pack_unit(pack["id"], make_clerk_headers("ship-1"))
        validate_error(resp, ApiErrorId.ERR_PACK_COUNT_OUT_OF_TOLERANCE.value)

        after = fixtures.read_pack_unit(pack["id"])
        assert after["status"] == "OPEN", (
            f"The refused seal must leave the pack OPEN, got {after['status']}"
        )
        assert after["sealed_at"] is None, (
            f"Expected sealed_at empty after a refused seal, got {after['sealed_at']}"
        )
        lot_after = fixtures.read_lot(env["lot"]["id"])
        assert lot_after["packed_count"] == lot_before["packed_count"], (
            "The refused seal moves no pieces, expected packed_count "
            f"{lot_before['packed_count']}, got {lot_after['packed_count']}"
        )
        assert lot_after["available_count"] == lot_before["available_count"], (
            "The refused seal moves no pieces, expected available_count "
            f"{lot_before['available_count']}, got {lot_after['available_count']}"
        )
        assert lot_after["process_state"] == "CERTIFIED", (
            f"Expected the lot to stay CERTIFIED, got {lot_after['process_state']}"
        )

    def test_a_pack_exactly_at_tolerance_seals_and_moves_its_declared_count(self):
        """Declaring 102 pieces sits exactly at tolerance and moves 102, not the nominal 100.

        PRD: "`declared_count`, the number printed on the label, is `actual_count` verbatim for a `BY_COUNT` pack, and for a `BY_WEIGHT` pack it is the pack's own `net_weight_kg` multiplied by the part's `pieces_per_kg`, rounded half up to a whole piece."

        PRD: "On success the pack moves `OPEN → SEALED`, `sealed_at` is stamped from the logical clock, the lot's `packed_count` grows by `declared_count` while its `available_count` shrinks by the same amount, the lot moves `CERTIFIED → PACKED`, and the pack's `version` and the lot's `version` each increment by 1."

        Design: Corner/calculations/pack_count_tolerance_is_two_pieces_and_seal_updates_the_ledger
        """
        env = fixtures.setup_certified_lot(
            unplated=True,
            spec_overrides=dict(UNPLATED_SPEC),
            core_hardness_hv=330.0,
            surface_decarb_depth_mm=0.020,
            min_measured_core_hardness_hv=322.0,
            lot_overrides={"lot_code": "L-2601"},
            cert_serial="CERT-0001",
        )
        lot_before = fixtures.read_lot(env["lot"]["id"])
        assert lot_before["available_count"] == 4780, (
            "4850 pieces less the 70-piece destructive sample leaves 4780, got "
            f"{lot_before['available_count']}"
        )

        pack = fixtures.open_pack(
            env["lot"]["id"],
            env["certificate"]["id"],
            label_serial="PK-0002",
            actual_count=102,
            label_fields_complete=True,
        )
        assert pack["count_tolerance_pieces"] == 2, (
            f"floor(100 * 0.02) is 2, got {pack['count_tolerance_pieces']}"
        )
        assert pack["declared_count"] == 102, (
            f"Expected declared_count 102, got {pack['declared_count']}"
        )

        sealed = validate_success(
            api_client.seal_pack_unit(pack["id"], make_clerk_headers("ship-1"))
        )
        assert sealed["status"] == "SEALED", (
            f"A deviation exactly at tolerance seals, got {sealed['status']}"
        )
        assert sealed["sealed_at"] is not None, "sealed_at must be stamped on the seal"
        assert sealed["version"] == pack["version"] + 1, (
            f"Expected the pack version to advance to {pack['version'] + 1}, got "
            f"{sealed['version']}"
        )

        lot_after = fixtures.read_lot(env["lot"]["id"])
        assert lot_after["packed_count"] == 102, (
            f"The declared 102 is what moves, not the nominal 100; got packed_count "
            f"{lot_after['packed_count']}"
        )
        assert lot_after["available_count"] == 4678, (
            f"Expected available_count 4780 - 102 = 4678, got {lot_after['available_count']}"
        )
        assert lot_after["process_state"] == "PACKED", (
            f"Expected the lot in PACKED after the seal, got {lot_after['process_state']}"
        )
        assert lot_after["version"] == lot_before["version"] + 1, (
            f"Expected the lot version to advance to {lot_before['version'] + 1}, got "
            f"{lot_after['version']}"
        )
        assert_lot_piece_ledger(lot_after)


def test_traceability_projection_replays_the_snapshot_not_the_live_tool_counter():
    """A second lot on the same die moves the live counter; the projection does not follow.

    PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

    PRD: "The certificate's `traceability_chain` is a frozen provenance object projected at draft time (and re-projected on reissue), and the same projection is available as a computed read on the lot itself even before any certificate exists."

    PRD: "It gathers, from the lot's steel heat, the `heat_number`, `mill_code`, `mill_cert_serial` and current `cert_status`; from the lot's wire lot, the drawing reduction — exposed in the projection as `wire_lot_reduction_pct` — and the `lubricant_coating`; from the lot's die set, the `tool_code` and its regrind count, exposed as `tool_regrind_count`; from the lot itself, `tool_utilization_pct` and `pinned_part_spec_version`; from the governing heat treatment run, the `austenitize_temp_c`, `core_hardness_hv` and `total_decarb_depth_mm`; and from the governing plating run, the `bake_delay_hours` and `bake_duration_min`."

    PRD: "Every value is copied as stored, with no re-rounding at projection time."

    Design: Corner/calculations/traceability_projection_replays_the_snapshot_not_the_live_tool_counter
    """
    env = fixtures.setup_tested_lot(
        unplated=True,
        spec_overrides=dict(UNPLATED_SPEC),
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.020,
        min_measured_core_hardness_hv=322.0,
        booking_overrides={"austenitize_temp_c": 870.0},
        lot_overrides={
            "lot_code": "L-2601",
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T08:00:00Z",
        },
    )
    first = fixtures.read_lot(env["lot"]["id"])
    assert first["tool_utilization_pct"] == pytest.approx(4.13, abs=0.001), (
        "4960 pieces against a 120000-piece derated budget snapshots 4.13, got "
        f"{first['tool_utilization_pct']}"
    )

    second = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2602",
        planned_pieces=5000,
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
    )
    second = fixtures.report_heading(second["id"], 4900, 60)

    tool = fixtures.read_tool(env["tool"]["id"])
    assert tool["cumulative_pieces_current_cycle"] == 9920, (
        "Two lots of 4960 pieces each must leave the open cycle at 9920, got "
        f"{tool['cumulative_pieces_current_cycle']}"
    )
    assert second["tool_utilization_pct"] == pytest.approx(8.27, abs=0.001), (
        "The second lot snapshots 9920 / 120000 as 8.27, got "
        f"{second['tool_utilization_pct']}"
    )

    payload = validate_success(
        api_client.get_lot_traceability(env["lot"]["id"], fixtures.MANAGER)
    )
    chain = payload.get("traceability_chain", payload)
    assert_traceability_projection(chain)

    assert chain["tool_utilization_pct"] == pytest.approx(4.13, abs=0.001), (
        "The projection replays the first lot's own snapshot of 4.13, not the live "
        f"8.27 the die's 9920 pieces now imply; got {chain['tool_utilization_pct']}"
    )
    assert chain["tool_code"] == "DIE-4S-001", (
        f"Expected tool_code DIE-4S-001, got {chain['tool_code']}"
    )
    assert chain["tool_regrind_count"] == 0, (
        f"The die has never been reground, expected 0, got {chain['tool_regrind_count']}"
    )
    assert chain["heat_number"] == "H-77410", (
        f"Expected heat_number H-77410, got {chain['heat_number']}"
    )
    assert chain["mill_code"] == "MC-A", f"Expected mill_code MC-A, got {chain['mill_code']}"
    assert chain["mill_cert_serial"] == "MC-2026-000481", (
        f"Expected mill_cert_serial MC-2026-000481, got {chain['mill_cert_serial']}"
    )
    assert chain["cert_status"] == "VERIFIED", (
        f"Expected the heat's current cert_status VERIFIED, got {chain['cert_status']}"
    )
    assert chain["wire_lot_reduction_pct"] == pytest.approx(27.75, abs=0.001), (
        "8.00 -> 6.80 mm stores 27.75 and is copied as stored, got "
        f"{chain['wire_lot_reduction_pct']}"
    )
    assert chain["lubricant_coating"] == "PHOSPHATE", (
        f"Expected lubricant_coating PHOSPHATE, got {chain['lubricant_coating']}"
    )
    assert chain["austenitize_temp_c"] == pytest.approx(870.0, abs=0.001), (
        f"Expected austenitize_temp_c 870 from the PASS run, got {chain['austenitize_temp_c']}"
    )
    assert chain["core_hardness_hv"] == pytest.approx(330.0, abs=0.001), (
        f"Expected core_hardness_hv 330.0 from the PASS run, got {chain['core_hardness_hv']}"
    )
    assert chain["total_decarb_depth_mm"] == pytest.approx(0.020, abs=0.0005), (
        f"Expected total_decarb_depth_mm 0.020, got {chain['total_decarb_depth_mm']}"
    )
    assert chain["bake_delay_hours"] is None, (
        "An unplated part has no plating run, so the bake contribution is empty; got "
        f"{chain['bake_delay_hours']}"
    )
    assert chain["bake_duration_min"] is None, (
        "An unplated part has no plating run, so the bake contribution is empty; got "
        f"{chain['bake_duration_min']}"
    )
    assert chain["pinned_part_spec_version"] == 1, (
        f"Expected pinned_part_spec_version 1, got {chain['pinned_part_spec_version']}"
    )
