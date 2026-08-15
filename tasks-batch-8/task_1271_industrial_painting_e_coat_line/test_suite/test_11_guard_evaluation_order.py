"""Guard evaluation order (PRD §2.6): earlier-rung failures mask later checks."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_master_data,
    create_lot_payload, create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx,
    schedule_slot, drive_stage_out_of_range,
    get_line,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]


class TestStateBeforeChemicalSafety:
    def test_lot_not_queued_masks_stage_out_of_range(self, api):
        """PRD §2.6: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order, and a failure at an earlier rung
        masks every later check."
        PRD §2.6: "6. **State preconditions** — the target resources are in a state
        that allows the operation: a lot `QUEUED` for scheduling, a slot `SCHEDULED`
        for start or cancel, a slot `RUNNING` for completion, a rework order `DRAFT`
        for approval or `APPROVED` for strip completion, a specification `ACTIVE` at
        lot acceptance, a permit period live at close, a recheck parent failed and
        childless, no slot running while line speed is changed, cure passed before
        testing, tests complete before release"
        PRD §2.6: "7. **Chemical safety gate** — every pretreatment stage of the line
        must be `IN_RANGE` to schedule a run slot (`ERR_STAGE_OUT_OF_RANGE`), and the
        line's posture must be `RUNNING` to start one (`ERR_LINE_ON_CHEM_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/slot_create_state_error_precedes_chem_safety_error
        """
        ctx = setup_master_data()
        # Lot booked but never accepted -> RECEIVED (state rung violated).
        lot = validate_success(
            api.create_lot(
                create_lot_payload(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=100),
                SCHED,
            ),
            201,
        )
        # Drive the stage OUT_OF_RANGE (safety rung also violated).
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
        validate_error(res, "ERR_LOT_NOT_QUEUED", expected_status=409)

    def test_state_rung_alone_reports_same_error(self, api):
        """PRD §3.4: "With the concurrency guard satisfied, the state guard requires
        the lot to be `QUEUED`; scheduling anything else is rejected with
        `ERR_LOT_NOT_QUEUED`."

        Design: Difficulty/priority_pair_validation_conflict/slot_create_state_error_precedes_chem_safety_error
        """
        ctx = setup_master_data()
        lot = validate_success(
            api.create_lot(
                create_lot_payload(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=100),
                SCHED,
            ),
            201,
        )
        # Chemistry healthy — only the state rung is violated.
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_LOT_NOT_QUEUED", expected_status=409)


class TestTemporalBeforeFiscal:
    def test_overlap_masks_voc_cap_exceeded(self, api):
        """PRD §2.6: "When several checks could reject the same request, the server
        evaluates them in a fixed priority order, and a failure at an earlier rung
        masks every later check."
        PRD §2.6: "8. **Interval conflicts** — run-slot half-open overlap
        (`ERR_RUN_SLOT_OVERLAP`), buffered color-change window conflict
        (`ERR_COLOR_CHANGE_CONFLICT`), and oven aggregate capacity on closed intervals
        (`ERR_OVEN_CAPACITY_FULL`)."
        PRD §2.6: "10. **VOC permit fiscal checks** — a covering non-closed permit
        exists (`ERR_NO_ACTIVE_PERMIT`) and the projected emission fits under the cap
        (`ERR_VOC_CAP_EXCEEDED`)."

        Design: Difficulty/priority_pair_validation_conflict/slot_create_overlap_precedes_voc_cap_error
        """
        ctx = setup_master_data(permit_overrides={"cap_kg": 0.3})
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)

        # Slot A reserved ~0.277 kg against the 0.3 kg cap.
        slot_a = schedule_slot(ctx["line"]["id"], lot_a["id"],
                               "2026-05-05T08:00:00Z", "2026-05-05T10:00:00Z")
        assert slot_a["status"] == "SCHEDULED"

        # Slot B both overlaps slot A (09:00 < 10:00) and would push the projection
        # over the cap (0.277 + 0.277 = 0.554 > 0.30): the temporal rung wins.
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot_b["id"],
                start_utc="2026-05-05T09:00:00Z", end_utc="2026-05-05T11:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_RUN_SLOT_OVERLAP", expected_status=409)

    def test_voc_cap_alone_reports_fiscal_error(self, api):
        """PRD §2.6: "10. **VOC permit fiscal checks** — a covering non-closed permit
        exists (`ERR_NO_ACTIVE_PERMIT`) and the projected emission fits under the cap
        (`ERR_VOC_CAP_EXCEEDED`)."
        PRD §3.4: "if the resulting sum of `used_kg`, `reserved_kg`, and the new
        projection exceeds `cap_kg` — strictly exceeds, since landing exactly on the
        cap is allowed — the create is rejected with `ERR_VOC_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/slot_create_overlap_precedes_voc_cap_error
        """
        ctx = setup_master_data(permit_overrides={"cap_kg": 0.3})
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)

        slot_a = schedule_slot(ctx["line"]["id"], lot_a["id"],
                               "2026-05-05T08:00:00Z", "2026-05-05T10:00:00Z")
        assert slot_a["status"] == "SCHEDULED"

        # Slot B is adjacent (no overlap); only the fiscal rung can fire.
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot_b["id"],
                start_utc="2026-05-05T10:00:00Z", end_utc="2026-05-05T12:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_VOC_CAP_EXCEEDED", expected_status=409)
