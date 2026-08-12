"""Run-slot lifecycle, half-open overlap, metered VOC posting, and line-speed gating."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_master_data, setup_lot_scheduled, setup_lot_curing,
    create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx, schedule_slot,
    get_lot, get_line, get_permit,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestHalfOpenOverlap:
    def test_adjacent_slot_allowed_and_overlapping_slot_rejected(self, api):
        """PRD §3.4: "Two slots on the same line may not occupy the line at once. Among
        slots in `SCHEDULED` or `RUNNING` status, a conflict exists when the existing
        slot starts before the new window ends and the new window starts before the
        existing slot ends — half-open interval semantics, so a new slot beginning
        exactly when an existing one ends is legal adjacency. A genuine collision is
        rejected with `ERR_RUN_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/run_slot_half_open_adjacency_allowed
        """
        ctx = setup_master_data()
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)
        lot_c = create_and_accept_lot_in_ctx(ctx)

        slot_a = schedule_slot(ctx["line"]["id"], lot_a["id"],
                               "2026-05-05T08:00:00Z", "2026-05-05T10:00:00Z")
        assert slot_a["status"] == "SCHEDULED"

        # Adjacent: starts exactly when slot A ends — half-open adjacency is legal.
        slot_b = schedule_slot(ctx["line"]["id"], lot_b["id"],
                               "2026-05-05T10:00:00Z", "2026-05-05T12:00:00Z")
        assert slot_b["status"] == "SCHEDULED"

        # True collision: 09:59 start overlaps slot A's [08:00, 10:00) window.
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot_c["id"],
                start_utc="2026-05-05T09:59:00Z", end_utc="2026-05-05T11:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_RUN_SLOT_OVERLAP", expected_status=409)

    def test_completed_slot_no_longer_blocks_the_window(self, api):
        """PRD §3.4: "Two slots on the same line may not occupy the line at once. Among
        slots in `SCHEDULED` or `RUNNING` status, a conflict exists when the existing
        slot starts before the new window ends and the new window starts before the
        existing slot ends — half-open interval semantics, so a new slot beginning
        exactly when an existing one ends is legal adjacency. A genuine collision is
        rejected with `ERR_RUN_SLOT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/run_slot_half_open_adjacency_allowed
        """
        ctx = setup_lot_curing()  # slot COMPLETED over 2026-05-05 08:00-10:00
        lot_b = create_and_accept_lot_in_ctx(ctx)
        slot_b = schedule_slot(ctx["line"]["id"], lot_b["id"],
                               "2026-05-05T08:30:00Z", "2026-05-05T09:30:00Z")
        assert slot_b["status"] == "SCHEDULED"


class TestSlotTerminalLockdown:
    def test_cancel_completed_slot_rejected_and_emission_not_reversed(self, api):
        """PRD §3.5: "Cancelling a slot, available only from `SCHEDULED`, moves it to
        the terminal `CANCELLED`, returns the lot to `QUEUED` so it can be scheduled
        again, and releases the reservation by the same `voc_projected_kg` amount — the
        compensating action that keeps `reserved_kg` conserved."

        Design: Corner/state_machines/run_slot_cancel_completed_returns_invalid_state
        """
        ctx = setup_lot_curing(paint_used_liters=0.95)  # metered entry 0.304 kg posted
        res = api.cancel_run_slot(ctx["slot"]["id"], SCHED)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        permit_after = get_permit(ctx["permit"]["id"])
        assert permit_after["used_kg"] == pytest.approx(0.304, abs=1e-9)
        lot_after = get_lot(ctx["lot"]["id"])
        assert lot_after["status"] == "CURING"


class TestLineSpeedGate:
    def test_set_line_speed_rejected_while_slot_running_then_allowed(self, api):
        """PRD §3.1: "Later, a `LineScheduler` may change the conveyor speed by
        supplying a new `line_speed_fpm`, but only while no run slot of that line is
        `RUNNING`; the attempt during a running slot is rejected with `ERR_LINE_BUSY`,
        and a successful change increments the line's `version`."

        Design: Corner/errors/set_line_speed_while_running_returns_line_busy
        """
        ctx = setup_lot_scheduled()
        validate_success(api.start_run_slot(ctx["slot"]["id"], SCHED), 200)

        res = api.set_line_speed(ctx["line"]["id"], {"line_speed_fpm": 12.0}, SCHED)
        validate_error(res, "ERR_LINE_BUSY", expected_status=409)

        validate_success(
            api.complete_run_slot(ctx["slot"]["id"], {"paint_used_liters": 0.95}, SCHED), 200
        )
        updated = validate_success(
            api.set_line_speed(ctx["line"]["id"], {"line_speed_fpm": 12.0}, SCHED), 200
        )
        assert updated["line_speed_fpm"] == pytest.approx(12.0, abs=1e-9)
