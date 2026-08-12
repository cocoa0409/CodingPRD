"""Corner coverage: maintenance_due 500-hour boundary, and posture BLOCKED by
an overdue review taking precedence over the AT_RISK streak contribution."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, get_success_data,
    create_active_home_patient, create_log, list_reviews, set_clock,
    get_patient, create_patient, api_client,
    make_admin_headers, make_biomed_headers, make_nurse_headers,
)
from test_helpers.fixtures import _dates_between
from datetime import date


class TestMaintenanceDueBoundary500Hours:
    """49 logs x 600 min = 490.0h stays clear; the 50th lands exactly on
    500.0h and the inclusive threshold makes the machine due."""

    def _setup_machine_at_hours(self, api, num_logs):
        # Cadence 100 so no review fires across 50 logs; streak threshold 99.
        ctx = create_active_home_patient(
            tpw=7, upt=6, review_cadence_treatments=100,
            max_missed_log_streak=99)
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-06-19T12:00:00Z")
        dates = _dates_between(date(2026, 5, 1), num_logs)
        for d in dates:
            create_log(pat, mach, d, duration_minutes=600)
        return ctx, pat, mach

    def test_below_boundary_not_due(self, api):
        """PRD §3.4: "and `maintenance_due` is true exactly when the difference
        between the two is at least 500 hours — a machine at exactly 500.0
        hours since service is due, because the comparison is inclusive."

        Design: Corner/calculations/maintenance_due_boundary_500_hours
        """
        ctx, pat, mach = self._setup_machine_at_hours(api, 49)
        machine = get_success_data(api.get_machine(mach,
                                                   make_admin_headers("admin-1")))
        assert machine["total_runtime_hours"] == pytest.approx(490.0, abs=0.001)
        assert machine["maintenance_due"] is False
        # Cadence never fired (100 exceeds the 49-log count).
        assert list_reviews(pat) == []

    def test_exactly_500_hours_is_due_and_blocks_assignment(self, api):
        """PRD §3.4: "and `maintenance_due` is true exactly when the difference
        between the two is at least 500 hours — a machine at exactly 500.0
        hours since service is due, because the comparison is inclusive."
        PRD §3.4: "Beyond that, the machine must be `IN_STOCK` or `ASSIGNED`
        (`ERR_MACHINE_INVALID_STATE`), it must not be maintenance-due
        (`ERR_MACHINE_MAINTENANCE_DUE`), and the target patient must exist and
        not be `TRANSITIONED_OUT` (`ERR_PATIENT_NOT_ACTIVE_HOME`)."

        Design: Corner/calculations/maintenance_due_boundary_500_hours
        """
        ctx, pat, mach = self._setup_machine_at_hours(api, 49)
        create_log(pat, mach, "2026-06-19", duration_minutes=600)
        machine = get_success_data(api.get_machine(mach,
                                                   make_admin_headers("admin-1")))
        assert machine["total_runtime_hours"] == pytest.approx(500.0, abs=0.001)
        assert machine["maintenance_due"] is True, (
            "exactly 500.0 hours is due (>=)")
        # A due machine cannot be assigned to another patient.
        validate_success(api.unassign_machine(mach,
                                              make_biomed_headers("biomed-1")))
        pat2 = create_patient(ctx["program"]["id"], full_name="Pat Second")
        cur = get_success_data(api.get_machine(mach,
                                               make_admin_headers("admin-1")))
        resp = api.assign_machine(
            mach, {"patient_id": pat2["id"],
                   "expected_machine_version": cur["version"]},
            make_biomed_headers("biomed-1"))
        validate_error(resp, ApiErrorId.ERR_MACHINE_MAINTENANCE_DUE)


class TestPostureBlockedByOverdueReview:
    """A PENDING review whose due_at passes flips posture to BLOCKED — with
    precedence over the AT_RISK streak contribution that also holds."""

    def test_overdue_review_blocks_posture(self, api):
        """PRD §2.10: "The patient is `BLOCKED` when any of the following
        holds: some training module lacks a `SIGNED_OFF` passing attempt whose
        `signed_off_at` is strictly more recent than 365 days ago
        (certification expired); no `ACCEPTED` assessment has an `accepted_at`
        strictly more recent than 730 days ago (assessment expired); a
        `PENDING` ClinicalReview has its `due_at` before the current clock
        instant (review overdue); an open escalation exists — an `ESCALATED`
        review created after the most recent `SIGNED_OFF` review, or any
        `ESCALATED` review at all when no review was ever signed off; or
        `retraining_required` is true."
        PRD §2.5: "A ClinicalReview whose `due_at` falls before the current
        clock instant counts as overdue for posture purposes."

        Design: Corner/calculations/posture_blocked_by_overdue_review
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-05-03T12:00:00Z")
        create_log(pat, mach, "2026-05-02")
        create_log(pat, mach, "2026-05-03")
        reviews = list_reviews(pat)
        assert reviews and reviews[0]["status"] == "PENDING"
        # due_at = 2026-05-03T12:00 + 5 days = 2026-05-08T12:00; 05-09 is past.
        set_clock("2026-05-09T00:00:00Z")
        patient = get_patient(pat)
        reviews_after = list_reviews(pat)
        assert reviews_after[0]["status"] == "PENDING", (
            "overdue does not transition the review itself")
        assert patient["missed_log_streak"] == 3, (
            "floor(6 days silence / 2 day interval): AT_RISK also holds")
        assert patient["posture"] == "BLOCKED", (
            "the overdue-review BLOCKED rung takes precedence over AT_RISK")

    def test_due_at_set_five_days_after_creation(self, api):
        """PRD §3.6: "The second monitor is the cadence trigger on log
        creation: after inserting the new log, the server counts the patient's
        logs in `SUBMITTED` or `FLAGGED`, and when that count reaches the
        program's `review_cadence_treatments` while no `PENDING` review exists
        for the patient, it opens a ClinicalReview with `due_reason` `CADENCE`,
        `period_start` set to the day after the latest prior review's
        `period_end` (or the date of the patient's `created_at` when there is
        no prior review), `period_end` set to the new log's `treatment_date`,
        and `due_at` set to five days after creation."

        Design: Corner/calculations/posture_blocked_by_overdue_review
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        mach = ctx["machine"]["id"]
        set_clock("2026-05-03T12:00:00Z")
        create_log(pat, mach, "2026-05-02")
        create_log(pat, mach, "2026-05-03")
        reviews = list_reviews(pat)
        assert reviews[0]["due_reason"] == "CADENCE"
        # Five days after 2026-05-03T12:00:00Z creation.
        assert reviews[0]["due_at"].startswith("2026-05-08T12:00"), (
            "due_at = created_at + 5 days")
        # At due_at exactly the review is not yet overdue (due_at < now).
        set_clock("2026-05-08T12:00:00Z")
        patient = get_patient(pat)
        assert patient["posture"] != "BLOCKED", (
            "overdue requires due_at strictly before now")
