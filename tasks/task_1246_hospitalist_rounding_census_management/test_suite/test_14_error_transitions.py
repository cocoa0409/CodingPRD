"""Error / invalid-transition tests: admission accept from QUEUED, accept by
non-offered, cancel-transfer on ACTIVE, accept-transfer by non-target,
duplicate active assignment, enrollment errors, shift invalid window.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, make_hospitalist_headers,
    set_clock, create_hospitalist, create_patient, create_shift,
    admit_and_accept, create_coverage_window,
)

ADMIN = TEST_USERS["group_admin_headers"]


class TestAdmissionAcceptFromQueuedRejected:
    """Corner instance: admission_accept_from_queued_rejected."""

    def test_accept_on_queued_fails(self, api):
        """PRD §3.3: "The admission must currently be `OFFERED`, else
        `ERR_ADMISSION_INVALID_STATE` (HTTP 409)."
        PRD §3.3: "When the pool is empty the admission simply remains
        `QUEUED` with a null `offered_to_hospitalist_id` — a documented
        fallback, not an error".

        Design: Corner/state_machines/admission_accept_from_queued_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)  # no shift
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="S001", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["status"] == "QUEUED"
        resp = api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_ADMISSION_INVALID_STATE)


class TestAdmissionAcceptByNonOfferedRejected:
    """Corner instance: admission_accept_by_non_offered_rejected."""

    def test_accept_by_other_hospitalist_fails(self, api):
        """PRD §3.3: "the caller must equal `offered_to_hospitalist_id`, else
        `ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST` (HTTP 409)".

        Design: Corner/errors/admission_accept_by_non_offered_rejected
        """
        h_a = create_hospitalist("H A", "ICU", max_census_cap=16)
        h_b = create_hospitalist("H B", "INTERNAL_MEDICINE", max_census_cap=16)
        create_shift(h_a["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        create_shift(h_b["id"], "DAY", "2026-05-01T07:00:00Z", "2026-05-01T19:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X001", acuity="LOW", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a1["offered_to_hospitalist_id"] == h_a["id"]
        resp = api.accept_admission(a1["id"], make_hospitalist_headers(h_b["id"]))
        validate_error(resp, ApiErrorId.ERR_ADMISSION_NOT_OFFERED_TO_HOSPITALIST)
        # admission remains OFFERED to h_a
        a_now = get_success_data(api.get_admission(a1["id"], ADMIN))
        assert a_now["status"] == "OFFERED"
        assert a_now["offered_to_hospitalist_id"] == h_a["id"]


class TestAssignmentCancelTransferWhenActiveRejected:
    """Corner instance: assignment_cancel_transfer_when_active_rejected."""

    def test_cancel_on_active_fails(self, api):
        """PRD §3.4: "cancelling requires the assignment to be
        `PENDING_TRANSFER` (else `ERR_ASSIGNMENT_INVALID_STATE`)".

        Design: Corner/errors/assignment_cancel_transfer_when_active_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X002", acuity="LOW", admit_source="DIRECT",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        _, asg_id = admit_and_accept(p1["id"])
        resp = api.cancel_transfer(asg_id, make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "ACTIVE"


class TestAcceptTransferByNonTargetRejected:
    """Corner instance: accept_transfer_by_non_target_rejected."""

    def test_accept_by_non_target_fails(self, api):
        """PRD §3.4: "the caller must equal `transfer_target_hospitalist_id`
        (else `ERR_TRANSFER_TARGET_MISMATCH`, HTTP 409)".

        Design: Corner/errors/accept_transfer_by_non_target_rejected
        """
        h_s = create_hospitalist("H S", "ICU", max_census_cap=16)
        h_t = create_hospitalist("H T", "INTERNAL_MEDICINE", max_census_cap=16)
        h_x = create_hospitalist("H X", "FAMILY_MEDICINE", max_census_cap=16)
        create_shift(h_s["id"], "DAY", "2026-05-01T08:00:00Z", "2026-05-01T20:00:00Z", activate=True)
        create_shift(h_t["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        create_shift(h_x["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X003", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:30:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        # All three candidates score 1.0 at census 0; H_S's shift starts later
        # (08:00), and H_T/H_X tie on shift start (06:00) and shift created_at.
        # Whoever the selector picks, the transfer target must differ from the
        # current holder (PRD §2.7 item 3), so choose target and bystander
        # from the two hospitalists who did not win the offer.
        acc = get_success_data(api.accept_admission(
            a1["id"], make_hospitalist_headers(a1["offered_to_hospitalist_id"])
        ))
        asg_id = acc["assignment_id"]
        holder_id = acc["offered_to_hospitalist_id"]
        others = [h for h in (h_s, h_t, h_x) if h["id"] != holder_id]
        target, bystander = others[0], others[1]
        asg_v = get_success_data(api.get_assignment(asg_id, ADMIN))["version"]
        # Transfer target chosen != holder; accept attempted by the bystander
        # (who also holds an ACTIVE shift covering now).
        get_success_data(api.transfer_assignment(
            asg_id,
            {"target_hospitalist_id": target["id"], "expected_assignment_version": asg_v},
            make_hospitalist_headers(holder_id),
        ))
        resp = api.accept_transfer(asg_id, make_hospitalist_headers(bystander["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_TARGET_MISMATCH)
        asg_now = get_success_data(api.get_assignment(asg_id, ADMIN))
        assert asg_now["status"] == "PENDING_TRANSFER"
        assert asg_now["transfer_target_hospitalist_id"] == target["id"]


class TestDuplicateActiveAssignmentRejected:
    """Corner instance: duplicate_active_assignment_rejected."""

    def test_second_accept_fails(self, api):
        """PRD §3.3: "the patient must not already hold an `ACTIVE`
        assignment, else `ERR_DUPLICATE_ACTIVE_ASSIGNMENT` (HTTP 409)".
        PRD §2.5: "no patient ever holds more than one `ACTIVE` assignment".

        Design: Corner/errors/duplicate_active_assignment_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=True)
        set_clock("2026-05-01T09:00:00Z")
        p1 = create_patient(mrn="X007", acuity="MEDIUM", admit_source="ED",
                            stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z")
        a1 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        acc1 = get_success_data(api.accept_admission(a1["id"], make_hospitalist_headers(h1["id"])))
        asg1 = acc1["assignment_id"]
        # Second admission for the same patient — may be queued and offered
        a2 = get_success_data(api.create_admission({"patient_id": p1["id"]}, ADMIN))
        assert a2["status"] == "OFFERED"
        # Accept fails: P1 already has an ACTIVE assignment
        resp = api.accept_admission(a2["id"], make_hospitalist_headers(a2["offered_to_hospitalist_id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ASSIGNMENT)
        # P1 still has exactly one ACTIVE assignment
        asg_now = get_success_data(api.get_assignment(asg1, ADMIN))
        assert asg_now["status"] == "ACTIVE"


class TestEnrollTwiceRejected:
    """Corner instance: enroll_twice_rejected."""

    def test_second_enroll_fails(self, api):
        """PRD §3.9: "The cross-entity tier rejects a caller already present
        in `enrolled_hospitalist_ids` with `ERR_ALREADY_ENROLLED` (HTTP 409)."

        Design: Corner/errors/enroll_twice_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        w = create_coverage_window(window_type="NIGHT_PRIMARY", capacity=3)
        get_success_data(api.enroll_coverage_window(w["id"], make_hospitalist_headers(h1["id"])))
        resp = api.enroll_coverage_window(w["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_ENROLLED)
        w_now = get_success_data(api.get_coverage_window(w["id"], ADMIN))
        assert w_now["enrolled_count"] == 1


class TestEnrollLockedWindowRejected:
    """Corner instance: enroll_locked_window_rejected."""

    def test_enroll_after_lock_fails(self, api):
        """PRD §3.9: "A window in `LOCKED` or `CLOSED` rejects at the state
        tier with `ERR_COVERAGE_WINDOW_NOT_OPEN` (HTTP 409)."
        PRD §3.9: "a window in `OPEN` or `FULL` locks — moving to `LOCKED` —
        once the logical clock reaches `start_at`".

        Design: Corner/errors/enroll_locked_window_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        w = create_coverage_window(window_type="NIGHT_PRIMARY", capacity=2,
                                   start_at="2026-05-01T19:00:00Z",
                                   end_at="2026-05-02T07:00:00Z")
        set_clock("2026-05-01T20:00:00Z")
        mr = get_success_data(api.monitor_run(ADMIN))
        assert w["id"] in mr["locked_window_ids"]
        resp = api.enroll_coverage_window(w["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_COVERAGE_WINDOW_NOT_OPEN)


class TestEnrollWithOverlappingShiftRejected:
    """Corner instance: enroll_with_overlapping_shift_rejected."""

    def test_overlapping_shift_blocks_adjacent_allows(self, api):
        """PRD §3.9: "The temporal tier then rejects a caller who owns a
        shift whose half-open interval overlaps the window's with
        `ERR_ENROLL_SHIFT_CONFLICT` (HTTP 409), adjacency permitted."
        PRD §2.8: "Pure adjacency — one interval's `end_at` equal to
        another's `start_at` — never counts as an overlap."

        Design: Corner/errors/enroll_with_overlapping_shift_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        create_shift(h1["id"], "NIGHT", "2026-05-01T19:00:00Z", "2026-05-02T07:00:00Z", activate=True)
        # Overlapping window [18:00, 06:00+1d)
        w1 = create_coverage_window(window_date="2026-05-01",
                                    window_type="NIGHT_CROSS_COVER",
                                    start_at="2026-05-01T18:00:00Z",
                                    end_at="2026-05-02T06:00:00Z", capacity=2)
        # Adjacent window: start == shift end (07:00 next day)
        w2 = create_coverage_window(window_date="2026-05-02",
                                    window_type="NIGHT_PRIMARY",
                                    start_at="2026-05-02T07:00:00Z",
                                    end_at="2026-05-02T12:00:00Z", capacity=2)
        set_clock("2026-05-01T12:00:00Z")
        resp = api.enroll_coverage_window(w1["id"], make_hospitalist_headers(h1["id"]))
        validate_error(resp, ApiErrorId.ERR_ENROLL_SHIFT_CONFLICT)
        ok = get_success_data(api.enroll_coverage_window(w2["id"], make_hospitalist_headers(h1["id"])))
        assert ok["enrolled_count"] == 1


class TestShiftInvalidWindowRejected:
    """Corner instance: shift_invalid_window_rejected."""

    def test_end_before_start_rejected(self, api):
        """PRD §3.1: "`end_at` must be strictly later than `start_at`,
        failing with `ERR_SHIFT_INVALID_WINDOW` (HTTP 422)".

        Design: Corner/errors/shift_invalid_window_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        resp = api.create_shift({
            "hospitalist_id": h1["id"], "shift_type": "DAY",
            "start_at": "2026-05-01T19:00:00Z", "end_at": "2026-05-01T07:00:00Z",
        }, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_WINDOW)


class TestShiftCloseFromScheduledRejected:
    """Corner instance: shift_close_from_scheduled_rejected."""

    def test_close_from_scheduled_fails(self, api):
        """PRD §3.1: "closing from any state other than `ACTIVE` again fails
        with `ERR_SHIFT_INVALID_STATE`."

        Design: Corner/state_machines/shift_close_from_scheduled_rejected
        """
        h1 = create_hospitalist("H One", "ICU", max_census_cap=16)
        s1 = create_shift(h1["id"], "DAY", "2026-05-01T06:00:00Z", "2026-05-01T18:00:00Z", activate=False)
        resp = api.close_shift(s1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_INVALID_STATE)
        s_now = get_success_data(api.get_shift(s1["id"], ADMIN))
        assert s_now["state"] == "SCHEDULED"
