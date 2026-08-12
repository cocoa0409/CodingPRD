"""Downtime windows and staged shipment planning: half-open overlap with
adjacency allowed, empty-window rejection, the window lock ratchet, closed-bounds
containment, and the two-day sibling gap."""

import test_helpers as fx
from test_helpers import (
    LOGISTICS,
    ApiErrorId,
    create_downtime_window_payload,
    create_shipment_stage_payload,
    validate_error,
    validate_success,
)

WINDOW_START = "2026-06-01T00:00:00Z"
WINDOW_END = "2026-07-01T00:00:00Z"


def _window(api, customer_id, starts_at, ends_at):
    return api.create_downtime_window(
        create_downtime_window_payload(customer_id, starts_at=starts_at, ends_at=ends_at),
        LOGISTICS,
    )


class TestDowntimeWindowOverlapHalfOpen:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "The new window must also not overlap any other window of the same customer whose `status` is `OPEN` or `LOCKED`: under half-open semantics, two intervals overlap when each starts strictly before the other ends, and any such overlap is rejected with `ERR_WINDOW_OVERLAP`; mere adjacency — one window's `starts_at` exactly equal to the other's `ends_at`, or vice versa — is permitted."
        PRD §3.5: "A window is born `OPEN`."

        Design: Difficulty/resource_temporal_overlap/downtime_window_overlap_half_open_adjacency
        """
        customer = fx.create_customer()
        first = validate_success(_window(api, customer["id"], WINDOW_START, WINDOW_END), 201)
        assert first["status"] == "OPEN"

        overlap = _window(api, customer["id"], "2026-06-15T00:00:00Z", "2026-07-15T00:00:00Z")
        validate_error(overlap, ApiErrorId.ERR_WINDOW_OVERLAP.value)

    def test_adjacency_allowed_and_zero_length_rejected(self, api):
        """PRD §3.5: "The new window must also not overlap any other window of the same customer whose `status` is `OPEN` or `LOCKED`: under half-open semantics, two intervals overlap when each starts strictly before the other ends, and any such overlap is rejected with `ERR_WINDOW_OVERLAP`; mere adjacency — one window's `starts_at` exactly equal to the other's `ends_at`, or vice versa — is permitted."
        PRD §3.5: "An `ends_at` that is not strictly after `starts_at`, including a zero-length window, is rejected with `ERR_WINDOW_EMPTY`."

        Design: Difficulty/resource_temporal_overlap/downtime_window_overlap_half_open_adjacency
        """
        customer = fx.create_customer()
        validate_success(_window(api, customer["id"], WINDOW_START, WINDOW_END), 201)

        # Adjacent: starts exactly at the existing window's ends_at -> permitted.
        adjacent = validate_success(
            _window(api, customer["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z"), 201
        )
        assert adjacent["status"] == "OPEN"

        # Zero-length: ends_at == starts_at -> rejected.
        empty = _window(api, customer["id"], "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z")
        validate_error(empty, ApiErrorId.ERR_WINDOW_EMPTY.value)


class TestShipmentStageGapBuffer:
    def _decided_project_with_window(self):
        ctx = fx.setup_project_decided()
        window = fx.create_window(ctx.customer["id"])
        return ctx, window

    def _stage(self, api, project_id, window_id, sequence, ship, ret):
        return api.create_shipment_stage(
            project_id,
            create_shipment_stage_payload(
                window_id, stage_sequence=sequence,
                planned_ship_date=ship, planned_return_date=ret,
            ),
            LOGISTICS,
        )

    def test_sibling_gap_one_day_rejected_exactly_two_days_allowed(self, api):
        """PRD §3.5: "Finally, the sibling-gap rule keeps staged shipments apart: against every other non-`CANCELLED` stage of the same project, either this stage's `planned_ship_date` must be at least two full days after that sibling's `planned_return_date`, or the sibling's `planned_ship_date` must be at least two full days after this stage's `planned_return_date`."
        PRD §3.5: "A gap of exactly two days is allowed; a gap one day shorter is rejected with `ERR_STAGE_GAP_TOO_SMALL`."
        PRD §3.5: "A stage is born `PLANNED`, and its creation is the act that locks its window."

        Design: Difficulty/resource_temporal_overlap/shipment_stage_gap_buffer_semantics
        """
        ctx, window = self._decided_project_with_window()

        stage_a = validate_success(
            self._stage(api, ctx.project["id"], window["id"], 1,
                        "2026-06-10T00:00:00Z", "2026-06-15T00:00:00Z"),
            201,
        )
        assert stage_a["status"] == "PLANNED"
        assert fx.get_window(window["id"])["status"] == "LOCKED"

        # One-day gap after stage A's return (06-15 -> 06-16): rejected.
        too_close = self._stage(api, ctx.project["id"], window["id"], 2,
                                "2026-06-16T00:00:00Z", "2026-06-20T00:00:00Z")
        validate_error(too_close, ApiErrorId.ERR_STAGE_GAP_TOO_SMALL.value)

        # Exactly two full days (06-15 -> 06-17): allowed.
        stage_b = validate_success(
            self._stage(api, ctx.project["id"], window["id"], 2,
                        "2026-06-17T00:00:00Z", "2026-06-25T00:00:00Z"),
            201,
        )
        assert stage_b["status"] == "PLANNED"

    def test_containment_closed_bounds_and_outside_window_rejected(self, api):
        """PRD §3.5: "Containment is then checked with closed bounds on both ends: the window's `starts_at` must be at or before the `planned_ship_date`, and the `planned_return_date` must be at or before the window's `ends_at`; any breach is rejected with `ERR_STAGE_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/shipment_stage_gap_buffer_semantics
        """
        ctx, window = self._decided_project_with_window()
        validate_success(
            self._stage(api, ctx.project["id"], window["id"], 1,
                        "2026-06-10T00:00:00Z", "2026-06-15T00:00:00Z"),
            201,
        )
        validate_success(
            self._stage(api, ctx.project["id"], window["id"], 2,
                        "2026-06-17T00:00:00Z", "2026-06-25T00:00:00Z"),
            201,
        )

        # Ships before the window starts: containment breach.
        outside = self._stage(api, ctx.project["id"], window["id"], 3,
                              "2026-05-30T00:00:00Z", "2026-06-05T00:00:00Z")
        validate_error(outside, ApiErrorId.ERR_STAGE_OUTSIDE_WINDOW.value)

        # Return exactly at the window's ends_at: closed bounds make it legal,
        # and the gap to the 06-25 sibling is exactly two days.
        stage_d = validate_success(
            self._stage(api, ctx.project["id"], window["id"], 3,
                        "2026-06-27T00:00:00Z", "2026-07-01T00:00:00Z"),
            201,
        )
        assert stage_d["status"] == "PLANNED"


def test_window_cancel_locked_rejected(api):
    """PRD §3.5: "The first shipment stage that references it locks it, moving it to `LOCKED`, which is a one-way ratchet: a `LOCKED` window can no longer be cancelled, while an `OPEN` window may be cancelled to `CANCELLED` by its customer or a logistics coordinator (attempting to cancel a window that is not `OPEN` fails with `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/window_cancel_locked_rejected
    """
    ctx = fx.setup_project_decided()
    window = fx.create_window(ctx.customer["id"])
    fx.create_stage(ctx.project["id"], window["id"])
    assert fx.get_window(window["id"])["status"] == "LOCKED"

    res = api.cancel_downtime_window(window["id"], LOGISTICS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    assert fx.get_window(window["id"])["status"] == "LOCKED"


def test_stage_ship_before_acceptance_rejected(api):
    """PRD §3.5: "Shipping a stage — `PLANNED` to `SHIPPED` — is permitted only while the project's `work_status` is `ACCEPTED`, `TRAINING_IN_PROGRESS`, or `HANDOVER_READY`; shipping at any other time fails with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/stage_ship_before_acceptance_rejected
    """
    ctx = fx.setup_project_awaiting_acceptance()
    window = fx.create_window(ctx.customer["id"])
    stage = fx.create_stage(ctx.project["id"], window["id"])

    res = api.ship_stage(stage["id"], LOGISTICS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    assert fx.get_stage(stage["id"])["status"] == "PLANNED"
