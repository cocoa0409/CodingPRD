"""Which refusal a caller sees when one request breaks several plant rules at once.

The PRD evaluates its rules in a strict ascending ladder in which the first rule
violated decides the response, so a lot that is frozen, mis-routed and mis-counted
all at the same time must answer with the *earliest* violated rule and nothing
else. This module works through the freezes and orderings that decide those
answers: the quarantine freeze that outranks the hold freeze even on the endpoint
whose whole job is clearing a hold, the symmetric thread-timing gate, the wire
release state that is read before steel-grade eligibility, the secondary-operation
queue whose half-finished route answers two different errors on two different
endpoints, the inclusive scrap-allowance cap on heading completion, the part
specification drift that permanently blocks a pinned certificate, and the
inclusive furnace-window bounds on run start. It also covers the freezes that
outlast their cause: a quarantine lifted by re-verification returns the lot to
``IN_PROCESS`` rather than to the operator hold it overwrote.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_lot_piece_ledger,
    assert_wire_mass_ledger,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-09-01T06:00:00Z"


# ---------------------------------------------------------------------------
# Local route builders. Each test starts against an empty plant, so every
# precondition below is built from scratch through PRD-declared endpoints.
# ---------------------------------------------------------------------------
def _lot_quarantined_after_a_quality_hold():
    """A lot in SETUP put on a QUALITY hold, then swept into quarantine."""
    env = fixtures.setup_lot_in_setup(
        planned_pieces=5000,
        unplated=True,
        spec_overrides={"max_decarb_depth_mm": 0.100, "scrap_allowance_pct": 0.05},
        lot_overrides={"lot_code": "L-2620"},
    )
    fixtures.place_hold(env["lot"]["id"], reason="AWAITING_FIRST_ARTICLE_APPROVAL")
    fixtures.flag_heat_counterfeit(
        env["heat"]["id"], reason="MILL_CERT_SERIAL_NOT_ON_MILL_REGISTER"
    )
    env["lot"] = fixtures.read_lot(env["lot"]["id"])
    env["wire"] = fixtures.read_wire_lot(env["wire"]["id"])
    return env


def _headed_lot_on_an_after_heat_treat_part():
    """A HEADED lot whose part rolls its thread after heat treatment."""
    env = fixtures.setup_master_data(
        clock=CLOCK_START,
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-AHT",
            "thread_timing": "AFTER_HEAT_TREAT",
            "required_secondary_ops": ["DRILL", "THREAD_ROLL"],
            "max_decarb_depth_mm": 0.100,
            "scrap_allowance_pct": 0.05,
        },
    )
    env["lot"] = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2621",
        planned_pieces=1000,
        press_window_start_at="2026-09-01T06:00:00Z",
        press_window_end_at="2026-09-01T08:00:00Z",
    )
    env["lot"] = fixtures.report_heading(env["lot"]["id"], 980, 20)
    return env


def _heat_treated_lot_on_a_before_heat_treat_part():
    """A HEAT_TREATED lot whose part rolled its thread before the furnace."""
    env = fixtures.setup_master_data(
        clock=CLOCK_START,
        unplated=True,
        spec_overrides={
            "thread_timing": "BEFORE_HEAT_TREAT",
            "required_secondary_ops": ["THREAD_ROLL"],
            "max_decarb_depth_mm": 0.100,
            "scrap_allowance_pct": 0.05,
        },
    )
    env["lot"] = fixtures.open_production_lot(
        env["spec"]["id"],
        env["wire"]["id"],
        env["tool"]["id"],
        press_code=env["press_code"],
        lot_code="L-2622",
        planned_pieces=1000,
        press_window_start_at="2026-09-01T08:00:00Z",
        press_window_end_at="2026-09-01T10:00:00Z",
    )
    fixtures.report_heading(env["lot"]["id"], 980, 20)
    fixtures.run_secondary_op(
        env["lot"]["id"], op_type="THREAD_ROLL", sequence_no=1, pieces_out=970
    )
    env["heat_treat_run"] = fixtures.run_heat_treat(
        env["lot"]["id"], env["furnace"]["id"]
    )
    env["lot"] = fixtures.read_lot(env["lot"]["id"])
    return env


def _lot_with_a_half_finished_two_operation_route():
    """A lot needing DRILL then THREAD_ROLL, with only the DRILL queued."""
    env = fixtures.setup_headed_lot(
        planned_pieces=1000,
        headed_count=980,
        heading_scrap_count=20,
        unplated=True,
        spec_overrides={
            "part_number": "NP-M8-DT",
            "required_secondary_ops": ["DRILL", "THREAD_ROLL"],
            "thread_timing": "BEFORE_HEAT_TREAT",
            "max_decarb_depth_mm": 0.100,
            "scrap_allowance_pct": 0.05,
        },
        lot_overrides={"lot_code": "L-2624"},
    )
    env["drill_op"] = fixtures.queue_op(
        env["lot"]["id"], op_type="DRILL", sequence_no=1, machine_code="DR-1"
    )
    env["lot"] = fixtures.read_lot(env["lot"]["id"])
    return env


def _lot_in_setup_with_a_five_percent_allowance():
    """A lot planned for 5000 pieces at the default five percent scrap allowance."""
    return fixtures.setup_lot_in_setup(
        planned_pieces=5000,
        unplated=True,
        spec_overrides={"max_decarb_depth_mm": 0.100, "scrap_allowance_pct": 0.05},
        lot_overrides={"lot_code": "L-2625"},
    )


def _secondary_done_lot_and_a_furnace():
    """An unplated lot in SECONDARY_DONE with one registered furnace."""
    return fixtures.setup_secondary_done_lot(
        planned_pieces=5000,
        headed_count=4900,
        heading_scrap_count=60,
        unplated=True,
        spec_overrides={"max_decarb_depth_mm": 0.100, "scrap_allowance_pct": 0.05},
        lot_overrides={
            "lot_code": "L-2626",
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T07:00:00Z",
        },
    )


# ---------------------------------------------------------------------------
# The quarantine freeze against the hold freeze
# ---------------------------------------------------------------------------
class TestQuarantineOutranksHold:
    def test_quarantine_answers_ahead_of_the_hold_freeze_on_every_lot_endpoint(
        self, api, engineer_headers, inspector_headers, manager_headers
    ):
        """A lot held for quality and then quarantined answers ERR_LOT_QUARANTINED everywhere.

        PRD: "The production lot in scope must not have `disposition` of `QUARANTINED` — otherwise `ERR_LOT_QUARANTINED` (409)."

        PRD: "Quarantined material is frozen ahead of every other business check, including its own hold state."

        PRD: "This rule guards the same twenty-two operations as tier 8 minus two: releasing a hold is exempt (it is the operation that clears the hold) and placing a hold is exempt (it has its own precondition)."

        Design: Corner/validations/quarantine_freeze_outranks_hold_and_is_not_restored_as_hold
        """
        env = _lot_quarantined_after_a_quality_hold()
        lot_id = env["lot"]["id"]

        assert env["lot"]["disposition"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {env['lot']['disposition']} after the counterfeit flag"
        )
        assert env["lot"]["hold_source"] == "HEAT_COUNTERFEIT", (
            f"Expected hold_source HEAT_COUNTERFEIT, got {env['lot']['hold_source']}"
        )
        assert env["wire"]["status"] == "QUARANTINED", (
            f"Expected the wire lot QUARANTINED, got {env['wire']['status']}"
        )

        heading = api.complete_heading(
            lot_id, {"headed_count": 4900, "heading_scrap_count": 60}, engineer_headers
        )
        validate_error(heading, ApiErrorId.ERR_LOT_QUARANTINED.value)

        second_hold = api.hold_production_lot(
            lot_id, {"reason": "SECOND_HOLD_ATTEMPT"}, inspector_headers
        )
        validate_error(second_hold, ApiErrorId.ERR_LOT_QUARANTINED.value)

        release = api.release_hold(
            lot_id, {"note": "TRYING_TO_RELEASE_A_QUARANTINED_LOT"}, manager_headers
        )
        validate_error(release, ApiErrorId.ERR_LOT_QUARANTINED.value)

        frozen = fixtures.read_lot(lot_id)
        assert frozen["process_state"] == "SETUP", (
            f"Expected SETUP, got {frozen['process_state']} after three refused calls"
        )
        assert frozen["disposition"] == "QUARANTINED", (
            f"Expected QUARANTINED, got {frozen['disposition']} after three refused calls"
        )
        assert frozen["headed_count"] == 0, (
            f"Expected headed_count 0, got {frozen['headed_count']} after a refused heading report"
        )

    def test_reverification_returns_the_lot_to_in_process_without_reinstating_the_hold(
        self, api, engineer_headers
    ):
        """Clearing the counterfeit suspicion thaws the lot outright, discarding the QUALITY hold.

        PRD: "Every wire lot of the heat tagged `quarantine_source` of `HEAT_COUNTERFEIT` returns, in ascending `created_at` order, to `status` `DRAWN` with `quarantine_source` reset to `NONE` and `inspected_at` cleared — the lot goes back to being merely drawn, and a fresh inspection release is required before it can feed heading again."

        PRD: "Every production lot in `disposition` `QUARANTINED` with `hold_source` `HEAT_COUNTERFEIT` whose wire lot was among those restored returns to `disposition` `IN_PROCESS` with `hold_source` reset to `NONE`."

        Design: Corner/validations/quarantine_freeze_outranks_hold_and_is_not_restored_as_hold
        """
        env = _lot_quarantined_after_a_quality_hold()
        lot_id = env["lot"]["id"]

        fixtures.verify_heat(env["heat"]["id"], lab_report_reference="LAB-0002")

        heat = fixtures.read_heat(env["heat"]["id"])
        assert heat["cert_status"] == "VERIFIED", (
            f"Expected VERIFIED, got {heat['cert_status']} after re-verification"
        )

        wire = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire["status"] == "DRAWN", (
            f"Expected the restored wire lot DRAWN, got {wire['status']}"
        )
        assert wire["quarantine_source"] == "NONE", (
            f"Expected quarantine_source NONE, got {wire['quarantine_source']}"
        )
        assert not wire["inspected_at"], (
            f"Expected inspected_at cleared, got {wire['inspected_at']}"
        )

        thawed = fixtures.read_lot(lot_id)
        assert thawed["disposition"] == "IN_PROCESS", (
            f"Expected IN_PROCESS, got {thawed['disposition']} after the compensating cascade"
        )
        assert thawed["hold_source"] == "NONE", (
            f"Expected hold_source NONE — the operator's QUALITY hold is not reinstated — "
            f"got {thawed['hold_source']}"
        )

        resumed = validate_success(
            api.complete_heading(
                lot_id,
                {"headed_count": 4900, "heading_scrap_count": 60},
                engineer_headers,
            )
        )
        assert resumed["process_state"] == "HEADED", (
            f"Expected HEADED, got {resumed['process_state']} after the thaw"
        )
        assert resumed["headed_count"] == 4900, (
            f"Expected headed_count 4900, got {resumed['headed_count']}"
        )
        assert resumed["available_count"] == 4900, (
            f"Expected available_count 4900, got {resumed['available_count']}"
        )
        assert_lot_piece_ledger(resumed)
        assert_wire_mass_ledger(fixtures.read_wire_lot(env["wire"]["id"]))


# ---------------------------------------------------------------------------
# Thread timing, both directions
# ---------------------------------------------------------------------------
class TestThreadTimingSymmetry:
    def test_early_thread_roll_is_refused_but_a_drill_is_accepted_at_the_same_stage(
        self, api, engineer_headers
    ):
        """An AFTER_HEAT_TREAT part refuses a THREAD_ROLL queued while the lot is still HEADED.

        PRD: "A `THREAD_ROLL` operation created *after* heat treatment has completed requires `thread_timing` to be `AFTER_HEAT_TREAT`; a `THREAD_ROLL` operation created *before* heat treatment has completed requires `thread_timing` to be `BEFORE_HEAT_TREAT`."

        PRD: "Either mismatch is refused with `ERR_THREAD_TIMING_VIOLATION`."

        PRD: "The new operation is created in `status` `PENDING` with `pieces_in` taken from the lot's current `available_count` — the client never supplies it — and with `performed_after_heat_treat` capturing whether the lot's `heat_treat_completed` flag was already true at the moment of creation."

        Design: Corner/validations/thread_timing_is_checked_in_both_directions
        """
        env = _headed_lot_on_an_after_heat_treat_part()
        lot_id = env["lot"]["id"]

        early = api.queue_secondary_operation(
            lot_id,
            {"op_type": "THREAD_ROLL", "sequence_no": 1, "machine_code": "TR-1"},
            engineer_headers,
        )
        validate_error(early, ApiErrorId.ERR_THREAD_TIMING_VIOLATION.value)

        after_refusal = fixtures.read_lot(lot_id)
        assert after_refusal["process_state"] == "HEADED", (
            f"Expected HEADED, got {after_refusal['process_state']} after a refused THREAD_ROLL"
        )
        rows, pagination = validate_paginated(
            api.list_secondary_operations(lot_id, engineer_headers)
        )
        assert pagination["total_count"] == 0, (
            f"Expected no secondary operation row, got {pagination['total_count']}"
        )
        assert rows == [], f"Expected an empty operation list, got {rows}"

        drill = validate_success(
            api.queue_secondary_operation(
                lot_id,
                {"op_type": "DRILL", "sequence_no": 1, "machine_code": "DR-1"},
                engineer_headers,
            ),
            201,
        )
        assert drill["status"] == "PENDING", (
            f"Expected PENDING, got {drill['status']} on the new DRILL"
        )
        assert drill["performed_after_heat_treat"] is False, (
            "A DRILL queued before the furnace must carry performed_after_heat_treat false, "
            f"got {drill['performed_after_heat_treat']}"
        )
        assert drill["pieces_in"] == 980, (
            f"Expected pieces_in 980 from the lot's available_count, got {drill['pieces_in']}"
        )

        moved = fixtures.read_lot(lot_id)
        assert moved["process_state"] == "SECONDARY_IN_PROGRESS", (
            f"Expected SECONDARY_IN_PROGRESS, got {moved['process_state']} after queueing the DRILL"
        )

    def test_late_thread_roll_is_refused_for_a_before_heat_treat_part(
        self, api, engineer_headers
    ):
        """A BEFORE_HEAT_TREAT part refuses a THREAD_ROLL queued once the lot is HEAT_TREATED.

        PRD: "A `THREAD_ROLL` operation created *after* heat treatment has completed requires `thread_timing` to be `AFTER_HEAT_TREAT`; a `THREAD_ROLL` operation created *before* heat treatment has completed requires `thread_timing` to be `BEFORE_HEAT_TREAT`."

        PRD: "Either mismatch is refused with `ERR_THREAD_TIMING_VIOLATION`."

        Design: Corner/validations/thread_timing_is_checked_in_both_directions
        """
        env = _heat_treated_lot_on_a_before_heat_treat_part()
        lot_id = env["lot"]["id"]

        assert env["lot"]["process_state"] == "HEAT_TREATED", (
            f"Expected HEAT_TREATED, got {env['lot']['process_state']} before the trigger"
        )
        assert env["lot"]["heat_treat_completed"] is True, (
            "The lot must record heat_treat_completed true after a passing run"
        )

        late = api.queue_secondary_operation(
            lot_id,
            {"op_type": "THREAD_ROLL", "sequence_no": 2, "machine_code": "TR-1"},
            engineer_headers,
        )
        validate_error(late, ApiErrorId.ERR_THREAD_TIMING_VIOLATION.value)

        unchanged = fixtures.read_lot(lot_id)
        assert unchanged["process_state"] == "HEAT_TREATED", (
            f"Expected HEAT_TREATED, got {unchanged['process_state']} after the refusal"
        )
        _, pagination = validate_paginated(
            api.list_secondary_operations(lot_id, engineer_headers)
        )
        assert pagination["total_count"] == 1, (
            "Only the pre-furnace THREAD_ROLL may exist, "
            f"got {pagination['total_count']} operations"
        )


# ---------------------------------------------------------------------------
# Wire release state before steel-grade eligibility
# ---------------------------------------------------------------------------
def test_lot_opening_reports_the_unreleased_wire_before_the_disallowed_grade(
    api, engineer_headers
):
    """A wire lot that is both still DRAWN and of a disallowed grade answers on the release gate first.

    PRD: "Rules are evaluated in a strict ascending ladder."

    PRD: "The first rule violated decides the response, and no later rule runs."

    PRD: "The named wire lot must be in `status` `RELEASED`, or the request is refused with `ERR_WIRE_LOT_NOT_RELEASED`."

    PRD: "The wire lot's steel grade must appear in the part's `allowed_steel_grades`, or the request is refused with `ERR_GRADE_NOT_ALLOWED`."

    Design: Corner/validations/wire_release_state_is_checked_before_grade_allowance
    """
    env = fixtures.setup_master_data(
        clock=CLOCK_START,
        unplated=True,
        release_wire=False,
        spec_overrides={
            "allowed_steel_grades": ["SAE_10B21"],
            "max_decarb_depth_mm": 0.100,
            "scrap_allowance_pct": 0.05,
        },
        heat_overrides={
            "heat_number": "H-99001",
            "mill_code": "MC-B",
            "grade": "SAE_1018",
            "carbon_pct": 0.18,
            "boron_ppm": 0,
            "gross_mass_kg": 200.0,
            "mill_cert_serial": "MC-2026-000902",
        },
        wire_overrides={"gross_mass_kg": 200.0},
    )
    wire_id = env["wire"]["id"]

    def _lot_payload(expected_version):
        return {
            "lot_code": "L-2623",
            "part_spec_id": env["spec"]["id"],
            "wire_lot_id": wire_id,
            "heading_tool_id": env["tool"]["id"],
            "press_code": env["press_code"],
            "press_window_start_at": "2026-09-01T06:00:00Z",
            "press_window_end_at": "2026-09-01T10:00:00Z",
            "planned_pieces": 1000,
            "expected_wire_lot_version": expected_version,
        }

    first = api.create_production_lot(
        _lot_payload(fixtures.wire_lot_version(wire_id)), engineer_headers
    )
    validate_error(first, ApiErrorId.ERR_WIRE_LOT_NOT_RELEASED.value)

    released = fixtures.release_wire_lot(wire_id)
    assert released["status"] == "RELEASED", (
        f"Expected RELEASED, got {released['status']} after the inspection release"
    )
    assert released["reduction_pct"] == pytest.approx(27.75, abs=0.001), (
        f"Expected reduction_pct 27.75, got {released['reduction_pct']}"
    )

    second = api.create_production_lot(
        _lot_payload(fixtures.wire_lot_version(wire_id)), engineer_headers
    )
    validate_error(second, ApiErrorId.ERR_GRADE_NOT_ALLOWED.value)

    lots, pagination = validate_paginated(api.list_production_lots(engineer_headers))
    assert pagination["total_count"] == 0, (
        f"Neither refusal may create a lot, got {pagination['total_count']} lots"
    )
    assert lots == [], f"Expected no production lot rows, got {lots}"

    wire = fixtures.read_wire_lot(wire_id)
    assert wire["reserved_mass_kg"] == pytest.approx(0.0, abs=0.001), (
        f"Expected reserved_mass_kg 0.000, got {wire['reserved_mass_kg']} after two refusals"
    )
    assert wire["available_mass_kg"] == pytest.approx(200.0, abs=0.001), (
        f"Expected available_mass_kg 200.000, got {wire['available_mass_kg']}"
    )
    assert_wire_mass_ledger(wire)


# ---------------------------------------------------------------------------
# The secondary-operation queue and the two downstream gates
# ---------------------------------------------------------------------------
class TestSecondaryOperationQueueGates:
    def test_queue_refuses_a_second_pending_operation(self, api, engineer_headers):
        """Only one operation of a lot may be PENDING at a time.

        PRD: "The self-loop imposes two extra conditions: no other operation of the lot may still be in `status` `PENDING`, and the new `sequence_no` must be strictly greater than every `sequence_no` already used on the lot; a violation of either is refused with `ERR_OP_SEQUENCE_CONFLICT`."

        Design: Corner/validations/secondary_op_queue_rejects_conflicts_and_gates_the_furnace
        """
        env = _lot_with_a_half_finished_two_operation_route()
        lot_id = env["lot"]["id"]

        assert env["lot"]["process_state"] == "SECONDARY_IN_PROGRESS", (
            f"Expected SECONDARY_IN_PROGRESS, got {env['lot']['process_state']}"
        )

        while_pending = api.queue_secondary_operation(
            lot_id,
            {"op_type": "THREAD_ROLL", "sequence_no": 5, "machine_code": "TR-1"},
            engineer_headers,
        )
        validate_error(while_pending, ApiErrorId.ERR_OP_SEQUENCE_CONFLICT.value)

        _, pagination = validate_paginated(
            api.list_secondary_operations(lot_id, engineer_headers)
        )
        assert pagination["total_count"] == 1, (
            f"Only the PENDING DRILL may exist, got {pagination['total_count']} operations"
        )

    def test_queue_refuses_a_reused_sequence_number_and_accepts_a_greater_one(
        self, api, engineer_headers
    ):
        """A reused sequence number collides; an unused-but-not-greater one conflicts.

        PRD: "Every other business identifier collision reports `ERR_DUPLICATE_IDENTIFIER` (409): ... and `sequence_no` on secondary-operation queueing, unique within its production lot."

        PRD: "The self-loop imposes two extra conditions: no other operation of the lot may still be in `status` `PENDING`, and the new `sequence_no` must be strictly greater than every `sequence_no` already used on the lot; a violation of either is refused with `ERR_OP_SEQUENCE_CONFLICT`."

        PRD: "The lot absorbs the yield: its `available_count` is replaced by `pieces_out` and its `scrap_count` grows by `scrap_pieces`, keeping the piece ledger of §2.8 balanced."

        Design: Corner/validations/secondary_op_queue_rejects_conflicts_and_gates_the_furnace
        """
        env = _lot_with_a_half_finished_two_operation_route()
        lot_id = env["lot"]["id"]

        fixtures.complete_op(env["drill_op"]["id"], 975)

        after_drill = fixtures.read_lot(lot_id)
        assert after_drill["process_state"] == "SECONDARY_IN_PROGRESS", (
            "The lot may not bubble up while THREAD_ROLL has no DONE row, got "
            f"{after_drill['process_state']}"
        )
        assert after_drill["available_count"] == 975, (
            f"Expected available_count 975, got {after_drill['available_count']}"
        )
        assert_lot_piece_ledger(after_drill)

        # Reusing sequence_no 1 is an identifier collision, which the §2.10 ladder
        # decides at tier 6 — ahead of the tier-16 sequencing rule.
        reused = api.queue_secondary_operation(
            lot_id,
            {"op_type": "THREAD_ROLL", "sequence_no": 1, "machine_code": "TR-1"},
            engineer_headers,
        )
        validate_error(reused, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

        # Open a gap in the numbering with a non-required operation, closed at once so
        # that nothing of the lot is left PENDING.
        slot = fixtures.queue_op(lot_id, op_type="SLOT", sequence_no=5, machine_code="SL-1")
        fixtures.complete_op(slot["id"], 975)

        # sequence_no 3 is unused, so tier 6 is silent, and nothing is PENDING — the only
        # rule it can break is the strictly-greater condition.
        not_greater = api.queue_secondary_operation(
            lot_id,
            {"op_type": "THREAD_ROLL", "sequence_no": 3, "machine_code": "TR-1"},
            engineer_headers,
        )
        validate_error(not_greater, ApiErrorId.ERR_OP_SEQUENCE_CONFLICT.value)

        accepted = validate_success(
            api.queue_secondary_operation(
                lot_id,
                {"op_type": "THREAD_ROLL", "sequence_no": 6, "machine_code": "TR-1"},
                engineer_headers,
            ),
            201,
        )
        assert accepted["status"] == "PENDING", (
            f"Expected PENDING, got {accepted['status']} on the accepted THREAD_ROLL"
        )
        assert accepted["pieces_in"] == 975, (
            f"Expected pieces_in 975 from the lot's available_count, got {accepted['pieces_in']}"
        )
        assert accepted["sequence_no"] == 6, (
            f"Expected sequence_no 6, got {accepted['sequence_no']}"
        )

    def test_half_finished_route_answers_differently_at_the_furnace_and_at_the_test_bench(
        self, api, heat_treat_headers, inspector_headers
    ):
        """Booking a furnace reports the incomplete route; opening a test reports the lot state.

        PRD: "For a part with `thread_timing` of `BEFORE_HEAT_TREAT`, every `op_type` listed in `required_secondary_ops` must have a `DONE` operation."

        PRD: "Should a lot be charged into a furnace or opened for testing while a required operation for its stage is missing or still `PENDING`, the request is refused with `ERR_SECONDARY_OPS_INCOMPLETE`."

        PRD: "The lot must be admissible: normally its `process_state` must be `BAKED`, but a part whose `plating_spec` is `NONE` may be tested straight from `HEAT_TREATED` or from `SECONDARY_DONE` — the latter covering parts whose thread rolling ran after heat treatment — and a lot already in `TESTING` may be tested again only when every existing test of that lot came back with `result` `REJECT`."

        PRD: "Anything else is refused with `ERR_INVALID_LOT_STATE`."

        Design: Corner/validations/secondary_op_queue_rejects_conflicts_and_gates_the_furnace
        """
        env = _lot_with_a_half_finished_two_operation_route()
        lot_id = env["lot"]["id"]
        fixtures.complete_op(env["drill_op"]["id"], 975)

        booking = api.create_heat_treat_run(
            {
                "production_lot_id": lot_id,
                "furnace_id": env["furnace"]["id"],
                "window_start_at": "2026-09-01T18:00:00Z",
                "window_end_at": "2026-09-01T23:00:00Z",
                "austenitize_temp_c": 870.0,
                "quench_medium": "OIL",
                "temper_temp_c": 420.0,
                "temper_time_min": 60,
                "carbon_potential_pct": 0.42,
            },
            heat_treat_headers,
        )
        validate_error(booking, ApiErrorId.ERR_SECONDARY_OPS_INCOMPLETE.value)

        _, run_pagination = validate_paginated(
            api.list_heat_treat_runs(heat_treat_headers)
        )
        assert run_pagination["total_count"] == 0, (
            f"The refused booking may not create a run, got {run_pagination['total_count']}"
        )

        test_open = api.create_lot_test(
            {"production_lot_id": lot_id}, inspector_headers
        )
        validate_error(test_open, ApiErrorId.ERR_INVALID_LOT_STATE.value)

        lot = fixtures.read_lot(lot_id)
        assert lot["destructive_test_count"] == 0, (
            f"Expected destructive_test_count 0, got {lot['destructive_test_count']}"
        )
        assert lot["process_state"] == "SECONDARY_IN_PROGRESS", (
            f"Expected SECONDARY_IN_PROGRESS, got {lot['process_state']} after both refusals"
        )
        assert_lot_piece_ledger(lot)


# ---------------------------------------------------------------------------
# The inclusive scrap-allowance cap on heading completion
# ---------------------------------------------------------------------------
class TestScrapAllowanceCap:
    def test_reported_output_above_the_allowance_cap_is_refused(
        self, api, engineer_headers
    ):
        """5200 good plus 60 scrap exceeds the 5250-piece cap and changes nothing.

        PRD: "The reported output must also stay inside the allowance: `headed_count` plus `heading_scrap_count` may not exceed `planned_pieces` multiplied by one plus `scrap_allowance_pct`, truncated downward to a whole number of pieces, or the report is refused with `ERR_PIECE_COUNT_INVALID`."

        Design: Corner/validations/scrap_allowance_cap_is_inclusive_at_planned_times_allowance
        """
        env = _lot_in_setup_with_a_five_percent_allowance()
        lot_id = env["lot"]["id"]

        over = api.complete_heading(
            lot_id, {"headed_count": 5200, "heading_scrap_count": 60}, engineer_headers
        )
        validate_error(over, ApiErrorId.ERR_PIECE_COUNT_INVALID.value)

        lot = fixtures.read_lot(lot_id)
        assert lot["process_state"] == "SETUP", (
            f"Expected SETUP, got {lot['process_state']} after a refused heading report"
        )
        assert lot["headed_count"] == 0, (
            f"Expected headed_count 0, got {lot['headed_count']}"
        )
        assert lot["available_count"] == 0, (
            f"Expected available_count 0, got {lot['available_count']}"
        )

        wire = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire["reserved_mass_kg"] == pytest.approx(105.0, abs=0.001), (
            f"Expected reserved_mass_kg 105.000 still held, got {wire['reserved_mass_kg']}"
        )
        assert_wire_mass_ledger(wire)

        tool = fixtures.read_tool(env["tool"]["id"])
        assert tool["cumulative_pieces_current_cycle"] == 0, (
            "A refused report may not advance the die set, got "
            f"{tool['cumulative_pieces_current_cycle']}"
        )

    def test_reported_output_exactly_at_the_allowance_cap_is_accepted(
        self, api, engineer_headers
    ):
        """5190 good plus 60 scrap lands exactly on the 5250-piece cap and passes.

        PRD: "The reported output must also stay inside the allowance: `headed_count` plus `heading_scrap_count` may not exceed `planned_pieces` multiplied by one plus `scrap_allowance_pct`, truncated downward to a whole number of pieces, or the report is refused with `ERR_PIECE_COUNT_INVALID`."

        PRD: "The reported counts land: `headed_count` and `available_count` both take the reported good-piece count, while `heading_scrap_count` and `scrap_count` both take the reported scrap count."

        PRD: "The lot then snapshots its own wear picture as `tool_utilization_pct`, which is 100 multiplied by the set's new `cumulative_pieces_current_cycle`, divided by its `rated_derated_life_pieces`, rounded half up to two decimal places — note that wear is always measured against the *rated derated* budget, never against the conservative one, whatever the part's qualification programme."

        Design: Corner/validations/scrap_allowance_cap_is_inclusive_at_planned_times_allowance
        """
        env = _lot_in_setup_with_a_five_percent_allowance()
        lot_id = env["lot"]["id"]

        headed = validate_success(
            api.complete_heading(
                lot_id,
                {"headed_count": 5190, "heading_scrap_count": 60},
                engineer_headers,
            )
        )
        assert headed["process_state"] == "HEADED", (
            f"Expected HEADED, got {headed['process_state']} at the cap"
        )
        assert headed["headed_count"] == 5190, (
            f"Expected headed_count 5190, got {headed['headed_count']}"
        )
        assert headed["heading_scrap_count"] == 60, (
            f"Expected heading_scrap_count 60, got {headed['heading_scrap_count']}"
        )
        assert headed["scrap_count"] == 60, (
            f"Expected scrap_count 60, got {headed['scrap_count']}"
        )
        assert headed["available_count"] == 5190, (
            f"Expected available_count 5190, got {headed['available_count']}"
        )
        assert headed["tool_utilization_pct"] == pytest.approx(4.38, abs=0.001), (
            f"Expected tool_utilization_pct 4.38, got {headed['tool_utilization_pct']}"
        )
        assert_lot_piece_ledger(headed)

        wire = fixtures.read_wire_lot(env["wire"]["id"])
        assert wire["consumed_mass_kg"] == pytest.approx(105.0, abs=0.001), (
            f"Expected consumed_mass_kg 105.000, got {wire['consumed_mass_kg']}"
        )
        assert wire["reserved_mass_kg"] == pytest.approx(0.0, abs=0.001), (
            f"Expected reserved_mass_kg 0.000, got {wire['reserved_mass_kg']}"
        )
        assert wire["available_mass_kg"] == pytest.approx(395.0, abs=0.001), (
            f"Expected available_mass_kg 395.000, got {wire['available_mass_kg']}"
        )
        assert_wire_mass_ledger(wire)

        tool = fixtures.read_tool(env["tool"]["id"])
        assert tool["cumulative_pieces_current_cycle"] == 5250, (
            "The die set must advance by the whole reported output, got "
            f"{tool['cumulative_pieces_current_cycle']}"
        )


# ---------------------------------------------------------------------------
# Part specification drift against a pinned certificate
# ---------------------------------------------------------------------------
def test_a_revision_after_drafting_blocks_the_issue_even_once_the_value_is_restored(
    api, engineer_headers, manager_headers
):
    """Neither lot nor certificate re-pins, so a revised specification blocks signing for good.

    PRD: "A revision increments the specification's `version` by 1, and when `plating_spec` changes it re-derives both `he_bake_required` and `he_bake_min_minutes` from the new finish and the unchanged strength class."

    PRD: "Crucially, a revision never re-pins anything: production lots keep the `pinned_part_spec_version` they captured when they were opened, and certificates keep theirs."

    PRD: "The certificate's `pinned_part_spec_version` must still equal the part specification's live `version`, or the request is refused with `ERR_PART_SPEC_VERSION_DRIFT` — a specification revised since drafting forces a deliberate reissue rather than a silent re-pin."

    Design: Corner/validations/part_spec_revision_permanently_blocks_the_pinned_lot_certificate
    """
    env = fixtures.setup_drafted_certificate(
        unplated=True,
        min_measured_core_hardness_hv=322.0,
        spec_overrides={"max_decarb_depth_mm": 0.100, "scrap_allowance_pct": 0.05},
    )
    spec_id = env["spec"]["id"]
    cert_id = env["certificate"]["id"]

    assert env["certificate"]["pinned_part_spec_version"] == 1, (
        f"Expected the certificate pinned at version 1, got "
        f"{env['certificate']['pinned_part_spec_version']}"
    )
    assert env["lot"]["pinned_part_spec_version"] == 1, (
        f"Expected the lot pinned at version 1, got {env['lot']['pinned_part_spec_version']}"
    )

    revised = validate_success(
        api.revise_part_spec(spec_id, {"max_decarb_depth_mm": 0.080}, engineer_headers)
    )
    assert revised["version"] == 2, (
        f"Expected the specification at version 2, got {revised['version']}"
    )

    drifted = api.issue_certification_document(cert_id, manager_headers)
    validate_error(drifted, ApiErrorId.ERR_PART_SPEC_VERSION_DRIFT.value)

    restored = validate_success(
        api.revise_part_spec(spec_id, {"max_decarb_depth_mm": 0.100}, engineer_headers)
    )
    assert restored["version"] == 3, (
        f"Expected the specification at version 3, got {restored['version']}"
    )
    assert restored["max_decarb_depth_mm"] == pytest.approx(0.100, abs=0.0001), (
        f"Expected max_decarb_depth_mm 0.100 again, got {restored['max_decarb_depth_mm']}"
    )

    still_drifted = api.issue_certification_document(cert_id, manager_headers)
    validate_error(still_drifted, ApiErrorId.ERR_PART_SPEC_VERSION_DRIFT.value)

    cert = fixtures.read_certificate(cert_id)
    assert cert["status"] == "DRAFT", (
        f"Expected the certificate still DRAFT, got {cert['status']}"
    )
    assert cert["revision"] == 1, f"Expected revision 1, got {cert['revision']}"
    assert not cert["signed_by_user_id"], (
        f"Expected signed_by_user_id empty, got {cert['signed_by_user_id']}"
    )
    assert not cert["issued_at"], f"Expected issued_at empty, got {cert['issued_at']}"
    assert cert["pinned_part_spec_version"] == 1, (
        f"The certificate must not re-pin, got {cert['pinned_part_spec_version']}"
    )

    lot = fixtures.read_lot(env["lot"]["id"])
    assert lot["process_state"] == "TESTED", (
        f"Expected the lot still TESTED, got {lot['process_state']}"
    )

    run = fixtures.read_heat_treat_run(env["heat_treat_run"]["id"])
    assert run["total_decarb_depth_mm"] == pytest.approx(0.020, abs=0.0001), (
        f"Expected total_decarb_depth_mm 0.020, got {run['total_decarb_depth_mm']}"
    )
    assert run["result"] == "PASS", (
        f"The furnace verdict was judged against the pinned limit and must stay PASS, "
        f"got {run['result']}"
    )


# ---------------------------------------------------------------------------
# Inclusive furnace-window bounds on run start
# ---------------------------------------------------------------------------
class TestRunStartWindow:
    def test_start_one_minute_early_is_refused_and_exactly_at_the_start_succeeds(
        self, api, heat_treat_headers
    ):
        """The lower window bound is inclusive: 17:59 is refused, 18:00 charges the furnace.

        PRD: "The logical clock must lie inside the booked window — at or after `window_start_at` and at or before `window_end_at` — or the start is refused with `ERR_OUTSIDE_RUN_WINDOW`."

        PRD: "On success `started_at` is stamped from the logical clock, the furnace flips `IDLE → OCCUPIED`, and both the run's `version` and the furnace's `version` increment by 1."

        Design: Corner/validations/furnace_run_start_must_fall_inside_its_declared_window
        """
        env = _secondary_done_lot_and_a_furnace()
        run = fixtures.book_heat_treat(
            env["lot"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T18:00:00Z",
            window_end_at="2026-09-01T20:00:00Z",
        )
        assert run["charge_mass_kg"] == pytest.approx(97.0, abs=0.001), (
            f"Expected charge_mass_kg 97.000 at booking, got {run['charge_mass_kg']}"
        )

        fixtures.set_clock("2026-09-01T17:59:00Z", heat_treat_headers)
        early = api.start_heat_treat_run(run["id"], heat_treat_headers)
        validate_error(early, ApiErrorId.ERR_OUTSIDE_RUN_WINDOW.value)

        still_planned = fixtures.read_heat_treat_run(run["id"])
        assert still_planned["status"] == "PLANNED", (
            f"Expected PLANNED, got {still_planned['status']} after an early start"
        )
        assert not still_planned["started_at"], (
            f"Expected started_at empty, got {still_planned['started_at']}"
        )
        idle = fixtures.read_furnace(env["furnace"]["id"])
        assert idle["status"] == "IDLE", (
            f"A refused start may not occupy the furnace, got {idle['status']}"
        )

        fixtures.set_clock("2026-09-01T18:00:00Z", heat_treat_headers)
        started = validate_success(
            api.start_heat_treat_run(run["id"], heat_treat_headers)
        )
        assert started["status"] == "RUNNING", (
            f"Expected RUNNING at exactly window_start_at, got {started['status']}"
        )
        assert started["started_at"].startswith("2026-09-01T18:00:00"), (
            f"Expected started_at stamped at 18:00:00Z, got {started['started_at']}"
        )
        occupied = fixtures.read_furnace(env["furnace"]["id"])
        assert occupied["status"] == "OCCUPIED", (
            f"Expected OCCUPIED after the start, got {occupied['status']}"
        )

    def test_a_run_whose_window_has_closed_can_never_be_started(
        self, api, heat_treat_headers
    ):
        """The upper window bound is inclusive too: a window that ended at 07:00 is dead at 08:00.

        PRD: "The logical clock must lie inside the booked window — at or after `window_start_at` and at or before `window_end_at` — or the start is refused with `ERR_OUTSIDE_RUN_WINDOW`."

        Design: Corner/validations/furnace_run_start_must_fall_inside_its_declared_window
        """
        env = _secondary_done_lot_and_a_furnace()
        run = fixtures.book_heat_treat(
            env["lot"]["id"],
            env["furnace"]["id"],
            window_start_at="2026-09-01T06:00:00Z",
            window_end_at="2026-09-01T07:00:00Z",
        )
        assert run["charge_mass_kg"] == pytest.approx(97.0, abs=0.001), (
            f"Expected charge_mass_kg 97.000 at booking, got {run['charge_mass_kg']}"
        )

        fixtures.set_clock("2026-09-01T08:00:00Z", heat_treat_headers)
        late = api.start_heat_treat_run(run["id"], heat_treat_headers)
        validate_error(late, ApiErrorId.ERR_OUTSIDE_RUN_WINDOW.value)

        stalled = fixtures.read_heat_treat_run(run["id"])
        assert stalled["status"] == "PLANNED", (
            f"Expected PLANNED, got {stalled['status']} after the window closed"
        )
        assert stalled["result"] == "PENDING", (
            f"Expected result PENDING, got {stalled['result']}"
        )
        furnace = fixtures.read_furnace(env["furnace"]["id"])
        assert furnace["status"] == "IDLE", (
            f"A refused start may not occupy the furnace, got {furnace['status']}"
        )
        lot = fixtures.read_lot(env["lot"]["id"])
        assert lot["process_state"] == "SECONDARY_DONE", (
            f"Expected the lot still SECONDARY_DONE, got {lot['process_state']}"
        )
