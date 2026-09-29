"""Writes refused because of the state of a neighbouring record.

Two gates in this API read another entity rather than the one being written: a
heading completion report is refused while the lot's die set has left ``MOUNTED``
(PRD §2.10, §3.4), and the start of a heat treatment run is refused while the
furnace that run names is not ``IDLE`` (PRD §2.10, §3.5). Every test below pairs
the refusal with its positive control — the identical request succeeding once the
neighbouring record is back in an acceptable state — and checks that the refused
call left both records exactly as they were.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    fixtures,
    validate_error,
    validate_success,
)

# The heading report used unchanged on both sides of the die-set gate: 4900 good
# pieces and 60 spoiled ones against a lot planned for 5000.
HEADING_REPORT = {"headed_count": 4900, "heading_scrap_count": 60}


# ---------------------------------------------------------------------------
# Local setup chains (built only from PRD-declared endpoints)
# ---------------------------------------------------------------------------
def _lot_in_setup_under_a_condemned_die_set():
    """A clean ``SETUP`` / ``IN_PROCESS`` lot whose die set has been condemned.

    Condemning the set also holds the lot, so the hold is released again: the
    lot's own two state dimensions are then beyond reproach and the only thing
    wrong anywhere is the die set's ``WORN`` status.
    """
    env = fixtures.setup_lot_in_setup(planned_pieces=5000)
    env["tool"] = fixtures.condemn_tool(env["tool"]["id"], reason="CHIPPED_STATION_2")
    env["lot"] = fixtures.release_hold(env["lot"]["id"], note="TOOLING_SWAP_PLANNED")
    return env


def _two_secondary_done_lots():
    """Two lots on one press, both bubbled up to ``SECONDARY_DONE``.

    Both are built from the same master data, so they share the part
    specification, the wire lot, the die set and the furnace; their press windows
    abut rather than overlap.
    """
    env = fixtures.setup_master_data(furnace_overrides={"cooldown_minutes": 30})
    ops = [{"op_type": "THREAD_ROLL", "sequence_no": 1, "pieces_out": 470}]
    env = fixtures.setup_secondary_done_lot(
        planned_pieces=500,
        headed_count=480,
        heading_scrap_count=20,
        ops=ops,
        env=env,
        lot_overrides={
            "lot_code": "L-2680",
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T08:00:00Z",
        },
    )
    lot_a = env["lot"]
    env = fixtures.setup_secondary_done_lot(
        planned_pieces=500,
        headed_count=480,
        heading_scrap_count=20,
        ops=ops,
        env=env,
        lot_overrides={
            "lot_code": "L-2681",
            "press_window_start_at": "2026-09-01T08:00:00Z",
            "press_window_end_at": "2026-09-01T10:00:00Z",
        },
    )
    env["lot_a"] = lot_a
    env["lot_b"] = env["lot"]
    return env


# ---------------------------------------------------------------------------
# The die set under the lot
# ---------------------------------------------------------------------------
class TestHeadingCompletionAgainstTheDieSetState:
    """Reporting heading reads the die set's status, not just the lot's."""

    def test_complete_heading_refused_while_its_die_set_sits_worn(
        self, api, engineer_headers
    ):
        """A blameless SETUP lot cannot report heading while its condemned die set is WORN.

        PRD: "The lot's die set must be `MOUNTED` when heading completion is reported — a tool condemned or worn out mid-lot blocks the completion report with `ERR_INVALID_TOOL_STATE` (409)."

        PRD: "The operator route is a `ProcessEngineer` or `QualityInspector` condemning a chipped or cracked die with a supplied `reason`: `status` becomes `WORN`, that `reason` is recorded as `condemn_reason`, `mounted_press_code` is cleared, and every production lot on that set in `process_state` `SETUP` moves, in ascending `created_at` order, to `disposition` `HOLD` with `hold_source` `TOOL_WEAR`."

        Design: Difficulty/cross_entity_state_dependency/heading_completion_blocked_while_its_tool_is_worn
        """
        env = _lot_in_setup_under_a_condemned_die_set()
        assert env["tool"]["status"] == "WORN", (
            f"Expected the condemned set to be WORN, got {env['tool']['status']}"
        )
        assert env["tool"]["condemn_reason"] == "CHIPPED_STATION_2", (
            "The condemnation reason must be recorded as condemn_reason, got "
            f"{env['tool']['condemn_reason']!r}"
        )
        assert env["lot"]["disposition"] == "IN_PROCESS", (
            "The released lot must be back in IN_PROCESS, got "
            f"{env['lot']['disposition']}"
        )

        lot_before = fixtures.read_lot(env["lot"]["id"])
        wire_before = fixtures.read_wire_lot(env["wire"]["id"])
        assert lot_before["process_state"] == "SETUP", (
            f"Expected SETUP before the report, got {lot_before['process_state']}"
        )

        response = api.complete_heading(
            env["lot"]["id"], dict(HEADING_REPORT), engineer_headers
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TOOL_STATE.value)

        lot_after = fixtures.read_lot(env["lot"]["id"])
        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert lot_after["process_state"] == "SETUP", (
            f"Expected the lot to stay in SETUP, got {lot_after['process_state']}"
        )
        assert lot_after["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS, got {lot_after['disposition']}"
        )
        assert lot_after["headed_count"] == 0, (
            f"Expected headed_count 0 after the refusal, got {lot_after['headed_count']}"
        )
        assert lot_after["available_count"] == 0, (
            f"Expected available_count 0 after the refusal, got {lot_after['available_count']}"
        )
        assert lot_after["version"] == lot_before["version"], (
            f"A refused report must not mutate the lot: version moved from "
            f"{lot_before['version']} to {lot_after['version']}"
        )
        assert wire_after["consumed_mass_kg"] == pytest.approx(0.0, abs=0.001), (
            f"Expected consumed_mass_kg 0.000, got {wire_after['consumed_mass_kg']}"
        )
        assert wire_after["reserved_mass_kg"] == pytest.approx(105.0, abs=0.001), (
            "The reservation of 105.000 kg must survive the refusal, got "
            f"{wire_after['reserved_mass_kg']}"
        )
        assert wire_after["version"] == wire_before["version"], (
            "A refused report must not mutate the wire lot: version moved from "
            f"{wire_before['version']} to {wire_after['version']}"
        )
        assert_wire_mass_ledger(wire_after)
        assert_lot_piece_ledger(lot_after)

    def test_complete_heading_succeeds_once_the_die_set_is_reground_and_remounted(
        self, api, engineer_headers
    ):
        """The identical report goes through once the same die set is back to MOUNTED.

        PRD: "The lot's die set must be `MOUNTED` when heading completion is reported — a tool condemned or worn out mid-lot blocks the completion report with `ERR_INVALID_TOOL_STATE` (409)."

        PRD: "When `regrind_count` is still below `max_regrinds`, the set goes `WORN → AVAILABLE`: the open cycle's `cumulative_pieces_current_cycle` is appended to `cycle_pieces_history`, `completed_cycle_count` and `regrind_count` each increment by 1, `cumulative_pieces_current_cycle` resets to zero, `observed_avg_cycle_pieces`, `rated_derated_life_pieces` and `conservative_life_pieces` are all recomputed, `condemn_reason` is cleared, and the set's `version` increments by 1 — closing the cycle `AVAILABLE → MOUNTED → WORN → AVAILABLE`."

        PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

        Design: Difficulty/cross_entity_state_dependency/heading_completion_blocked_while_its_tool_is_worn
        """
        env = _lot_in_setup_under_a_condemned_die_set()

        refused = api.complete_heading(
            env["lot"]["id"], dict(HEADING_REPORT), engineer_headers
        )
        validate_error(refused, ApiErrorId.ERR_INVALID_TOOL_STATE.value)

        reground = fixtures.regrind_tool(env["tool"]["id"])
        assert reground["status"] == "AVAILABLE", (
            f"A regrind inside the allowance returns the set to AVAILABLE, got "
            f"{reground['status']}"
        )
        assert reground["regrind_count"] == 1, (
            f"Expected regrind_count 1 after one regrind, got {reground['regrind_count']}"
        )
        assert reground["completed_cycle_count"] == 1, (
            "The regrind closes one cycle, got completed_cycle_count "
            f"{reground['completed_cycle_count']}"
        )
        assert reground["rated_derated_life_pieces"] == 102000, (
            "120000 derated by 0.15 for one regrind is 102000, got "
            f"{reground['rated_derated_life_pieces']}"
        )

        remounted = fixtures.mount_tool(env["tool"]["id"], env["press_code"])
        assert remounted["status"] == "MOUNTED", (
            f"Expected the set back on the press as MOUNTED, got {remounted['status']}"
        )

        response = api.complete_heading(
            env["lot"]["id"], dict(HEADING_REPORT), engineer_headers
        )
        lot = validate_success(response)
        assert lot["process_state"] == "HEADED", (
            f"Expected the lot to reach HEADED, got {lot['process_state']}"
        )
        assert lot["headed_count"] == 4900, (
            f"Expected headed_count 4900, got {lot['headed_count']}"
        )
        assert lot["available_count"] == 4900, (
            f"Expected available_count 4900, got {lot['available_count']}"
        )
        assert lot["heading_scrap_count"] == 60, (
            f"Expected heading_scrap_count 60, got {lot['heading_scrap_count']}"
        )
        assert lot["scrap_count"] == 60, (
            f"Heading scrap is a component of scrap_count, got {lot['scrap_count']}"
        )
        assert lot["tool_utilization_pct"] == pytest.approx(4.86, abs=0.001), (
            "100 * 4960 / 102000 rounded half up to two places is 4.86, got "
            f"{lot['tool_utilization_pct']}"
        )
        assert lot["wire_consumed_kg"] == pytest.approx(99.2, abs=0.001), (
            f"4960 pieces at 20.0 g consume 99.200 kg, got {lot['wire_consumed_kg']}"
        )
        assert_lot_piece_ledger(lot)

        tool_after = fixtures.read_tool(env["tool"]["id"])
        assert tool_after["status"] == "MOUNTED", (
            "4960 pieces stay well below the derated budget, so the set stays "
            f"MOUNTED, got {tool_after['status']}"
        )
        assert tool_after["cumulative_pieces_current_cycle"] == 4960, (
            "The open cycle grows by the two reported counts, got "
            f"{tool_after['cumulative_pieces_current_cycle']}"
        )

        wire_after = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire_after["consumed_mass_kg"] == pytest.approx(99.2, abs=0.001), (
            f"Expected consumed_mass_kg 99.200, got {wire_after['consumed_mass_kg']}"
        )
        assert wire_after["reserved_mass_kg"] == pytest.approx(0.0, abs=0.001), (
            f"The reservation settles to zero, got {wire_after['reserved_mass_kg']}"
        )
        assert_wire_mass_ledger(wire_after)

    def test_complete_heading_refused_when_a_sibling_lot_wore_the_die_set_out(
        self, api, engineer_headers
    ):
        """A second lot on the same set cannot report heading after the first wore it out.

        PRD: "The counter-driven route fires automatically when heading completion pushes `cumulative_pieces_current_cycle` to or past `rated_derated_life_pieces`: `status` becomes `WORN`, `mounted_press_code` is cleared, `condemn_reason` stays empty because no operator gave a reason, and every *other* production lot queued on that set whose `process_state` is `SETUP` moves, in ascending `created_at` order, to `disposition` of `HOLD` with `hold_source` of `TOOL_WEAR`."

        PRD: "The lot's die set must be `MOUNTED` when heading completion is reported — a tool condemned or worn out mid-lot blocks the completion report with `ERR_INVALID_TOOL_STATE` (409)."

        Design: Difficulty/cross_entity_state_dependency/heading_completion_blocked_while_its_tool_is_worn
        """
        env = fixtures.setup_master_data(
            spec_overrides={"scrap_allowance_pct": 0.0},
            tool_overrides={"rated_life_pieces": 4000},
        )
        first = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code=env["press_code"],
            lot_code="L-2640",
            planned_pieces=4000,
            press_window_start_at="2026-09-01T06:00:00Z",
            press_window_end_at="2026-09-01T08:00:00Z",
        )
        second = fixtures.open_production_lot(
            env["spec"]["id"],
            env["wire"]["id"],
            env["tool"]["id"],
            press_code=env["press_code"],
            lot_code="L-2641",
            planned_pieces=500,
            press_window_start_at="2026-09-01T08:00:00Z",
            press_window_end_at="2026-09-01T10:00:00Z",
        )

        fixtures.report_heading(first["id"], 3900, 100)
        tool = fixtures.read_tool(env["tool"]["id"])
        assert tool["status"] == "WORN", (
            "4000 pieces reach the derated budget of 4000, so the set wears out, got "
            f"{tool['status']}"
        )
        assert tool["condemn_reason"] in (None, ""), (
            "The counter-driven route leaves condemn_reason empty, got "
            f"{tool['condemn_reason']!r}"
        )

        held = fixtures.read_lot(second["id"])
        assert held["disposition"] == "HOLD", (
            f"The sibling SETUP lot must be held, got {held['disposition']}"
        )
        assert held["hold_source"] == "TOOL_WEAR", (
            f"Expected hold_source TOOL_WEAR, got {held['hold_source']}"
        )

        released = fixtures.release_hold(second["id"], note="TOOLING_SWAP_PLANNED")
        assert released["disposition"] == "IN_PROCESS", (
            f"Expected the released lot in IN_PROCESS, got {released['disposition']}"
        )

        response = api.complete_heading(
            second["id"],
            {"headed_count": 475, "heading_scrap_count": 25},
            engineer_headers,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_TOOL_STATE.value)

        after = fixtures.read_lot(second["id"])
        assert after["process_state"] == "SETUP", (
            f"Expected the refused lot to stay in SETUP, got {after['process_state']}"
        )
        assert after["headed_count"] == 0, (
            f"Expected headed_count 0 after the refusal, got {after['headed_count']}"
        )
        assert after["version"] == released["version"], (
            f"A refused report must not mutate the lot: version moved from "
            f"{released['version']} to {after['version']}"
        )
        assert_lot_piece_ledger(after)


# ---------------------------------------------------------------------------
# The furnace under the run
# ---------------------------------------------------------------------------
class TestRunStartAgainstTheFurnaceState:
    """Starting a run reads the named furnace's status, not just the run's own."""

    def test_run_start_refused_while_its_furnace_is_occupied_by_another_lots_run(
        self, api, heat_treat_headers
    ):
        """A PLANNED run inside its own window cannot start while its furnace is OCCUPIED.

        PRD: "The furnace named by a run must be `IDLE` when the run starts — otherwise `ERR_FURNACE_OCCUPIED` (409)."

        PRD: "On success `started_at` is stamped from the logical clock, the furnace flips `IDLE → OCCUPIED`, and both the run's `version` and the furnace's `version` increment by 1."

        Design: Difficulty/cross_entity_state_dependency/furnace_run_start_blocked_while_furnace_is_occupied
        """
        env = _two_secondary_done_lots()
        run_a = fixtures.book_heat_treat(
            env["lot_a"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T18:00:00Z",
            window_end_at="2026-09-01T20:00:00Z",
        )
        run_b = fixtures.book_heat_treat(
            env["lot_b"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T21:00:00Z",
            window_end_at="2026-09-01T23:00:00Z",
        )

        fixtures.start_heat_treat(run_a["id"], at="2026-09-01T19:00:00Z")
        occupied = fixtures.read_furnace(env["furnace"]["id"])
        assert occupied["status"] == "OCCUPIED", (
            f"Starting a run flips the furnace to OCCUPIED, got {occupied['status']}"
        )

        fixtures.set_clock("2026-09-01T21:30:00Z")
        response = api.start_heat_treat_run(run_b["id"], heat_treat_headers)
        validate_error(response, ApiErrorId.ERR_FURNACE_OCCUPIED.value)

        run_b_after = fixtures.read_heat_treat_run(run_b["id"])
        assert run_b_after["status"] == "PLANNED", (
            f"The refused run must stay PLANNED, got {run_b_after['status']}"
        )
        assert run_b_after["started_at"] in (None, ""), (
            f"The refused run must keep started_at empty, got {run_b_after['started_at']!r}"
        )
        assert run_b_after["version"] == run_b["version"], (
            f"A refused start must not mutate the run: version moved from "
            f"{run_b['version']} to {run_b_after['version']}"
        )

        furnace_after = fixtures.read_furnace(env["furnace"]["id"])
        assert furnace_after["status"] == "OCCUPIED", (
            f"The furnace stays with the run that holds it, got {furnace_after['status']}"
        )
        assert furnace_after["version"] == occupied["version"], (
            f"A refused start must not mutate the furnace: version moved from "
            f"{occupied['version']} to {furnace_after['version']}"
        )

        run_a_after = fixtures.read_heat_treat_run(run_a["id"])
        assert run_a_after["status"] == "RUNNING", (
            f"The run holding the furnace is untouched, got {run_a_after['status']}"
        )

    def test_run_start_succeeds_once_the_earlier_runs_results_free_the_furnace(
        self, api, heat_treat_headers
    ):
        """Recording the first run's results returns the furnace to IDLE and the same start works.

        PRD: "The furnace must be `IDLE`, or the start is refused with `ERR_FURNACE_OCCUPIED`."

        PRD: "Recording results always takes the run `RUNNING → COMPLETED` (a terminal status), stamps `completed_at` from the logical clock, returns the furnace to `IDLE`, and sets the furnace's `last_run_end_at` to the same instant."

        PRD: "On success `started_at` is stamped from the logical clock, the furnace flips `IDLE → OCCUPIED`, and both the run's `version` and the furnace's `version` increment by 1."

        Design: Difficulty/cross_entity_state_dependency/furnace_run_start_blocked_while_furnace_is_occupied
        """
        env = _two_secondary_done_lots()
        run_a = fixtures.book_heat_treat(
            env["lot_a"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T18:00:00Z",
            window_end_at="2026-09-01T20:00:00Z",
        )
        run_b = fixtures.book_heat_treat(
            env["lot_b"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T21:00:00Z",
            window_end_at="2026-09-01T23:00:00Z",
        )
        fixtures.start_heat_treat(run_a["id"], at="2026-09-01T19:00:00Z")

        fixtures.set_clock("2026-09-01T21:30:00Z")
        refused = api.start_heat_treat_run(run_b["id"], heat_treat_headers)
        validate_error(refused, ApiErrorId.ERR_FURNACE_OCCUPIED.value)

        completed = fixtures.record_heat_treat_results(
            run_a["id"], core_hardness_hv=330.0, surface_decarb_depth_mm=0.020
        )
        assert completed["status"] == "COMPLETED", (
            f"Recording results always completes the run, got {completed['status']}"
        )
        assert completed["result"] == "PASS", (
            "330 HV inside 304-361 with no carbon deficit is a PASS, got "
            f"{completed['result']}"
        )

        freed = fixtures.read_furnace(env["furnace"]["id"])
        assert freed["status"] == "IDLE", (
            f"Recording results returns the furnace to IDLE, got {freed['status']}"
        )
        assert str(freed["last_run_end_at"]).startswith("2026-09-01T21:30:00"), (
            "last_run_end_at takes the instant results were recorded, got "
            f"{freed['last_run_end_at']!r}"
        )

        run_b_before = fixtures.read_heat_treat_run(run_b["id"])
        response = api.start_heat_treat_run(run_b["id"], heat_treat_headers)
        started = validate_success(response)
        assert started["status"] == "RUNNING", (
            f"The identical start now takes the run to RUNNING, got {started['status']}"
        )
        assert str(started["started_at"]).startswith("2026-09-01T21:30:00"), (
            f"started_at is stamped from the logical clock, got {started['started_at']!r}"
        )
        assert started["version"] == run_b_before["version"] + 1, (
            f"Expected the run's version to advance to {run_b_before['version'] + 1}, "
            f"got {started['version']}"
        )

        furnace_after = fixtures.read_furnace(env["furnace"]["id"])
        assert furnace_after["status"] == "OCCUPIED", (
            f"The successful start flips the furnace to OCCUPIED, got "
            f"{furnace_after['status']}"
        )
        assert furnace_after["version"] == freed["version"] + 1, (
            f"Expected the furnace's version to advance to {freed['version'] + 1}, got "
            f"{furnace_after['version']}"
        )

    def test_run_start_reads_only_the_furnace_the_run_names(
        self, api, heat_treat_headers
    ):
        """A run booked on a second, idle furnace starts while the first stays occupied.

        PRD: "The furnace named by a run must be `IDLE` when the run starts — otherwise `ERR_FURNACE_OCCUPIED` (409)."

        PRD: "On success `started_at` is stamped from the logical clock, the furnace flips `IDLE → OCCUPIED`, and both the run's `version` and the furnace's `version` increment by 1."

        Design: Difficulty/cross_entity_state_dependency/furnace_run_start_blocked_while_furnace_is_occupied
        """
        env = _two_secondary_done_lots()
        second_furnace = fixtures.register_furnace(
            furnace_code="FCE-2", max_charge_mass_kg=400.0, cooldown_minutes=30
        )
        run_a = fixtures.book_heat_treat(
            env["lot_a"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T18:00:00Z",
            window_end_at="2026-09-01T20:00:00Z",
        )
        run_b = fixtures.book_heat_treat(
            env["lot_b"]["id"],
            second_furnace["id"],
            window_start_at="2026-09-01T18:00:00Z",
            window_end_at="2026-09-01T20:00:00Z",
        )

        fixtures.start_heat_treat(run_a["id"], at="2026-09-01T19:00:00Z")
        first_furnace = fixtures.read_furnace(env["furnace"]["id"])
        assert first_furnace["status"] == "OCCUPIED", (
            f"The first furnace is held by its run, got {first_furnace['status']}"
        )

        response = api.start_heat_treat_run(run_b["id"], heat_treat_headers)
        started = validate_success(response)
        assert started["status"] == "RUNNING", (
            "A run whose own furnace is IDLE starts even while another furnace is "
            f"occupied, got {started['status']}"
        )
        assert str(started["started_at"]).startswith("2026-09-01T19:00:00"), (
            f"started_at is stamped from the logical clock, got {started['started_at']!r}"
        )
        assert started["version"] == run_b["version"] + 1, (
            f"Expected the run's version to advance to {run_b['version'] + 1}, got "
            f"{started['version']}"
        )

        assert fixtures.read_furnace(second_furnace["id"])["status"] == "OCCUPIED", (
            "The second furnace now holds its own run"
        )
        assert fixtures.read_furnace(env["furnace"]["id"])["status"] == "OCCUPIED", (
            "The first furnace is untouched by the second furnace's start"
        )
