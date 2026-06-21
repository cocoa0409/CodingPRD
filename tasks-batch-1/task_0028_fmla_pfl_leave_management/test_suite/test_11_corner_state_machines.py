"""Corner — state_machines section: initial state, valid transitions, terminal-state
lockdown, invalid transitions. The `leave_case_denied_terminal_lockdown` stub is
NOT translated — it's excluded by the difficulty instance
`leave_case_branching_eligibility_pending_to_denied_vs_certpending`.
"""
from test_helpers import (
    ApiErrorId,
    apply_payment,
    apply_payment_payload,
    complete_case,
    create_employee,
    create_employer,
    forfeit_restoration,
    get_case,
    get_employee,
    list_benefit_ledgers_for_case,
    record_interval,
    restore_case,
    seed_historic_interval,
    set_clock,
    setup_active_case_with_first_interval,
    setup_approved_case,
    setup_case_in_certification_pending,
    submit_case,
    submit_certification,
    TEST_USERS,
    validate_error,
    validate_success,
)


class TestLeaveCaseInitialStateAutoAdvancesToEligibilityPending:
    def test_leave_case_create_returns_eligibility_pending(self, api):
        """PRD §3.4: "On acceptance the case enters `SUBMITTED` and, within the same request, advances to `ELIGIBILITY_PENDING`; an `ELIGIBILITY_NOTICE` and a `RIGHTS_RESPONSIBILITIES_NOTICE` are auto-created at that moment"

        Design: Corner/state_machines/leave_case_initial_state_submitted_then_auto_advances_to_eligibility_pending
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(employer["id"])
        set_clock("2026-05-01T00:00:00.000Z")
        from test_helpers import create_case_payload

        res = api.create_case(
            create_case_payload(
                emp["id"],
                requested_start_at="2026-06-01T00:00:00.000Z",
                requested_end_at="2026-07-01T00:00:00.000Z",
            ),
            TEST_USERS["hr_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ELIGIBILITY_PENDING", (
            f"submitted case must auto-advance to ELIGIBILITY_PENDING within same request; "
            f"got {data['status']!r}"
        )
        assert data["eligibility_evaluated"] is False


class TestLeaveCaseCompleteToJobRestoredHappyPath:
    def test_completed_protected_case_restored_clears_deadline_and_returns_active(self, api):
        """PRD §3.6: "HR drives `COMPLETED` → `JOB_RESTORED` when `job_restoration_protected` is true and now is at or before `job_restoration_deadline`, clearing `job_restoration_deadline` on the way"

        Design: Corner/state_machines/leave_case_complete_to_job_restored_happy_path
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-06-08T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-06-08T00:00:00.000Z",
            interval_hours=40,
            cert_expected_duration_weeks=1,
        )
        complete_case(bundle["case"]["id"])
        set_clock("2026-06-10T00:00:00.000Z")
        restored = restore_case(bundle["case"]["id"])
        assert restored["status"] == "JOB_RESTORED"
        emp_after = get_employee(bundle["employee"]["id"])
        assert emp_after["job_restoration_deadline"] is None, (
            f"restore must clear job_restoration_deadline; got {emp_after['job_restoration_deadline']!r}"
        )
        assert emp_after["employment_status"] == "ACTIVE"


class TestLeaveCaseCompleteToJobForfeitedWhenUnprotected:
    def test_completed_unprotected_case_forfeit_marks_forfeited(self, api):
        """PRD §3.6: "HR drives `COMPLETED` → `JOB_FORFEITED`, also clearing `job_restoration_deadline`. Both `JOB_RESTORED` and `JOB_FORFEITED` are terminal."

        Design: Corner/state_machines/leave_case_complete_to_job_forfeited_when_unprotected
        """
        # Force protection=false by seeding 480 hours of FMLA on the case before
        # recording an interval that advances it to ACTIVE.
        bundle = setup_approved_case(
            employer_state="FED",
            fmla_method="CALENDAR_YEAR",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-09-01T00:00:00.000Z",
            cert_expected_duration_weeks=12,
        )
        seed_historic_interval(
            bundle.case["id"],
            "2026-02-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            480,
            480,
            0,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        case_after_interval = get_case(bundle.case["id"])
        assert case_after_interval["job_restoration_protected"] is False
        complete_case(bundle.case["id"])
        forfeit = forfeit_restoration(bundle.case["id"])
        assert forfeit["status"] == "JOB_FORFEITED"


class TestCertPendingToCompleteSkipsReceivedIsInvalidState:
    def test_mark_complete_on_pending_cert_returns_invalid_state(self, api):
        """PRD §3.5: "When the signed copy reaches HR, HR drives the receive transition: the record's `received_at` is stamped with now, and it moves from `PENDING` to `RECEIVED`."
        PRD §3.5: "A received record is then either marked complete or marked insufficient."

        Design: Corner/state_machines/cert_pending_to_complete_skips_received_is_invalid_state
        """
        base = setup_case_in_certification_pending(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        cert = submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=4,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
        )
        # cert is in PENDING — try mark-complete without going through receive.
        res = api.mark_certification_complete(
            cert["id"], TEST_USERS["hr_admin_headers"]
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestLedgerApplyPaymentFromPaidStateRejected:
    def test_apply_payment_to_paid_ledger_returns_invalid_state(self, api):
        """PRD §3.7: "The status ranges over `PENDING`, `PARTIAL`, `PAID`, and `DELINQUENT`; `PAID` and `DELINQUENT` are terminal for the row."

        Design: Corner/state_machines/ledger_apply_payment_from_paid_state_rejected
        """
        bundle = setup_active_case_with_first_interval(
            employer_state="FED",
            monthly_premium_total_cents=10000,
            employer_premium_share_pct=0.50,
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
            interval_start="2026-06-01T00:00:00.000Z",
            interval_end="2026-07-01T00:00:00.000Z",
            interval_hours=160,
        )
        ledgers = list_benefit_ledgers_for_case(bundle["case"]["id"])
        ledger_id = ledgers[0]["id"]
        # Fully pay off (5000 cents).
        apply_payment(ledger_id, 5000)
        # A second apply-payment must be rejected with ERR_INVALID_STATE.
        res = api.apply_payment(
            ledger_id,
            apply_payment_payload(100),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
