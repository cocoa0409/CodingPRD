"""Inspections: scheduling occupation regimes, reporting, and the rework loop."""
from test_helpers import (
    ApiErrorId,
    PARTIES,
    TEST_USERS,
    create_draw,
    get_holdback,
    get_work_order,
    list_draws,
    list_inspections,
    report_inspection,
    schedule_and_report_inspection,
    schedule_inspection,
    set_logical_clock,
    setup_active_holdback,
    setup_engagement,
    submit_completion,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestWorkOrderReworkCycle:
    def test_failed_final_loops_work_order_back_to_in_progress(self, api):
        """PRD §3.4: "`FAILED` loops the work order back from `COMPLETION_SUBMITTED` to `IN_PROGRESS`, increments `failed_final_count` by one, recomputes `work_verified` to false, and drops `closeout_status` back to `NOT_READY`."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        submit_completion(ctx["work_order"]["id"])

        fins = schedule_and_report_inspection(
            hb_id, purpose="FINAL_VERIFICATION",
            scheduled_start="2026-08-20T09:00:00Z", scheduled_end="2026-08-20T10:00:00Z",
            result="FAILED", result_notes="Flashing missing")
        assert fins["status"] == "FAILED"

        wo = get_work_order(hb_id)
        assert wo["status"] == "IN_PROGRESS", "rework loop traversed"
        assert wo["failed_final_count"] == 1

        hb = get_holdback(hb_id)
        assert hb["work_verified"] is False
        assert hb["closeout_status"] == "NOT_READY"

    def test_reinspection_pass_after_rework_verifies(self, api):
        """PRD §3.4: "The rework loop is thus cyclic: after a failure the contractor works, declares completion again, and faces another final inspection or a reinspection."
        PRD §3.4: "`PASSED` moves the work order from `COMPLETION_SUBMITTED` to its terminal `VERIFIED` state, recomputing the holdback's `work_verified` to true and recomputing `closeout_status`"
        PRD §3.4: "A `REINSPECTION` presupposes a prior failed final: scheduling one while the work order's `failed_final_count` is still zero is rejected with `ERR_INVALID_STATE`."

        After one FAILED final, resubmission plus a PASSED reinspection reaches
        VERIFIED with failed_final_count == 1.

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        submit_completion(ctx["work_order"]["id"])
        fins = schedule_and_report_inspection(
            hb_id, purpose="FINAL_VERIFICATION",
            scheduled_start="2026-08-20T09:00:00Z", scheduled_end="2026-08-20T10:00:00Z",
            result="FAILED", result_notes="Flashing missing")
        assert fins["status"] == "FAILED"

        # Rework: contractor declares completion again, then a REINSPECTION
        # (enabled solely by the prior failure) passes.
        submit_completion(ctx["work_order"]["id"])
        rins = schedule_and_report_inspection(
            hb_id, purpose="REINSPECTION",
            scheduled_start="2026-08-28T09:00:00Z", scheduled_end="2026-08-28T10:00:00Z",
            result="PASSED")
        assert rins["status"] == "PASSED"

        wo = get_work_order(hb_id)
        assert wo["status"] == "VERIFIED"
        assert wo["failed_final_count"] == 1

        statuses = {i["id"]: i["status"] for i in list_inspections(hb_id)}
        assert statuses[fins["id"]] == "FAILED"
        assert statuses[rins["id"]] == "PASSED"

        hb = get_holdback(hb_id)
        assert hb["work_verified"] is True


class TestFinalInspectionGating:
    def test_final_report_requires_completion_submitted(self, api):
        """PRD §3.4: "A `FINAL_VERIFICATION` or `REINSPECTION` report requires the work order to be sitting in `COMPLETION_SUBMITTED` — reporting otherwise fails with `ERR_WORK_NOT_SUBMITTED`"

        While the work order is IN_PROGRESS the report is rejected and the
        inspection stays PLANNED.

        Design: Difficulty/cross_entity_state_dependency/final_inspection_requires_completion_submitted
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        fins = schedule_inspection(hb_id, purpose="FINAL_VERIFICATION",
                                   scheduled_start="2026-08-25T09:00:00Z",
                                   scheduled_end="2026-08-25T10:00:00Z")

        resp = api.report_inspection(fins["id"], {"result": "PASSED"},
                                     TEST_USERS["insp_1_headers"])
        validate_error(resp, ApiErrorId.ERR_WORK_NOT_SUBMITTED)

        statuses = {i["id"]: i["status"] for i in list_inspections(hb_id)}
        assert statuses[fins["id"]] == "PLANNED", "no state consumption on failure"

    def test_final_report_succeeds_after_completion_submitted(self, api):
        """PRD §3.4: "A `FINAL_VERIFICATION` or `REINSPECTION` report requires the work order to be sitting in `COMPLETION_SUBMITTED` — reporting otherwise fails with `ERR_WORK_NOT_SUBMITTED` — and it drives the verification state machine: `PASSED` moves the work order from `COMPLETION_SUBMITTED` to its terminal `VERIFIED` state"

        The same report succeeds once the contractor declares completion.

        Design: Difficulty/cross_entity_state_dependency/final_inspection_requires_completion_submitted
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]
        fins = schedule_inspection(hb_id, purpose="FINAL_VERIFICATION",
                                   scheduled_start="2026-08-25T09:00:00Z",
                                   scheduled_end="2026-08-25T10:00:00Z")
        early = api.report_inspection(fins["id"], {"result": "PASSED"},
                                      TEST_USERS["insp_1_headers"])
        validate_error(early, ApiErrorId.ERR_WORK_NOT_SUBMITTED)

        submit_completion(ctx["work_order"]["id"])
        reported = validate_success(
            api.report_inspection(fins["id"], {"result": "PASSED"},
                                  TEST_USERS["insp_1_headers"]),
            200,
        )
        assert reported["status"] == "PASSED"
        assert get_work_order(hb_id)["status"] == "VERIFIED"
        assert get_holdback(hb_id)["work_verified"] is True


class TestSchedulingRegimes:
    def test_inspector_calendar_allows_half_open_adjacency(self, api):
        """PRD §3.4: "Because the end instant itself is free, pure adjacency is allowed: a new window beginning exactly when an existing one ends, or ending exactly when one begins, does not conflict."

        insp_1 holds [10:00,11:00) on holdback A; [11:00,12:00) on holdback B
        for the same inspector is accepted.

        Design: Difficulty/resource_temporal_overlap/inspector_calendar_half_open_overlap
        """
        set_logical_clock()
        ctx_a = setup_active_holdback(
            clock=None, file_overrides={"property_address": "1 Harbor Way"})
        schedule_inspection(ctx_a["holdback"]["id"], purpose="DRAW_VERIFICATION",
                            scheduled_start="2026-08-20T10:00:00Z",
                            scheduled_end="2026-08-20T11:00:00Z")

        ctx_b = setup_active_holdback(
            clock=None, file_overrides={"property_address": "2 Cedar Ln"})
        adjacent = validate_success(
            api.create_inspection(
                {"holdback_id": ctx_b["holdback"]["id"],
                 "inspector_user_id": PARTIES["inspector"],
                 "purpose": "DRAW_VERIFICATION",
                 "scheduled_start": "2026-08-20T11:00:00Z",
                 "scheduled_end": "2026-08-20T12:00:00Z"},
                OFFICER),
            201,
        )
        assert adjacent["status"] == "PLANNED"

    def test_inspector_calendar_rejects_cross_holdback_overlap(self, api):
        """PRD §3.4: "The inspector-calendar regime is half-open across the inspector's entire book of work: a new window conflicts with any `PLANNED` inspection of the same `inspector_user_id` on any holdback when the new window begins before the existing window ends and the existing window begins before the new window ends."
        PRD §3.4: "A violation is `ERR_INSPECTOR_SCHEDULE_CONFLICT`."

        [10:30,11:30) collides with insp_1's existing [10:00,11:00) even though
        the existing booking sits on another holdback.

        Design: Difficulty/resource_temporal_overlap/inspector_calendar_half_open_overlap
        """
        set_logical_clock()
        ctx_a = setup_active_holdback(
            clock=None, file_overrides={"property_address": "1 Harbor Way"})
        schedule_inspection(ctx_a["holdback"]["id"], purpose="DRAW_VERIFICATION",
                            scheduled_start="2026-08-20T10:00:00Z",
                            scheduled_end="2026-08-20T11:00:00Z")
        ctx_b = setup_active_holdback(
            clock=None, file_overrides={"property_address": "2 Cedar Ln"})

        resp = api.create_inspection(
            {"holdback_id": ctx_b["holdback"]["id"],
             "inspector_user_id": PARTIES["inspector"],
             "purpose": "DRAW_VERIFICATION",
             "scheduled_start": "2026-08-20T10:30:00Z",
             "scheduled_end": "2026-08-20T11:30:00Z"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_SCHEDULE_CONFLICT)

    def test_property_slot_closed_interval_adjacency_conflicts(self, api):
        """PRD §3.4: "The property-slot regime is closed within the single holdback: a new window conflicts with any `PLANNED` inspection of the same holdback when it begins before or exactly when the existing window ends and the existing window begins before or exactly when the new window ends — so here adjacency does conflict."
        PRD §3.4: "A violation is `ERR_INSPECTION_SLOT_OCCUPIED`."

        With [10:00,11:00] already PLANNED on the holdback, an adjacent
        [11:00,12:00] from a DIFFERENT inspector conflicts on the property slot.

        Design: Difficulty/resource_temporal_overlap/property_slot_closed_interval_overlap
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        schedule_inspection(hb_id, purpose="DRAW_VERIFICATION",
                            scheduled_start="2026-08-20T10:00:00Z",
                            scheduled_end="2026-08-20T11:00:00Z")

        resp = api.create_inspection(
            {"holdback_id": hb_id, "inspector_user_id": PARTIES["inspector_b"],
             "purpose": "DRAW_VERIFICATION",
             "scheduled_start": "2026-08-20T11:00:00Z",
             "scheduled_end": "2026-08-20T12:00:00Z"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_SLOT_OCCUPIED)

    def test_property_slot_accepts_one_second_gap(self, api):
        """PRD §3.4: "The property-slot regime is closed within the single holdback: a new window conflicts with any `PLANNED` inspection of the same holdback when it begins before or exactly when the existing window ends and the existing window begins before or exactly when the new window ends — so here adjacency does conflict."

        Starting one second after the existing window's end satisfies closed
        semantics; the new inspection is PLANNED.

        Design: Difficulty/resource_temporal_overlap/property_slot_closed_interval_overlap
        """
        ctx = setup_active_holdback()
        hb_id = ctx["holdback"]["id"]
        schedule_inspection(hb_id, purpose="DRAW_VERIFICATION",
                            scheduled_start="2026-08-20T10:00:00Z",
                            scheduled_end="2026-08-20T11:00:00Z")

        ok = validate_success(
            api.create_inspection(
                {"holdback_id": hb_id, "inspector_user_id": PARTIES["inspector_b"],
                 "purpose": "DRAW_VERIFICATION",
                 "scheduled_start": "2026-08-20T11:00:01Z",
                 "scheduled_end": "2026-08-20T12:00:00Z"},
                OFFICER),
            201,
        )
        assert ok["status"] == "PLANNED"


class TestReportingDiscipline:
    def test_double_inspection_report_rejected(self, api):
        """PRD §3.4: "Reporting belongs to the assigned inspector: the caller's user id must equal the inspection's `inspector_user_id` (`ERR_NOT_FILE_PARTY`), and the inspection must still be `PLANNED` (`ERR_INSPECTION_NOT_PLANNED`)."

        Design: Corner/state_machines/double_inspection_report_rejected
        """
        ctx = setup_active_holdback()
        ins = schedule_and_report_inspection(ctx["holdback"]["id"],
                                             purpose="DRAW_VERIFICATION",
                                             result="PASSED")
        assert ins["status"] == "PASSED"

        again = api.report_inspection(ins["id"], {"result": "FAILED"},
                                      TEST_USERS["insp_1_headers"])
        validate_error(again, ApiErrorId.ERR_INSPECTION_NOT_PLANNED)

        statuses = {i["id"]: i["status"] for i in list_inspections(ctx["holdback"]["id"])}
        assert statuses[ins["id"]] == "PASSED"

    def test_reinspection_without_prior_failure_rejected(self, api):
        """PRD §3.4: "A `REINSPECTION` presupposes a prior failed final: scheduling one while the work order's `failed_final_count` is still zero is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinspection_without_prior_failure_rejected
        """
        ctx = setup_engagement()
        assert ctx["work_order"]["failed_final_count"] == 0

        resp = api.create_inspection(
            {"holdback_id": ctx["holdback"]["id"],
             "inspector_user_id": PARTIES["inspector"],
             "purpose": "REINSPECTION",
             "scheduled_start": "2026-08-20T10:00:00Z",
             "scheduled_end": "2026-08-20T11:00:00Z"},
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestVerifyingInspection:
    def test_verifying_inspection_must_postdate_draw(self, api):
        """PRD §3.5: "a verifying inspection must exist: one in `PASSED` state whose `purpose` is `DRAW_VERIFICATION` or `FINAL_VERIFICATION` and whose `reported_at` is on or after the draw's `created_at` — among qualifying inspections the one with the latest `reported_at` serves as the verification of record, ties broken by the earliest `created_at`. Without one, approval fails with `ERR_NO_VERIFYING_INSPECTION`."

        A pass reported at 2026-08-20 predates a draw created at 2026-08-21 and
        is filtered out of the approval input set.

        Design: Corner/calculations/verifying_inspection_must_postdate_draw
        """
        ctx = setup_engagement()
        hb_id = ctx["holdback"]["id"]

        set_logical_clock("2026-08-20T00:00:00Z")
        schedule_and_report_inspection(hb_id, purpose="DRAW_VERIFICATION",
                                       scheduled_start="2026-08-20T10:00:00Z",
                                       scheduled_end="2026-08-20T11:00:00Z",
                                       result="PASSED")

        set_logical_clock("2026-08-21T00:00:00Z")
        draw = create_draw(hb_id, 50000, description="Stage 1")

        resp = api.approve_draw_request(draw["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_NO_VERIFYING_INSPECTION)

        draws = {d["id"]: d for d in list_draws(hb_id)}
        assert draws[draw["id"]]["status"] == "SUBMITTED"
