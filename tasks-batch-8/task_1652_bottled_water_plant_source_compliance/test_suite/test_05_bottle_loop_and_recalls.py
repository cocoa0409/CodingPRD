"""The returnable-bottle loop, wash-batch lifecycle, recalls, and the
multi-hop cascades that cross-cut them."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_bottle,
    create_permit,
    create_plant,
    create_recall_for_lots,
    create_running_wash_with_bottles,
    create_validated_run,
    create_wash_batch,
    create_withdrawal_event_payload,
    get_success_data,
    loop_bottle_to_dirty,
    post_withdrawal_event,
    setup_line_with_preforms,
    setup_released_lot_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, COMPLIANCE_OFFICER, SOURCE_MONITOR, PL1, QA1, SL1,
    create_lot_in_qa_hold, create_lot_on_line, create_treatment_run,
    wash_bottle_once, find_finished_product_test,
)


class TestBottleLoopCycle:
    def test_full_loop_returns_to_sanitized(self, api):
        """PRD §3.8: "A passing batch moves to `PASSED` and sanitizes its
        load — every assigned bottle moves from `IN_WASH` back to
        `SANITIZED`, its `wash_cycle_count` increments by 1, its
        `last_wash_batch_id` is set to this batch, its `current_wash_batch_id`
        clears".

        Design: Difficulty/non_linear_state_machine/bottle_loop_cycle_counter_increments_once
        """
        s = setup_released_lot_scenario("Plant NL1", planned_units=500,
                                        produced_units=500)
        plant, lot = s["plant"], s["lot"]
        b = create_bottle(plant["id"], "B-LOOP")
        dirty = loop_bottle_to_dirty(plant["id"], b["id"], lot["id"])
        assert dirty["status"] == "RETURNED_DIRTY"

        batch = create_running_wash_with_bottles(plant["id"], [b["id"]])
        in_wash = validate_success(api.get_bottle(b["id"], SL1))
        assert in_wash["status"] == "IN_WASH"

        completed = validate_success(api.complete_wash_batch(
            batch["id"], {"rinse_temp_c": 71.1, "sanitizer_ppm": 50.0}, SL1
        ))
        assert completed["status"] == "PASSED"

        after = validate_success(api.get_bottle(b["id"], SL1))
        assert after["status"] == "SANITIZED", "cycle closed back to the initial state"
        assert after["wash_cycle_count"] == 1, "exactly one increment for one PASSED wash"
        assert after["last_wash_batch_id"] == batch["id"]
        assert after["current_wash_batch_id"] is None

    def test_passed_wash_spawns_auto_sanitation_test(self, api):
        """PRD §3.8: "then the system auto-creates the batch's
        `BOTTLE_SANITATION` lab test, due one day out with `origin` `AUTO`."

        Design: Difficulty/non_linear_state_machine/bottle_loop_cycle_counter_increments_once
        """
        s = setup_released_lot_scenario("Plant NL1", planned_units=500,
                                        produced_units=500)
        plant, lot = s["plant"], s["lot"]
        b = create_bottle(plant["id"], "B-LOOP")
        _bottle, batch = wash_bottle_once(plant["id"], b["id"], lot["id"])
        assert batch["status"] == "PASSED"

        page, meta = validate_paginated(api.list_lab_tests(
            QA1, params={"subject_wash_batch_id": batch["id"],
                         "test_type": "BOTTLE_SANITATION"}
        ))
        assert meta["total_count"] == 1
        assert page[0]["origin"] == "AUTO"
        assert page[0]["status"] == "SCHEDULED"
        # Clock is the startup default 2026-08-01; due one day out (§3.4).
        assert page[0]["due_date"] == "2026-08-02"


class TestWashBatchFailureAndCancel:
    def _dirty_bottle_in_running_batch(self, api, plant, lot, washer="WASHER_A"):
        b = create_bottle(plant["id"], f"B-{plant['name']}")
        loop_bottle_to_dirty(plant["id"], b["id"], lot["id"])
        batch = create_running_wash_with_bottles(plant["id"], [b["id"]], washer_unit=washer)
        return b, batch

    def test_wash_batch_fail_returns_bottles_without_count(self, api):
        """PRD §3.8: "A failing batch moves to `FAILED`, returns every
        assigned bottle to `RETURNED_DIRTY` without incrementing any cycle
        count, and spawns no sanitation test."

        Design: Corner/state_machines/wash_batch_fail_returns_bottles_without_count
        """
        s = setup_released_lot_scenario("Plant SM20", planned_units=100,
                                        produced_units=100, preform_units=1000)
        plant, lot = s["plant"], s["lot"]
        b, batch = self._dirty_bottle_in_running_batch(api, plant, lot)

        failed = validate_success(api.complete_wash_batch(
            batch["id"], {"rinse_temp_c": 70.0, "sanitizer_ppm": 50.0}, SL1
        ))
        assert failed["status"] == "FAILED", "rinse 70.0 < 71.1"

        after = validate_success(api.get_bottle(b["id"], SL1))
        assert after["status"] == "RETURNED_DIRTY"
        assert after["wash_cycle_count"] == 0
        assert after["current_wash_batch_id"] is None

        page, meta = validate_paginated(api.list_lab_tests(
            QA1, params={"subject_wash_batch_id": batch["id"]}
        ))
        assert meta["total_count"] == 0, "no sanitation test for a failed batch"

    def test_wash_batch_cancel_releases_assigned_bottles(self, api):
        """PRD §3.8: "Cancelling a `SCHEDULED` batch moves it to `CANCELLED`
        and compensates any already-assigned bottles back to `RETURNED_DIRTY`
        with `current_wash_batch_id` cleared."

        Design: Corner/state_machines/wash_batch_cancel_releases_assigned_bottles
        """
        s = setup_released_lot_scenario("Plant SM21", planned_units=100,
                                        produced_units=100, preform_units=1000)
        plant, lot = s["plant"], s["lot"]
        b = create_bottle(plant["id"], "B-SM21")
        loop_bottle_to_dirty(plant["id"], b["id"], lot["id"])
        batch = create_wash_batch(
            plant["id"], washer_unit="WASHER_B",
            scheduled_start="2026-08-05T09:00:00Z", scheduled_end="2026-08-05T10:00:00Z",
        )
        assigned = validate_success(api.assign_bottles(
            batch["id"], {"bottle_ids": [b["id"]]}, SL1
        ))
        assert assigned["bottle_count"] == 1

        cancelled = validate_success(api.cancel_wash_batch(batch["id"], SL1))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["bottle_count"] == 0

        after = validate_success(api.get_bottle(b["id"], SL1))
        assert after["status"] == "RETURNED_DIRTY"
        assert after["current_wash_batch_id"] is None


class TestWashBatchScheduling:
    def test_washer_purge_buffer_thirty_minute_semantics(self, api):
        """PRD §3.8: "a mandatory 30-minute purge separates consecutive
        batches on one washer: starting less than 30 minutes after the
        previous batch's end, or ending less than 30 minutes before the next
        batch's start, fails with `ERR_WASHER_PURGE_BUFFER` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/washer_purge_buffer_thirty_minute_semantics
        """
        plant = create_plant("Plant TO2")
        create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T09:00:00Z", scheduled_end="2026-08-06T10:00:00Z",
        )
        # Adjacent (0 minutes of purge) — rejected.
        resp2 = api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T10:00:00Z",
             "scheduled_end": "2026-08-06T11:00:00Z"},
            SL1,
        )
        validate_error(resp2, ApiErrorId.ERR_WASHER_PURGE_BUFFER)

        # 15 minutes of purge — rejected.
        resp3 = api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T10:15:00Z",
             "scheduled_end": "2026-08-06T11:00:00Z"},
            SL1,
        )
        validate_error(resp3, ApiErrorId.ERR_WASHER_PURGE_BUFFER)

        # Exactly 30 minutes of purge — satisfies the rule.
        w4 = validate_success(api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T10:30:00Z",
             "scheduled_end": "2026-08-06T11:30:00Z"},
            SL1,
        ), expected_status=201)
        assert w4["status"] == "SCHEDULED"

        # The other washer is a different resource; time overlap is irrelevant.
        w5 = validate_success(api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_B",
             "scheduled_start": "2026-08-06T09:30:00Z",
             "scheduled_end": "2026-08-06T10:15:00Z"},
            SL1,
        ), expected_status=201)
        assert w5["status"] == "SCHEDULED"

    def test_washer_purge_buffer_applies_before_next_batch(self, api):
        """PRD §3.8: "a mandatory 30-minute purge separates consecutive
        batches on one washer: starting less than 30 minutes after the
        previous batch's end, or ending less than 30 minutes before the next
        batch's start, fails with `ERR_WASHER_PURGE_BUFFER` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/washer_purge_buffer_thirty_minute_semantics
        """
        plant = create_plant("Plant TO2b")
        create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T10:30:00Z", scheduled_end="2026-08-06T11:30:00Z",
        )
        # Ends only 15 minutes before the existing batch's start — the buffer
        # binds in the other direction too.
        resp = api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T09:15:00Z",
             "scheduled_end": "2026-08-06T10:15:00Z"},
            SL1,
        )
        validate_error(resp, ApiErrorId.ERR_WASHER_PURGE_BUFFER)

        # Ends exactly 30 minutes before the next batch's start — allowed.
        ok = validate_success(api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T09:00:00Z",
             "scheduled_end": "2026-08-06T10:00:00Z"},
            SL1,
        ), expected_status=201)
        assert ok["status"] == "SCHEDULED"

    def test_wash_batch_direct_overlap_rejected(self, api):
        """PRD §3.8: "Two batches on the same washer may not overlap — any
        window intersection with another batch not in `CANCELLED` status on
        that washer fails with `ERR_WASHER_WINDOW_CONFLICT` (HTTP 409)".

        Design: Corner/state_machines/wash_batch_direct_overlap_rejected
        """
        plant = create_plant("Plant SM22")
        create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T09:00:00Z", scheduled_end="2026-08-06T10:00:00Z",
        )
        resp = api.create_wash_batch(
            plant["id"],
            {"washer_unit": "WASHER_A",
             "scheduled_start": "2026-08-06T09:30:00Z",
             "scheduled_end": "2026-08-06T10:30:00Z"},
            SL1,
        )
        validate_error(resp, ApiErrorId.ERR_WASHER_WINDOW_CONFLICT)

    def test_wash_batch_second_running_same_washer_rejected(self, api):
        """PRD §3.8: "Starting a batch requires it to be `SCHEDULED` and
        requires that no other batch on the same `washer_unit` is currently
        `RUNNING` — at most one running batch per washer".

        Design: Corner/state_machines/wash_batch_second_running_same_washer_rejected
        """
        plant = create_plant("Plant SM23")
        w1 = create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T09:00:00Z", scheduled_end="2026-08-06T10:00:00Z",
        )
        w2 = create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T10:30:00Z", scheduled_end="2026-08-06T11:30:00Z",
        )
        validate_success(api.start_wash_batch(w1["id"], SL1))

        resp = api.start_wash_batch(w2["id"], SL1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBottleTerminalAndFill:
    def test_bottle_retire_terminal_lockdown(self, api):
        """PRD §3.8: "Retirement by a `SanitationLead` is admitted from
        `RETURNED_DIRTY`, `SANITIZED`, or `QUARANTINED` and moves the bottle
        to the terminal `RETIRED` state".

        Design: Corner/state_machines/bottle_retire_terminal_lockdown
        """
        plant = create_plant("Plant SM24")
        b = create_bottle(plant["id"], "B-SM24")

        retired = validate_success(api.retire_bottle(b["id"], SL1))
        assert retired["status"] == "RETIRED"

        resp1 = api.deliver_bottle(b["id"], SL1)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.return_bottle(b["id"], SL1)
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)

    def test_bottle_fill_unreleased_lot_rejected(self, api):
        """PRD §3.8: "The lot must exist, must belong to the same plant as
        the bottle — traced through the lot's line — otherwise
        `ERR_CROSS_PLANT_REFERENCE`, and must be `RELEASED`, otherwise
        `ERR_LOT_NOT_RELEASED` (HTTP 409)."

        Design: Corner/state_machines/bottle_fill_unreleased_lot_rejected
        """
        # Build to QA_HOLD only (never released).
        plant = create_plant("Plant SM25")
        permit = create_permit(plant["id"], permit_number="SP-SM25")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=500)
        run = create_validated_run(plant["id"], permit["id"])
        lot_qa, _fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=100, produced_units=100,
        )
        b = create_bottle(plant["id"], "B-SM25")

        resp = api.fill_bottle(b["id"], {"lot_id": lot_qa["id"]}, PL1)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_RELEASED)
        after = validate_success(api.get_bottle(b["id"], SL1))
        assert after["status"] == "SANITIZED"

    def test_bottle_duplicate_code_rejected(self, api):
        """PRD §3.8: "A `SanitationLead` registers a bottle beneath the plant
        with an etched `bottle_code`, unique among the plant's bottles that
        are not `RETIRED`; reusing a live code fails with
        `ERR_BOTTLE_CODE_EXISTS` (HTTP 409)."

        Design: Corner/entities/bottle_duplicate_code_rejected
        """
        plant_a = create_plant("Plant EN10A")
        plant_b = create_plant("Plant EN10B")
        b_a = create_bottle(plant_a["id"], "B-DUP")
        assert b_a["status"] == "SANITIZED"

        resp = api.create_bottle(plant_a["id"], {"bottle_code": "B-DUP"}, SL1)
        validate_error(resp, ApiErrorId.ERR_BOTTLE_CODE_EXISTS)

        # Uniqueness is scoped to the plant.
        b_b = validate_success(
            api.create_bottle(plant_b["id"], {"bottle_code": "B-DUP"}, SL1),
            expected_status=201,
        )
        assert b_b["status"] == "SANITIZED"


class TestRecallLifecycle:
    def test_recall_initiation_cascade_lots_then_bottles(self, api):
        """PRD §3.7: "Initiation moves each scoped lot to `RECALLED` with
        `recall_id` set, quarantines every bottle in `FILLED` or
        `WITH_CUSTOMER` status whose `last_filled_lot_id` is in scope ...
        freezes `units_in_scope` to the sum of the scoped lots'
        `produced_units` at that instant, and starts the recall in
        `INITIATED` with `units_recovered` 0."

        Design: Difficulty/transitive_cascade/recall_initiation_cascade_lots_then_bottles
        """
        s = setup_released_lot_scenario("Plant TC2", planned_units=100,
                                        produced_units=100)
        plant, lot = s["plant"], s["lot"]
        b1 = create_bottle(plant["id"], "B-R1")
        b2 = create_bottle(plant["id"], "B-R2")
        b3 = create_bottle(plant["id"], "B-R3")
        validate_success(api.fill_bottle(b1["id"], {"lot_id": lot["id"]}, PL1))
        validate_success(api.fill_bottle(b2["id"], {"lot_id": lot["id"]}, PL1))
        validate_success(api.deliver_bottle(b2["id"], SL1))

        recall = validate_success(api.create_recall(
            plant["id"], {"reason": "micro positive", "lot_ids": [lot["id"]]},
            COMPLIANCE_OFFICER,
        ), expected_status=201)
        assert recall["status"] == "INITIATED"
        assert recall["units_in_scope"] == 100
        assert recall["units_recovered"] == 0

        lot_now = validate_success(api.get_production_lot(lot["id"], COMPLIANCE_OFFICER))
        assert lot_now["status"] == "RECALLED"
        assert lot_now["recall_id"] == recall["id"]

        # Hop 3: bottles last filled from the recalled lot are quarantined;
        # the never-filled bottle is untouched.
        assert validate_success(api.get_bottle(b1["id"], SL1))["status"] == "QUARANTINED"
        assert validate_success(api.get_bottle(b2["id"], SL1))["status"] == "QUARANTINED"
        assert validate_success(api.get_bottle(b3["id"], SL1))["status"] == "SANITIZED"

        plant_now = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert plant_now["compliance_posture"] == "BREACH"

    def test_recall_quarantine_and_close_release_bottles(self, api):
        """PRD §3.7: "Initiation moves each scoped lot to `RECALLED` with
        `recall_id` set, quarantines every bottle in `FILLED` or
        `WITH_CUSTOMER` status whose `last_filled_lot_id` is in scope" and
        "Closure moves the recall to the terminal `CLOSED` state, releases
        every `QUARANTINED` bottle whose `last_filled_lot_id` belongs to the
        recall's scope back to `RETURNED_DIRTY`".

        Design: Difficulty/transitive_cascade/recall_initiation_cascade_lots_then_bottles
        """
        s = setup_released_lot_scenario("Plant TC2b", planned_units=100,
                                        produced_units=100, preform_units=1000)
        plant, lot = s["plant"], s["lot"]
        b1 = create_bottle(plant["id"], "B-Q1")
        b2 = create_bottle(plant["id"], "B-Q2")
        validate_success(api.fill_bottle(b1["id"], {"lot_id": lot["id"]}, PL1))
        validate_success(api.fill_bottle(b2["id"], {"lot_id": lot["id"]}, PL1))
        validate_success(api.deliver_bottle(b2["id"], SL1))

        recall = create_recall_for_lots(plant["id"], [lot["id"]])
        assert validate_success(api.get_bottle(b1["id"], SL1))["status"] == "QUARANTINED"
        assert validate_success(api.get_bottle(b2["id"], SL1))["status"] == "QUARANTINED"

        # Recover the full scope and close: both quarantined bottles are
        # released to the dirty returns pool.
        validate_success(api.post_recall_recovery(
            recall["id"], {"recovered_units": 100}, COMPLIANCE_OFFICER
        ))
        closed = validate_success(api.close_recall(recall["id"], COMPLIANCE_OFFICER))
        assert closed["status"] == "CLOSED"
        assert validate_success(api.get_bottle(b1["id"], SL1))["status"] == "RETURNED_DIRTY"
        assert validate_success(api.get_bottle(b2["id"], SL1))["status"] == "RETURNED_DIRTY"

    def test_recall_close_requires_full_recovery_boundary(self, api):
        """PRD §3.7: "Closing is admitted only from `RECOVERING` and only
        once `units_recovered` has reached at least `units_in_scope`; closing
        short of full recovery fails with `ERR_RECOVERY_INCOMPLETE` (HTTP
        409)."

        Design: Corner/state_machines/recall_close_requires_full_recovery_boundary
        """
        s = setup_released_lot_scenario("Plant SM26", planned_units=100,
                                        produced_units=100, preform_units=1000)
        plant, lot = s["plant"], s["lot"]
        b = create_bottle(plant["id"], "B-SM26")
        validate_success(api.fill_bottle(b["id"], {"lot_id": lot["id"]}, PL1))
        recall = create_recall_for_lots(plant["id"], [lot["id"]], reason="micro positive")

        r1 = validate_success(api.post_recall_recovery(
            recall["id"], {"recovered_units": 99}, COMPLIANCE_OFFICER
        ))
        assert r1["units_recovered"] == 99
        assert r1["status"] == "RECOVERING", "first posting flipped INITIATED -> RECOVERING"

        resp = api.close_recall(recall["id"], COMPLIANCE_OFFICER)
        validate_error(resp, ApiErrorId.ERR_RECOVERY_INCOMPLETE)

        r2 = validate_success(api.post_recall_recovery(
            recall["id"], {"recovered_units": 1}, COMPLIANCE_OFFICER
        ))
        assert r2["units_recovered"] == 100

        closed = validate_success(api.close_recall(recall["id"], COMPLIANCE_OFFICER))
        assert closed["status"] == "CLOSED", "recovery exactly == scope satisfies the >= guard"

        b_now = validate_success(api.get_bottle(b["id"], SL1))
        assert b_now["status"] == "RETURNED_DIRTY", "quarantine released on close"

        plant_now = validate_success(api.get_plant(plant["id"], PLANT_ADMIN))
        assert plant_now["compliance_posture"] == "GREEN"

    def test_recall_recovery_over_posting_rejected(self, api):
        """PRD §3.7: "a posting that would push `units_recovered` past
        `units_in_scope` fails with `ERR_RECOVERY_EXCEEDS_SCOPE` (HTTP 422)."

        Design: Corner/state_machines/recall_recovery_over_posting_rejected
        """
        s = setup_released_lot_scenario("Plant SM27", planned_units=50,
                                        produced_units=50, preform_units=1000)
        plant, lot = s["plant"], s["lot"]
        recall = create_recall_for_lots(plant["id"], [lot["id"]], reason="label defect")
        assert recall["units_in_scope"] == 50

        resp = api.post_recall_recovery(
            recall["id"], {"recovered_units": 51}, COMPLIANCE_OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_RECOVERY_EXCEEDS_SCOPE)

        recall_now = validate_success(api.get_recall(recall["id"], COMPLIANCE_OFFICER))
        assert recall_now["status"] == "INITIATED", "failed posting applied nothing"
        assert recall_now["units_recovered"] == 0

    def test_recall_empty_scope_rejected(self, api):
        """PRD §3.7: "An empty scope is rejected with
        `ERR_EMPTY_RECALL_SCOPE` (HTTP 422)".

        Design: Corner/state_machines/recall_empty_scope_rejected
        """
        plant = create_plant("Plant SM28")
        resp = api.create_recall(
            plant["id"], {"reason": "no lots", "lot_ids": []}, COMPLIANCE_OFFICER
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_RECALL_SCOPE)

    def test_recall_scope_non_released_lot_rejected(self, api):
        """PRD §3.7: "every listed lot must exist and must currently be
        `RELEASED`, otherwise `ERR_RECALL_LOT_NOT_RELEASED` (HTTP 409)."

        Design: Corner/state_machines/recall_scope_non_released_lot_rejected
        """
        plant = create_plant("Plant SM29")
        permit = create_permit(plant["id"], permit_number="SP-SM29")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=500)
        run = create_treatment_run(plant["id"], permit["id"])
        lot_qa, _ = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=100, produced_units=100,
        )
        resp = api.create_recall(
            plant["id"], {"reason": "premature", "lot_ids": [lot_qa["id"]]},
            COMPLIANCE_OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_RECALL_LOT_NOT_RELEASED)


class TestSanitationGatePriority:
    def test_sanitation_gate_blocks_refill_until_micro_test_passes(self, api):
        """PRD §3.8: "if the bottle has been washed before, the
        `BOTTLE_SANITATION` lab test covering the batch named by
        `last_wash_batch_id` must be `COMPLETED_PASS`, otherwise
        `ERR_SANITATION_TEST_PENDING` (HTTP 409); never-washed new stock,
        with a null `last_wash_batch_id`, passes this gate on its first
        fill."

        Design: Difficulty/priority_pair_validation_conflict/sanitation_pending_safety_beats_cross_plant_referential
        """
        s = setup_released_lot_scenario("Plant PP2-C", planned_units=100,
                                        produced_units=100, preform_units=2000)
        plant, lot = s["plant"], s["lot"]
        b = create_bottle(plant["id"], "B-PP2C")
        # First fill passes the gate (never-washed stock), then one PASSED
        # wash leaves the AUTO sanitation micro test SCHEDULED.
        bottle, batch = wash_bottle_once(plant["id"], b["id"], lot["id"])
        assert batch["status"] == "PASSED"
        assert bottle["status"] == "SANITIZED"
        assert bottle["last_wash_batch_id"] == batch["id"]

        # Same-plant lot, so only the sanitation gate can fire: the pending
        # micro test blocks the refill.
        resp = api.fill_bottle(b["id"], {"lot_id": lot["id"]}, PL1)
        validate_error(resp, ApiErrorId.ERR_SANITATION_TEST_PENDING)
        after = validate_success(api.get_bottle(b["id"], SL1))
        assert after["status"] == "SANITIZED"

    def test_sanitation_pending_safety_beats_cross_plant_referential(self, api):
        """PRD §2.7 rung 6 sits before rung 8, and §3.8: "The sanitation gate
        comes first among the business checks: if the bottle has been washed
        before, the `BOTTLE_SANITATION` lab test covering the batch named by
        `last_wash_batch_id` must be `COMPLETED_PASS`, otherwise
        `ERR_SANITATION_TEST_PENDING` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/sanitation_pending_safety_beats_cross_plant_referential
        """
        # Plant A: bottle washed once (PASSED batch) so last_wash_batch_id is
        # set; its AUTO sanitation test is left SCHEDULED (never resulted).
        sa = setup_released_lot_scenario("Plant PP2-A", planned_units=100,
                                         produced_units=100, preform_units=2000)
        plant_a, lot_a = sa["plant"], sa["lot"]
        b = create_bottle(plant_a["id"], "B-PP2")
        bottle, batch_a = wash_bottle_once(plant_a["id"], b["id"], lot_a["id"])
        assert batch_a["status"] == "PASSED"
        assert bottle["status"] == "SANITIZED"
        assert bottle["last_wash_batch_id"] == batch_a["id"]

        # Plant B: fully independent second plant with its own RELEASED lot.
        sb = setup_released_lot_scenario("Plant PP2-B", planned_units=100,
                                         produced_units=100, preform_units=2000)
        lot_b = sb["lot"]

        # The fill violates both the sanitation gate (priority 6) and the
        # cross-plant rule (priority 8); the safety error wins.
        resp = api.fill_bottle(b["id"], {"lot_id": lot_b["id"]}, PL1)
        validate_error(resp, ApiErrorId.ERR_SANITATION_TEST_PENDING)


class TestSuspendedPermitPriority:
    def test_suspended_permit_outright_posting_rejected_regardless_of_volume(self, api):
        """PRD §3.1: "Posting against a permit that is not `ACTIVE` —
        including a superseding correction — is rejected with
        `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_permit_state_beats_daily_cap
        """
        plant = create_plant("Plant PP1b")
        permit = create_permit(plant["id"], permit_number="SP-PP1B",
                               daily_cap_gallons=1000, monthly_cap_gallons=30000)
        validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))
        suspended = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert suspended["status"] == "SUSPENDED"

        # Even a small posting well under the cap is refused on a suspended
        # permit: the state guard fires before any cap arithmetic.
        payload = create_withdrawal_event_payload(
            gallons=100, meter_reading_start_gallons=0,
            meter_reading_end_gallons=100,
            expected_permit_version=suspended["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

    def test_suspended_permit_state_beats_daily_cap(self, api):
        """PRD §2.7 rung 5 sits before rung 9, and §3.1: "Posting against a
        permit that is not `ACTIVE` — including a superseding correction — is
        rejected with `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/suspended_permit_state_beats_daily_cap
        """
        plant = create_plant("Plant PP1")
        permit = create_permit(plant["id"], permit_number="SP-PP1",
                               daily_cap_gallons=1000, monthly_cap_gallons=30000)
        # Fill the daily provisional total to exactly the cap.
        post_withdrawal_event(permit["id"], gallons=1000)
        validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))

        suspended = validate_success(api.get_permit(permit["id"], SOURCE_MONITOR))
        assert suspended["status"] == "SUSPENDED"

        # One more gallon would violate the cap, but the state guard (rung 5)
        # fires before the capacity check (rung 9); the OCC version is fresh
        # so rung 4 passes.
        payload = create_withdrawal_event_payload(
            gallons=1, meter_reading_start_gallons=1000,
            meter_reading_end_gallons=1001,
            expected_permit_version=suspended["version"],
        )
        resp = api.create_withdrawal_event(permit["id"], payload, SOURCE_MONITOR)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)


class TestPreformLedgerCompensation:
    def test_lot_completion_consumes_and_releases_in_one_step(self, api):
        """PRD §3.6: "Completion stamps the operator into
        `completed_by_user_id`, consumes the preforms by subtracting
        `produced_units` from the line's `preform_on_hand_units`, releases
        the reservation by subtracting `planned_units` from
        `preform_reserved_units`, increments the line's `version`".

        Design: Difficulty/compensating_invariant/preform_reservation_create_cancel_conservation
        """
        plant = create_plant("Plant CI1b")
        permit = create_permit(plant["id"], permit_number="SP-CI1B")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=5000)
        run = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-10T06:00:00Z", scheduled_end="2026-08-10T08:00:00Z",
        )
        lot = create_lot_on_line(
            line["id"], run["id"], planned_units=2000,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        mid = validate_success(api.get_bottling_line(line["id"], PL1))
        assert mid["preform_on_hand_units"] == 5000
        assert mid["preform_reserved_units"] == 2000

        validate_success(api.start_production_lot(lot["id"], PL1))
        completed = validate_success(api.complete_production_lot(
            lot["id"], {"produced_units": 1500}, PL1
        ))
        assert completed["status"] == "QA_HOLD"

        after = validate_success(api.get_bottling_line(line["id"], PL1))
        # Reservation released (2000) and consumption booked (1500).
        assert after["preform_on_hand_units"] == 3500
        assert after["preform_reserved_units"] == 0
        assert after["preform_free_units"] == 3500

    def test_preform_reservation_create_cancel_conservation(self, api):
        """PRD §3.6: "the reservation books `planned_units` into the line's
        `preform_reserved_units`" and "Cancellation ... releases the
        reservation by subtracting `planned_units` from the line's
        `preform_reserved_units`".

        Design: Difficulty/compensating_invariant/preform_reservation_create_cancel_conservation
        """
        plant = create_plant("Plant CI1")
        permit = create_permit(plant["id"], permit_number="SP-CI1")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=5000)
        run = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-10T06:00:00Z", scheduled_end="2026-08-10T08:00:00Z",
        )

        baseline = validate_success(api.get_bottling_line(line["id"], PL1))
        assert baseline["preform_on_hand_units"] == 5000
        assert baseline["preform_reserved_units"] == 0
        assert baseline["preform_free_units"] == 5000

        lot = create_lot_on_line(
            line["id"], run["id"], planned_units=2000,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        after_create = validate_success(api.get_bottling_line(line["id"], PL1))
        assert after_create["preform_on_hand_units"] == 5000
        assert after_create["preform_reserved_units"] == 2000
        assert after_create["preform_free_units"] == 3000

        cancelled = validate_success(api.cancel_production_lot(lot["id"], PL1))
        assert cancelled["status"] == "CANCELLED"
        after_cancel = validate_success(api.get_bottling_line(line["id"], PL1))
        assert after_cancel["preform_on_hand_units"] == 5000
        assert after_cancel["preform_reserved_units"] == 0
        assert after_cancel["preform_free_units"] == 5000, (
            "compensating cancel restores the exact baseline — zero drift"
        )
