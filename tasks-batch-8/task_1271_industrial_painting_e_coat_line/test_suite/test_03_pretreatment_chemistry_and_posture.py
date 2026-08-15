"""Pretreatment titration, the stage compliance loop, and line posture cascades."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_adjustment_payload,
    create_customer, create_spec, create_paint_line, create_stage,
    setup_line_with_stage, setup_master_data, setup_lot_scheduled,
    create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx,
    drive_stage_out_of_range, drive_stage_in_range_reading, record_adjustment,
    get_line, get_stage,
    TEST_USERS, make_chemist_headers, make_scheduler_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestStageComplianceCycle:
    def test_full_compliance_loop_closes_back_to_in_range(self, api):
        """PRD §3.2: "The only cycle is `IN_RANGE → OUT_OF_RANGE → ADJUSTING →
        IN_RANGE`, possibly looping through `ADJUSTING → OUT_OF_RANGE` on the way."

        Design: Difficulty/non_linear_state_machine/pretreatment_stage_compliance_cycle
        """
        line, stage = setup_line_with_stage()
        rd_low = drive_stage_out_of_range(stage["id"], measured=19.9)
        assert rd_low["in_range"] is False
        assert get_stage(stage["id"])["status"] == "OUT_OF_RANGE"
        assert get_line(line["id"])["posture"] == "CHEM_HOLD"

        record_adjustment(stage["id"], chemical_added_kg=2.5)
        assert get_stage(stage["id"])["status"] == "ADJUSTING"
        assert get_line(line["id"])["posture"] == "CHEM_HOLD"

        rd_ok = drive_stage_in_range_reading(stage["id"], measured=25.0)
        assert rd_ok["in_range"] is True
        assert get_stage(stage["id"])["status"] == "IN_RANGE"
        assert get_line(line["id"])["posture"] == "RUNNING"

    def test_adjusting_stage_pushed_back_out_of_range_keeps_line_on_hold(self, api):
        """PRD §3.2: "An out-of-range reading recorded against an `ADJUSTING` stage
        pushes the stage back to `OUT_OF_RANGE`, and the line stays on `CHEM_HOLD`."

        Design: Difficulty/non_linear_state_machine/pretreatment_stage_compliance_cycle
        """
        line, stage = setup_line_with_stage()
        drive_stage_out_of_range(stage["id"], measured=19.9)
        record_adjustment(stage["id"], chemical_added_kg=2.5)
        assert get_stage(stage["id"])["status"] == "ADJUSTING"

        rd_low2 = drive_stage_out_of_range(stage["id"], measured=35.0)
        assert rd_low2["in_range"] is False
        assert get_stage(stage["id"])["status"] == "OUT_OF_RANGE"
        assert get_line(line["id"])["posture"] == "CHEM_HOLD"


class TestInRangeReadingWhileOutOfRange:
    def test_in_range_reading_does_not_skip_the_adjustment_step(self, api):
        """PRD §3.2: "And a reading recorded while a stage sits `OUT_OF_RANGE` never
        returns the stage to `IN_RANGE` on its own, even if the value lands inside the
        band: passing through the recorded adjustment is mandatory."

        Design: Corner/state_machines/stage_in_range_reading_while_out_of_range_stays_out
        """
        line, stage = setup_line_with_stage()
        drive_stage_out_of_range(stage["id"], measured=19.9)

        rd_ok = drive_stage_in_range_reading(stage["id"], measured=25.0)
        assert rd_ok["in_range"] is True
        assert get_stage(stage["id"])["status"] == "OUT_OF_RANGE"
        assert get_line(line["id"])["posture"] == "CHEM_HOLD"


class TestAdjustmentStateGuard:
    def test_adjustment_on_in_range_stage_rejected(self, api):
        """PRD §3.2: "A `ProcessChemist` records a chemical addition by supplying
        `chemical_added_kg`; this is permitted only while the stage is `OUT_OF_RANGE`
        (otherwise `ERR_INVALID_STATE`) and moves the stage to `ADJUSTING`, with the
        line remaining on `CHEM_HOLD` throughout."

        Design: Corner/errors/adjustment_on_in_range_stage_returns_invalid_state
        """
        line, stage = setup_line_with_stage()
        res = api.record_adjustment(
            stage["id"], create_adjustment_payload(chemical_added_kg=1.0),
            make_chemist_headers("chem-1"),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_stage(stage["id"])["status"] == "IN_RANGE"


class TestTitrationCascadeBlocksSlotStart:
    def test_out_of_range_reading_flips_posture_and_blocks_start(self, api):
        """PRD §2.9: "The line's `posture` is `CHEM_HOLD` while any of its pretreatment
        stages is `OUT_OF_RANGE` or `ADJUSTING`, and `RUNNING` only when every stage is
        `IN_RANGE`."
        PRD §3.5: "The slot must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and —
        the runtime counterpart of the scheduling gate — the line's `posture` must be
        `RUNNING`; attempting to start while the line sits on `CHEM_HOLD` is rejected
        with `ERR_LINE_ON_CHEM_HOLD`."

        Design: Difficulty/transitive_cascade/titration_out_of_range_cascade_blocks_slot_start
        """
        ctx = setup_lot_scheduled()
        drive_stage_out_of_range(ctx["stage"]["id"], measured=35.0)
        assert get_stage(ctx["stage"]["id"])["status"] == "OUT_OF_RANGE"
        assert get_line(ctx["line"]["id"])["posture"] == "CHEM_HOLD"

        res = api.start_run_slot(ctx["slot"]["id"], SCHED)
        validate_error(res, "ERR_LINE_ON_CHEM_HOLD", expected_status=409)
        slot_after = validate_success(api.get_run_slot(ctx["slot"]["id"], SCHED), 200)
        assert slot_after["status"] == "SCHEDULED"

    def test_start_succeeds_once_chemistry_returns_in_range(self, api):
        """PRD §3.2: "An in-range reading recorded against an `ADJUSTING` stage returns
        the stage to `IN_RANGE`; if no other stage of the line remains `OUT_OF_RANGE` or
        `ADJUSTING`, the same request restores the line's `posture` to `RUNNING` and
        increments the line's `version`."
        PRD §3.5: "The slot must be `SCHEDULED` (otherwise `ERR_INVALID_STATE`), and —
        the runtime counterpart of the scheduling gate — the line's `posture` must be
        `RUNNING`; attempting to start while the line sits on `CHEM_HOLD` is rejected
        with `ERR_LINE_ON_CHEM_HOLD`."

        Design: Difficulty/transitive_cascade/titration_out_of_range_cascade_blocks_slot_start
        """
        ctx = setup_lot_scheduled()
        drive_stage_out_of_range(ctx["stage"]["id"], measured=35.0)
        res = api.start_run_slot(ctx["slot"]["id"], SCHED)
        validate_error(res, "ERR_LINE_ON_CHEM_HOLD", expected_status=409)

        record_adjustment(ctx["stage"]["id"], chemical_added_kg=2.5)
        drive_stage_in_range_reading(ctx["stage"]["id"], measured=25.0)
        assert get_line(ctx["line"]["id"])["posture"] == "RUNNING"

        started = validate_success(api.start_run_slot(ctx["slot"]["id"], SCHED), 200)
        assert started["status"] == "RUNNING"


class TestSchedulingGateByStageState:
    def test_schedule_rejected_while_stage_out_of_range(self, api):
        """PRD §3.4: "Then the chemical gate requires every pretreatment stage of the
        line to be `IN_RANGE` — a single out-of-range or adjusting stage blocks
        scheduling with `ERR_STAGE_OUT_OF_RANGE`."

        Design: Difficulty/cross_entity_state_dependency/run_slot_blocked_by_pretreatment_stage_state
        """
        ctx = setup_master_data()
        lot = create_and_accept_lot_in_ctx(ctx)
        drive_stage_out_of_range(ctx["stage"]["id"], measured=19.9)
        assert get_line(ctx["line"]["id"])["posture"] == "CHEM_HOLD"

        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_STAGE_OUT_OF_RANGE", expected_status=409)
        lot_after = validate_success(api.get_lot(lot["id"], SCHED), 200)
        assert lot_after["status"] == "QUEUED"

    def test_schedule_rejected_while_stage_adjusting(self, api):
        """PRD §3.4: "Then the chemical gate requires every pretreatment stage of the
        line to be `IN_RANGE` — a single out-of-range or adjusting stage blocks
        scheduling with `ERR_STAGE_OUT_OF_RANGE`."

        Design: Difficulty/cross_entity_state_dependency/run_slot_blocked_by_pretreatment_stage_state
        """
        ctx = setup_master_data()
        lot = create_and_accept_lot_in_ctx(ctx)
        drive_stage_out_of_range(ctx["stage"]["id"], measured=19.9)
        record_adjustment(ctx["stage"]["id"], chemical_added_kg=2.5)
        assert get_stage(ctx["stage"]["id"])["status"] == "ADJUSTING"

        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_STAGE_OUT_OF_RANGE", expected_status=409)
        lot_after = validate_success(api.get_lot(lot["id"], SCHED), 200)
        assert lot_after["status"] == "QUEUED"
