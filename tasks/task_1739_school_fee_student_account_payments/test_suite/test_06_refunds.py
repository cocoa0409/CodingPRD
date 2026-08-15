"""Refunds: withdrawal/cancellation proration tiers, zero refunds, denial,
purchase refunds, and the waived-portion exclusion."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_optional_purchase_item_payload, create_offering_payload,
    setup_open_year, setup_year_with_fee, add_student_with_account,
    setup_account_enrolled, setup_approved_waiver_account,
    pay_and_settle, set_clock,
    make_bookkeeper_headers, make_family_headers,
)

BK = make_bookkeeper_headers()


class TestRefundProrationVariants:
    def test_refund_proration_withdrawal_vs_cancellation_diverge(self):
        """PRD §3.7: "when the elapsed days exceed refund_full_days but do not
        exceed refund_partial_days, the tier is partial and the refund is the
        collected amount times partial_refund_pct_bp divided by ten thousand,
        rounded down to a whole cent"
        PRD §3.7: "a `SCHEDULED` offering's cancellation always lands in the full
        tier because the fee was cancelled before start, while an `IN_SESSION`
        offering's cancellation prorates at the cancellation date."

        Design: Difficulty/dual_variant_calc/refund_proration_withdrawal_vs_cancellation_diverge
        """
        env = setup_year_with_fee(fee_amount=10000)
        year_id, dept_id, fee_id = env["year"]["id"], env["department"]["id"], env["fee_item"]["id"]
        o1 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            title="Chem", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-09-01", end_date="2026-12-15"), BK))
        o2 = get_success_data(api_client.create_offering(year_id, create_offering_payload(
            kind="ACTIVITY", title="Robotics", department_id=dept_id, fee_item_id=fee_id,
            start_date="2026-10-01", end_date="2027-02-28"), BK))
        s1, a1 = add_student_with_account(year_id, external_ref="S-1", family_id="fam-a",
                                          full_name="Ada")
        s2, a2 = add_student_with_account(year_id, external_ref="S-2", family_id="fam-b",
                                          full_name="Ben", grade_level=11)
        e1 = get_success_data(api_client.create_enrollment(a1["id"], {"offering_id": o1["id"]}, BK))
        get_success_data(api_client.create_enrollment(a2["id"], {"offering_id": o2["id"]}, BK))
        pay_and_settle(a1["id"], 10000, idempotency_key="k1")
        pay_and_settle(a2["id"], 10000, idempotency_key="k2", method="ACH")
        set_clock("2026-09-04T00:00:00Z")
        # Withdrawal variant: days_elapsed = 3 -> PARTIAL tier -> floor(10000*0.5)
        get_success_data(api_client.withdraw_enrollment(a1["id"], e1["id"], BK))
        # Cancellation variant on the still-SCHEDULED offering: forced FULL
        get_success_data(api_client.cancel_offering(year_id, o2["id"], BK))
        r1 = get_success_data(api_client.list_refunds(a1["id"], BK))[0]
        r2 = get_success_data(api_client.list_refunds(a2["id"], BK))[0]
        assert r1["reason"] == "WITHDRAWAL"
        assert r1["refund_cents"] == 5000, (
            f"Withdrawal at day 3 (PARTIAL): floor(10000*5000/10000)=5000; got {r1['refund_cents']}")
        assert r2["reason"] == "ACTIVITY_CANCELLATION"
        assert r2["refund_cents"] == 10000, (
            f"SCHEDULED cancellation is forced FULL regardless of date; got {r2['refund_cents']}")

    def test_refund_full_tier_inclusive_boundary(self):
        """PRD §3.7: "Otherwise the tier boundaries are inclusive at both edges:
        when the elapsed days do not exceed the year's refund_full_days, the tier
        is full and the refund equals everything collected toward the assessment"

        Design: Difficulty/dual_variant_calc/refund_proration_withdrawal_vs_cancellation_diverge
        """
        env = setup_account_enrolled(fee_amount=10000,
                                     year_overrides={"refund_full_days": 2,
                                                     "refund_partial_days": 10})
        pay_and_settle(env["account"]["id"], 10000, idempotency_key="k1")
        # days_elapsed = 2 == refund_full_days -> FULL tier (inclusive boundary)
        set_clock("2026-09-03T00:00:00Z")
        get_success_data(api_client.withdraw_enrollment(
            env["account"]["id"], env["enrollment"]["id"], BK))
        refund = get_success_data(api_client.list_refunds(env["account"]["id"], BK))[0]
        assert refund["refund_cents"] == 10000, (
            f"Day 2 == refund_full_days is FULL by the inclusive boundary; got {refund['refund_cents']}")


class TestRefundExecution:
    def test_refund_none_tier_zero_execute_rejected(self):
        """PRD §3.7: "beyond refund_partial_days, the refund is zero."
        PRD §3.7: "Executing a refund moves it `PENDING` → `EXECUTED` and requires
        refund_cents above zero — a zero-valued refund cannot execute and is
        refused with `ERR_ZERO_REFUND` (HTTP 422)."

        Design: Corner/calculations/refund_none_tier_zero_execute_rejected
        """
        env = setup_account_enrolled(fee_amount=10000)
        pay_and_settle(env["account"]["id"], 10000, idempotency_key="k1")
        # days_elapsed = 19 > refund_partial_days 10 -> NONE tier
        set_clock("2026-09-20T00:00:00Z")
        get_success_data(api_client.withdraw_enrollment(
            env["account"]["id"], env["enrollment"]["id"], BK))
        refund = get_success_data(api_client.list_refunds(env["account"]["id"], BK))[0]
        assert refund["refund_cents"] == 0, (
            f"NONE tier computes refund_cents 0; got {refund['refund_cents']}")
        resp = api_client.execute_refund(env["account"]["id"], refund["id"], BK)
        validate_error(resp, ApiErrorId.ERR_ZERO_REFUND)
        refund_now = get_success_data(api_client.get_refund(
            env["account"]["id"], refund["id"], BK))
        assert refund_now["status"] == "PENDING"

    def test_refund_deny_no_side_effects(self):
        """PRD §3.7: "Denying a `PENDING` refund moves it to `DENIED` and changes
        nothing — no ledger, no assessment updates."

        Design: Corner/state_machines/refund_deny_no_side_effects
        """
        env = setup_account_enrolled(fee_amount=10000)
        pay_and_settle(env["account"]["id"], 10000, idempotency_key="k1")
        set_clock("2026-09-02T00:00:00Z")  # day 1 -> FULL tier
        get_success_data(api_client.withdraw_enrollment(
            env["account"]["id"], env["enrollment"]["id"], BK))
        refund = get_success_data(api_client.list_refunds(env["account"]["id"], BK))[0]
        resp = api_client.deny_refund(env["account"]["id"], refund["id"], BK)
        data = validate_success(resp, 200)
        assert data["status"] == "DENIED"
        dept = get_success_data(api_client.get_department(
            env["year"]["id"], env["department"]["id"], BK))
        assert dept["distributed_cents"] == 10000, (
            f"Denial writes no reversal; distributed stays 10000, got {dept['distributed_cents']}")

    def test_student_withdraw_cascade_to_department_ledger(self):
        """PRD §3.7: "every `ACTIVE` enrollment on every account of the student
        moves to `WITHDRAWN`, each triggering its own proration refund exactly as
        a single-enrollment withdrawal"
        PRD §2.11: "A department's distributed_cents is the sum of its
        DISTRIBUTION_CREDIT entries plus the sum of its DISTRIBUTION_REVERSAL
        entries (reversals being negative)."
        PRD §3.7: "For assessment-sourced refunds (withdrawal or cancellation):
        the source assessment's allocated_cents drops by refund_cents, its
        refunded_cents grows by the same, and its status becomes `REFUNDED` from
        `PARTIALLY_PAID` or `PAID`"

        Design: Difficulty/transitive_cascade/student_withdraw_cascade_to_department_ledger
        """
        env = setup_account_enrolled(fee_amount=10000,
                                     year_overrides={"refund_full_days": 2})
        account_id = env["account"]["id"]
        pay_and_settle(account_id, 10000, idempotency_key="k1")
        set_clock("2026-09-02T00:00:00Z")  # day 1 -> FULL refund
        dept_before = get_success_data(api_client.get_department(
            env["year"]["id"], env["department"]["id"], BK))
        assert dept_before["distributed_cents"] == 10000
        # The withdraw cascade: enrollment WITHDRAWN + PENDING refund spawned
        get_success_data(api_client.withdraw_student(env["student"]["id"], BK))
        refund = get_success_data(api_client.list_refunds(account_id, BK))[0]
        assert refund["refund_cents"] == 10000
        assert refund["reason"] == "WITHDRAWAL"
        # Executing the refund writes the reversal back to the department
        get_success_data(api_client.execute_refund(account_id, refund["id"], BK))
        dept_after = get_success_data(api_client.get_department(
            env["year"]["id"], env["department"]["id"], BK))
        assert dept_after["distributed_cents"] == 0, (
            f"10000 credit - 10000 reversal = 0; got {dept_after['distributed_cents']}")
        account = get_success_data(api_client.get_student_account(account_id, BK))
        assert account["balance_cents"] == 0
        fa = get_success_data(api_client.list_fee_assessments(account_id, BK))[0]
        assert fa["status"] == "REFUNDED"

    def test_withdraw_cascades_enrollment_and_plan(self):
        """PRD §3.7: "Withdrawing the whole **student** is a depth-3 cascade
        executed by a `Bookkeeper`."
        PRD §3.7: "every `ACTIVE` payment plan on those accounts moves to
        `CANCELLED` with its `SCHEDULED` and `DUE` installments becoming
        `WAIVED_BY_DEFAULT`; and each affected account recomputes its posture."

        Design: Difficulty/transitive_cascade/student_withdraw_cascade_to_department_ledger
        """
        from test_helpers import setup_account_with_plan, current_account_version
        env = setup_account_with_plan(assessed_amount_cents=4000)
        account_id, plan_id = env["account"]["id"], env["plan"]["id"]
        get_success_data(api_client.withdraw_student(env["student"]["id"], BK))
        plan = get_success_data(api_client.get_payment_plan(account_id, plan_id, BK))
        assert plan["status"] == "CANCELLED", (
            f"Withdraw must cancel the ACTIVE plan; got {plan['status']}")
        installments = get_success_data(api_client.list_plan_installments(
            account_id, plan_id, BK))
        assert all(i["status"] == "WAIVED_BY_DEFAULT" for i in installments), (
            f"All SCHEDULED/DUE installments become WAIVED_BY_DEFAULT; got "
            f"{[i['status'] for i in installments]}")


class TestPurchaseRefunds:
    def test_purchase_sold_count_computed_and_reversed(self):
        """PRD §3.5: "The purchase charges atomically at creation: the Purchase row
        is created directly in `COMPLETED` status with amount_cents pinned from
        the item's price at purchase time, a `DISTRIBUTION_CREDIT` ledger entry
        lands on the item's department, and sold_count increments by 1."
        PRD §3.7: "For purchase-sourced refunds: the purchase moves `COMPLETED` →
        `REFUNDED` and the item's sold_count decrements by 1."
        PRD §3.7: "every `COMPLETED` purchase of a refundable item on the
        student's accounts spawns a `PENDING` refund with reason `WITHDRAWAL` for
        the full purchase amount"

        Design: Corner/entities/purchase_sold_count_computed_and_reversed
        """
        env = setup_open_year()
        item = get_success_data(api_client.create_optional_purchase_item(
            env["year"]["id"],
            create_optional_purchase_item_payload(
                name="Yearbook", amount_cents=1000,
                department_id=env["department"]["id"], inventory_cap=5), BK))
        student, account = add_student_with_account(env["year"]["id"])
        purchase = get_success_data(api_client.create_purchase(
            account["id"], {"item_id": item["id"], "method": "CARD"},
            make_family_headers()))
        assert purchase["status"] == "COMPLETED"
        item_now = get_success_data(api_client.get_optional_purchase_item(
            env["year"]["id"], item["id"], BK))
        assert item_now["sold_count"] == 1
        # Withdraw spawns the full-amount purchase refund
        get_success_data(api_client.withdraw_student(student["id"], BK))
        refunds = get_success_data(api_client.list_refunds(account["id"], BK))
        assert len(refunds) == 1
        assert refunds[0]["reason"] == "WITHDRAWAL"
        assert refunds[0]["refund_cents"] == 1000
        get_success_data(api_client.execute_refund(account["id"], refunds[0]["id"], BK))
        item_end = get_success_data(api_client.get_optional_purchase_item(
            env["year"]["id"], item["id"], BK))
        assert item_end["sold_count"] == 0, (
            f"Executed purchase refund decrements sold_count; got {item_end['sold_count']}")

    def test_waived_portion_never_refunded(self):
        """PRD §3.7: "Only collected cents are refundable — the assessment's
        allocated_cents — and waived portions are never refunded."

        Design: Corner/calculations/waived_portion_never_refunded
        """
        env = setup_approved_waiver_account(fee_amount=10000, waiver_pct_bp=5000,
                                            grade_level=10, enroll=True)
        account_id = env["account"]["id"]
        # 5000 waived provisionally; pay the remaining 5000
        pay_and_settle(account_id, 5000, idempotency_key="k1")
        set_clock("2026-09-02T00:00:00Z")  # day 1 -> FULL tier
        get_success_data(api_client.withdraw_enrollment(
            account_id, env["enrollment"]["id"], BK))
        refund = get_success_data(api_client.list_refunds(account_id, BK))[0]
        assert refund["refund_cents"] == 5000, (
            f"paid_toward = allocated 5000; the waived half is never refunded; "
            f"got {refund['refund_cents']}")
