"""Finish room: batch QC color match, sheen lots, assignment gates, cascades."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_finish_batch_payload,
    create_finish_spec_payload,
    get_success_data,
    make_dealer_headers,
    setup_door_order_in_production,
    validate_error,
    validate_paginated,
    validate_success,
    create_submitted_door_order,
    create_mixing_batch,
    assign_line_to_batch,
    add_door_line,
    create_draft_order,
    create_dealer,
    create_door_style,
    create_finish,
)

ADMIN = TEST_USERS["plant_admin_headers"]
FINISH = TEST_USERS["finish_supervisor_headers"]


class TestDeltaEBoundary:
    def _two_mixing_batches(self, api):
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(
                    finish_code="FS-QC", color_name="Cherry", sheen="SEMI_GLOSS",
                    upcharge_pct=0.12, delta_e_tolerance=1.5,
                ),
                ADMIN,
            )
        )
        b1 = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(finish["id"], sheen_lot_no="LOT-A", capacity_doors=10), FINISH
            )
        )
        b2 = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(finish["id"], sheen_lot_no="LOT-B", capacity_doors=10), FINISH
            )
        )
        return b1, b2

    def test_deviation_exactly_at_tolerance_passes(self, api):
        """PRD §3.4: "The batch's finish supplies the pass threshold: the batch
        releases when the absolute value of `measured_delta_e` is less than or
        equal to the finish's `delta_e_tolerance`, and a deviation exactly equal
        to the tolerance passes."
        PRD §3.4: "On a pass the batch moves `MIXING` → `RELEASED`, every assigned
        door line moves `IN_PROGRESS` → `COMPLETED`, and each affected order
        re-evaluates progression to `READY_TO_SHIP`."

        Design: Difficulty/boundary_precision_check/delta_e_tolerance_boundary_exact_pass
        """
        b1, _b2 = self._two_mixing_batches(api)
        data = validate_success(api.record_batch_qc(b1["id"], {"measured_delta_e": 1.5}, FINISH))
        assert data["status"] == "RELEASED", "boundary value 1.5 <= 1.5 must release the batch"
        assert data["measured_delta_e"] == pytest.approx(1.5)

    def test_deviation_one_tick_above_tolerance_fails(self, api):
        """PRD §3.4: "On a fail — absolute deviation strictly greater than the
        tolerance — the batch moves `MIXING` → `FAILED` and a three-hop cascade
        fires."

        Design: Difficulty/boundary_precision_check/delta_e_tolerance_boundary_exact_pass
        """
        _b1, b2 = self._two_mixing_batches(api)
        data = validate_success(api.record_batch_qc(b2["id"], {"measured_delta_e": 1.51}, FINISH))
        assert data["status"] == "FAILED", "1.51 > 1.5 must fail the batch"


class TestRemixCycle:
    def _failed_batch(self, api):
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(
                    finish_code="FS-QC", color_name="Cherry", sheen="SEMI_GLOSS",
                    upcharge_pct=0.12, delta_e_tolerance=1.5,
                ),
                ADMIN,
            )
        )
        batch = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(finish["id"], sheen_lot_no="LOT-9", capacity_doors=10), FINISH
            )
        )
        failed = get_success_data(api.record_batch_qc(batch["id"], {"measured_delta_e": 1.9}, FINISH))
        assert failed["status"] == "FAILED"
        return batch["id"]

    def test_failed_batch_remixes_to_mixing_with_counters(self, api):
        """PRD §3.4: "Remixing moves it `FAILED` → `MIXING` — only a `FAILED` batch
        may be remixed, else `ERR_BATCH_NOT_REMIXABLE` — clearing
        `measured_delta_e` back to null and incrementing `remix_count` by 1."

        Design: Difficulty/non_linear_state_machine/finish_batch_failed_remix_release_cycle
        """
        batch_id = self._failed_batch(api)
        data = validate_success(api.remix_batch(batch_id, FINISH))
        assert data["status"] == "MIXING"
        assert data["remix_count"] == 1
        assert data["measured_delta_e"] is None, "remix must clear the recorded deviation"

    def test_remixed_batch_releases_on_second_qc_pass(self, api):
        """PRD §3.4: "After remix the batch accepts fresh assignments and another
        QC recording; the remix cycle may repeat until the color matches."
        PRD §3.4: "The batch's finish supplies the pass threshold: the batch
        releases when the absolute value of `measured_delta_e` is less than or
        equal to the finish's `delta_e_tolerance`, and a deviation exactly equal
        to the tolerance passes."

        Design: Difficulty/non_linear_state_machine/finish_batch_failed_remix_release_cycle
        """
        batch_id = self._failed_batch(api)
        get_success_data(api.remix_batch(batch_id, FINISH))
        data = validate_success(api.record_batch_qc(batch_id, {"measured_delta_e": 1.2}, FINISH))
        assert data["status"] == "RELEASED", "1.2 <= 1.5 must release the remixed batch"

    def test_remix_mixing_batch_rejected(self, api):
        """PRD §3.4: "Remixing moves it `FAILED` → `MIXING` — only a `FAILED` batch
        may be remixed, else `ERR_BATCH_NOT_REMIXABLE` — clearing
        `measured_delta_e` back to null and incrementing `remix_count` by 1."

        Design: Corner/state_machines/remix_mixing_batch_rejected
        """
        finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-QC", sheen="SEMI_GLOSS", upcharge_pct=0.12),
                ADMIN,
            )
        )
        batch = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(finish["id"], sheen_lot_no="LOT-M", capacity_doors=10), FINISH
            )
        )
        resp = api.remix_batch(batch["id"], FINISH)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_REMIXABLE)


class TestBatchAssignmentCompatibility:
    def test_finish_mismatch_on_assign(self, api):
        """PRD §3.4: "First, the line's `finish_id` must equal the batch's
        `finish_id` (`ERR_FINISH_MISMATCH`, HTTP 422). Second, the sheen lot rule:
        if the line's `required_sheen_lot_no` is set, it must equal the batch's
        `sheen_lot_no` (`ERR_SHEEN_LOT_MISMATCH`, HTTP 422). Third, capacity: the
        batch's `assigned_door_count` plus the line's `qty` must not exceed
        `capacity_doors` (`ERR_BATCH_CAPACITY_EXCEEDED`, HTTP 422)."

        Design: Corner/validations/finish_mismatch_on_assign
        """
        env = create_submitted_door_order(price_level="L4", qty=2, upcharge_pct=0.10)
        other_finish = get_success_data(
            api.create_finish_spec(
                create_finish_spec_payload(finish_code="FS-2", color_name="Cherry", sheen="SATIN",
                                           upcharge_pct=0.12),
                ADMIN,
            )
        )
        batch = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(other_finish["id"], sheen_lot_no="LOT-2", capacity_doors=10),
                FINISH,
            )
        )
        resp = api.assign_batch_line(batch["id"], {"order_line_id": env["line"]["id"]}, FINISH)
        validate_error(resp, ApiErrorId.ERR_FINISH_MISMATCH)

    def test_sheen_lot_mismatch_on_assign(self, api):
        """PRD §3.4: "Second, the sheen lot rule: if the line's
        `required_sheen_lot_no` is set, it must equal the batch's `sheen_lot_no`
        (`ERR_SHEEN_LOT_MISMATCH`, HTTP 422)."

        Design: Corner/validations/sheen_lot_mismatch_on_assign
        """
        env = create_submitted_door_order(
            price_level="L4", qty=2, upcharge_pct=0.10, required_sheen_lot_no="LOT-A"
        )
        batch = get_success_data(
            api.create_finish_batch(
                create_finish_batch_payload(env["finish"]["id"], sheen_lot_no="LOT-B", capacity_doors=10),
                FINISH,
            )
        )
        resp = api.assign_batch_line(batch["id"], {"order_line_id": env["line"]["id"]}, FINISH)
        validate_error(resp, ApiErrorId.ERR_SHEEN_LOT_MISMATCH)

    def test_batch_capacity_exact_fit_then_overflow(self, api):
        """PRD §3.4: "Third, capacity: the batch's `assigned_door_count` plus the
        line's `qty` must not exceed `capacity_doors` (`ERR_BATCH_CAPACITY_EXCEEDED`,
        HTTP 422). A batch whose `assigned_door_count` exactly reaches
        `capacity_doors` after the assignment is legitimate, because the rule
        rejects only strict excess."

        Design: Corner/calculations/batch_capacity_exact_fit_then_overflow
        """
        dealer = create_dealer(price_level="L3")
        style = create_door_style()
        finish = create_finish(upcharge_pct=0.10)
        order = create_draft_order(dealer)
        line_a = add_door_line(order, style, finish, qty=4)
        line_b = add_door_line(order, style, finish, qty=1)
        get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        batch = create_mixing_batch(finish, capacity_doors=4, sheen_lot_no="LOT-C")

        assigned = validate_success(
            api.assign_batch_line(batch["id"], {"order_line_id": line_a["id"]}, FINISH)
        )
        assert assigned["assigned_door_count"] == 4, "exact fit at capacity must be accepted"
        resp = api.assign_batch_line(batch["id"], {"order_line_id": line_b["id"]}, FINISH)
        validate_error(resp, ApiErrorId.ERR_BATCH_CAPACITY_EXCEEDED)

    def test_line_not_assignable_when_already_assigned(self, api):
        """PRD §3.4: "The batch must be in `MIXING` (`ERR_BATCH_NOT_MIXING`), and
        the target line — named by `order_line_id` — must be a `QUOTED`, currently
        unassigned `DOOR` line; anything else is rejected with
        `ERR_LINE_NOT_ASSIGNABLE` (HTTP 409)."

        Design: Corner/validations/line_not_assignable_when_already_assigned
        """
        env = create_submitted_door_order(price_level="L4", qty=2, upcharge_pct=0.10)
        b1 = create_mixing_batch(env["finish"], capacity_doors=10, sheen_lot_no="LOT-1")
        b2 = create_mixing_batch(env["finish"], capacity_doors=10, sheen_lot_no="LOT-2")
        assign_line_to_batch(b1, env["line"])
        resp = api.assign_batch_line(b2["id"], {"order_line_id": env["line"]["id"]}, FINISH)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_ASSIGNABLE)


class TestOrderAutoAdvance:
    def test_order_auto_advances_to_in_production_on_full_coverage(self, api):
        """PRD §3.7: "From `SUBMITTED`, an order auto-advances to `IN_PRODUCTION`
        when its `hold_status` is `NONE`, every door line carries a
        `finish_batch_id`, and every box line has `slotted_qty` equal to its
        `qty`; the evaluation runs after each batch assignment, sub-lot creation,
        and hold release."

        Design: Corner/state_machines/order_auto_advances_to_in_production_on_full_coverage
        """
        env = create_submitted_door_order(price_level="L4", qty=4, upcharge_pct=0.10)
        batch = create_mixing_batch(env["finish"], capacity_doors=10, sheen_lot_no="LOT-1")
        assign_line_to_batch(batch, env["line"])
        order = validate_success(api.get_order(env["order"]["id"], FINISH))
        assert order["status"] == "IN_PRODUCTION", (
            "assigning the last unassigned door line must auto-advance the order"
        )


class TestQcFailCascade:
    def _two_orders_one_batch(self, api):
        dealer = create_dealer(price_level="L3")
        style = create_door_style(construction="RAISED_PANEL", base_list_price_cents=22000)
        finish = create_finish(upcharge_pct=0.12, tolerance=1.5, finish_code="FS-CH",
                               color_name="Cherry", sheen="SEMI_GLOSS")
        o1 = create_draft_order(dealer)
        l1 = add_door_line(o1, style, finish, qty=4, unit_price=22000)
        get_success_data(api.submit_order(o1["id"], make_dealer_headers(dealer["id"])))
        o2 = create_draft_order(dealer)
        l2 = add_door_line(o2, style, finish, qty=6, unit_price=22000)
        get_success_data(api.submit_order(o2["id"], make_dealer_headers(dealer["id"])))
        batch = create_mixing_batch(finish, capacity_doors=50, sheen_lot_no="LOT-7")
        assign_line_to_batch(batch, l1)
        batch_after = assign_line_to_batch(batch, l2)
        assert batch_after["assigned_door_count"] == 10
        return {"dealer": dealer, "finish": finish, "batch": batch_after,
                "o1": o1, "o2": o2, "l1": l1, "l2": l2}

    def test_qc_fail_unassigns_lines_and_zeroes_batch_count(self, api):
        """PRD §3.4: "First, every assigned door line is unassigned: its
        `finish_batch_id` is cleared to null, the line falls back `IN_PROGRESS` →
        `QUOTED`, and the batch's `assigned_door_count` is recomputed downward by
        each affected line's `qty`."

        Design: Difficulty/transitive_cascade/batch_qc_fail_unassign_hold_cascade
        """
        env = self._two_orders_one_batch(api)
        failed = validate_success(
            api.record_batch_qc(env["batch"]["id"], {"measured_delta_e": 2.0}, FINISH)
        )
        assert failed["status"] == "FAILED"
        assert failed["assigned_door_count"] == 0, (
            "the fail cascade must recompute the count down by each affected line's qty"
        )
        line = validate_success(api.get_order_line(env["l1"]["id"], FINISH))
        assert line["status"] == "QUOTED"
        assert line["finish_batch_id"] is None

    def test_qc_fail_places_finish_qc_holds_on_each_order(self, api):
        """PRD §3.4: "Second, for each distinct order owning an affected line, an
        `OrderHold` with `reason` `FINISH_QC` is placed, flipping that order's
        `hold_status` to `ON_HOLD`."

        Design: Difficulty/transitive_cascade/batch_qc_fail_unassign_hold_cascade
        """
        env = self._two_orders_one_batch(api)
        get_success_data(api.record_batch_qc(env["batch"]["id"], {"measured_delta_e": 2.0}, FINISH))
        for order in (env["o1"], env["o2"]):
            holds, _meta = validate_paginated(api.list_order_holds(order["id"], FINISH))
            assert len(holds) == 1, f"order {order['id']} must carry exactly one hold"
            assert holds[0]["reason"] == "FINISH_QC"
            assert holds[0]["status"] == "PLACED"
            reread = validate_success(api.get_order(order["id"], FINISH))
            assert reread["hold_status"] == "ON_HOLD"


class TestBatchDoorCountConservation:
    def _order_with_assigned_line(self, api):
        env = setup_door_order_in_production(
            price_level="L3", qty=30, unit_price=30000, upcharge_pct=0.10, capacity_doors=50
        )
        return env

    def test_assign_then_qc_fail_returns_count_to_zero(self, api):
        """PRD §3.4: "A successful assignment sets the line's `finish_batch_id` to
        the batch, advances the line `QUOTED` → `IN_PROGRESS`, and increases the
        batch's `assigned_door_count` by the line's `qty`."
        PRD §3.4: "First, every assigned door line is unassigned: its
        `finish_batch_id` is cleared to null, the line falls back `IN_PROGRESS` →
        `QUOTED`, and the batch's `assigned_door_count` is recomputed downward by
        each affected line's `qty`."

        Design: Difficulty/compensating_invariant/batch_door_count_conserved_under_qc_fail_and_reassign
        """
        env = self._order_with_assigned_line(api)
        assert env["batch"]["assigned_door_count"] == 30
        failed = validate_success(
            api.record_batch_qc(env["batch"]["id"], {"measured_delta_e": 2.4}, FINISH)
        )
        assert failed["status"] == "FAILED"
        assert failed["assigned_door_count"] == 0, (
            "QC fail compensation must return the batch count from 30 to exactly 0"
        )

    def test_reassign_restores_count_and_releases_hold(self, api):
        """PRD §3.7: "A finish-QC hold releases automatically when the held order's
        last unassigned door line is assigned to a batch in `MIXING` or
        `RELEASED`."
        PRD §3.4: "Assignment also feeds two larger re-evaluations: an order whose
        every door line is now assigned and every box line fully slotted may
        auto-advance `SUBMITTED` → `IN_PRODUCTION`; and if the assigned line was
        the last unassigned door line of an order held for finish QC, that order's
        `PLACED` `FINISH_QC` holds release (see §3.7)."

        Design: Difficulty/compensating_invariant/batch_door_count_conserved_under_qc_fail_and_reassign
        """
        env = self._order_with_assigned_line(api)
        get_success_data(api.record_batch_qc(env["batch"]["id"], {"measured_delta_e": 2.4}, FINISH))
        b2 = create_mixing_batch(env["finish"], capacity_doors=50, sheen_lot_no="LOT-2")
        assigned = validate_success(
            api.assign_batch_line(b2["id"], {"order_line_id": env["line"]["id"]}, FINISH)
        )
        assert assigned["assigned_door_count"] == 30, (
            "reassignment must restore the conserved door count to the line's qty"
        )
        order = validate_success(api.get_order(env["order"]["id"], FINISH))
        assert order["hold_status"] == "NONE", (
            "assigning the held order's last unassigned door line must auto-release the hold"
        )
        assert order["status"] == "IN_PRODUCTION"
