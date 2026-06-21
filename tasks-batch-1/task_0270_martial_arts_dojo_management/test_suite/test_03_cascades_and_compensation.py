"""Transitive cascades, cross-entity state dependencies, and compensating
invariants: billing->suspend->past_due->tournament-withdraw chains, member-freeze
enrollment holds, withdraw cascades, and the conserved-quantity restorations on
class-cancel and test-cancel.

Covers difficulty rules transitive_cascade, cross_entity_state_dependency, and
compensating_invariant plus related cross_cutting and state-machine corner instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, create_program, create_member, create_instructor,
    create_program_with_simple_chain, create_program_single_terminal_rank,
    setup_enrolled_member, create_enrollment, schedule_promotion_test,
    sign_contract, run_billing, get_invoices, register_tournament,
    create_class_session, check_in, make_member_headers, make_instructor_headers,
    member_version, TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


class TestBillingSuspensionCascadeChain:
    """run-billing -> balance over threshold -> Member SUSPENDED -> Contract PAST_DUE
    -> future tournament registration WITHDRAWN (depth-4 transitive chain)."""

    def _setup_member_with_tournament_and_contract(self):
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=16000)
        member = create_member()
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        registration = register_tournament(member["id"], enrollment["id"], "2026-09-01T00:00:00Z",
                                            tournament_name="Spring Open")
        m_v = member_version(member["id"])
        contract = sign_contract(member["id"], prog["id"], m_v, term_months=12)
        return prog, member, enrollment, registration, contract

    def test_full_chain_from_single_billing_run(self, api):
        """PRD §3.3: "When invoice generation or an overdue sweep pushes an `ACTIVE`
        member's `outstanding_balance_cents` strictly above that 10000-cent threshold,
        the member auto-transitions from `ACTIVE` to `SUSPENDED`. Suspension cascades
        to billing: every `ACTIVE` contract of that member moves to `PAST_DUE`, and
        that contract change in turn strips the member's future tournament spots."

        Design: Difficulty/transitive_cascade/billing_overdue_suspend_pastdue_tournament_withdraw_chain
        """
        prog, member, enrollment, registration, contract = self._setup_member_with_tournament_and_contract()
        run_billing(contract["id"])
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 16000, m_after
        assert m_after["account_status"] == "SUSPENDED", m_after
        ctr_after = validate_success(api.get_contract(contract["id"], FD), 200)
        assert ctr_after["status"] == "PAST_DUE", ctr_after
        reg_after = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_after["status"] == "WITHDRAWN", reg_after

    def test_balance_drives_suspension_threshold(self, api):
        """PRD §3.7: "when a member is suspended and their contracts go `PAST_DUE`,
        every still-`REGISTERED` registration of that member whose `event_date` is in
        the future is withdrawn to `WITHDRAWN`, stripping the suspended member's
        competition eligibility."

        Design: Difficulty/transitive_cascade/billing_overdue_suspend_pastdue_tournament_withdraw_chain
        """
        prog, member, enrollment, registration, contract = self._setup_member_with_tournament_and_contract()
        # Confirm the registration was REGISTERED before billing.
        reg_before = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_before["status"] == "REGISTERED", reg_before
        run_billing(contract["id"])
        reg_after = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_after["status"] == "WITHDRAWN", reg_after


class TestMemberFreezeEnrollmentHold:
    """Freezing a member cascades each ACTIVE enrollment to ON_HOLD."""

    def test_freeze_holds_both_enrollments(self, api):
        """PRD §3.3: "Freezing a member ... sets `account_status` to `FROZEN` and
        **cascades down**: every enrollment of that member whose `status` is `ACTIVE`
        moves to `ON_HOLD`."

        Design: Difficulty/transitive_cascade/member_freeze_enrollment_onhold_chain
        """
        prog_x = create_program(discipline="KARATE")
        prog_y = create_program(discipline="JUDO")
        member = create_member()
        enr_x = create_enrollment(member["id"], prog_x["id"], member["version"])
        enr_y = create_enrollment(member["id"], prog_y["id"], member_version(member["id"]))
        m_v = member_version(member["id"])
        frozen = validate_success(api.freeze_member(member["id"], {"expected_member_version": m_v}, FD), 200)
        assert frozen["account_status"] == "FROZEN", frozen
        ex_after = validate_success(api.get_enrollment(enr_x["id"], FD), 200)
        ey_after = validate_success(api.get_enrollment(enr_y["id"], FD), 200)
        assert ex_after["status"] == "ON_HOLD", ex_after
        assert ey_after["status"] == "ON_HOLD", ey_after

    def test_member_status_frozen_after_freeze(self, api):
        """PRD §3.3: "Freezing a member is a front-desk action available only from
        `ACTIVE` and guarded by `expected_member_version`. It sets `account_status` to
        `FROZEN`."

        Design: Difficulty/transitive_cascade/member_freeze_enrollment_onhold_chain
        """
        prog = create_program()
        member = create_member()
        create_enrollment(member["id"], prog["id"], member["version"])
        m_v = member_version(member["id"])
        frozen = validate_success(api.freeze_member(member["id"], {"expected_member_version": m_v}, FD), 200)
        assert frozen["account_status"] == "FROZEN", frozen


class TestAttendanceBlockedByFrozenMember:
    """Attendance check-in is gated on the owning Member being ACTIVE."""

    def test_frozen_member_cannot_check_in(self, api):
        """PRD §3.4: "a member whose `account_status` is not `ACTIVE` is blocked with
        `ERR_MEMBER_NOT_ACTIVE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/attendance_blocked_by_member_frozen
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=5)
        m_v = member_version(member["id"])
        get_success_data(api.freeze_member(member["id"], {"expected_member_version": m_v}, FD))
        res = api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"]))
        validate_error(res, "ERR_MEMBER_NOT_ACTIVE", 422)

    def test_no_attendance_created_on_block(self, api):
        """PRD §2.4: "`ClassSession.confirmed_count` counts the `CONFIRMED`
        attendances for a session." (A blocked check-in records no CONFIRMED
        attendance, so confirmed_count stays 0.)

        Design: Difficulty/cross_entity_state_dependency/attendance_blocked_by_member_frozen
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=5)
        m_v = member_version(member["id"])
        get_success_data(api.freeze_member(member["id"], {"expected_member_version": m_v}, FD))
        api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"]))
        sess_after = validate_success(api.get_class_session(session["id"], FD), 200)
        assert sess_after["confirmed_count"] == 0, sess_after


class TestTournamentWithdrawnByContractPastDue:
    """A registration's valid state depends on the member's Contract state."""

    def test_contract_pastdue_withdraws_registration(self, api):
        """PRD §3.3: "Suspension cascades to billing: every `ACTIVE` contract of that
        member moves to `PAST_DUE`, and that contract change in turn strips the
        member's future tournament spots (see §3.7)."

        Design: Difficulty/cross_entity_state_dependency/tournament_withdrawn_by_contract_pastdue
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=16000)
        member = create_member()
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        registration = register_tournament(member["id"], enrollment["id"], "2026-10-01T00:00:00Z",
                                            tournament_name="CE Cup")
        contract = sign_contract(member["id"], prog["id"], member_version(member["id"]), term_months=12)
        run_billing(contract["id"])
        ctr_after = validate_success(api.get_contract(contract["id"], FD), 200)
        assert ctr_after["status"] == "PAST_DUE", ctr_after
        reg_after = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_after["status"] == "WITHDRAWN", reg_after

    def test_contract_reaches_pastdue_when_member_suspended(self, api):
        """PRD §3.6: "After the invoice is generated the member's outstanding balance
        is recomputed; if that pushes the balance past the 10000-cent suspension
        threshold, the member auto-suspends, which cascades the contract to `PAST_DUE`
        as described in §3.3."

        Design: Difficulty/cross_entity_state_dependency/tournament_withdrawn_by_contract_pastdue
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=16000)
        member = create_member()
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        registration = register_tournament(member["id"], enrollment["id"], "2026-10-01T00:00:00Z")
        contract = sign_contract(member["id"], prog["id"], member_version(member["id"]), term_months=12)
        run_billing(contract["id"])
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["account_status"] == "SUSPENDED", m_after
        ctr_after = validate_success(api.get_contract(contract["id"], FD), 200)
        assert ctr_after["status"] == "PAST_DUE", ctr_after

    def test_registration_active_until_contract_pastdue(self, api):
        """PRD §3.7: "Withdrawal also happens automatically as a cascade: when a
        member is suspended and their contracts go `PAST_DUE`, every still-`REGISTERED`
        registration of that member whose `event_date` is in the future is withdrawn
        to `WITHDRAWN`."

        Design: Difficulty/cross_entity_state_dependency/tournament_withdrawn_by_contract_pastdue
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=16000)
        member = create_member()
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        registration = register_tournament(member["id"], enrollment["id"], "2026-10-01T00:00:00Z")
        reg_before = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_before["status"] == "REGISTERED", reg_before
        contract = sign_contract(member["id"], prog["id"], member_version(member["id"]), term_months=12)
        run_billing(contract["id"])
        reg_after = validate_success(api.get_tournament_registration(registration["id"], FD), 200)
        assert reg_after["status"] == "WITHDRAWN", reg_after


class TestClassCancelRestoresRankPool:
    """Conserved quantity: Enrollment.rank_attendance_count. Check-in +1; class
    cancel compensates back to the pre-check-in value."""

    def test_cancel_restores_attendance_count(self, api):
        """PRD §3.4: "every `CONFIRMED` attendance of that session is set to
        `CANCELLED`, and for each such attendance that had been credited toward rank
        (its `counts_toward_rank` was true) the owning enrollment's
        `rank_attendance_count` is decremented by 1, returning the attendance pool to
        its pre-check-in value; the session's `confirmed_count` is reset to 0."

        Design: Difficulty/compensating_invariant/class_cancel_restores_rank_attendance_pool
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=5)
        check_in(enrollment["id"], session["id"], member["id"])
        before = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert before["rank_attendance_count"] == 1, before
        sess = validate_success(api.get_class_session(session["id"], FD), 200)
        get_success_data(api.cancel_class_session(
            session["id"], {"expected_class_session_version": sess["version"]}, FD))
        after = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert after["rank_attendance_count"] == 0, after

    def test_cancel_resets_confirmed_count(self, api):
        """PRD §3.4: "the session's `confirmed_count` is reset to 0; and the session's
        `version` increments by 1."

        Design: Difficulty/compensating_invariant/class_cancel_restores_rank_attendance_pool
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program()
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        session = create_class_session(prog["id"], instructor["id"],
                                       "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z", capacity=5)
        check_in(enrollment["id"], session["id"], member["id"])
        sess = validate_success(api.get_class_session(session["id"], FD), 200)
        assert sess["confirmed_count"] == 1, sess
        cancelled = validate_success(api.cancel_class_session(
            session["id"], {"expected_class_session_version": sess["version"]}, FD), 200)
        assert cancelled["status"] == "CANCELLED", cancelled
        assert cancelled["confirmed_count"] == 0, cancelled


class TestTestCancelRestoresLedger:
    """Conserved quantity: Member.outstanding_balance_cents. Scheduling a test debits
    a TEST_FEE invoice; cancelling voids it and recomputes the balance."""

    def test_cancel_voids_fee_and_restores_balance(self, api):
        """PRD §3.5: "Cancelling a `SCHEDULED` test moves it to `CANCELLED` and runs
        the fee compensation: the `TEST_FEE` invoice generated at scheduling is voided
        (its `status` set to `VOID`) and the member's outstanding balance is
        recomputed, so the ledger returns to its pre-scheduling total."

        Design: Difficulty/compensating_invariant/test_cancel_restores_invoice_ledger
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", test_fee_cents=4000,
            min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-10T00:00:00Z")
        before = validate_success(api.get_member(member["id"], FD), 200)
        assert before["outstanding_balance_cents"] == 4000, before
        get_success_data(api.cancel_promotion_test(test["id"], make_instructor_headers(instructor["id"])))
        fees = get_invoices(member["id"], kind="TEST_FEE")
        assert len(fees) == 1 and fees[0]["status"] == "VOID", fees
        after = validate_success(api.get_member(member["id"], FD), 200)
        assert after["outstanding_balance_cents"] == 0, after

    def test_scheduling_test_debits_fee(self, api):
        """PRD §3.5: "At scheduling the system ... generates a `TEST_FEE` invoice for
        the program's `test_fee_cents`, which raises the member's outstanding balance."

        Design: Difficulty/compensating_invariant/test_cancel_restores_invoice_ledger
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", test_fee_cents=4000,
            min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-10T00:00:00Z")
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 4000, m_after


class TestWithdrawCascade:
    """Withdrawing a member drops enrollments and terminates contracts with buyout."""

    def test_withdraw_drops_enrollment_and_terminates_contract(self, api):
        """PRD §3.3: "every non-terminal enrollment (one whose `status` is `ACTIVE` or
        `ON_HOLD`) is dropped to `DROPPED`; every `ACTIVE` or `PAST_DUE` contract is
        terminated to `TERMINATED`, and for each such contract whose `months_billed`
        is still below its `term_months`, one `BUYOUT` invoice is generated."

        Design: Corner/cross_cutting_complexity_layers/cascade_member_withdraw_drops_enrollments_and_terminates_contract
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=10000)
        member = create_member()
        enrollment = create_enrollment(member["id"], prog["id"], member["version"])
        contract = sign_contract(member["id"], prog["id"], member_version(member["id"]), term_months=12)
        m_v = member_version(member["id"])
        get_success_data(api.withdraw_member(member["id"], {"expected_member_version": m_v}, FD))
        enr_after = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert enr_after["status"] == "DROPPED", enr_after
        ctr_after = validate_success(api.get_contract(contract["id"], FD), 200)
        assert ctr_after["status"] == "TERMINATED", ctr_after
        buyouts = get_invoices(member["id"], kind="BUYOUT")
        assert len(buyouts) == 1, buyouts
        # remaining 12, monthly 10000 (solo pinned 0.00), raw rhu(12*10000*0.5)=60000 -> capped 50000.
        assert buyouts[0]["amount_due_cents"] == 50000, buyouts[0]

    def test_waive_reconciles_balance(self, api):
        """PRD §3.8: "Waiving an invoice (front-desk only) is available while it is
        `DUE` or `OVERDUE`, moves it to `WAIVED`, and recomputes the balance, removing
        that invoice from the unpaid sum."

        Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciliation_after_waive
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=9000)
        member = create_member()
        contract = sign_contract(member["id"], prog["id"], member["version"], term_months=12)
        run_billing(contract["id"])
        inv_id = get_invoices(member["id"], kind="TUITION")[0]["id"]
        waived = validate_success(api.waive_invoice(inv_id, FD), 200)
        assert waived["status"] == "WAIVED", waived
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 0, m_after
