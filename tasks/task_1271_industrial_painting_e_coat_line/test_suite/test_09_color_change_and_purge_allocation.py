"""Color changeovers: purge cost constants, allocation policies, buffered conflicts."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_color_change_payload,
    create_customer, create_spec, create_paint_line, create_stage, create_permit,
    create_and_accept_lot, schedule_slot,
    setup_master_data, create_and_accept_lot_in_ctx,
    get_line, get_permit, get_lot,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


class TestPurgeCostConstants:
    def test_purge_cost_voc_color_switch_and_unallocated_cost(self, api):
        """PRD §3.8: "The `purge_cost_cents` is the solvent volume multiplied by 450
        cents per liter, rounded half-up to a whole cent, plus a fixed purge handling
        fee of 12,000 cents. The `purge_voc_kg` is the solvent volume multiplied by 880
        grams of VOC per liter, divided by 1000, and rounded half-up to three decimal
        places."
        PRD §3.8: "When no queued lot matches the new color, the cost simply stays
        unallocated: no error, no partial write, under either policy."

        Design: Corner/calculations/purge_cost_constants_applied
        """
        line = create_paint_line()  # RAL9005, FULL_TO_NEXT_LOT
        permit = create_permit()

        cc = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    line["id"], to_color_code="RAL1018", purge_solvent_liters=40.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        # 40.0 x 450 + 12000 = 30000; 40.0 x 880 / 1000 = 35.200.
        assert cc["purge_cost_cents"] == 30000
        assert cc["purge_voc_kg"] == pytest.approx(35.200, abs=1e-9)
        assert cc["from_color_code"] == "RAL9005"
        assert cc["allocation_method"] == "FULL_TO_NEXT_LOT"

        line_after = get_line(line["id"])
        assert line_after["current_color_code"] == "RAL1018"
        assert line_after["version"] == 2

        permit_after = get_permit(permit["id"])
        assert permit_after["used_kg"] == pytest.approx(35.200, abs=1e-9)

    def test_unallocated_purge_cost_leaves_queued_lots_of_other_colors_untouched(self, api):
        """PRD §3.8: "When no queued lot matches the new color, the cost simply stays
        unallocated: no error, no partial write, under either policy."
        PRD §3.8: "The purge cost is then allocated to the work waiting for the new
        color: every lot in `QUEUED` status whose specification's `color_code` equals
        `to_color_code`, under the line's policy."

        Design: Corner/calculations/purge_cost_constants_applied
        """
        ctx = setup_master_data(with_oven=False)
        # Queued lot is RAL9005; changeover targets RAL1018 — no matching lot.
        lot = create_and_accept_lot_in_ctx(ctx)
        cc = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    ctx["line"]["id"], to_color_code="RAL1018", purge_solvent_liters=40.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        assert cc["purge_cost_cents"] == 30000
        lot_after = get_lot(lot["id"])
        assert lot_after["purge_alloc_cents"] == 0


class TestDualVariantAllocation:
    def test_full_to_next_lot_allocates_entire_cost_to_earliest_queued(self, api):
        """PRD §3.8: "Under `FULL_TO_NEXT_LOT`, one lot absorbs everything: the target
        lot with the earliest `created_at` — ties broken toward the larger
        `part_quantity` — has the entire `purge_cost_cents` added to its
        `purge_alloc_cents`."

        Design: Difficulty/dual_variant_calc/purge_allocation_full_vs_prorata_diverge
        """
        customer = create_customer()
        spec_y = create_spec(customer["id"], color_code="RAL1018")
        line_f = create_paint_line(name="L-FULL", allocation_policy="FULL_TO_NEXT_LOT")
        create_stage(line_f["id"])
        create_permit()
        lot_f1 = create_and_accept_lot(customer["id"], spec_y["id"], part_quantity=100)
        lot_f2 = create_and_accept_lot(customer["id"], spec_y["id"], part_quantity=300)

        cc = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    line_f["id"], to_color_code="RAL1018", purge_solvent_liters=25.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        # 25.0 x 450 + 12000 = 23250.
        assert cc["purge_cost_cents"] == 23250
        # Earliest-created QUEUED lot of the new color absorbs 100%.
        assert get_lot(lot_f1["id"])["purge_alloc_cents"] == 23250
        assert get_lot(lot_f2["id"])["purge_alloc_cents"] == 0

    def test_pro_rata_by_parts_splits_with_remainder_to_last(self, api):
        """PRD §3.8: "Under `PRO_RATA_BY_PARTS`, the targets are ordered by
        `created_at` ascending with the same larger-`part_quantity` tie-break; every
        lot except the last receives its share as the purge cost multiplied by its own
        `part_quantity` and divided by the summed `part_quantity` of all targets,
        rounded half-up to a whole cent, and the last lot in the order receives the
        remainder — the purge cost minus the sum of the shares already assigned — so
        the allocations always sum to exactly `purge_cost_cents` with no rounding
        drift."

        Design: Difficulty/dual_variant_calc/purge_allocation_full_vs_prorata_diverge
        """
        customer = create_customer()
        spec_g = create_spec(customer["id"], color_code="RAL3000")
        line_p = create_paint_line(name="L-PRO", allocation_policy="PRO_RATA_BY_PARTS")
        create_stage(line_p["id"])
        create_permit()
        lot_a = create_and_accept_lot(customer["id"], spec_g["id"], part_quantity=100)
        lot_b = create_and_accept_lot(customer["id"], spec_g["id"], part_quantity=300)

        cc = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    line_p["id"], to_color_code="RAL3000", purge_solvent_liters=25.0,
                    window_start_utc="2026-05-06T08:00:00Z",
                    window_end_utc="2026-05-06T09:00:00Z",
                ),
                SCHED,
            ),
            201,
        )
        assert cc["purge_cost_cents"] == 23250
        # First lot: round_half_up(23250 x 100/400) = 5813; last gets 23250 - 5813.
        alloc_a = get_lot(lot_a["id"])["purge_alloc_cents"]
        alloc_b = get_lot(lot_b["id"])["purge_alloc_cents"]
        assert alloc_a == 5813
        assert alloc_b == 17437
        assert alloc_a + alloc_b == 23250


class TestBufferedWindowConflict:
    def test_slot_at_buffer_boundary_allowed_and_inside_buffer_rejected(self, api):
        """PRD §3.8: "The changeover window blocks production with a buffer. A slot in
        `SCHEDULED` or `RUNNING` status on the same line conflicts when it starts
        before the window end **plus a 30-minute post-purge buffer** and ends after the
        window start; unlike the half-open adjacency allowed between two run slots, a
        slot beginning within 30 minutes after `window_end_utc` still collides. Any
        such conflict is rejected with `ERR_COLOR_CHANGE_CONFLICT`."

        Design: Corner/endpoints/color_change_buffer_conflict
        """
        ctx = setup_master_data()
        lot_a = create_and_accept_lot_in_ctx(ctx)
        lot_b = create_and_accept_lot_in_ctx(ctx)
        # Slot A 09:00-10:00; slot B 12:00-13:00 on 2026-05-05.
        schedule_slot(ctx["line"]["id"], lot_a["id"],
                      "2026-05-05T09:00:00Z", "2026-05-05T10:00:00Z")
        schedule_slot(ctx["line"]["id"], lot_b["id"],
                      "2026-05-05T12:00:00Z", "2026-05-05T13:00:00Z")

        # CC1 window 08:00-08:30: slot A starts 09:00 == 08:30 + 30 min buffer.
        cc1 = validate_success(
            api.create_color_change(
                create_color_change_payload(
                    ctx["line"]["id"], to_color_code="RAL1018", purge_solvent_liters=1.0,
                    window_start_utc="2026-05-05T08:00:00Z",
                    window_end_utc="2026-05-05T08:30:00Z",
                ),
                SCHED,
            ),
            201,
        )
        assert cc1["to_color_code"] == "RAL1018"

        # CC2 window 11:00-11:40: slot B starts 12:00 < 11:40 + 30 min = 12:10.
        res = api.create_color_change(
            create_color_change_payload(
                ctx["line"]["id"], to_color_code="RAL6005", purge_solvent_liters=1.0,
                window_start_utc="2026-05-05T11:00:00Z",
                window_end_utc="2026-05-05T11:40:00Z",
            ),
            SCHED,
        )
        validate_error(res, "ERR_COLOR_CHANGE_CONFLICT", expected_status=409)
