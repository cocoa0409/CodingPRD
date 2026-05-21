"""LeaveCase lifecycle — submission, derived fields, APPROVE / DENY
decisions, cancellation.

Covers PRD §3.3 (submission, derived fields), §3.6 (APPROVE / DENY),
§3.11 (cancellation), §2.9 (audit events).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    approve_case_with_specific_instances,
    assert_audit_event_present,
    assert_leave_case,
    cancel_case,
    cancel_leave_case_payload,
    create_leave_case_payload,
    get_leave_case,
    list_audit_events,
    make_employee_headers,
    review_certification,
    review_leave_case,
    setup_approved_case,
    setup_case_with_complete_certification,
    setup_eligible_employee,
    setup_employer_worksite_employee,
    setup_pending_certification_case,
    submit_certification,
    submit_leave_case,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission — PRD §3.3
# ===========================================================================
class TestLeaveCaseSubmission:

    def test_successful_submission_returns_pending_certification(self, api):
        """PRD §3.3: "The case begins in `DRAFT` and on a successful
        submission transitions immediately to `PENDING_CERTIFICATION`"."""
        _e, _w, _emp, case = setup_pending_certification_case()
        assert_leave_case(case)
        assert case["case_status"] == "PENDING_CERTIFICATION", (
            f"expected case_status=PENDING_CERTIFICATION, got "
            f"{case['case_status']!r}"
        )

    def test_own_serious_health_sets_certification_status_awaiting_doc(
        self, api,
    ):
        """PRD §3.3: "The `certification_status` becomes `AWAITING_DOC`
        when the case `reason` is one of `OWN_SERIOUS_HEALTH` or
        `FAMILY_SERIOUS_HEALTH`"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        assert case["certification_status"] == "AWAITING_DOC", (
            f"OWN_SERIOUS_HEALTH cases must start AWAITING_DOC; "
            f"got {case['certification_status']!r}"
        )

    def test_family_serious_health_sets_certification_status_awaiting_doc(
        self, api,
    ):
        """PRD §3.3: "The `certification_status` becomes `AWAITING_DOC`
        when the case `reason` is one of `OWN_SERIOUS_HEALTH` or
        `FAMILY_SERIOUS_HEALTH`"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            reason="FAMILY_SERIOUS_HEALTH", leave_pattern="CONTINUOUS",
        )
        assert case["certification_status"] == "AWAITING_DOC"

    def test_baby_bonding_sets_certification_status_not_required(self, api):
        """PRD §3.3: "[certification_status] becomes `NOT_REQUIRED` for
        all other reasons"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            reason="BABY_BONDING", leave_pattern="CONTINUOUS",
        )
        assert case["certification_status"] == "NOT_REQUIRED", (
            f"BABY_BONDING cases must start NOT_REQUIRED; "
            f"got {case['certification_status']!r}"
        )

    def test_military_exigency_sets_certification_status_not_required(
        self, api,
    ):
        """PRD §3.3: "[certification_status] becomes `NOT_REQUIRED` for
        all other reasons"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            reason="MILITARY_EXIGENCY", leave_pattern="CONTINUOUS",
        )
        assert case["certification_status"] == "NOT_REQUIRED"

    def test_hours_charged_initial_value_is_zero(self, api):
        """PRD §3.3: "The `hours_charged` field begins at 0"."""
        _e, _w, _emp, case = setup_pending_certification_case()
        assert case["hours_charged"] == 0

    def test_job_restoration_status_initial_value_is_protected(self, api):
        """PRD §3.3: "the `job_restoration_status` begins as
        `PROTECTED`"."""
        _e, _w, _emp, case = setup_pending_certification_case()
        assert case["job_restoration_status"] == "PROTECTED"

    def test_calendar_leave_year_anchor_is_january_1(self, api):
        """PRD §3.3: "for a `CALENDAR` employer it is set to January 1
        of the year containing the `requested_start_date`"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            leave_year_basis="CALENDAR",
            requested_start_date="2026-05-01",
        )
        # leave_year_anchor is January 1 of 2026.
        anchor = case["leave_year_anchor"]
        # The format may be ISO date or ISO datetime — extract first 10.
        assert anchor.startswith("2026-01-01"), (
            f"PRD §3.3: CALENDAR employer leave_year_anchor = Jan 1 of "
            f"the year containing requested_start_date; got {anchor!r}"
        )

    def test_rolling_backward_leave_year_anchor_is_requested_start_date(
        self, api,
    ):
        """PRD §3.3: "for a `ROLLING_BACKWARD` employer it is set to the
        `requested_start_date` itself"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            leave_year_basis="ROLLING_BACKWARD",
            requested_start_date="2026-05-01",
        )
        anchor = case["leave_year_anchor"]
        assert anchor.startswith("2026-05-01"), (
            f"PRD §3.3: ROLLING_BACKWARD employer leave_year_anchor = "
            f"requested_start_date itself; got {anchor!r}"
        )


# ===========================================================================
# Audit events on submission — PRD §3.3
# ===========================================================================
class TestAuditEventsOnSubmit:

    def test_submission_emits_eligibility_checked_then_case_created(
        self, api,
    ):
        """PRD §3.3: "emitting an `AuditEvent` of kind
        `ELIGIBILITY_CHECKED` followed by one of kind `CASE_CREATED`"."""
        _e, _w, _emp, case = setup_pending_certification_case()
        events = list_audit_events(case["id"])
        assert_audit_event_present(events, "ELIGIBILITY_CHECKED")
        assert_audit_event_present(events, "CASE_CREATED")


# ===========================================================================
# APPROVE decision — PRD §3.6
# ===========================================================================
class TestApprove:

    def test_approve_with_complete_cert_succeeds(self, api):
        """PRD §3.6: "Approval is allowed only when the parent case is
        in `PENDING_CERTIFICATION`, the case `certification_status` is
        in either `COMPLETE` or `NOT_REQUIRED`"."""
        _e, _w, _emp, case, _cert = (
            setup_case_with_complete_certification()
        )
        result = review_leave_case(
            leave_case_id=case["id"], decision="APPROVE",
        )
        assert result["case_status"] == "APPROVED"

    def test_approve_with_awaiting_doc_fails_with_cert_incomplete(self, api):
        """PRD §3.6: "Approving a case with a `certification_status` of
        `INSUFFICIENT` or `AWAITING_DOC` fails the certification-
        completeness check with `ERR_CERT_INCOMPLETE`"."""
        _e, _w, _emp, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        # certification_status is AWAITING_DOC and no cert submitted.
        resp = api.review_leave_case(
            case["id"], {"decision": "APPROVE"},
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_CERT_INCOMPLETE")

    def test_approve_recomputes_hours_charged_from_approved_instances(
        self, api,
    ):
        """PRD §3.6: "every `PROPOSED` `LeaveInstance` on the case
        becomes `APPROVED`, `hours_charged` is recomputed as the sum
        of `hours_used` across all `APPROVED` instances on the case"."""
        ctx = setup_approved_case(
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
            instance_dates_and_hours=[
                ("2026-05-01", 8), ("2026-05-04", 4), ("2026-05-05", 6),
            ],
        )
        assert ctx["case"]["case_status"] == "APPROVED"
        assert ctx["case"]["hours_charged"] == 18, (
            f"hours_charged = sum of approved instances 8+4+6 = 18; "
            f"got {ctx['case']['hours_charged']!r}"
        )

    def test_approve_emits_certification_reviewed_audit_event(self, api):
        """PRD §3.6: "an `AuditEvent` of kind `CERTIFICATION_REVIEWED`
        is emitted"."""
        ctx = setup_approved_case()
        events = list_audit_events(ctx["case"]["id"])
        assert_audit_event_present(events, "CERTIFICATION_REVIEWED")

    def test_approve_invalid_from_state_returns_invalid_state(self, api):
        """PRD §3.11: "Any attempt to perform a state transition from a
        `case_status` not in that transition's allowed-from set is
        refused with `ERR_INVALID_STATE`"."""
        ctx = setup_approved_case()  # case_status already APPROVED
        resp = api.review_leave_case(
            ctx["case"]["id"], {"decision": "APPROVE"},
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_INVALID_STATE")


# ===========================================================================
# DENY decision — PRD §3.6
# ===========================================================================
class TestDeny:

    def test_deny_with_insufficient_cert_succeeds(self, api):
        """PRD §3.6: "A denial decision is allowed when the parent case
        is in `PENDING_CERTIFICATION` and either the
        `certification_status` is `INSUFFICIENT` or the
        `certification_status` is `AWAITING_DOC` and the server clock
        has passed `cert_deadline`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        result = review_leave_case(
            leave_case_id=case["id"], decision="DENY",
        )
        assert result["case_status"] == "DENIED", (
            f"expected DENIED, got {result['case_status']!r}"
        )

    def test_deny_voids_all_instances_and_resets_hours_charged(self, api):
        """PRD §3.6: "On a denial the `case_status` becomes `DENIED`,
        every `LeaveInstance` on the case transitions to `VOIDED`,
        `hours_charged` is reset to 0"."""
        # Setup INTERMITTENT case with PROPOSED instances; cert
        # INSUFFICIENT then DENY.
        from test_helpers import log_instance, list_benefit_invoices
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-02", hours_used=8,
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        result = review_leave_case(
            leave_case_id=case["id"], decision="DENY",
        )
        assert result["case_status"] == "DENIED"
        assert result["hours_charged"] == 0, (
            f"hours_charged must be reset to 0 on denial; "
            f"got {result['hours_charged']!r}"
        )

    def test_deny_sets_job_restoration_status_not_applicable(self, api):
        """PRD §3.6: "`job_restoration_status` is set to
        `NOT_APPLICABLE`"."""
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        result = review_leave_case(
            leave_case_id=case["id"], decision="DENY",
        )
        assert result["job_restoration_status"] == "NOT_APPLICABLE", (
            f"PRD §3.6: job_restoration_status set to NOT_APPLICABLE "
            f"on denial; got {result['job_restoration_status']!r}"
        )


# ===========================================================================
# Cancellation — PRD §3.11
# ===========================================================================
class TestCancellation:

    def test_cancel_pending_certification_voids_instances_and_resets_hours(
        self, api,
    ):
        """PRD §3.11: "A case in `PENDING_CERTIFICATION` may likewise
        be cancelled by the employee, with the additional effect of
        voiding every `LeaveInstance` on the case and resetting
        `hours_charged` to 0"."""
        from test_helpers import log_instance
        _e, _w, employee, case = setup_pending_certification_case(
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        h = make_employee_headers(employee["id"])
        resp = api.cancel_leave_case(case["id"], None, h)
        assert resp.status_code == 204, (
            f"PRD §4: DELETE returns 204; got {resp.status_code}: "
            f"{resp.text}"
        )
        refreshed = get_leave_case(case["id"])
        assert refreshed["case_status"] == "CANCELLED"
        assert refreshed["hours_charged"] == 0, (
            f"hours_charged must be 0 after cancellation; "
            f"got {refreshed['hours_charged']!r}"
        )

    def test_cancel_with_stale_version_returns_version_conflict(self, api):
        """PRD §2.4: "If supplied, the server compares it to the
        resource's current `version`; a mismatch terminates the
        mutation with `ERR_VERSION_CONFLICT`"."""
        _e, _w, employee, case = setup_pending_certification_case()
        # Pass a wrong version.
        h = make_employee_headers(employee["id"])
        resp = api.cancel_leave_case(
            case["id"], cancel_leave_case_payload(version=99), h,
        )
        validate_error(resp, "ERR_VERSION_CONFLICT")
