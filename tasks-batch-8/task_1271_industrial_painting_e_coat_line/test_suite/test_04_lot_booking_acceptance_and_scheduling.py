"""Lot booking/acceptance/cancel lifecycle and run-slot scheduling gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_lot, assert_run_slot,
    create_customer_payload, create_coating_spec_payload, create_lot_payload,
    create_customer, create_spec, create_paint_line, create_stage,
    setup_master_data, setup_lot_scheduled, setup_lot_running, setup_lot_curing,
    create_and_accept_lot_in_ctx, create_run_slot_payload_for_ctx,
    schedule_slot, accept_lot, get_lot, get_line,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestAcceptanceGuards:
    def test_accept_with_superseded_spec_rejected(self, api):
        """PRD §3.3: "Two guards apply, in guard-ladder order: the lot must actually be
        in `RECEIVED` (any other status draws `ERR_INVALID_STATE`), and its
        specification must still be `ACTIVE` — a lot booked against a spec that has
        since been superseded is refused with `ERR_SPEC_NOT_ACTIVE`."

        Design: Corner/entities/accept_with_superseded_spec_returns_not_active
        """
        customer = create_customer()
        spec_a = create_spec(customer["id"], color_code="RAL9005")
        # Supersede spec A with a second spec for the same (customer, color) pair.
        create_spec(customer["id"], color_code="RAL9005", film_build_min_um=20.0,
                    film_build_max_um=26.0)
        lot = validate_success(
            api.create_lot(create_lot_payload(customer["id"], spec_a["id"], part_quantity=10), SCHED),
            201,
        )
        res = api.accept_lot(lot["id"], SCHED)
        validate_error(res, "ERR_SPEC_NOT_ACTIVE", expected_status=409)
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "RECEIVED"

    def test_accept_a_second_time_rejected_as_invalid_state(self, api):
        """PRD §3.3: "Two guards apply, in guard-ladder order: the lot must actually be
        in `RECEIVED` (any other status draws `ERR_INVALID_STATE`), and its
        specification must still be `ACTIVE` — a lot booked against a spec that has
        since been superseded is refused with `ERR_SPEC_NOT_ACTIVE`."

        Design: Corner/entities/accept_with_superseded_spec_returns_not_active
        """
        ctx = setup_master_data(with_oven=False, with_permit=False)
        lot = create_and_accept_lot_in_ctx(ctx)
        assert lot["status"] == "QUEUED"
        res = api.accept_lot(lot["id"], SCHED)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestBaseChargeAtAccept:
    def test_accept_computes_base_charge(self, api):
        """PRD §3.3: "Acceptance prices the base coat: the per-part charge is the
        spec's `area_dm2_per_part` multiplied by the base coat rate of 110 cents per
        square decimeter, rounded half-up to a whole cent first, and that per-part
        amount is then multiplied by `part_quantity` to produce `base_charge_cents`."

        Design: Corner/calculations/base_charge_computed_at_accept
        """
        ctx = setup_master_data(with_oven=False, with_permit=False)
        lot = validate_success(
            api.create_lot(
                create_lot_payload(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=100),
                SCHED,
            ),
            201,
        )
        assert lot["base_charge_cents"] == 0
        accepted = validate_success(api.accept_lot(lot["id"], SCHED), 200)
        assert accepted["status"] == "QUEUED"
        # 100 parts x round_half_up(12.0 dm2 x 110 cents) = 132000.
        assert accepted["base_charge_cents"] == 132000


class TestLotCancellation:
    def test_cancel_from_received_then_terminal_lockdown(self, api):
        """PRD §3.3: "A lot that will not run can be cancelled, moving it to the
        terminal `CANCELLED` status — but only from `RECEIVED` or `QUEUED`."

        Design: Corner/state_machines/lot_cancel_then_terminal_lockdown
        """
        ctx = setup_master_data(with_oven=False, with_permit=False)
        lot = validate_success(
            api.create_lot(
                create_lot_payload(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=10),
                SCHED,
            ),
            201,
        )
        cancelled = validate_success(api.cancel_lot(lot["id"], SCHED), 200)
        assert cancelled["status"] == "CANCELLED"
        res = api.cancel_lot(lot["id"], SCHED)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_cancel_from_queued_succeeds(self, api):
        """PRD §3.3: "A lot that will not run can be cancelled, moving it to the
        terminal `CANCELLED` status — but only from `RECEIVED` or `QUEUED`."

        Design: Corner/state_machines/lot_cancel_then_terminal_lockdown
        """
        ctx = setup_master_data(with_oven=False, with_permit=False)
        lot = create_and_accept_lot_in_ctx(ctx)
        assert lot["status"] == "QUEUED"
        cancelled = validate_success(api.cancel_lot(lot["id"], SCHED), 200)
        assert cancelled["status"] == "CANCELLED"


class TestReleaseStateGuard:
    def test_release_from_received_rejected(self, api):
        """PRD §3.6: "The lot must be in `QC_PENDING` (otherwise `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/lot_release_from_received_returns_invalid_state
        """
        ctx = setup_master_data(with_oven=False, with_permit=False)
        lot = validate_success(
            api.create_lot(
                create_lot_payload(ctx["customer"]["id"], ctx["spec"]["id"], part_quantity=10),
                SCHED,
            ),
            201,
        )
        res = api.release_lot(lot["id"], TEST_USERS["qm_headers"])
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "RECEIVED"


class TestSchedulingGuards:
    def test_color_mismatch_rejected(self, api):
        """PRD §3.4: "The process constraints follow: the lot's specification color
        must equal the line's `current_color_code`, since the tank can only coat the
        color it holds, else `ERR_COLOR_MISMATCH` and a color changeover (§3.8) must
        happen first; and `parts_per_hanger` must be at least 1 and no more than the
        line's `hanger_capacity_parts`, with an excess rejected as
        `ERR_HANGER_DENSITY_EXCEEDED`."

        Design: Corner/validations/color_mismatch_rejected
        """
        ctx = setup_master_data(spec_overrides={"color_code": "RAL1018"})
        # Line carries the default RAL9005; the spec is RAL1018.
        lot = create_and_accept_lot_in_ctx(ctx)
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_COLOR_MISMATCH", expected_status=409)
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "QUEUED"

    def test_hanger_density_boundary_60_allowed_61_rejected(self, api):
        """PRD §3.4: "The process constraints follow: the lot's specification color
        must equal the line's `current_color_code`, since the tank can only coat the
        color it holds, else `ERR_COLOR_MISMATCH` and a color changeover (§3.8) must
        happen first; and `parts_per_hanger` must be at least 1 and no more than the
        line's `hanger_capacity_parts`, with an excess rejected as
        `ERR_HANGER_DENSITY_EXCEEDED`."

        Design: Corner/validations/hanger_density_capacity_boundary
        """
        ctx = setup_master_data()
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)

        slot_a = validate_success(
            api.create_run_slot(
                create_run_slot_payload_for_ctx(
                    ctx, lot_a["id"],
                    start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                    parts_per_hanger=60,
                ),
                SCHED,
            ),
            201,
        )
        assert_run_slot(slot_a)
        assert slot_a["status"] == "SCHEDULED"

        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot_b["id"],
                start_utc="2026-05-05T10:00:00Z", end_utc="2026-05-05T12:00:00Z",
                parts_per_hanger=61,
            ),
            SCHED,
        )
        validate_error(res, "ERR_HANGER_DENSITY_EXCEEDED", expected_status=422)

    def test_no_active_permit_blocks_schedule(self, api):
        """PRD §3.4: "Finally, the VOC reservation. A covering permit must exist — one
        whose `status` is not `CLOSED` and whose half-open period contains the current
        logical clock — or the create fails with `ERR_NO_ACTIVE_PERMIT`."

        Design: Corner/validations/no_active_permit_blocks_schedule
        """
        ctx = setup_master_data(with_permit=False)
        lot = create_and_accept_lot_in_ctx(ctx)
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        validate_error(res, "ERR_NO_ACTIVE_PERMIT", expected_status=409)

    def test_voc_cap_exceeded_at_schedule(self, api):
        """PRD §3.4: "The slot's `voc_projected_kg` is computed by the theoretical
        emission model of §3.9 and added to the permit's `reserved_kg`; if the resulting
        sum of `used_kg`, `reserved_kg`, and the new projection exceeds `cap_kg` —
        strictly exceeds, since landing exactly on the cap is allowed — the create is
        rejected with `ERR_VOC_CAP_EXCEEDED`."

        Design: Corner/validations/voc_cap_exceeded_at_schedule
        """
        ctx = setup_master_data(permit_overrides={"cap_kg": 0.2})
        lot = create_and_accept_lot_in_ctx(ctx)
        res = api.create_run_slot(
            create_run_slot_payload_for_ctx(
                ctx, lot["id"],
                start_utc="2026-05-05T08:00:00Z", end_utc="2026-05-05T10:00:00Z",
                parts_per_hanger=20,
            ),
            SCHED,
        )
        # Theoretical projection for 100 parts ≈ 0.277 kg > 0.2 kg cap.
        validate_error(res, "ERR_VOC_CAP_EXCEEDED", expected_status=409)
        lot_after = get_lot(lot["id"])
        assert lot_after["status"] == "QUEUED"


class TestOccOnLineVersion:
    def test_stale_version_rejected_after_first_create(self, api):
        """PRD §2.7: "If that value does not match the PaintLine's current `version` —
        because scheduling activity, a line-speed change, a color changeover, or a
        titration-driven posture cascade has advanced the line since the client read it —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "a successful creation itself increments the line's `version` by one,
        so back-to-back scheduling against the same stale read fails exactly as
        intended."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_version_increments
        """
        ctx = setup_master_data()
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)

        line_read = validate_success(api.get_paint_line(ctx["line"]["id"], SCHED), 200)
        stale_version = line_read["version"]

        slot_a = validate_success(
            api.create_run_slot(
                {
                    "paint_line_id": ctx["line"]["id"],
                    "lot_id": lot_a["id"],
                    "start_utc": "2026-05-05T08:00:00Z",
                    "end_utc": "2026-05-05T10:00:00Z",
                    "parts_per_hanger": 20,
                    "expected_paint_line_version": stale_version,
                },
                SCHED,
            ),
            201,
        )
        assert slot_a["status"] == "SCHEDULED"
        line_after = validate_success(api.get_paint_line(ctx["line"]["id"], SCHED), 200)
        assert line_after["version"] == stale_version + 1

        res = api.create_run_slot(
            {
                "paint_line_id": ctx["line"]["id"],
                "lot_id": lot_b["id"],
                "start_utc": "2026-05-05T10:00:00Z",
                "end_utc": "2026-05-05T12:00:00Z",
                "parts_per_hanger": 20,
                "expected_paint_line_version": stale_version,
            },
            SCHED,
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)

    def test_line_speed_change_invalidates_prior_version_read(self, api):
        """PRD §2.7: "If that value does not match the PaintLine's current `version` —
        because scheduling activity, a line-speed change, a color changeover, or a
        titration-driven posture cascade has advanced the line since the client read it —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "Later, a `LineScheduler` may change the conveyor speed by supplying a
        new `line_speed_fpm`, but only while no run slot of that line is `RUNNING`; the
        attempt during a running slot is rejected with `ERR_LINE_BUSY`, and a successful
        change increments the line's `version`."

        Design: Corner/cross_cutting_layers/occ_stale_version_rejected_and_version_increments
        """
        ctx = setup_master_data()
        lot = create_and_accept_lot_in_ctx(ctx)

        line_read = validate_success(api.get_paint_line(ctx["line"]["id"], SCHED), 200)
        stale_version = line_read["version"]

        # A line-speed change advances the line version (no slot RUNNING).
        validate_success(
            api.set_line_speed(ctx["line"]["id"], {"line_speed_fpm": 11.0}, SCHED), 200
        )

        res = api.create_run_slot(
            {
                "paint_line_id": ctx["line"]["id"],
                "lot_id": lot["id"],
                "start_utc": "2026-05-05T08:00:00Z",
                "end_utc": "2026-05-05T10:00:00Z",
                "parts_per_hanger": 20,
                "expected_paint_line_version": stale_version,
            },
            SCHED,
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)


class TestLotPagination:
    def test_lot_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §2.3: "Paginated list responses carry four fields in the `meta` object of
        the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_on_lot_list
        """
        customer = create_customer()
        spec = create_spec(customer["id"])
        for _ in range(11):
            validate_success(
                api.create_lot(
                    create_lot_payload(customer["id"], spec["id"], part_quantity=10), SCHED
                ),
                201,
            )

        page1, meta1 = validate_paginated(api.list_lots(SCHED))
        assert len(page1) == 10
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_lots(SCHED, params={"offset": 10}))
        assert len(page2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False
