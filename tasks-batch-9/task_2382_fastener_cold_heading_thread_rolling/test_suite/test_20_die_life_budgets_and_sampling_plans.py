"""The two die-life budgets and the two sampling-plan severities.

One physical die set carries both a nameplate budget derated for regrinds and a
conservative budget that listens to the cycles it has actually achieved, and PRD
§3.4 makes the part's ``qualification_program`` pick which one the lot-opening
capacity gate spends. The same doubling appears at the far end of the route: PRD
§3.7 derives a sampling plan whose ``sample_size`` and ``acceptance_number``
depend on the severity the lot's ``risk_score_pre_test`` selects, so an identical
measured failure count can accept one lot and reject its sibling. This module
exercises both branches head to head.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_heading_tool,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    create_production_lot_payload,
    fixtures,
    validate_error,
    validate_success,
)

# ---------------------------------------------------------------------------
# Scenario builders
# ---------------------------------------------------------------------------

AUTO_SPEC = {
    "part_number": "SM-AUTO",
    "thread_designation": "M4x0.7",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 2.0,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.150,
    "plating_spec": "ZINC_CLEAR",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 1000,
    "pieces_per_kg": 500.0,
    "proof_load_kn": 12.0,
}

AERO_SPEC = {
    "part_number": "SM-AERO",
    "thread_designation": "M4x0.7",
    "strength_class": "CLASS_12_9",
    "qualification_program": "AEROSPACE_NADCAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 2.0,
    "station_count_required": 4,
    "thread_timing": "AFTER_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL"],
    "min_core_hardness_hv": 366,
    "max_core_hardness_hv": 414,
    "max_decarb_depth_mm": 0.100,
    "plating_spec": "NONE",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 1000,
    "pieces_per_kg": 500.0,
    "proof_load_kn": 45.0,
}

SAMPLING_SPEC = {
    "part_number": "HX-M8-109",
    "thread_designation": "M8x1.25",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 20.0,
    "station_count_required": 4,
    "thread_timing": "BEFORE_HEAT_TREAT",
    "required_secondary_ops": ["THREAD_ROLL", "POINT"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.150,
    "plating_spec": "ZINC_CLEAR",
    "packaging_mode": "BY_WEIGHT",
    "nominal_pack_count": 500,
    "pieces_per_kg": 62.5,
    "proof_load_kn": 34.7,
}


def _reground_tool_with_two_programmes():
    """A die set with one short closed cycle, plus an automotive and an aerospace part.

    Nameplate 40000 pieces; one 12000-piece cycle closed by an early condemnation
    and a regrind. That leaves ``rated_derated_life_pieces`` at 34000 and
    ``conservative_life_pieces`` at 10800 — the two budgets a lot-opening call may
    be measured against. The 200.0 kg wire lot has 176.0 kg free once the burn-in
    lot's reservation has settled.
    """
    fixtures.set_clock("2026-09-01T06:00:00Z")
    spec_auto = fixtures.register_part_spec(**AUTO_SPEC)
    spec_aero = fixtures.register_part_spec(**AERO_SPEC)
    heat = fixtures.create_verified_heat(gross_mass_kg=200.0)
    wire = fixtures.create_released_wire_lot(heat["id"], gross_mass_kg=200.0)
    tool = fixtures.create_mounted_tool(
        tool_code="DIE-4S-002", station_count=4, rated_life_pieces=40000
    )
    burn_in = fixtures.open_production_lot(
        spec_auto["id"],
        wire["id"],
        tool["id"],
        lot_code="L-BURNIN",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T08:00:00Z",
        planned_pieces=12000,
    )
    fixtures.report_heading(burn_in["id"], 11900, 100)
    fixtures.condemn_tool(tool["id"], reason="CHIPPED_STATION_3")
    fixtures.regrind_tool(tool["id"])
    tool = fixtures.mount_tool(tool["id"], "PRESS-3")
    return {
        "spec_auto": spec_auto,
        "spec_aero": spec_aero,
        "heat": heat,
        "wire": wire,
        "tool": tool,
        "burn_in_lot": fixtures.read_lot(burn_in["id"]),
    }


def _open_lot_response(env, spec, lot_code, start_at, end_at, planned_pieces, headers):
    """POST /production-lots for the shared die set, echoing the wire lot's live version."""
    payload = create_production_lot_payload(
        spec["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        fixtures.wire_lot_version(env["wire"]["id"]),
        lot_code=lot_code,
        press_code="PRESS-3",
        press_window_start_at=start_at,
        press_window_end_at=end_at,
        planned_pieces=planned_pieces,
    )
    return api_client.create_production_lot(payload, headers)


def _two_lots_baked_at_diverging_risk():
    """Two lots of one part, both holding 9740 available pieces, at 28.33 and 43.32 risk.

    The lots are identical apart from two inputs the pre-test score reads: the
    measured surface decarburization (0.100 mm against 0.150 mm) and the relief
    bake delay (3.0 hours against 3.5 hours).
    """
    fixtures.set_clock("2026-09-01T06:00:00Z")
    spec = fixtures.register_part_spec(**SAMPLING_SPEC)
    heat = fixtures.create_verified_heat(gross_mass_kg=500.0)
    wire = fixtures.create_released_wire_lot(heat["id"], gross_mass_kg=500.0)
    tool = fixtures.create_mounted_tool(
        tool_code="DIE-4S-001", station_count=4, rated_life_pieces=120000
    )
    furnace_a = fixtures.register_furnace(furnace_code="FCE-1", max_charge_mass_kg=400.0)
    furnace_b = fixtures.register_furnace(furnace_code="FCE-2", max_charge_mass_kg=400.0)

    lot_a = fixtures.open_production_lot(
        spec["id"],
        wire["id"],
        tool["id"],
        lot_code="L-2601",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
        planned_pieces=10000,
    )
    lot_b = fixtures.open_production_lot(
        spec["id"],
        wire["id"],
        tool["id"],
        lot_code="L-2602",
        press_code="PRESS-3",
        press_window_start_at="2026-09-01T10:00:00Z",
        press_window_end_at="2026-09-01T14:00:00Z",
        planned_pieces=10000,
    )

    fixtures.report_heading(lot_a["id"], 9800, 150)
    fixtures.report_heading(lot_b["id"], 9800, 150)

    for lot in (lot_a, lot_b):
        fixtures.run_secondary_op(
            lot["id"],
            op_type="THREAD_ROLL",
            sequence_no=1,
            pieces_out=9750,
            machine_code="TR-1",
        )
        fixtures.run_secondary_op(
            lot["id"],
            op_type="POINT",
            sequence_no=2,
            pieces_out=9740,
            machine_code="PT-1",
        )

    booking = {
        "window_start_at": "2026-09-01T18:00:00Z",
        "window_end_at": "2026-09-01T23:00:00Z",
        "austenitize_temp_c": 870.0,
        "quench_medium": "OIL",
        "temper_temp_c": 420.0,
        "temper_time_min": 60,
        "carbon_potential_pct": 0.42,
    }
    ht_a = fixtures.book_heat_treat(lot_a["id"], furnace_a["id"], **booking)
    ht_b = fixtures.book_heat_treat(lot_b["id"], furnace_b["id"], **booking)
    fixtures.start_heat_treat(ht_a["id"], at="2026-09-01T19:00:00Z")
    fixtures.start_heat_treat(ht_b["id"])
    fixtures.record_heat_treat_results(
        ht_a["id"],
        at="2026-09-01T22:00:00Z",
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.100,
    )
    fixtures.record_heat_treat_results(
        ht_b["id"], core_hardness_hv=330.0, surface_decarb_depth_mm=0.150
    )

    plate_a = fixtures.schedule_plating(lot_a["id"])
    plate_b = fixtures.schedule_plating(lot_b["id"])
    fixtures.complete_plating(plate_a["id"], at="2026-09-02T02:00:00Z")
    fixtures.complete_plating(plate_b["id"])
    fixtures.start_bake(
        plate_a["id"],
        at="2026-09-02T05:00:00Z",
        bake_temp_c=210.0,
        bake_duration_min=240,
    )
    fixtures.start_bake(
        plate_b["id"],
        at="2026-09-02T05:30:00Z",
        bake_temp_c=210.0,
        bake_duration_min=240,
    )
    fixtures.complete_bake(plate_a["id"], at="2026-09-02T10:00:00Z")
    fixtures.complete_bake(plate_b["id"])

    return {
        "spec": spec,
        "heat": heat,
        "wire": wire,
        "tool": tool,
        "lot_a": fixtures.read_lot(lot_a["id"]),
        "lot_b": fixtures.read_lot(lot_b["id"]),
    }


# ---------------------------------------------------------------------------
# Instance: tool_life_budget_rated_derated_vs_conservative_observed
# ---------------------------------------------------------------------------
class TestTwoDieLifeBudgets:
    """One reground die set offers two different budgets for the same planned run."""

    def test_regrind_recomputes_both_budgets_from_the_closed_cycle(self):
        """A 40000-piece set whose one closed cycle ran 12000 pieces derates to 34000 but budgets conservatively at 10800.

        PRD: "When `regrind_count` is still below `max_regrinds`, the set goes `WORN → AVAILABLE`: the open cycle's `cumulative_pieces_current_cycle` is appended to `cycle_pieces_history`, `completed_cycle_count` and `regrind_count` each increment by 1, `cumulative_pieces_current_cycle` resets to zero, `observed_avg_cycle_pieces`, `rated_derated_life_pieces` and `conservative_life_pieces` are all recomputed, `condemn_reason` is cleared, and the set's `version` increments by 1 — closing the cycle `AVAILABLE → MOUNTED → WORN → AVAILABLE`."

        PRD: "`rated_derated_life_pieces` is the nameplate `rated_life_pieces` multiplied by one minus 0.15 for each completed regrind — that is, by one minus the product of `regrind_count` and 0.15 — with the result truncated downward to a whole number of pieces."

        PRD: "Once at least one cycle has closed, `observed_avg_cycle_pieces` is the sum of every entry in `cycle_pieces_history` divided by `completed_cycle_count`, rounded half up to two decimal places, and `conservative_life_pieces` is the smaller of `rated_derated_life_pieces` and 0.90 multiplied by `observed_avg_cycle_pieces`, truncated downward to a whole number of pieces."

        Design: Difficulty/dual_variant_calc/tool_life_budget_rated_derated_vs_conservative_observed
        """
        env = _reground_tool_with_two_programmes()
        tool = fixtures.read_tool(env["tool"]["id"])

        assert tool["regrind_count"] == 1, (
            f"Expected 1 regrind behind the set, got {tool['regrind_count']}"
        )
        assert tool["cycle_pieces_history"] == [12000], (
            f"Expected the 12000-piece cycle appended, got {tool['cycle_pieces_history']}"
        )
        assert tool["completed_cycle_count"] == 1, (
            f"Expected 1 closed cycle, got {tool['completed_cycle_count']}"
        )
        assert tool["cumulative_pieces_current_cycle"] == 0, (
            "The regrind resets the open cycle, got "
            f"{tool['cumulative_pieces_current_cycle']}"
        )
        assert tool["observed_avg_cycle_pieces"] == pytest.approx(12000.00, abs=0.001), (
            f"Expected observed_avg_cycle_pieces 12000.00, got "
            f"{tool['observed_avg_cycle_pieces']}"
        )
        assert tool["rated_derated_life_pieces"] == 34000, (
            "40000 nameplate derated by 0.15 for one regrind is 34000, got "
            f"{tool['rated_derated_life_pieces']}"
        )
        assert tool["conservative_life_pieces"] == 10800, (
            "0.90 of a 12000-piece observed average truncates to 10800, got "
            f"{tool['conservative_life_pieces']}"
        )
        assert tool["status"] == "MOUNTED", (
            f"The set was remounted after the regrind, got {tool['status']}"
        )
        assert_heading_tool(tool)

    def test_automotive_lot_is_admitted_against_the_rated_derated_budget(self, engineer_headers):
        """An AUTOMOTIVE_PPAP lot of 20000 pieces fits the 34000-piece derated budget and reserves 42.0 kg of wire.

        PRD: "The demand is the planned output inflated by the scrap allowance — `planned_pieces` multiplied by one plus the part's `scrap_allowance_pct`, raised upward to the next whole piece."

        PRD: "For a part whose `qualification_program` is `NONE` or `AUTOMOTIVE_PPAP`, the applicable budget is `rated_derated_life_pieces`, and the tool's observed history is ignored entirely — a set whose real cycles ran short still offers its full nameplate minus the regrind derate."

        PRD: "On success, that amount is subtracted from `available_mass_kg`, added to `reserved_mass_kg`, and stored on the lot as `wire_reserved_kg`; the wire lot's `version` increments by 1."

        Design: Difficulty/dual_variant_calc/tool_life_budget_rated_derated_vs_conservative_observed
        """
        env = _reground_tool_with_two_programmes()
        wire_before = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_before["available_mass_kg"] == pytest.approx(176.0, abs=0.001), (
            "The burn-in lot leaves 176.0 kg free, got "
            f"{wire_before['available_mass_kg']}"
        )

        response = _open_lot_response(
            env,
            env["spec_auto"],
            "L-AUTO-1",
            "2026-09-01T09:00:00Z",
            "2026-09-01T12:00:00Z",
            20000,
            engineer_headers,
        )
        lot = validate_success(response, 201)

        assert lot["process_state"] == "SETUP", (
            f"A freshly opened lot is in SETUP, got {lot['process_state']}"
        )
        assert lot["wire_reserved_kg"] == pytest.approx(42.0, abs=0.001), (
            "20000 pieces at 2.0 g inflated by the 0.05 allowance reserves 42.0 kg, got "
            f"{lot['wire_reserved_kg']}"
        )

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["available_mass_kg"] == pytest.approx(134.0, abs=0.001), (
            f"Expected 134.0 kg free after the reservation, got "
            f"{wire_after['available_mass_kg']}"
        )
        assert wire_after["reserved_mass_kg"] == pytest.approx(42.0, abs=0.001), (
            f"Expected 42.0 kg reserved, got {wire_after['reserved_mass_kg']}"
        )
        assert wire_after["consumed_mass_kg"] == pytest.approx(24.0, abs=0.001), (
            "The burn-in lot burned 24.0 kg into blanks, got "
            f"{wire_after['consumed_mass_kg']}"
        )
        assert wire_after["version"] == wire_before["version"] + 1, (
            f"Expected the wire lot version to advance to "
            f"{wire_before['version'] + 1}, got {wire_after['version']}"
        )
        assert_wire_mass_ledger(wire_after)

    def test_aerospace_lot_of_the_same_size_is_refused_by_the_conservative_budget(self, engineer_headers):
        """The same die set that just admitted a 20000-piece automotive lot refuses an identically sized aerospace one.

        PRD: "For a part whose `qualification_program` is `AEROSPACE_NADCAP`, the applicable budget is `conservative_life_pieces`, the smaller of the derated nameplate and 0.90 multiplied by the observed cycle average."

        PRD: "Where a history of short cycles exists the aerospace budget is strictly smaller, so the same die set will accept an automotive lot and refuse an identically sized aerospace one."

        PRD: "If the demand exceeds the remaining life, the request is refused with `ERR_TOOL_LIFE_EXHAUSTED`."

        Design: Difficulty/dual_variant_calc/tool_life_budget_rated_derated_vs_conservative_observed
        """
        env = _reground_tool_with_two_programmes()

        accepted = validate_success(
            _open_lot_response(
                env,
                env["spec_auto"],
                "L-AUTO-1",
                "2026-09-01T09:00:00Z",
                "2026-09-01T12:00:00Z",
                20000,
                engineer_headers,
            ),
            201,
        )
        assert accepted["planned_pieces"] == 20000, (
            f"Expected a 20000-piece automotive run, got {accepted['planned_pieces']}"
        )

        refused = _open_lot_response(
            env,
            env["spec_aero"],
            "L-AERO-1",
            "2026-09-01T13:00:00Z",
            "2026-09-01T16:00:00Z",
            20000,
            engineer_headers,
        )
        validate_error(refused, ApiErrorId.ERR_TOOL_LIFE_EXHAUSTED.value)

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["available_mass_kg"] == pytest.approx(134.0, abs=0.001), (
            "The refused aerospace lot must reserve nothing, got "
            f"{wire_after['available_mass_kg']} kg free"
        )
        assert wire_after["reserved_mass_kg"] == pytest.approx(42.0, abs=0.001), (
            "Only the automotive lot holds a reservation, got "
            f"{wire_after['reserved_mass_kg']} kg reserved"
        )
        assert wire_after["consumed_mass_kg"] == pytest.approx(24.0, abs=0.001), (
            f"Expected 24.0 kg consumed, got {wire_after['consumed_mass_kg']}"
        )
        assert_wire_mass_ledger(wire_after)

        tool_after = fixtures.read_tool(env["tool"]["id"])
        assert tool_after["cumulative_pieces_current_cycle"] == 0, (
            "Neither lot has been headed yet, got "
            f"{tool_after['cumulative_pieces_current_cycle']}"
        )


# ---------------------------------------------------------------------------
# Instance: sampling_plan_normal_accepts_where_tightened_rejects
# ---------------------------------------------------------------------------
class TestTwoSamplingPlanSeverities:
    """One measured failure accepts the normal-inspection lot and rejects the tightened one."""

    def test_pre_test_risk_score_selects_the_severity_frozen_on_each_lot(self, inspector_headers):
        """Sibling lots scoring 28.33 and 43.32 freeze NORMAL and TIGHTENED respectively.

        PRD: "The score is 0.30 multiplied by the heat term, plus 0.20 multiplied by the tool term, plus 0.25 multiplied by the bake term, plus 0.25 multiplied by the decarburization term, with the sum rounded half up to two decimal places exactly once at the end — the individual weighted terms are never rounded on their own."

        PRD: "Severity is `TIGHTENED` when either of two things is true: the lot's `risk_score_pre_test` is at least 40.0, or a rejected test already exists anywhere in the plant on a production lot sharing both the same `part_spec_id` and the same `traceability_heat_id` as this lot."

        PRD: "The chosen severity is copied onto the test as `severity` and simultaneously frozen onto the lot as `inspection_severity`; later movement in the lot's risk score never re-derives it, and it is always the pass-one score that feeds the decision."

        Design: Difficulty/dual_variant_calc/sampling_plan_normal_accepts_where_tightened_rejects
        """
        env = _two_lots_baked_at_diverging_risk()
        lot_a, lot_b = env["lot_a"], env["lot_b"]

        assert lot_a["risk_score_pre_test"] == pytest.approx(28.33, abs=0.001), (
            f"Expected a pre-test score of 28.33 for L-2601, got "
            f"{lot_a['risk_score_pre_test']}"
        )
        assert lot_b["risk_score_pre_test"] == pytest.approx(43.32, abs=0.001), (
            f"Expected a pre-test score of 43.32 for L-2602, got "
            f"{lot_b['risk_score_pre_test']}"
        )
        assert lot_a["available_count"] == 9740, (
            f"Expected 9740 available pieces on L-2601, got {lot_a['available_count']}"
        )
        assert lot_b["available_count"] == 9740, (
            f"Expected 9740 available pieces on L-2602, got {lot_b['available_count']}"
        )

        test_a = validate_success(
            api_client.create_lot_test({"production_lot_id": lot_a["id"]}, inspector_headers),
            201,
        )
        test_b = validate_success(
            api_client.create_lot_test({"production_lot_id": lot_b["id"]}, inspector_headers),
            201,
        )

        assert test_a["severity"] == "NORMAL", (
            "A pre-test score below 40.0 selects normal inspection, got "
            f"{test_a['severity']}"
        )
        assert test_b["severity"] == "TIGHTENED", (
            "A pre-test score of at least 40.0 selects tightened inspection, got "
            f"{test_b['severity']}"
        )

        assert fixtures.read_lot(lot_a["id"])["inspection_severity"] == "NORMAL", (
            "The chosen severity is frozen onto the lot as inspection_severity"
        )
        assert fixtures.read_lot(lot_b["id"])["inspection_severity"] == "TIGHTENED", (
            "The chosen severity is frozen onto the lot as inspection_severity"
        )

    def test_normal_plan_draws_99_pieces_and_accepts_one_failure(self, inspector_headers):
        """Under normal inspection a 9740-piece lot is sampled 99 deep with an acceptance number of 1, so one failure accepts.

        PRD: "Under **normal inspection**, `sample_size` is the greater of 8 and the square root of the lot's `available_count` raised upward to the next whole piece, and `acceptance_number` is 1 when that `sample_size` is at least 20 and 0 otherwise — so a single failure is tolerated on any lot holding 400 or more available pieces, and a lot holding fewer than 8 available pieces cannot be sampled at all."

        PRD: "The test's `destructive` flag defaults to true and the create payload offers no way to change it, so the sample is consumed: when `destructive` is true, the lot's `destructive_test_count` grows by `sample_size` and its `available_count` shrinks by the same amount, keeping the piece ledger balanced."

        PRD: "On `ACCEPT` the test moves `PENDING → ACCEPT`, the lot's `achieved_strength_class` is derived, `risk_score_final` is computed, and the lot moves `TESTING → TESTED`."

        Design: Difficulty/dual_variant_calc/sampling_plan_normal_accepts_where_tightened_rejects
        """
        env = _two_lots_baked_at_diverging_risk()
        lot_a, lot_b = env["lot_a"], env["lot_b"]

        test_a = validate_success(
            api_client.create_lot_test({"production_lot_id": lot_a["id"]}, inspector_headers),
            201,
        )
        validate_success(
            api_client.create_lot_test({"production_lot_id": lot_b["id"]}, inspector_headers),
            201,
        )

        assert test_a["severity"] == "NORMAL", (
            f"Expected the normal plan for L-2601, got {test_a['severity']}"
        )
        assert test_a["sample_size"] == 99, (
            "The square root of 9740 raised upward is 99, got "
            f"{test_a['sample_size']}"
        )
        assert test_a["acceptance_number"] == 1, (
            "A sample of 99 pieces is at least 20, so one failure is tolerated, got "
            f"acceptance_number {test_a['acceptance_number']}"
        )
        assert test_a["result"] == "PENDING", (
            f"A new test starts PENDING, got {test_a['result']}"
        )

        sampled = fixtures.read_lot(lot_a["id"])
        assert sampled["destructive_test_count"] == 99, (
            "The destructive sample consumes 99 pieces, got "
            f"{sampled['destructive_test_count']}"
        )
        assert sampled["available_count"] == 9641, (
            f"Expected 9740 - 99 = 9641 available pieces, got {sampled['available_count']}"
        )
        assert sampled["process_state"] == "TESTING", (
            f"Opening the test moves the lot to TESTING, got {sampled['process_state']}"
        )
        assert_lot_piece_ledger(sampled)

        closed = validate_success(
            api_client.record_lot_test_results(
                test_a["id"],
                {
                    "proof_load_failures": 0,
                    "tensile_failures": 1,
                    "min_measured_core_hardness_hv": 322.0,
                },
                inspector_headers,
            )
        )
        assert closed["total_failures"] == 1, (
            f"Expected one counted failure, got {closed['total_failures']}"
        )
        assert closed["result"] == "ACCEPT", (
            "One failure against an acceptance number of 1 accepts the lot, got "
            f"{closed['result']}"
        )

        tested = fixtures.read_lot(lot_a["id"])
        assert tested["process_state"] == "TESTED", (
            f"An accepted lot moves TESTING -> TESTED, got {tested['process_state']}"
        )
        assert tested["disposition"] == "IN_PROCESS", (
            f"An accepted lot stays IN_PROCESS, got {tested['disposition']}"
        )
        assert tested["hold_source"] == "NONE", (
            f"An accepted lot carries no hold tag, got {tested['hold_source']}"
        )
        assert tested["risk_score_final"] == pytest.approx(40.83, abs=0.001), (
            "28.33 plus 12.5 for the single failure is 40.83, got "
            f"{tested['risk_score_final']}"
        )
        assert_lot_piece_ledger(tested)

    def test_tightened_plan_draws_149_pieces_and_rejects_the_same_one_failure(self, inspector_headers):
        """Under tightened inspection the sibling lot is sampled 149 deep with an acceptance number of 0, so the identical single failure rejects.

        PRD: "Under **tightened inspection**, `sample_size` is the greater of 13 and 1.5 multiplied by the square root of `available_count`, raised upward to the next whole piece, and `acceptance_number` is 0 unconditionally — the very same measured failure count that accepts a lot under normal inspection rejects it under tightened inspection, and the sampling floor of 13 pieces is itself out of reach for a nearly exhausted lot."

        PRD: "The verdict is a straight comparison against the frozen plan: `ACCEPT` when `total_failures` is at most `acceptance_number`, and `REJECT` when it is greater."

        PRD: "On `REJECT` the test moves `PENDING → REJECT`, `risk_score_final` is still computed, the lot's `disposition` moves to `HOLD` with `hold_source` of `TEST_REJECT`, and the lot's `process_state` stays at `TESTING` — which is exactly why a certificate drafted after a retest can still be pointing at the first, rejected test."

        Design: Difficulty/dual_variant_calc/sampling_plan_normal_accepts_where_tightened_rejects
        """
        env = _two_lots_baked_at_diverging_risk()
        lot_a, lot_b = env["lot_a"], env["lot_b"]

        test_a = validate_success(
            api_client.create_lot_test({"production_lot_id": lot_a["id"]}, inspector_headers),
            201,
        )
        test_b = validate_success(
            api_client.create_lot_test({"production_lot_id": lot_b["id"]}, inspector_headers),
            201,
        )

        assert test_b["severity"] == "TIGHTENED", (
            f"Expected the tightened plan for L-2602, got {test_b['severity']}"
        )
        assert test_b["sample_size"] == 149, (
            "1.5 times the square root of 9740 raised upward is 149, got "
            f"{test_b['sample_size']}"
        )
        assert test_b["acceptance_number"] == 0, (
            "Tightened inspection tolerates no failure at all, got acceptance_number "
            f"{test_b['acceptance_number']}"
        )

        sampled = fixtures.read_lot(lot_b["id"])
        assert sampled["destructive_test_count"] == 149, (
            "The tightened sample consumes 149 pieces, got "
            f"{sampled['destructive_test_count']}"
        )
        assert sampled["available_count"] == 9591, (
            f"Expected 9740 - 149 = 9591 available pieces, got {sampled['available_count']}"
        )
        assert_lot_piece_ledger(sampled)

        failures = {
            "proof_load_failures": 0,
            "tensile_failures": 1,
            "min_measured_core_hardness_hv": 322.0,
        }
        accepted = validate_success(
            api_client.record_lot_test_results(test_a["id"], failures, inspector_headers)
        )
        rejected = validate_success(
            api_client.record_lot_test_results(test_b["id"], failures, inspector_headers)
        )

        assert accepted["total_failures"] == rejected["total_failures"] == 1, (
            "Both lots measured exactly one failure, got "
            f"{accepted['total_failures']} and {rejected['total_failures']}"
        )
        assert accepted["result"] == "ACCEPT", (
            f"The normal-inspection lot accepts, got {accepted['result']}"
        )
        assert rejected["result"] == "REJECT", (
            "One failure exceeds a tightened acceptance number of 0, got "
            f"{rejected['result']}"
        )

        held = fixtures.read_lot(lot_b["id"])
        assert held["process_state"] == "TESTING", (
            f"A rejected lot stays at TESTING, got {held['process_state']}"
        )
        assert held["disposition"] == "HOLD", (
            f"A rejected lot is frozen on HOLD, got {held['disposition']}"
        )
        assert held["hold_source"] == "TEST_REJECT", (
            f"Expected hold_source TEST_REJECT, got {held['hold_source']}"
        )
        assert held["risk_score_final"] == pytest.approx(55.82, abs=0.001), (
            "43.32 plus 12.5 for the single failure is 55.82, got "
            f"{held['risk_score_final']}"
        )
        assert_lot_piece_ledger(held)
