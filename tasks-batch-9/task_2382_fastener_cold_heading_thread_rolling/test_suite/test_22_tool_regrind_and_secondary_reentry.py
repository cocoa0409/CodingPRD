"""Lifecycles that come back to a state they have already left.

A progressive die set walks the cycle AVAILABLE -> MOUNTED -> WORN -> AVAILABLE as often
as its regrind allowance permits, and the identical regrind request branches to the
terminal SCRAPPED once the allowance is spent, after which no transition is accepted at
all. A production lot for a part whose thread rolling belongs after heat treatment is
cyclic in the same way: it reaches SECONDARY_DONE without its thread rolling, goes to the
furnace, and then re-enters SECONDARY_IN_PROGRESS and SECONDARY_DONE a second time — while
a quality hold and its release move the lot's disposition dimension twice without shifting
its process_state at all. Every rule asserted here is stated in PRD §2.10, §3.3 and §3.5.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_heading_tool,
    assert_lot_piece_ledger,
    assert_versions_incremented,
    fixtures,
    validate_error,
    validate_success,
)

CLOCK = "2026-09-01T06:00:00Z"

# The die set of §3.3 with a single regrind in its allowance: one closed cycle takes it
# back to AVAILABLE, the second regrind request has nowhere left to go but SCRAPPED.
TWO_STATION_DIE = {
    "tool_code": "DIE-2S-009",
    "station_count": 2,
    "rated_life_pieces": 6000,
    "max_regrinds": 1,
}

# An AFTER_HEAT_TREAT part: POINT is due before the furnace, THREAD_ROLL only after it.
AFTER_HEAT_TREAT_SPEC = {
    "part_number": "AR-M6-129",
    "thread_designation": "M6x1.0",
    "strength_class": "CLASS_10_9",
    "qualification_program": "AUTOMOTIVE_PPAP",
    "allowed_steel_grades": ["SAE_10B21"],
    "blank_mass_g": 6.0,
    "station_count_required": 4,
    "thread_timing": "AFTER_HEAT_TREAT",
    "required_secondary_ops": ["POINT", "THREAD_ROLL"],
    "min_core_hardness_hv": 304,
    "max_core_hardness_hv": 361,
    "max_decarb_depth_mm": 0.150,
    "plating_spec": "NONE",
    "packaging_mode": "BY_COUNT",
    "nominal_pack_count": 1000,
    "pieces_per_kg": 166.6,
    "proof_load_kn": 19.5,
}

PLANNED_PIECES = 5000
HEADED_COUNT = 4900
HEADING_SCRAP = 60
POINT_PIECES_OUT = 4850
THREAD_ROLL_PIECES_OUT = 4800


# ---------------------------------------------------------------------------
# Local setup helpers
# ---------------------------------------------------------------------------
def _fresh_die_set():
    """Register DIE-2S-009 with one regrind of allowance, still AVAILABLE."""
    fixtures.set_clock(CLOCK)
    return fixtures.register_heading_tool(**TWO_STATION_DIE)


def _scrapped_die_set():
    """Drive DIE-2S-009 through both of its cycles so it ends up SCRAPPED."""
    tool = _fresh_die_set()
    fixtures.mount_tool(tool["id"], "PRESS-1")
    fixtures.condemn_tool(tool["id"], reason="CRACKED_PUNCH")
    fixtures.regrind_tool(tool["id"])
    fixtures.mount_tool(tool["id"], "PRESS-1")
    fixtures.condemn_tool(tool["id"], reason="CHIPPED_DIE")
    return fixtures.regrind_tool(tool["id"])


def _headed_after_heat_treat_lot():
    """Master data for AR-M6-129 plus lot L-2610 reported through heading."""
    return fixtures.setup_headed_lot(
        planned_pieces=PLANNED_PIECES,
        headed_count=HEADED_COUNT,
        heading_scrap_count=HEADING_SCRAP,
        clock=CLOCK,
        spec_overrides=AFTER_HEAT_TREAT_SPEC,
        tool_overrides={"tool_code": "DIE-4S-001", "rated_life_pieces": 120000},
        furnace_overrides={"furnace_code": "FCE-1", "max_charge_mass_kg": 400.0},
        lot_overrides={
            "lot_code": "L-2610",
            "press_window_end_at": "2026-09-01T12:00:00Z",
        },
    )


def _run_the_furnace(env):
    """Book, start and close a PASSing heat treatment run on the lot."""
    run = fixtures.book_heat_treat(
        env["lot"]["id"],
        env["furnace"]["id"],
        window_start_at="2026-09-01T18:00:00Z",
        window_end_at="2026-09-01T23:00:00Z",
        carbon_potential_pct=0.42,
    )
    fixtures.start_heat_treat(run["id"], at="2026-09-01T19:00:00Z")
    return fixtures.record_heat_treat_results(
        run["id"],
        at="2026-09-01T22:00:00Z",
        core_hardness_hv=330.0,
        surface_decarb_depth_mm=0.100,
    )


def _lot_at_heat_treated():
    """L-2610 with its POINT operation DONE and a PASSing furnace run behind it."""
    env = _headed_after_heat_treat_lot()
    point_op = fixtures.queue_op(
        env["lot"]["id"], op_type="POINT", sequence_no=1, machine_code="PT-1"
    )
    env["point_op"] = fixtures.complete_op(point_op["id"], POINT_PIECES_OUT)
    env["heat_treat_run"] = _run_the_furnace(env)
    env["lot"] = fixtures.read_lot(env["lot"]["id"])
    return env


# ---------------------------------------------------------------------------
# A die set revisits MOUNTED and WORN, then the regrind branches to SCRAPPED
# ---------------------------------------------------------------------------
class TestDieSetRegrindCycle:
    """The AVAILABLE -> MOUNTED -> WORN -> AVAILABLE loop and its terminal branch."""

    def test_first_regrind_closes_the_cycle_back_to_available(self, api, engineer_headers):
        """A worn die set with regrind allowance left returns to AVAILABLE and remounts.

        PRD: "A `ProcessEngineer` mounts an `AVAILABLE` set on a press by supplying the `press_code`, taking it `AVAILABLE → MOUNTED`, recording the press in `mounted_press_code`, clearing any previous `condemn_reason`, and incrementing the set's `version` by 1."

        PRD: "When `regrind_count` is still below `max_regrinds`, the set goes `WORN → AVAILABLE`: the open cycle's `cumulative_pieces_current_cycle` is appended to `cycle_pieces_history`, `completed_cycle_count` and `regrind_count` each increment by 1, `cumulative_pieces_current_cycle` resets to zero, `observed_avg_cycle_pieces`, `rated_derated_life_pieces` and `conservative_life_pieces` are all recomputed, `condemn_reason` is cleared, and the set's `version` increments by 1 — closing the cycle `AVAILABLE → MOUNTED → WORN → AVAILABLE`."

        PRD: "`rated_derated_life_pieces` is the nameplate `rated_life_pieces` multiplied by one minus 0.15 for each completed regrind — that is, by one minus the product of `regrind_count` and 0.15 — with the result truncated downward to a whole number of pieces."

        Design: Difficulty/non_linear_state_machine/heading_tool_regrind_cycle_revisits_then_branches_to_scrapped
        """
        tool = _fresh_die_set()
        assert tool["status"] == "AVAILABLE", (
            f"Expected AVAILABLE on registration, got {tool['status']}"
        )

        mounted = validate_success(
            api.mount_heading_tool(tool["id"], {"press_code": "PRESS-1"}, engineer_headers)
        )
        assert mounted["status"] == "MOUNTED", (
            f"Expected MOUNTED after the first mount, got {mounted['status']}"
        )
        assert mounted["mounted_press_code"] == "PRESS-1", (
            f"Expected PRESS-1 recorded, got {mounted['mounted_press_code']}"
        )
        assert_versions_incremented(tool, mounted)

        worn = validate_success(
            api.condemn_heading_tool(
                tool["id"], {"reason": "CRACKED_PUNCH"}, engineer_headers
            )
        )
        assert worn["status"] == "WORN", (
            f"Expected WORN after the first condemn, got {worn['status']}"
        )

        reground = validate_success(api.regrind_heading_tool(tool["id"], engineer_headers))
        assert reground["status"] == "AVAILABLE", (
            f"Expected the set back at AVAILABLE after its first regrind, "
            f"got {reground['status']}"
        )
        assert reground["regrind_count"] == 1, (
            f"Expected regrind_count 1, got {reground['regrind_count']}"
        )
        assert reground["completed_cycle_count"] == 1, (
            f"Expected completed_cycle_count 1, got {reground['completed_cycle_count']}"
        )
        assert reground["cycle_pieces_history"] == [0], (
            f"Expected the empty cycle appended as [0], "
            f"got {reground['cycle_pieces_history']}"
        )
        assert reground["cumulative_pieces_current_cycle"] == 0, (
            "The open cycle's count resets to zero on regrind, got "
            f"{reground['cumulative_pieces_current_cycle']}"
        )
        assert reground["rated_derated_life_pieces"] == 5100, (
            "6000 nameplate derated by 0.15 for one regrind is 5100, got "
            f"{reground['rated_derated_life_pieces']}"
        )
        assert reground["observed_avg_cycle_pieces"] == pytest.approx(0.0, abs=0.001), (
            "One closed cycle of 0 pieces averages 0.00, got "
            f"{reground['observed_avg_cycle_pieces']}"
        )
        assert reground["conservative_life_pieces"] == 0, (
            "0.90 of a 0-piece observed average truncates to 0, got "
            f"{reground['conservative_life_pieces']}"
        )
        assert not reground["condemn_reason"], (
            f"Regrind clears condemn_reason, got {reground['condemn_reason']!r}"
        )
        assert_versions_incremented(worn, reground)
        assert_heading_tool(reground)

        remounted = validate_success(
            api.mount_heading_tool(tool["id"], {"press_code": "PRESS-1"}, engineer_headers)
        )
        assert remounted["status"] == "MOUNTED", (
            "The same identity revisits MOUNTED on its second cycle, got "
            f"{remounted['status']}"
        )
        assert remounted["regrind_count"] == 1, (
            f"Mounting does not touch regrind_count, got {remounted['regrind_count']}"
        )
        assert_versions_incremented(reground, remounted)

    def test_second_regrind_branches_to_scrapped_once_allowance_is_spent(
        self, api, engineer_headers
    ):
        """The same regrind request scraps the set when regrind_count has reached max_regrinds.

        PRD: "The operator route is a `ProcessEngineer` or `QualityInspector` condemning a chipped or cracked die with a supplied `reason`: `status` becomes `WORN`, that `reason` is recorded as `condemn_reason`, `mounted_press_code` is cleared, and every production lot on that set in `process_state` `SETUP` moves, in ascending `created_at` order, to `disposition` `HOLD` with `hold_source` `TOOL_WEAR`."

        PRD: "When `regrind_count` has already reached `max_regrinds`, the very same request takes the set `WORN → SCRAPPED` instead: the open cycle's count is still appended to `cycle_pieces_history` and `completed_cycle_count` still increments by 1, but `regrind_count` does not advance, the set's `status` becomes `SCRAPPED`, and the `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/heading_tool_regrind_cycle_revisits_then_branches_to_scrapped
        """
        tool = _fresh_die_set()
        fixtures.mount_tool(tool["id"], "PRESS-1")
        fixtures.condemn_tool(tool["id"], reason="CRACKED_PUNCH")
        fixtures.regrind_tool(tool["id"])
        fixtures.mount_tool(tool["id"], "PRESS-1")

        worn_again = validate_success(
            api.condemn_heading_tool(
                tool["id"], {"reason": "CHIPPED_DIE"}, engineer_headers
            )
        )
        assert worn_again["status"] == "WORN", (
            f"The set revisits WORN on its second cycle, got {worn_again['status']}"
        )
        assert worn_again["condemn_reason"] == "CHIPPED_DIE", (
            f"Expected condemn_reason CHIPPED_DIE, got {worn_again['condemn_reason']}"
        )
        assert not worn_again["mounted_press_code"], (
            "Condemning clears mounted_press_code, got "
            f"{worn_again['mounted_press_code']!r}"
        )
        assert worn_again["regrind_count"] == 1, (
            "regrind_count is still 1 going into the second regrind, got "
            f"{worn_again['regrind_count']}"
        )

        scrapped = validate_success(api.regrind_heading_tool(tool["id"], engineer_headers))
        assert scrapped["status"] == "SCRAPPED", (
            "With regrind_count already at max_regrinds the regrind scraps the set, got "
            f"{scrapped['status']}"
        )
        assert scrapped["regrind_count"] == 1, (
            f"regrind_count must not advance on the scrap branch, "
            f"got {scrapped['regrind_count']}"
        )
        assert scrapped["completed_cycle_count"] == 2, (
            f"Expected completed_cycle_count 2, got {scrapped['completed_cycle_count']}"
        )
        assert scrapped["cycle_pieces_history"] == [0, 0], (
            "The second empty cycle is still appended, got "
            f"{scrapped['cycle_pieces_history']}"
        )
        assert_versions_incremented(worn_again, scrapped)
        assert_heading_tool(scrapped)

    @pytest.mark.parametrize("action", ["mount", "condemn", "regrind"])
    def test_scrapped_die_set_accepts_no_further_transition(
        self, api, engineer_headers, action
    ):
        """A scrapped die set refuses mounting, condemning and regrinding alike.

        PRD: "`SCRAPPED` is terminal; a scrapped set never mounts again."

        PRD: "A heading tool must be `AVAILABLE` to mount, `MOUNTED` to condemn, and `WORN` to regrind — otherwise `ERR_INVALID_TOOL_STATE` (409)."

        Design: Difficulty/non_linear_state_machine/heading_tool_regrind_cycle_revisits_then_branches_to_scrapped
        """
        scrapped = _scrapped_die_set()
        assert scrapped["status"] == "SCRAPPED", (
            f"Setup should leave the set SCRAPPED, got {scrapped['status']}"
        )

        if action == "mount":
            response = api.mount_heading_tool(
                scrapped["id"], {"press_code": "PRESS-1"}, engineer_headers
            )
        elif action == "condemn":
            response = api.condemn_heading_tool(
                scrapped["id"], {"reason": "CRACKED_PUNCH"}, engineer_headers
            )
        else:
            response = api.regrind_heading_tool(scrapped["id"], engineer_headers)

        validate_error(response, ApiErrorId.ERR_INVALID_TOOL_STATE.value)

        unchanged = fixtures.read_tool(scrapped["id"])
        assert unchanged["status"] == "SCRAPPED", (
            f"The refused {action} must leave the set SCRAPPED, got {unchanged['status']}"
        )
        assert unchanged["version"] == scrapped["version"], (
            f"A refused {action} mutates nothing, so version stays "
            f"{scrapped['version']}, got {unchanged['version']}"
        )


# ---------------------------------------------------------------------------
# A lot re-enters secondary operations after heat treatment, while its
# disposition dimension moves on its own
# ---------------------------------------------------------------------------
class TestSecondaryReentryAfterHeatTreatment:
    """The cyclic process dimension of an AFTER_HEAT_TREAT part, and the hold dimension."""

    def test_lot_reaches_secondary_done_with_thread_roll_still_outstanding(
        self, api, engineer_headers
    ):
        """POINT alone bubbles an AFTER_HEAT_TREAT lot to SECONDARY_DONE before the furnace.

        PRD: "From `HEADED` the lot moves `HEADED → SECONDARY_IN_PROGRESS`."

        PRD: "The new operation is created in `status` `PENDING` with `pieces_in` taken from the lot's current `available_count` — the client never supplies it — and with `performed_after_heat_treat` capturing whether the lot's `heat_treat_completed` flag was already true at the moment of creation."

        PRD: "For a part with `thread_timing` of `AFTER_HEAT_TREAT` whose `heat_treat_completed` is still false, every `op_type` in `required_secondary_ops` *except* `THREAD_ROLL` must have a `DONE` operation — the thread rolling is legitimately still outstanding, and the lot proceeds to the furnace without it."

        Design: Difficulty/non_linear_state_machine/after_heat_treat_lot_reenters_secondary_while_disposition_moves_independently
        """
        env = _headed_after_heat_treat_lot()
        lot_id = env["lot"]["id"]
        assert env["lot"]["process_state"] == "HEADED", (
            f"Setup should leave the lot HEADED, got {env['lot']['process_state']}"
        )

        point_op = validate_success(
            api.queue_secondary_operation(
                lot_id,
                {"op_type": "POINT", "sequence_no": 1, "machine_code": "PT-1"},
                engineer_headers,
            ),
            201,
        )
        assert point_op["pieces_in"] == HEADED_COUNT, (
            f"pieces_in comes from the lot's available_count {HEADED_COUNT}, "
            f"got {point_op['pieces_in']}"
        )
        assert point_op["performed_after_heat_treat"] is False, (
            "heat_treat_completed is still false when POINT is queued, so "
            "performed_after_heat_treat must be false, got "
            f"{point_op['performed_after_heat_treat']}"
        )

        queued_lot = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert queued_lot["process_state"] == "SECONDARY_IN_PROGRESS", (
            "Queueing the first operation takes the lot HEADED -> "
            f"SECONDARY_IN_PROGRESS, got {queued_lot['process_state']}"
        )

        done_op = validate_success(
            api.complete_secondary_operation(
                point_op["id"], {"pieces_out": POINT_PIECES_OUT}, engineer_headers
            )
        )
        assert done_op["status"] == "DONE", (
            f"Expected the POINT operation DONE, got {done_op['status']}"
        )
        assert done_op["scrap_pieces"] == HEADED_COUNT - POINT_PIECES_OUT, (
            f"Expected {HEADED_COUNT - POINT_PIECES_OUT} scrapped, "
            f"got {done_op['scrap_pieces']}"
        )

        bubbled_lot = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert bubbled_lot["process_state"] == "SECONDARY_DONE", (
            "With THREAD_ROLL not due before the furnace the lot bubbles to "
            f"SECONDARY_DONE, got {bubbled_lot['process_state']}"
        )
        assert bubbled_lot["available_count"] == POINT_PIECES_OUT, (
            f"available_count is replaced by pieces_out {POINT_PIECES_OUT}, "
            f"got {bubbled_lot['available_count']}"
        )
        assert bubbled_lot["heat_treat_completed"] is False, (
            "The lot has not seen the furnace yet, got heat_treat_completed "
            f"{bubbled_lot['heat_treat_completed']}"
        )
        assert_lot_piece_ledger(bubbled_lot)

    def test_hold_and_release_move_disposition_while_process_state_stays_heat_treated(
        self, api, inspector_headers, manager_headers
    ):
        """A quality hold and its release move the lot's disposition twice and its process route not at all.

        PRD: "The `disposition` dimension is deliberately independent of `process_state`: a lot can be frozen and thawed without moving one step along its process route."

        PRD: "A `QualityInspector` or `QualityManager` may place a hold with a `reason` on any lot whose `disposition` is `IN_PROCESS`, taking it `IN_PROCESS → HOLD` with `hold_source` of `QUALITY` and incrementing its `version` by 1."

        PRD: "A successful release takes the lot `HOLD → IN_PROCESS`, resets `hold_source` to `NONE`, and increments the `version` by 1."

        Design: Difficulty/non_linear_state_machine/after_heat_treat_lot_reenters_secondary_while_disposition_moves_independently
        """
        env = _lot_at_heat_treated()
        lot_id = env["lot"]["id"]
        before = env["lot"]
        assert before["process_state"] == "HEAT_TREATED", (
            f"A PASSing run leaves the lot HEAT_TREATED, got {before['process_state']}"
        )
        assert before["heat_treat_completed"] is True, (
            "A PASSing run sets heat_treat_completed, got "
            f"{before['heat_treat_completed']}"
        )
        assert before["disposition"] == "IN_PROCESS", (
            f"Expected disposition IN_PROCESS, got {before['disposition']}"
        )

        held = validate_success(
            api.hold_production_lot(
                lot_id, {"reason": "AWAITING_THREAD_ROLL_GAUGE"}, inspector_headers
            )
        )
        assert held["disposition"] == "HOLD", (
            f"Expected disposition HOLD after the hold, got {held['disposition']}"
        )
        assert held["hold_source"] == "QUALITY", (
            f"An operator hold is tagged QUALITY, got {held['hold_source']}"
        )
        assert held["process_state"] == "HEAT_TREATED", (
            "A hold moves no step along the process route, so process_state stays "
            f"HEAT_TREATED, got {held['process_state']}"
        )
        assert_versions_incremented(before, held)

        released = validate_success(
            api.release_hold(lot_id, {"note": "GAUGE_CALIBRATED"}, manager_headers)
        )
        assert released["disposition"] == "IN_PROCESS", (
            f"Releasing the hold returns the lot to IN_PROCESS, "
            f"got {released['disposition']}"
        )
        assert released["hold_source"] == "NONE", (
            f"Releasing the hold resets hold_source to NONE, "
            f"got {released['hold_source']}"
        )
        assert released["process_state"] == "HEAT_TREATED", (
            "The release leaves the process dimension where it was, so process_state "
            f"stays HEAT_TREATED, got {released['process_state']}"
        )
        assert_versions_incremented(held, released)

    def test_lot_revisits_secondary_in_progress_and_secondary_done_after_the_furnace(
        self, api, engineer_headers
    ):
        """The thread rolling of an AFTER_HEAT_TREAT part drives the lot through both secondary states a second time.

        PRD: "From `HEAT_TREATED` the lot moves `HEAT_TREATED → SECONDARY_IN_PROGRESS`, and this route is reserved for parts whose thread rolling belongs after heat treatment: queueing a `THREAD_ROLL` operation here requires the part's `thread_timing` to be `AFTER_HEAT_TREAT`, and the created operation carries `performed_after_heat_treat` as true."

        PRD: "The lot absorbs the yield: its `available_count` is replaced by `pieces_out` and its `scrap_count` grows by `scrap_pieces`, keeping the piece ledger of §2.8 balanced."

        PRD: "When the lot has no operation left in `status` `PENDING` *and* the operations due at this stage are all `DONE`, the lot moves `SECONDARY_IN_PROGRESS → SECONDARY_DONE`."

        Design: Difficulty/non_linear_state_machine/after_heat_treat_lot_reenters_secondary_while_disposition_moves_independently
        """
        env = _headed_after_heat_treat_lot()
        lot_id = env["lot"]["id"]

        # First pass through the two secondary states, without the thread rolling.
        first_op = validate_success(
            api.queue_secondary_operation(
                lot_id,
                {"op_type": "POINT", "sequence_no": 1, "machine_code": "PT-1"},
                engineer_headers,
            ),
            201,
        )
        first_visit = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert first_visit["process_state"] == "SECONDARY_IN_PROGRESS", (
            "First visit to SECONDARY_IN_PROGRESS expected, got "
            f"{first_visit['process_state']}"
        )
        validate_success(
            api.complete_secondary_operation(
                first_op["id"], {"pieces_out": POINT_PIECES_OUT}, engineer_headers
            )
        )
        first_done = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert first_done["process_state"] == "SECONDARY_DONE", (
            f"First visit to SECONDARY_DONE expected, got {first_done['process_state']}"
        )

        _run_the_furnace(env)
        heat_treated = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert heat_treated["process_state"] == "HEAT_TREATED", (
            f"Expected HEAT_TREATED after the furnace, "
            f"got {heat_treated['process_state']}"
        )

        # Second pass: the thread rolling that was legitimately outstanding.
        thread_op = validate_success(
            api.queue_secondary_operation(
                lot_id,
                {"op_type": "THREAD_ROLL", "sequence_no": 2, "machine_code": "TR-1"},
                engineer_headers,
            ),
            201,
        )
        assert thread_op["performed_after_heat_treat"] is True, (
            "An operation queued once heat_treat_completed is true carries "
            "performed_after_heat_treat true, got "
            f"{thread_op['performed_after_heat_treat']}"
        )
        assert thread_op["pieces_in"] == POINT_PIECES_OUT, (
            f"pieces_in comes from available_count {POINT_PIECES_OUT}, "
            f"got {thread_op['pieces_in']}"
        )

        second_visit = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert second_visit["process_state"] == "SECONDARY_IN_PROGRESS", (
            "The lot re-enters SECONDARY_IN_PROGRESS from HEAT_TREATED, got "
            f"{second_visit['process_state']}"
        )

        validate_success(
            api.complete_secondary_operation(
                thread_op["id"], {"pieces_out": THREAD_ROLL_PIECES_OUT}, engineer_headers
            )
        )
        second_done = validate_success(api.get_production_lot(lot_id, engineer_headers))
        assert second_done["process_state"] == "SECONDARY_DONE", (
            "With every required operation now DONE the lot revisits SECONDARY_DONE, got "
            f"{second_done['process_state']}"
        )
        assert second_done["available_count"] == THREAD_ROLL_PIECES_OUT, (
            f"available_count is replaced by pieces_out {THREAD_ROLL_PIECES_OUT}, "
            f"got {second_done['available_count']}"
        )
        expected_scrap = (
            HEADING_SCRAP
            + (HEADED_COUNT - POINT_PIECES_OUT)
            + (POINT_PIECES_OUT - THREAD_ROLL_PIECES_OUT)
        )
        assert second_done["scrap_count"] == expected_scrap, (
            f"Expected scrap_count {expected_scrap} after both operations, "
            f"got {second_done['scrap_count']}"
        )
        assert_lot_piece_ledger(second_done)
