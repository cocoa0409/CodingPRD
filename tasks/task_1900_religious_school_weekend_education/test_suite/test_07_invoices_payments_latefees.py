"""Billing: invoice issue/re-issue, payment waterfall + void, late-fee accrual,
withdrawal credit tiers."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_open_year_with_section, setup_family_with_invoice,
    create_family, create_student, enroll_student_fresh,
    enroll_students_sequential, issue_invoice_fresh, post_payment,
    get_family, get_invoice, get_section,
    create_year, setup_open_year, create_hired_teacher,
    create_staffed_section, create_school_year_payload,
)

ADMIN = TEST_USERS["admin_headers"]


class TestInvoiceIssue:
    def test_reissue_supersedes_prior_unpaid(self):
        """PRD §3.6: "if the family already has an open tuition invoice for the
        year (one in `ISSUED` or `PARTIALLY_PAID` status), the re-issue supersedes
        it, moving it to `VOID` — but only when that open invoice has `paid_cents`
        of exactly 0."

        Design: Corner/state_machines/invoice_reissue_supersedes_prior_unpaid
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv1 = bundle["family"], bundle["invoice"]
        assert inv1["total_due_cents"] == 72063
        inv2 = issue_invoice_fresh(family["id"], ctx["year"]["id"])
        assert inv2["id"] != inv1["id"]
        assert inv2["status"] == "ISSUED"
        assert inv2["total_due_cents"] == 72063
        inv1_now = get_invoice(inv1["id"])
        assert inv1_now["status"] == "VOID"

    def test_reissue_with_collected_payments_rejected(self):
        """PRD §3.6: "An open invoice that has already collected money blocks the
        re-issue outright with `ERR_INVOICE_HAS_PAYMENTS`, which is why no
        transition from `PARTIALLY_PAID` to `VOID` exists at all."

        Design: Corner/errors/reissue_with_collected_payments_rejected
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv1 = bundle["family"], bundle["invoice"]
        post_payment(family["id"], 20000, method="CHECK")
        fresh = get_family(family["id"])
        resp = api_client.issue_invoice(
            family["id"],
            {"school_year_id": ctx["year"]["id"],
             "expected_family_version": fresh["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_HAS_PAYMENTS)
        inv1_now = get_invoice(inv1["id"])
        assert inv1_now["status"] == "PARTIALLY_PAID"

    def test_invoice_issue_requires_billable_enrollment(self):
        """PRD §3.6: "at least one billable enrollment must exist — an enrollment
        of the family in that year with status `REGISTERED`, `ACTIVE`, or
        `COMPLETED` — or the issue fails with `ERR_NO_BILLABLE_ENROLLMENTS`."

        Design: Corner/errors/invoice_issue_without_billable_enrollments
        """
        ctx = setup_open_year_with_section()
        section, year = ctx["section"], ctx["year"]
        family = create_family()
        kid = create_student(family["id"])
        enr = enroll_student_fresh(section["id"], kid["id"])
        get_success_data(api_client.withdraw_enrollment(enr["id"], ADMIN))
        fresh = get_family(family["id"])
        resp = api_client.issue_invoice(
            family["id"],
            {"school_year_id": year["id"],
             "expected_family_version": fresh["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NO_BILLABLE_ENROLLMENTS)

    def test_occ_stale_family_version_on_issue(self):
        """PRD §2.7: "A prior invoice issue, payment, void, late-fee accrual, or
        withdrawal credit legitimately mutates the family's balances; issuing from a
        stale balance view would supersede the wrong invoice, so a mismatch with the
        family's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting/occ_stale_family_version_on_invoice_issue
        """
        ctx = setup_open_year_with_section()
        section, year = ctx["section"], ctx["year"]
        family = create_family()
        fam_v_at_create = family["version"]
        kid = create_student(family["id"])
        enroll_student_fresh(section["id"], kid["id"])
        inv1 = issue_invoice_fresh(family["id"], year["id"])
        # Second issue with the version captured at family creation -> stale.
        resp = api_client.issue_invoice(
            family["id"],
            {"school_year_id": year["id"],
             "expected_family_version": fam_v_at_create},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # The stale re-issue did not supersede the live invoice.
        assert get_invoice(inv1["id"])["status"] == "ISSUED"


class TestPaymentWaterfall:
    def test_two_years_oldest_first(self):
        """PRD §3.6: "the family's open invoices (those in `ISSUED` or
        `PARTIALLY_PAID`) are ordered by `issued_at` ascending with ties broken by
        `created_at` ascending, and the payment walks the list from oldest to
        newest, applying to each invoice the smaller of the remaining payment and
        that invoice's `balance_cents`."

        Design: Corner/calculations/payment_waterfall_two_years_oldest_first
        """
        # Year 1: open, enroll one student, issue invoice (72063).
        y1, _p1 = setup_open_year()
        teacher = create_hired_teacher()
        sec1, _ = create_staffed_section(y1["id"], teacher=teacher, room="R1")
        family = create_family()
        kid = create_student(family["id"])
        enroll_student_fresh(sec1["id"], kid["id"])
        inv1 = issue_invoice_fresh(family["id"], y1["id"])

        # Year 2 (2027-28): open, same student enrolled in a year-2 section.
        y2 = get_success_data(
            api_client.create_school_year(
                create_school_year_payload(
                    name="2027-28", start_date="2027-09-01", end_date="2028-06-01",
                    early_bird_deadline="2027-08-15T00:00:00Z",
                    tuition_due_date="2027-10-01",
                    withdrawal_deadline="2027-09-30",
                ),
                ADMIN,
            ),
            201,
        )
        from test_helpers import create_security_plan_payload
        sp2 = get_success_data(
            api_client.create_security_plan(y2["id"], create_security_plan_payload(), ADMIN),
            201,
        )
        get_success_data(api_client.submit_security_plan(sp2["id"], ADMIN))
        get_success_data(api_client.approve_security_plan(sp2["id"], ADMIN))
        get_success_data(api_client.open_school_year(y2["id"], ADMIN))
        sec2, _ = create_staffed_section(y2["id"], teacher=teacher, room="R1")
        get_success_data(
            api_client.set_clock({"to_iso8601": "2027-08-01T00:00:00Z"}, ADMIN)
        )
        enroll_student_fresh(sec2["id"], kid["id"])
        inv2 = issue_invoice_fresh(family["id"], y2["id"])

        pay = post_payment(family["id"], 80000, method="CHECK")
        assert pay["remainder_cents"] == 0
        i1 = get_invoice(inv1["id"])
        i2 = get_invoice(inv2["id"])
        assert i1["status"] == "PAID"
        assert i1["paid_cents"] == 72063
        assert i1["balance_cents"] == 0
        assert i2["status"] == "PARTIALLY_PAID"
        assert i2["paid_cents"] == 7937
        assert i2["balance_cents"] == 64126

    def test_payment_response_shows_applications_immediately(self):
        """PRD §2.4: "Consistency is immediate: every mutation and all of its
        cascade effects are visible in the same response." PRD §3.6: "The payment
        records the allocation in its `applications` array as `invoice_id` and
        `applied_cents` pairs in waterfall order."

        Design: Corner/consistency/payment_response_immediately_shows_applications
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv = bundle["family"], bundle["invoice"]
        pay = post_payment(family["id"], 20000, method="CARD")
        assert pay["applications"] == [
            {"invoice_id": inv["id"], "applied_cents": 20000}
        ]
        assert pay["remainder_cents"] == 0
        inv_now = get_invoice(inv["id"])
        assert inv_now["status"] == "PARTIALLY_PAID"
        assert inv_now["balance_cents"] == 52063

    def test_partial_then_full_payment_transitions(self):
        """PRD §3.6: "an invoice whose balance reaches 0 flips to `PAID`, while one
        that received some but not all of its balance moves `ISSUED` →
        `PARTIALLY_PAID` or stays `PARTIALLY_PAID`."

        Design: Corner/state_machines/initial_states_and_payment_auto_transitions
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv = bundle["family"], bundle["invoice"]
        assert inv["status"] == "ISSUED"
        post_payment(family["id"], 20000, method="CARD")
        mid = get_invoice(inv["id"])
        assert mid["status"] == "PARTIALLY_PAID"
        assert mid["balance_cents"] == 52063
        post_payment(family["id"], 52063, method="ACH")
        end = get_invoice(inv["id"])
        assert end["status"] == "PAID"
        assert end["balance_cents"] == 0

    def test_zero_payment_rejected(self):
        """PRD §2.8 step 5: "`amount_cents` greater than 0... otherwise
        `ERR_INVALID_REQUEST`." PRD §3.6: "with a positive `amount_cents`".

        Design: Corner/validations/zero_payment_rejected
        """
        family = create_family()
        resp = api_client.post_payment(
            family["id"], {"amount_cents": 0, "method": "CARD"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPaymentVoidInvariant:
    def test_post_then_void_restores_money(self):
        """PRD §3.6: "A successful void reverses every application in the
        waterfall: each affected invoice's `paid_cents` decreases and `balance_cents`
        increases by the applied amount, and its status regresses accordingly...
        The remainder is withdrawn from the family's credit, the outstanding balance
        is recomputed". PRD §3.6: "Whatever remains after every open invoice is
        satisfied becomes the payment's `remainder_cents` and is added to the
        family's `credit_balance_cents`".

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_money
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv = bundle["family"], bundle["invoice"]
        pre = get_family(family["id"])
        assert pre["outstanding_balance_cents"] == 72063
        assert pre["credit_balance_cents"] == 0

        pay = post_payment(family["id"], 80000, method="CARD")
        assert pay["remainder_cents"] == 7937
        get_success_data(api_client.void_payment(pay["id"], ADMIN))

        inv_now = get_invoice(inv["id"])
        assert inv_now["paid_cents"] == 0
        assert inv_now["balance_cents"] == 72063
        assert inv_now["status"] == "ISSUED"
        post = get_family(family["id"])
        assert post["outstanding_balance_cents"] == 72063
        assert post["credit_balance_cents"] == 0

    def test_void_regresses_invoice_status_through_partially_paid(self):
        """PRD §3.6: "its status regresses accordingly — `PAID` returns to
        `PARTIALLY_PAID` when a positive balance is restored with payments still on
        record, and `PARTIALLY_PAID` returns to `ISSUED` when `paid_cents` reaches
        0."

        Design: Difficulty/compensating_invariant/payment_post_then_void_restores_money
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv = bundle["family"], bundle["invoice"]
        # Two payments: 20000 then 52063 -> PAID.
        p1 = post_payment(family["id"], 20000, method="CARD")
        p2 = post_payment(family["id"], 52063, method="ACH")
        assert get_invoice(inv["id"])["status"] == "PAID"
        # Void the second payment: positive balance restored with paid_cents > 0.
        get_success_data(api_client.void_payment(p2["id"], ADMIN))
        mid = get_invoice(inv["id"])
        assert mid["status"] == "PARTIALLY_PAID"
        assert mid["paid_cents"] == 20000
        assert mid["balance_cents"] == 52063
        # Void the first: paid_cents reaches 0 -> ISSUED.
        get_success_data(api_client.void_payment(p1["id"], ADMIN))
        end = get_invoice(inv["id"])
        assert end["status"] == "ISSUED"
        assert end["paid_cents"] == 0
        assert end["balance_cents"] == 72063

    def test_void_consumed_credit_rejected(self):
        """PRD §3.6: "if the family's `credit_balance_cents` is less than the
        payment's `remainder_cents` — because a later invoice issue already consumed
        it — the void is rejected with `ERR_CREDIT_ALREADY_APPLIED`."

        Design: Corner/errors/credit_consumed_blocks_payment_void
        """
        # Year 1 invoice 72063 PAID via 80000 payment -> 7937 to credit.
        y1, _p1 = setup_open_year()
        teacher = create_hired_teacher()
        sec1, _ = create_staffed_section(y1["id"], teacher=teacher, room="R1")
        family = create_family()
        kid = create_student(family["id"])
        enroll_student_fresh(sec1["id"], kid["id"])
        inv1 = issue_invoice_fresh(family["id"], y1["id"])
        pay = post_payment(family["id"], 80000, method="CARD")

        # Year 2 issue consumes the credit.
        y2 = get_success_data(
            api_client.create_school_year(
                create_school_year_payload(
                    name="2027-28", start_date="2027-09-01", end_date="2028-06-01",
                    early_bird_deadline="2027-08-15T00:00:00Z",
                    tuition_due_date="2027-10-01",
                    withdrawal_deadline="2027-09-30",
                ),
                ADMIN,
            ),
            201,
        )
        from test_helpers import create_security_plan_payload
        sp2 = get_success_data(
            api_client.create_security_plan(y2["id"], create_security_plan_payload(), ADMIN),
            201,
        )
        get_success_data(api_client.submit_security_plan(sp2["id"], ADMIN))
        get_success_data(api_client.approve_security_plan(sp2["id"], ADMIN))
        get_success_data(api_client.open_school_year(y2["id"], ADMIN))
        sec2, _ = create_staffed_section(y2["id"], teacher=teacher, room="R2")
        get_success_data(
            api_client.set_clock({"to_iso8601": "2027-08-01T00:00:00Z"}, ADMIN)
        )
        enroll_student_fresh(sec2["id"], kid["id"])
        inv2 = issue_invoice_fresh(family["id"], y2["id"])
        assert inv2["credit_applied_cents"] == 7937
        # Family credit is now 0; voiding the year-1 payment must fail.
        resp = api_client.void_payment(pay["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_CREDIT_ALREADY_APPLIED)


class TestLateFees:
    def test_pre_fee_snapshot_no_same_run_compounding(self):
        """PRD §3.6: "For each eligible invoice the fee is computed against a
        snapshot of the balance taken before the fee is added: the snapshot
        multiplied by the year's `late_fee_pct`, rounded half up to whole cents...
        and because the snapshot excludes the fee itself, a single run never
        compounds its own charges; each pass adds at most one fee per invoice, and a
        later pass may add another if the invoice is still eligible."

        Design: Difficulty/combinatorial_formula/late_fee_pre_fee_snapshot_no_same_run_compounding
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv, year = bundle["family"], bundle["invoice"], ctx["year"]
        assert inv["total_due_cents"] == 72063
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, ADMIN)
        )
        run1 = get_success_data(api_client.accrue_late_fees(year["id"], ADMIN))
        # round_half_up(72063 * 0.015) = round_half_up(1080.945) = 1081
        assert run1["total_fees_cents"] == 1081
        mid = get_invoice(inv["id"])
        assert mid["balance_cents"] == 72063 + 1081
        run2 = get_success_data(api_client.accrue_late_fees(year["id"], ADMIN))
        # Second run starts from the post-run-1 snapshot: round_half_up(73144*0.015)
        assert run2["total_fees_cents"] == 1097
        end = get_invoice(inv["id"])
        assert end["late_fees_cents"] == 2178
        assert end["balance_cents"] == 74241

    def test_paid_invoice_exempt_from_accrual(self):
        """PRD §3.6: "One pass examines every invoice of the year in `ISSUED` or
        `PARTIALLY_PAID` status — `PAID` and `VOID` invoices are exempt."

        Design: Difficulty/combinatorial_formula/late_fee_pre_fee_snapshot_no_same_run_compounding
        """
        ctx = setup_open_year_with_section()
        bundle = setup_family_with_invoice(ctx["year"], ctx["section"], 1)
        family, inv, year = bundle["family"], bundle["invoice"], ctx["year"]
        # Pay the invoice in full -> PAID; move past the due date; accrue.
        post_payment(family["id"], 72063, method="CARD")
        assert get_invoice(inv["id"])["status"] == "PAID"
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, ADMIN)
        )
        run = get_success_data(api_client.accrue_late_fees(year["id"], ADMIN))
        assert run["total_fees_cents"] == 0
        end = get_invoice(inv["id"])
        assert end["late_fees_cents"] == 0
        assert end["balance_cents"] == 0

    def test_min_balance_boundary(self):
        """PRD §3.6: "an invoice is eligible when the logical clock's current date
        is strictly after its `due_date` and its `balance_cents` is at least the
        year's `late_fee_min_balance_cents` (balances strictly below that floor are
        exempt)."

        Design: Corner/calculations/late_fee_min_balance_boundary
        """
        # Tiny year: member tuition 100 + activity fee 400 -> balance exactly 500.
        ctx = setup_open_year_with_section(
            member_tuition_cents=100, non_member_tuition_cents=200,
            activity_fee_cents=400,
            early_bird_deadline="2026-07-01T00:00:00Z",
        )
        year, section = ctx["year"], ctx["section"]
        family = create_family()
        kid = create_student(family["id"])
        enroll_student_fresh(section["id"], kid["id"])
        inv = issue_invoice_fresh(family["id"], year["id"])
        assert inv["balance_cents"] == 500
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-10-02T00:00:00Z"}, ADMIN)
        )
        run1 = get_success_data(api_client.accrue_late_fees(year["id"], ADMIN))
        # 500 meets the >= 500 floor exactly: round_half_up(500 * 0.015) = 8
        assert run1["total_fees_cents"] == 8
        # Pay 9 -> balance 508 - 9 = 499, strictly below the floor.
        post_payment(family["id"], 9, method="CARD")
        run2 = get_success_data(api_client.accrue_late_fees(year["id"], ADMIN))
        assert run2["total_fees_cents"] == 0
        end = get_invoice(inv["id"])
        assert end["late_fees_cents"] == 8
        assert end["balance_cents"] == 499


class TestWithdrawalTiers:
    def test_refund_tiers_by_clock(self):
        """PRD §3.7: "A withdrawal before the year's `withdrawal_deadline` earns a
        full credit — a fraction of 1.0. A withdrawal on or after the deadline but
        before the year's `end_date` earns the fraction configured in
        `refund_pct_after_deadline`." PRD §3.7: "In every other case the withdrawal
        records its tier but grants nothing."

        Design: Corner/calculations/withdrawal_refund_tiers_by_clock
        """
        ctx = setup_open_year_with_section()
        section = ctx["section"]
        family = create_family()
        k1 = create_student(family["id"])
        k2 = create_student(family["id"])
        e1, e2 = enroll_students_sequential(section["id"], [k1["id"], k2["id"]])
        # Before the 2026-09-30 deadline -> 1.0
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-09-29T00:00:00Z"}, ADMIN)
        )
        w1 = get_success_data(api_client.withdraw_enrollment(e1["id"], ADMIN))
        assert w1["withdrawal_credit_pct"] == 1.0
        # On/after deadline but before end_date -> 0.5
        get_success_data(
            api_client.set_clock({"to_iso8601": "2026-10-15T00:00:00Z"}, ADMIN)
        )
        w2 = get_success_data(api_client.withdraw_enrollment(e2["id"], ADMIN))
        assert w2["withdrawal_credit_pct"] == 0.5
        # No billed+collected invoice exists -> no credit granted for either.
        assert w1["credit_applied"] is False
        assert w2["credit_applied"] is False
