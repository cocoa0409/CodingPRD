"""Inspection scheduling and results: PASS/FAIL fork, half-open inspector
double-booking, aggregate slot capacity, window containment, the
rough-before-final gate, and the parent-must-be-ISSUED gate.

PRD §3.7 (scheduling), §3.8 (results), §2.6 (validation order).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_issued_permit_with_scheduled_rough,
    create_issued_permit_with_slot,
    create_approved_permit,
    create_jurisdiction,
    create_contractor,
    create_inspector,
    create_slot,
    pay_in_full,
    record_result,
    schedule_inspection,
    make_applicant_headers,
    make_inspector_headers,
)


class TestInspectionFork:
    def test_fail_outcome_sets_status_failed(self, api):
        """PRD §3.8: "On a `FAIL` outcome, the inspection's `inspection_status`
        becomes `FAILED` and an `INSPECTION_FAILED` audit event is appended."

        Design: Difficulty/non_linear_state_machine/inspection_branching_pass_vs_fail_fork
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000))
        resp = api.record_inspection_result(
            rough["id"], {"outcome": "FAIL"}, make_inspector_headers(inspector["id"]))
        data = validate_success(resp)
        assert data["inspection_status"] == "FAILED"

    def test_failed_inspection_is_non_terminal_rerequest_allowed(self, api):
        """PRD §3.8: "A failed inspection is not terminal: the applicant may
        schedule a fresh inspection of the same type to try again."

        Design: Difficulty/non_linear_state_machine/inspection_branching_pass_vs_fail_fork
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000))
        record_result(rough["id"], inspector["id"], "FAIL")
        # A fresh ROUGH at a non-overlapping interval inside the window succeeds.
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T11:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            make_applicant_headers())
        data = validate_success(resp, 201)
        assert data["inspection_status"] == "SCHEDULED"


class TestInspectorDoubleBooking:
    def test_overlapping_interval_rejected(self, api):
        """PRD §3.7: "The slot's inspector must not already hold an inspection
        whose interval overlaps the requested one; overlap is judged on half-open
        intervals, so two intervals that merely touch at an endpoint do not
        overlap, while any genuine overlap is rejected with
        `ERR_INSPECTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/inspector_double_booking_half_open_adjacency_allowed
        """
        # One ROUGH [09:00,10:00) already booked; a second [09:30,10:30) overlaps.
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=5, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T09:30:00Z",
             "scheduled_end": "2026-07-01T10:30:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INSPECTOR_DOUBLE_BOOKED.value)

    def test_touching_interval_does_not_overlap(self, api):
        """PRD §3.7: "two intervals that merely touch at an endpoint do not
        overlap, while any genuine overlap is rejected with
        `ERR_INSPECTOR_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/inspector_double_booking_half_open_adjacency_allowed
        """
        # One ROUGH [09:00,10:00) booked; [10:00,11:00) merely touches => allowed.
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=5, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T10:00:00Z",
             "scheduled_end": "2026-07-01T11:00:00Z"},
            make_applicant_headers())
        data = validate_success(resp, 201)
        assert data["inspection_status"] == "SCHEDULED"


class TestSlotAggregateCapacity:
    def test_capacity_exhausted_rejects_nonoverlapping_booking(self, api):
        """PRD §3.7: "Finally, the slot's `booked_count` must be strictly less than
        its `max_inspections` before another booking is added; a full slot is
        rejected with `ERR_SLOT_CAPACITY_FULL`."

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_overlap_exhausted
        """
        # max_inspections=1; one ROUGH booked; a NON-overlapping second still rejected.
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=1, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        slot_read = validate_success(api.get_slot(slot["id"], make_applicant_headers()))
        assert slot_read["booked_count"] == 1
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T11:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_FULL.value)

    def test_capacity_full_distinct_from_double_booking(self, api):
        """PRD §3.7: "the slot's `booked_count` must be strictly less than its
        `max_inspections` before another booking is added; a full slot is rejected
        with `ERR_SLOT_CAPACITY_FULL`."

        Design: Difficulty/resource_temporal_overlap/slot_aggregate_capacity_overlap_exhausted
        """
        issued, reviewer, inspector, slot, rough = (
            create_issued_permit_with_scheduled_rough(
                max_inspections=1, work_class="REPAIR",
                fee_method="VALUATION", declared_valuation=2000))
        # Non-overlapping interval rules out double-booking; only capacity can fire.
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T13:00:00Z",
             "scheduled_end": "2026-07-01T14:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_FULL.value)


class TestOutsideSlotWindow:
    def test_interval_before_window_rejected(self, api):
        """PRD §3.7: "The requested interval must lie entirely within the chosen
        slot's window — its start at or after `window_start` and its end at or
        before `window_end` — or it is rejected with `ERR_OUTSIDE_SLOT_WINDOW`."

        Design: Corner/validations/inspection_outside_slot_window_returns_outside_window
        """
        issued, reviewer, inspector, slot = create_issued_permit_with_slot(
            max_inspections=5, work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T07:00:00Z",
             "scheduled_end": "2026-07-01T08:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SLOT_WINDOW.value)


class TestRoughBeforeFinalSchedule:
    def test_schedule_final_without_passed_rough_rejected(self, api):
        """PRD §3.7: "A `FINAL` inspection may not be scheduled unless a `PASSED`
        `ROUGH` inspection already exists for the permit; absent one, the request
        is rejected with `ERR_ROUGH_NOT_PASSED`."

        Design: Corner/validations/schedule_final_without_passed_rough_returns_rough_not_passed
        """
        issued, reviewer, inspector, slot = create_issued_permit_with_slot(
            max_inspections=5, work_class="REPAIR",
            fee_method="VALUATION", declared_valuation=2000)
        resp = api.schedule_inspection(
            issued["id"],
            {"slot_id": slot["id"], "inspection_type": "FINAL",
             "scheduled_start": "2026-07-01T11:00:00Z",
             "scheduled_end": "2026-07-01T12:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_ROUGH_NOT_PASSED.value)


class TestSchedulingRequiresIssuedPermit:
    def test_schedule_against_approved_permit_rejected(self, api):
        """PRD §3.7: "The parent permit's `status` must be `ISSUED`; scheduling
        against a permit in any other status is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/inspection_scheduling_depends_on_permit_issued
        """
        # Permit APPROVED + fully paid but NOT issued; a slot is available.
        jur = create_jurisdiction()
        con = create_contractor()
        inspector = create_inspector()
        slot = create_slot(inspector["id"], max_inspections=5)
        permit, _review, _rev = create_approved_permit(
            jurisdiction_id=jur["id"], contractor_id=con["id"],
            work_class="REPAIR", fee_method="VALUATION", declared_valuation=2000)
        pay_in_full(permit["id"])
        permit_read = validate_success(api.get_permit(permit["id"], make_applicant_headers()))
        assert permit_read["status"] == "APPROVED"
        resp = api.schedule_inspection(
            permit["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T09:00:00Z",
             "scheduled_end": "2026-07-01T10:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_schedule_against_submitted_permit_rejected(self, api):
        """PRD §3.7: "scheduling against a permit in any other status is rejected
        with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/inspection_scheduling_depends_on_permit_issued
        """
        from test_helpers import create_permit
        jur = create_jurisdiction()
        con = create_contractor()
        inspector = create_inspector()
        slot = create_slot(inspector["id"], max_inspections=5)
        permit = create_permit(jur["id"], con["id"],
                              work_class="REPAIR", fee_method="VALUATION",
                              declared_valuation=2000)
        resp = api.schedule_inspection(
            permit["id"],
            {"slot_id": slot["id"], "inspection_type": "ROUGH",
             "scheduled_start": "2026-07-01T09:00:00Z",
             "scheduled_end": "2026-07-01T10:00:00Z"},
            make_applicant_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
