"""Promotion-test fork-join lifecycle, contract cyclic billing loop, and the
related state-machine corner instances (private-lesson, pro-shop, invoice).

Covers difficulty rule non_linear_state_machine plus several state_machines corner
instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    set_clock, create_program, create_member, create_instructor,
    create_program_with_simple_chain, setup_enrolled_member,
    schedule_promotion_test, setup_contract, sign_contract, run_billing,
    run_billing_and_pay,
    get_invoices, make_instructor_headers, make_chief_instructor_headers,
    make_member_headers, request_private_lesson, member_version,
    TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


class TestPromotionForkJoin:
    """SCHEDULED forks to PASSED / PASSED_PENDING_SIGNOFF / FAILED; signoff rejoins
    PASSED. Divergent side-effects on each branch."""

    def _setup_chief_signoff_chain(self):
        # WHITE -> BLUE(terminal, requires chief signoff).
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", terminal_requires_signoff=True,
            min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor(full_name="InsT")
        chief = create_instructor(full_name="Chief", rank_level="CHIEF_INSTRUCTOR")
        member, enrollment = setup_enrolled_member(prog["id"])
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-02T00:00:00Z")
        return prog, member, enrollment, instructor, chief, test

    def test_pass_into_signoff_rank_defers_promotion(self, api):
        """PRD §3.5: "When the score reaches the pass mark and the target rank
        **does** require chief signoff, the test moves to `PASSED_PENDING_SIGNOFF`
        with its `score` recorded but **no rank change yet** — the promotion is
        deferred."

        Design: Difficulty/non_linear_state_machine/promotion_test_fork_join_pass_fail_signoff
        """
        prog, member, enrollment, instructor, chief, test = self._setup_chief_signoff_chain()
        graded = validate_success(api.grade_promotion_test(
            test["id"], {"score": 88}, make_instructor_headers(instructor["id"])), 200)
        assert graded["status"] == "PASSED_PENDING_SIGNOFF", graded
        enr = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert enr["current_rank_code"] == "WHITE", enr

    def test_signoff_applies_promotion_and_completes_terminal(self, api):
        """PRD §3.5: "Signoff moves the test from `PASSED_PENDING_SIGNOFF` to
        `PASSED`, records the signing instructor as `chief_signoff_instructor_id`, and
        applies the promotion at that point."
        PRD §3.5: "the just-acquired rank's `next_rank_code` is null: in that case the
        enrollment's `current_rank_code` is still set to `target_rank_code`, but the
        enrollment's `status` also moves to `COMPLETED`, marking the progression
        finished."

        Design: Difficulty/non_linear_state_machine/promotion_test_fork_join_pass_fail_signoff
        """
        prog, member, enrollment, instructor, chief, test = self._setup_chief_signoff_chain()
        get_success_data(api.grade_promotion_test(
            test["id"], {"score": 88}, make_instructor_headers(instructor["id"])))
        signed = validate_success(api.signoff_promotion_test(
            test["id"], make_chief_instructor_headers(chief["id"])), 200)
        assert signed["status"] == "PASSED", signed
        assert signed["chief_signoff_instructor_id"] == chief["id"], signed
        enr = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert enr["current_rank_code"] == "BLUE", enr
        assert enr["status"] == "COMPLETED", enr

    def test_fail_branch_no_rank_change(self, api):
        """PRD §3.5: "When the score is below the pass mark, the test moves to
        `FAILED` with its `score` recorded, no rank change occurs, and
        `rank_attendance_count` is left untouched (no compensation is needed)."

        Design: Difficulty/non_linear_state_machine/promotion_test_fork_join_pass_fail_signoff
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="BLUE", terminal_code="BLUE", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-02T00:00:00Z")
        graded = validate_success(api.grade_promotion_test(
            test["id"], {"score": 40}, make_instructor_headers(instructor["id"])), 200)
        assert graded["status"] == "FAILED", graded
        enr = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert enr["current_rank_code"] == "WHITE", enr

    def test_immediate_pass_no_signoff_promotes_and_resets_count(self, api):
        """PRD §3.5: "When the score reaches the pass mark and the target rank does
        **not** require chief signoff, the test moves to `PASSED`, its `score` is
        recorded, and the promotion is applied immediately."
        PRD §3.5: "the `rank_acquired_at` is reset to the current time, and
        `rank_attendance_count` is reset to 0 (the conserved attendance pool is
        cleared for the new rank)."

        Design: Corner/consistency_model/immediate_visibility_of_promotion_in_same_chain
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program_with_simple_chain(
            entry_next="GREEN", terminal_code="GREEN", min_attendance_for_test=0, min_days_in_rank=0)
        instructor = create_instructor()
        member, enrollment = setup_enrolled_member(prog["id"])
        # one counted attendance first
        session = get_success_data(api.create_class_session(
            {"program_id": prog["id"], "instructor_id": instructor["id"],
             "starts_at": "2026-01-02T10:00:00Z", "ends_at": "2026-01-02T11:00:00Z", "capacity": 10}, FD))
        get_success_data(api.create_attendance(
            {"enrollment_id": enrollment["id"], "class_session_id": session["id"]},
            make_member_headers(member["id"])))
        test = schedule_promotion_test(enrollment["id"], instructor["id"], "2026-01-03T00:00:00Z")
        get_success_data(api.grade_promotion_test(
            test["id"], {"score": 85}, make_instructor_headers(instructor["id"])))
        enr = validate_success(api.get_enrollment(enrollment["id"], FD), 200)
        assert enr["current_rank_code"] == "GREEN", enr
        assert enr["status"] == "COMPLETED", enr
        assert enr["rank_attendance_count"] == 0, enr


class TestContractCyclicBilling:
    """ACTIVE_to_ACTIVE self-loops each run-billing until the final term month flips
    the contract to FULFILLED."""

    def test_self_loop_stays_active_then_fulfills(self, api):
        """PRD §3.6: "The contract stays `ACTIVE` across runs until the term is met;
        on the run that bills the final term month — the one where `months_billed`
        plus 1 equals `term_months` — the final `TUITION` invoice is generated,
        `months_billed` reaches `term_months`, and the contract transitions to
        `FULFILLED`."

        Design: Difficulty/non_linear_state_machine/contract_cyclic_billing_loop
        """
        set_clock("2026-01-01T00:00:00Z")
        prog, member, contract = setup_contract(base_tuition_cents=10000, term_months=3, family_size=2)
        # Settle each monthly invoice so the running balance never crosses the
        # 10000-cent suspension threshold (PRD §3.3/§3.6); the contract then stays
        # ACTIVE across the billing loop until the final term month flips it to FULFILLED.
        after1 = run_billing_and_pay(contract["id"], member["id"])
        assert after1["status"] == "ACTIVE" and after1["months_billed"] == 1, after1
        after2 = run_billing_and_pay(contract["id"], member["id"])
        assert after2["status"] == "ACTIVE" and after2["months_billed"] == 2, after2
        after3 = run_billing_and_pay(contract["id"], member["id"])
        assert after3["status"] == "FULFILLED" and after3["months_billed"] == 3, after3

    def test_each_tuition_invoice_uses_pinned_discount(self, api):
        """PRD §3.6: "A run generates one `TUITION` invoice and increments
        `months_billed` by 1. The tuition amount is computed from the program's
        `base_monthly_tuition_cents` and the contract's *pinned*
        `locked_family_discount_pct` (not the live tier)."

        Design: Difficulty/non_linear_state_machine/contract_cyclic_billing_loop
        """
        set_clock("2026-01-01T00:00:00Z")
        prog, member, contract = setup_contract(base_tuition_cents=10000, term_months=3, family_size=2)
        # Settle each invoice between runs so the balance never crosses the
        # suspension threshold and the contract remains ACTIVE through all 3 runs.
        run_billing_and_pay(contract["id"], member["id"])
        run_billing_and_pay(contract["id"], member["id"])
        run_billing_and_pay(contract["id"], member["id"])
        invoices = get_invoices(member["id"], kind="TUITION")
        assert len(invoices) == 3, invoices
        # 10000 - rhu(10000*0.10=1000) = 9000 each.
        for inv in invoices:
            assert inv["amount_due_cents"] == 9000, inv


class TestPrivateLessonLifecycle:
    """REQUESTED -> CONFIRMED -> COMPLETED with the private-lesson invoice."""

    def test_confirm_free_instructor_succeeds(self, api):
        """PRD §3.7: "An instructor confirms a `REQUESTED` lesson only when their
        `is_available` is true and the lesson's interval does not overlap any of that
        instructor's other `CONFIRMED` private lessons or `SCHEDULED` class sessions
        ... confirmation moves the lesson to `CONFIRMED`."

        Design: Corner/state_machines/confirm_private_lesson_unavailable_instructor_invalid_state
        """
        set_clock("2026-01-01T00:00:00Z")
        instructor = create_instructor()
        member = create_member()
        lesson = request_private_lesson(member["id"], instructor["id"],
                                        "2026-02-01T09:00:00Z", "2026-02-01T10:00:00Z")
        confirmed = validate_success(api.confirm_private_lesson(
            lesson["id"], make_instructor_headers(instructor["id"])), 200)
        assert confirmed["status"] == "CONFIRMED", confirmed

    def test_complete_generates_private_lesson_invoice(self, api):
        """PRD §3.7: "Completing a `CONFIRMED` lesson moves it to `COMPLETED` and
        generates one `PRIVATE_LESSON` invoice, then recomputes the member's balance.
        The private-lesson charge is computed by taking the duration in minutes ...
        multiplying `hourly_rate_cents` by that duration divided by 60 ... and
        rounding that raw figure half up exactly once at the end."

        Design: Corner/state_machines/private_lesson_complete_generates_invoice_side_effect
        """
        set_clock("2026-01-01T00:00:00Z")
        instructor = create_instructor()
        member = create_member()
        lesson = request_private_lesson(member["id"], instructor["id"],
                                        "2026-02-02T09:00:00Z", "2026-02-02T10:30:00Z",
                                        hourly_rate_cents=6000)
        get_success_data(api.confirm_private_lesson(lesson["id"], make_instructor_headers(instructor["id"])))
        completed = validate_success(api.complete_private_lesson(
            lesson["id"], make_instructor_headers(instructor["id"])), 200)
        assert completed["status"] == "COMPLETED", completed
        invoices = get_invoices(member["id"], kind="PRIVATE_LESSON")
        assert len(invoices) == 1, invoices
        # 90 minutes at 6000/hr -> 6000 * 1.5 = 9000.
        assert invoices[0]["amount_due_cents"] == 9000, invoices[0]
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 9000, m_after


class TestProShopAndInvoiceTransitions:

    def test_cancel_placed_order_generates_no_invoice(self, api):
        """PRD §3.7: "A `PLACED` order may instead be cancelled (by the member or
        front desk) to `CANCELLED`." (No invoice is generated on cancel — only
        fulfilment generates the `PRO_SHOP` invoice.)

        Design: Corner/state_machines/proshop_cancel_no_invoice_side_effect
        """
        member = create_member()
        order = get_success_data(api.create_pro_shop_order(
            {"member_id": member["id"], "line_items": [{"sku": "BELT", "unit_price_cents": 2000, "qty": 1}]},
            make_member_headers(member["id"])))
        cancelled = validate_success(api.cancel_pro_shop_order(
            order["id"], make_member_headers(member["id"])), 200)
        assert cancelled["status"] == "CANCELLED", cancelled
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 0, m_after

    def test_pay_invoice_unsuspends_member(self, api):
        """PRD §3.8: "Paying an invoice is available while it is `DUE` or `OVERDUE`
        and moves it to `PAID`, then recomputes the member's outstanding balance; if
        that recomputation brings the balance to at most the 10000-cent threshold, the
        member auto-unsuspends and the cascade described in §3.3 returns their
        `PAST_DUE` contracts to `ACTIVE`."

        Design: Corner/state_machines/pay_invoice_recompute_unsuspend_bubble_up
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=16000)
        member = create_member()
        contract = sign_contract(member["id"], prog["id"], member["version"], term_months=12)
        run_billing(contract["id"])
        invoices = get_invoices(member["id"], kind="TUITION")
        inv_id = invoices[0]["id"]
        m_before = validate_success(api.get_member(member["id"], FD), 200)
        assert m_before["account_status"] == "SUSPENDED", m_before
        get_success_data(api.pay_invoice(inv_id, FD))
        m_after = validate_success(api.get_member(member["id"], FD), 200)
        assert m_after["outstanding_balance_cents"] == 0, m_after
        assert m_after["account_status"] == "ACTIVE", m_after

    def test_mark_overdue_after_clock_advance(self, api):
        """PRD §3.8: "Marking an invoice overdue moves a `DUE` invoice to `OVERDUE`
        when the current clock time has passed its `due_at`; this does not by itself
        change `amount_due_cents`."

        Design: Corner/state_machines/invoice_mark_overdue_after_clock_advance
        """
        set_clock("2026-01-01T00:00:00Z")
        prog = create_program(base_monthly_tuition_cents=9000)
        member = create_member()
        contract = sign_contract(member["id"], prog["id"], member["version"],
                                 term_months=12, billing_anchor_day=15)
        run_billing(contract["id"])
        inv_id = get_invoices(member["id"], kind="TUITION")[0]["id"]
        set_clock("2026-03-01T00:00:00Z")
        overdue = validate_success(api.mark_invoice_overdue(inv_id, FD), 200)
        assert overdue["status"] == "OVERDUE", overdue
