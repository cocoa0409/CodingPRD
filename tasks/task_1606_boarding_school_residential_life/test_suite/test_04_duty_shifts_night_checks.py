"""Duty shift scheduling, swaps, completion gates, night checks, and cascades."""
import pytest

from test_helpers import (
    TEST_USERS, api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_duty_shift, assert_night_check,
    create_duty_shift_payload, create_night_check_payload,
    make_dorm_parent_headers, make_dean_headers,
    make_dorm, make_room, make_active_term, make_parent, make_student,
    make_dorm_parent, make_dean,
    propose_assignment, confirm_assignment, setup_confirmed_residency,
    file_leave, parent_approve_leave, dorm_approve_leave, setup_leave_approved,
    make_duty_shift, record_night_check, get_student,
    report_case, sanction_minor_case,
)


class TestNightCheckCascade:
    def _setup_probation_student_with_approved_leave(self):
        """Student CONFIRMED, one APPROVED weekend leave, an 18-point sanction
        (standing PROBATION at 18), and a SCHEDULED WEEKDAY_NIGHT shift."""
        ctx = setup_leave_approved(grade=12, gender="MALE")
        reporter = make_dean("Dean One")
        decider = make_dean("Dean Two")
        case = report_case(ctx["student"]["id"], reporter["id"], category="MINOR",
                           description="Repeated curfew violations",
                           points_proposed=18)
        sanction_minor_case(case["id"], reporter["id"], decider["id"],
                            18, sanction_type="PROBATION")
        mid = get_student(ctx["student"]["id"])
        assert mid["demerit_points"] == 18
        assert mid["discipline_standing"] == "PROBATION"
        shift = make_duty_shift(ctx["dorm"]["id"], ctx["dorm_parent"]["id"],
                                duty_date="2026-09-07", shift_slot="WEEKDAY_NIGHT")
        ctx["shift"] = shift
        return ctx

    def test_absent_unexcused_bed_check_pushes_student_to_suspended(self, api):
        """PRD §3.5: "for a bed check, `PRESENT` and `ABSENT_EXCUSED` assess 0,
        `LATE_ARRIVAL` assesses 1, and `ABSENT_UNEXCUSED` assesses 3" and "The
        assessed points land on the check's `points_assessed` and add into the
        student's official demerit total, after which standing re-evaluation runs".
        PRD §2.8: "at least 20 points means `SUSPENDED`".

        Design: Difficulty/transitive_cascade/night_check_absence_cascades_points_standing_leave_cancel
        """
        ctx = self._setup_probation_student_with_approved_leave()
        check = record_night_check(ctx["shift"]["id"], ctx["student"]["id"],
                                   ctx["dorm_parent"]["id"],
                                   check_kind="BED_CHECK", result="ABSENT_UNEXCUSED")
        assert_night_check(check)
        assert check["points_assessed"] == 3

        student = get_student(ctx["student"]["id"])
        assert student["demerit_points"] == 21  # 18 + 3 crosses the 20 threshold
        assert student["discipline_standing"] == "SUSPENDED"

    def test_suspension_cascade_cancels_pending_leave(self, api, admin_headers):
        """PRD §3.5: "a student pushed to `SUSPENDED` by a night check has every
        pending leave cancelled with `denial_reason` set to `STANDING_SUSPENDED`."

        Design: Difficulty/transitive_cascade/night_check_absence_cascades_points_standing_leave_cancel
        """
        ctx = self._setup_probation_student_with_approved_leave()
        record_night_check(ctx["shift"]["id"], ctx["student"]["id"],
                           ctx["dorm_parent"]["id"],
                           check_kind="BED_CHECK", result="ABSENT_UNEXCUSED")

        leave = get_success_data(
            api.get_leave_request(ctx["leave"]["id"], admin_headers))
        assert leave["status"] == "CANCELLED"
        assert leave["denial_reason"] == "STANDING_SUSPENDED"


class TestNightCheckShiftState:
    def _setup_completed_shift(self):
        """One-student dorm; BED_CHECK recorded; shift completed by the assignee."""
        ctx = setup_confirmed_residency(grade=10, gender="FEMALE", beds=1)
        ctx["room"] = ctx["room"]  # 1-bed room
        shift = make_duty_shift(ctx["dorm"]["id"], ctx["dorm_parent"]["id"],
                                duty_date="2026-09-07", shift_slot="WEEKDAY_NIGHT")
        check = record_night_check(shift["id"], ctx["student"]["id"],
                                   ctx["dorm_parent"]["id"],
                                   check_kind="BED_CHECK", result="PRESENT")
        completed = validate_success(api_client.complete_shift(
            shift["id"], make_dorm_parent_headers(ctx["dorm_parent"]["id"])), 200)
        ctx["shift"] = completed
        ctx["check"] = check
        return ctx

    def test_night_check_on_completed_shift_rejected(self, api):
        """PRD §3.5: "`COMPLETED`, `MISSED`, and `CANCELLED` are terminal."
        PRD §2.6: "the system check whether the target resource sits in a
        legitimate from-state for the requested transition (`ERR_INVALID_STATE`,
        HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/night_check_requires_shift_scheduled
        """
        ctx = self._setup_completed_shift()
        assert ctx["shift"]["status"] == "COMPLETED"

        res = api.create_night_check(
            ctx["shift"]["id"],
            create_night_check_payload(ctx["student"]["id"], check_kind="STUDY_HALL",
                                       result="PRESENT"),
            make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_night_check_recorded_while_shift_scheduled(self, api, admin_headers):
        """PRD §3.5: "for a bed check, `PRESENT` and `ABSENT_EXCUSED` assess 0" —
        a PRESENT bed check recorded while the shift is SCHEDULED lands with
        `points_assessed` 0.

        Design: Difficulty/cross_entity_state_dependency/night_check_requires_shift_scheduled
        """
        ctx = setup_confirmed_residency(grade=10, gender="FEMALE", beds=1)
        shift = make_duty_shift(ctx["dorm"]["id"], ctx["dorm_parent"]["id"],
                                duty_date="2026-09-07", shift_slot="WEEKDAY_NIGHT")
        check = record_night_check(shift["id"], ctx["student"]["id"],
                                   ctx["dorm_parent"]["id"],
                                   check_kind="BED_CHECK", result="PRESENT")
        assert_night_check(check)
        assert check["points_assessed"] == 0

        fetched = get_success_data(api.get_night_check(check["id"], admin_headers))
        assert fetched["id"] == check["id"]


class TestNightCheckUniquenessAndResidency:
    def test_duplicate_night_check_same_kind_rejected(self, api):
        """PRD §3.5: "only one check per shift, student, and kind may exist
        (`ERR_CHECK_ALREADY_RECORDED`)".

        Design: Corner/validations/duplicate_night_check_rejected
        """
        ctx = setup_confirmed_residency(grade=10, gender="MALE")
        shift = make_duty_shift(ctx["dorm"]["id"], ctx["dorm_parent"]["id"],
                                duty_date="2026-09-07", shift_slot="WEEKDAY_NIGHT")
        record_night_check(shift["id"], ctx["student"]["id"],
                           ctx["dorm_parent"]["id"],
                           check_kind="BED_CHECK", result="PRESENT")

        res = api.create_night_check(
            shift["id"],
            create_night_check_payload(ctx["student"]["id"], check_kind="BED_CHECK",
                                       result="LATE_ARRIVAL"),
            make_dorm_parent_headers(ctx["dorm_parent"]["id"]))
        validate_error(res, ApiErrorId.ERR_CHECK_ALREADY_RECORDED)

        # A STUDY_HALL check is a different composite key and succeeds.
        other = record_night_check(shift["id"], ctx["student"]["id"],
                                   ctx["dorm_parent"]["id"],
                                   check_kind="STUDY_HALL", result="PRESENT")
        assert other["check_kind"] == "STUDY_HALL"

    def test_night_check_for_nonresident_rejected(self, api):
        """PRD §3.5: "Recording a night check requires an active term and an
        `ENROLLED` student who holds a `CONFIRMED` assignment in the shift's dorm
        for the active term (`ERR_NOT_RESIDENT`)".

        Design: Corner/validations/night_check_nonresident_rejected
        """
        dorm_a = make_dorm(name="Winslow House")
        dorm_b = make_dorm(name="Lowell House")
        room_b = make_room(dorm_b["id"], room_number="L-101", beds=2)
        term = make_active_term()
        parent = make_parent()
        student = make_student(parent["id"], grade=10, gender="FEMALE",
                               legal_name="Stu R")
        asg = propose_assignment(student["id"], room_b["id"], term["id"])
        confirm_assignment(asg["id"])
        dp = make_dorm_parent(dorm_a["id"])
        shift = make_duty_shift(dorm_a["id"], dp["id"], duty_date="2026-09-07",
                                shift_slot="WEEKDAY_NIGHT")

        res = api.create_night_check(
            shift["id"],
            create_night_check_payload(student["id"], check_kind="BED_CHECK",
                                       result="PRESENT"),
            make_dorm_parent_headers(dp["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESIDENT)


class TestShiftCompletion:
    def test_complete_with_outstanding_checks_rejected_then_succeeds(self, api):
        """PRD §3.5: "A shift completes only when every `ENROLLED` student with a
        confirmed assignment in the shift's dorm has a `BED_CHECK` recorded on
        that shift; attempting completion early is `ERR_CHECKS_OUTSTANDING`."

        Design: Corner/validations/complete_with_outstanding_checks_rejected
        """
        dorm = make_dorm()
        room = make_room(dorm["id"], room_number="W-101", beds=2)
        term = make_active_term()
        stu_a = make_student(make_parent()["id"], grade=10, gender="MALE",
                             legal_name="Stu AD")
        stu_b = make_student(make_parent()["id"], grade=10, gender="FEMALE",
                             legal_name="Stu AE")
        dp = make_dorm_parent(dorm["id"])
        asg_a = propose_assignment(stu_a["id"], room["id"], term["id"])
        confirm_assignment(asg_a["id"])
        asg_b = propose_assignment(stu_b["id"], room["id"], term["id"])
        confirm_assignment(asg_b["id"])
        shift = make_duty_shift(dorm["id"], dp["id"], duty_date="2026-09-07",
                                shift_slot="WEEKDAY_NIGHT")
        record_night_check(shift["id"], stu_a["id"], dp["id"],
                           check_kind="BED_CHECK", result="PRESENT")

        res = api.complete_shift(shift["id"], make_dorm_parent_headers(dp["id"]))
        validate_error(res, ApiErrorId.ERR_CHECKS_OUTSTANDING)

        record_night_check(shift["id"], stu_b["id"], dp["id"],
                           check_kind="BED_CHECK", result="PRESENT")
        completed = validate_success(
            api.complete_shift(shift["id"], make_dorm_parent_headers(dp["id"])), 200)
        assert completed["status"] == "COMPLETED"


class TestDutySwap:
    def _setup_swap_pending(self, duty_date="2026-09-07"):
        dorm = make_dorm()
        dp1 = make_dorm_parent(dorm["id"], full_name="DP One")
        dp2 = make_dorm_parent(dorm["id"], full_name="DP Two")
        shift = make_duty_shift(dorm["id"], dp1["id"], duty_date=duty_date,
                                shift_slot="WEEKDAY_NIGHT")
        get_success_data(api_client.request_swap(
            shift["id"], dp2["id"], make_dorm_parent_headers(dp1["id"])))
        return dorm, dp1, dp2, shift

    def test_swap_decline_keeps_owner(self, api):
        """PRD §3.5: "Declining leaves `staff_id` unchanged, clears
        `swap_requested_to_id`, and returns the shift to `SCHEDULED`."

        Design: Corner/state_machines/duty_swap_decline_keeps_owner
        """
        dorm, dp1, dp2, shift = self._setup_swap_pending("2026-09-07")
        responded = validate_success(api.swap_respond(
            shift["id"], False, make_dorm_parent_headers(dp2["id"])), 200)
        assert_duty_shift(responded)
        assert responded["status"] == "SCHEDULED"
        assert responded["staff_id"] == dp1["id"]
        assert responded["swap_requested_to_id"] is None

    def test_swap_accept_moves_ownership(self, api):
        """PRD §3.5: "Acceptance moves ownership: `staff_id` becomes the target,
        `swap_requested_to_id` clears, and the shift returns to `SCHEDULED` under
        its new owner."

        Design: Corner/state_machines/duty_swap_accept_moves_ownership
        """
        dorm, dp1, dp2, shift = self._setup_swap_pending("2026-09-08")
        responded = validate_success(api.swap_respond(
            shift["id"], True, make_dorm_parent_headers(dp2["id"])), 200)
        assert responded["status"] == "SCHEDULED"
        assert responded["staff_id"] == dp2["id"]
        assert responded["swap_requested_to_id"] is None

    def test_swap_to_non_dorm_parent_rejected(self, api):
        """PRD §3.5: "the target must be an active dorm parent other than the
        current assignee with no conflicting shift that date, under the same
        slot-conflict rules; failures are `ERR_SWAP_TARGET_INELIGIBLE`".

        Design: Corner/validations/swap_target_ineligible_rejected
        """
        from test_helpers import make_nurse
        dorm = make_dorm()
        dp = make_dorm_parent(dorm["id"], full_name="DP One")
        nurse = make_nurse("Nurse One")
        shift = make_duty_shift(dorm["id"], dp["id"], duty_date="2026-09-07",
                                shift_slot="WEEKDAY_NIGHT")

        res = api.request_swap(shift["id"], nurse["id"],
                               make_dorm_parent_headers(dp["id"]))
        validate_error(res, ApiErrorId.ERR_SWAP_TARGET_INELIGIBLE)


class TestShiftConflictAndOcc:
    def test_same_slot_same_date_conflict_rejected(self, api, admin_headers):
        """PRD §3.5: "A staff member may not hold two non-cancelled shifts on the
        same date with conflicting slots — the same slot always conflicts,
        `WEEKEND_DAY` and `WEEKEND_NIGHT` never conflict with each other, and
        `WEEKDAY_NIGHT` conflicts only with another `WEEKDAY_NIGHT`; a violation
        is `ERR_SHIFT_CONFLICT`."

        Design: Corner/validations/staff_shift_conflict_rejected
        """
        dorm_a = make_dorm(name="Winslow House")
        dorm_b = make_dorm(name="Lowell House")
        dp = make_dorm_parent(dorm_a["id"], full_name="DP One")
        make_duty_shift(dorm_a["id"], dp["id"], duty_date="2026-09-07",
                        shift_slot="WEEKDAY_NIGHT")

        dorm_b_fresh = get_success_data(api.get_dorm(dorm_b["id"], admin_headers))
        res = api.create_duty_shift(
            create_duty_shift_payload(dorm_b["id"], dp["id"],
                                      dorm_b_fresh["version"],
                                      duty_date="2026-09-07",
                                      shift_slot="WEEKDAY_NIGHT"),
            admin_headers)
        validate_error(res, ApiErrorId.ERR_SHIFT_CONFLICT)

    def test_stale_dorm_version_rejected_then_fresh_create_supersedes(self, api, admin_headers):
        """PRD §2.7: "Creating a duty shift requires `expected_dorm_version`,
        matching the target dorm's current `version`." and "a mismatch with the
        parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "Creating a shift for a dorm, date, and slot that already has a
        `SCHEDULED` shift supersedes the old one: it moves to `CANCELLED` with
        `cancel_reason` set to `SUPERSEDED`."

        Design: Corner/cross_cutting/duty_shift_create_stale_dorm_version_occ
        """
        dorm = make_dorm()
        dp1 = make_dorm_parent(dorm["id"], full_name="DP One")
        dp2 = make_dorm_parent(dorm["id"], full_name="DP Two")
        stale_version = dorm["version"]
        shift1 = get_success_data(api.create_duty_shift(
            create_duty_shift_payload(dorm["id"], dp1["id"], stale_version,
                                      duty_date="2026-09-07",
                                      shift_slot="WEEKDAY_NIGHT"), admin_headers))
        assert_duty_shift(shift1)

        # The first create bumped the dorm version; replaying it is stale.
        res = api.create_duty_shift(
            create_duty_shift_payload(dorm["id"], dp2["id"], stale_version,
                                      duty_date="2026-09-07",
                                      shift_slot="WEEKDAY_NIGHT"), admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        fresh = get_success_data(api.get_dorm(dorm["id"], admin_headers))
        shift2 = validate_success(api.create_duty_shift(
            create_duty_shift_payload(dorm["id"], dp2["id"], fresh["version"],
                                      duty_date="2026-09-07",
                                      shift_slot="WEEKDAY_NIGHT"), admin_headers), 201)
        assert shift2["status"] == "SCHEDULED"
        assert shift2["staff_id"] == dp2["id"]

        old = validate_success(api.get_duty_shift(shift1["id"], admin_headers), 200)
        assert old["status"] == "CANCELLED"
        assert old["cancel_reason"] == "SUPERSEDED"
