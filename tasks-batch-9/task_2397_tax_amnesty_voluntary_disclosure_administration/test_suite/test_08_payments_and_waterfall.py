"""Cash application: the ceiling rule, the waterfall, and exact reversal.

PRD §3.6 walks the `ACTIVE` plan's installments in ascending `seq_index`,
filling each completely before the next, and PRD §3.6 defines reversal as the
exact inverse of that walk while refusing to disturb a committed down payment.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CANONICAL_DOWN_PAYMENT_CENTS,
    CANONICAL_INSTALLMENT_BASE_CENTS,
    CANONICAL_INSTALLMENT_LAST_CENTS,
    CANONICAL_SCHEDULED_TOTAL_CENTS,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WATERFALL_PAYMENT_CENTS,
    CANONICAL_WATERFALL_TAIL_CENTS,
    ApiErrorId,
    assert_fields,
    assert_list_total,
    declare_breach,
    draft_return,
    file_return,
    installments_of,
    payment_payload,
    read_agreement,
    read_payment,
    read_plan,
    read_program,
    read_return,
    remit_payment,
    reverse_payment_payload,
    rows_by_seq_index,
    setup_approved_installment_plan,
    setup_executed_agreement,
    setup_filed_return,
    validate_error,
    validate_success,
)


class TestAgreementStateBeatsTheCeiling:
    """A breached agreement refuses cash before the amount is ever weighed."""

    def test_a_breached_agreement_reports_its_state_not_the_ceiling(self, api):
        """The payment is both mistimed and oversized; the state rule answers.

        PRD §2.6: "When more than one rule would reject a request, the rules are
        evaluated in strictly ascending precedence order and the **first**
        violation decides the response."

        PRD §2.6: "The addressed `VoluntaryDisclosureAgreement` must be in the
        state the operation requires — `DRAFTED` to execute, `DRAFTED` or
        `EXECUTED` to draft a return, `EXECUTED` to file returns, to amend, to
        certify, to propose or approve a plan, to pay or to declare breach, and
        `BREACHED` to rescind — otherwise `ERR_AGREEMENT_NOT_DRAFTED`,
        `ERR_AGREEMENT_NOT_EXECUTED` or `ERR_AGREEMENT_NOT_BREACHED` (409)."

        PRD §3.6: "A payment ordinarily may not exceed the agreement's
        outstanding amount — its `amount_cents` may not be greater than
        `total_due_cents` less `paid_total_cents`, otherwise
        `ERR_PAYMENT_EXCEEDS_BALANCE`"

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_check_precedes_payment_ceiling_check
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Ironwood Millworks LLC",
                "taxpayer_type": "BUSINESS",
                "tin_last4": "4409",
            },
        )
        declare_breach(api, ctx, breach_reason="AUDIT_CONCEALMENT_DISCOVERED")

        response = api.create_payment(
            payment_payload(ctx["agreement"]["id"], 5000000),
            ctx["taxpayer_headers"],
        )
        validate_error(response, ApiErrorId.AGREEMENT_NOT_EXECUTED)
        assert (
            response.json()["data"]["error_id"] != ApiErrorId.PAYMENT_EXCEEDS_BALANCE
        )

        assert_list_total(
            api.list_agreement_payments(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            0,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="BREACHED",
            paid_total_cents=0,
        )

    def test_an_executed_agreement_reports_the_ceiling_instead(self, api):
        """With the state rule satisfied the masked ceiling rule fires.

        PRD §3.6: "A payment ordinarily may not exceed the agreement's
        outstanding amount — its `amount_cents` may not be greater than
        `total_due_cents` less `paid_total_cents`, otherwise
        `ERR_PAYMENT_EXCEEDS_BALANCE`"

        Design: Difficulty/priority_pair_validation_conflict/agreement_state_check_precedes_payment_ceiling_check
        """
        ctx = setup_filed_return(
            api,
            taxpayer_overrides={
                "legal_name": "Ironwood Millworks LLC",
                "taxpayer_type": "BUSINESS",
                "tin_last4": "4409",
            },
        )

        validate_error(
            api.create_payment(
                payment_payload(ctx["agreement"]["id"], 5000000),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE,
        )
        assert_list_total(
            api.list_agreement_payments(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            0,
        )


class TestPaymentCeilingTiming:
    """The ceiling is switched off until the first return reaches `FILED`."""

    def test_a_pre_filing_payment_is_unbounded_then_the_ceiling_binds(self, api):
        """Good-faith cash lands in float; once filed, the balance is the cap.

        PRD §3.6: "but that ceiling is deliberately not enforced while the
        agreement has no return in `FILED`, `ASSESSED`, `SETTLED` or
        `REINSTATED` status, because a pre-filing down payment has nothing to be
        measured against and lands wholly in unapplied credit."

        PRD §3.6: "The agreement's `paid_total_cents` is then recomputed as the
        sum of `amount_cents` over its payments whose `status` is `APPLIED`, and
        the program's `collected_cents` is recomputed in turn."

        PRD §3.6: "`PAID_IN_FULL` when `paid_total_cents` is at least
        `total_due_cents`"

        Design: Corner/Table 4 Validations/payment_ceiling_is_unenforced_before_the_first_filing_then_binds
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Windlass Bay Charters LLC",
                "tin_last4": "1187",
            },
        )

        early = remit_payment(api, ctx, 200000, payment_reference="GOODFAITH-1")
        assert_fields(early, status="APPLIED", unapplied_delta_cents=200000)

        drafted = draft_return(api, ctx)
        filed = file_return(api, ctx, drafted["id"])
        assert_fields(filed, status="FILED")

        validate_error(
            api.create_payment(
                payment_payload(ctx["agreement"]["id"], 850001),
                ctx["taxpayer_headers"],
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE,
        )
        remit_payment(api, ctx, 850000, payment_reference="BALANCE-1")

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
            paid_total_cents=CANONICAL_TOTAL_DUE_CENTS,
            unapplied_credit_cents=CANONICAL_TOTAL_DUE_CENTS,
            payment_status="PAID_IN_FULL",
        )
        assert_fields(read_return(api, drafted["id"]), status="FILED")
        assert_list_total(
            api.list_agreement_payments(
                ctx["agreement"]["id"], ADMIN_HEADERS, {"status": "APPLIED", "limit": 100}
            ),
            2,
        )
        assert_fields(
            read_program(api, ctx["program"]["id"]),
            collected_cents=CANONICAL_TOTAL_DUE_CENTS,
        )


class TestWaterfall:
    """Cash fills the earliest open installment completely before the next."""

    def test_two_installments_fill_before_the_third_is_part_paid(self, api):
        """200,000 cents covers 85,909 twice and leaves 28,182 for the third.

        PRD §3.6: "The server walks the installments of the agreement's `ACTIVE`
        plan in ascending `seq_index` order, skipping any whose `status` is
        `PAID`, `VOIDED` or `DEFAULTED`. For each one it takes the smaller of the
        cash still remaining and that installment's `amount_cents` less its
        `paid_cents`; when that take is greater than zero it adds the take to
        `paid_cents`, appends an entry recording the `installment_id` and the
        `amount_cents` taken to the payment's `allocations` array, and reduces the
        remaining cash by the take; an installment whose `paid_cents` has reached
        its `amount_cents` transitions `SCHEDULED → PAID`; and the walk stops as
        soon as no cash remains. Earlier installments therefore fill completely
        before later ones receive anything."

        PRD §3.6: "Whatever cash is left when the walk ends is recorded as the
        payment's `unapplied_delta_cents` and added to the agreement's
        `unapplied_credit_cents`"

        Design: Corner/Table 3 Calculations/waterfall_fills_earliest_installments_before_later_ones
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Fallow Lane Provisions LLC",
                "tin_last4": "3081",
            },
        )
        plan_id = ctx["payment_plan"]["id"]
        assert_fields(
            ctx["payment_plan"],
            status="ACTIVE",
            scheduled_total_cents=CANONICAL_SCHEDULED_TOTAL_CENTS,
        )

        payment = remit_payment(
            api,
            ctx,
            CANONICAL_WATERFALL_PAYMENT_CENTS,
            payment_reference="INST-1-3",
        )
        assert_fields(payment, status="APPLIED", unapplied_delta_cents=0)

        rows = rows_by_seq_index(installments_of(api, plan_id))
        seq_of = {row["id"]: seq for seq, row in rows.items()}
        allocations = payment["allocations"]
        assert [seq_of[entry["installment_id"]] for entry in allocations] == [1, 2, 3]
        assert [entry["amount_cents"] for entry in allocations] == [
            CANONICAL_INSTALLMENT_BASE_CENTS,
            CANONICAL_INSTALLMENT_BASE_CENTS,
            CANONICAL_WATERFALL_TAIL_CENTS,
        ]

        paid_rows = assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "PAID", "limit": 100}
            ),
            2,
        )
        assert all(
            row["paid_cents"] == CANONICAL_INSTALLMENT_BASE_CENTS for row in paid_rows
        )
        assert_fields(
            rows[3],
            status="SCHEDULED",
            amount_cents=CANONICAL_INSTALLMENT_BASE_CENTS,
            paid_cents=CANONICAL_WATERFALL_TAIL_CENTS,
        )
        assert_fields(
            rows[11],
            amount_cents=CANONICAL_INSTALLMENT_LAST_CENTS,
            paid_cents=0,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            paid_total_cents=305000,
            unapplied_credit_cents=0,
            down_payment_applied_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            payment_status="PARTIAL",
        )
        assert_fields(read_plan(api, plan_id), status="ACTIVE")
        assert_fields(read_program(api, ctx["program"]["id"]), collected_cents=305000)


class TestPaymentReversal:
    """Reversal unwinds exactly what the payment did, and nothing else."""

    def test_reversal_unwinds_every_allocation_it_recorded(self, api):
        """Each named installment gives back precisely the amount it took.

        PRD §3.6: "Every entry in the payment's `allocations` array is then
        unwound — each named installment's `paid_cents` is reduced by the amount
        that entry recorded, and any installment that had reached `PAID` returns
        to `SCHEDULED`."

        PRD §3.6: "Reversing advances the payment `APPLIED → REVERSED` and
        records the supplied `reversal_reason`."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_the_cash_ledger_without_touching_the_down_payment
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Windrose Marine Supply LLC",
                "tin_last4": "4471",
            },
        )
        plan_id = ctx["payment_plan"]["id"]
        installment_payment = remit_payment(
            api,
            ctx,
            CANONICAL_WATERFALL_PAYMENT_CENTS,
            payment_reference="INST-1-3",
        )

        reversed_payment = validate_success(
            api.reverse_payment(
                installment_payment["id"],
                reverse_payment_payload(),
                ADMIN_HEADERS,
            )
        )
        assert_fields(
            reversed_payment,
            status="REVERSED",
            reversal_reason="ACH_RETURNED_INSUFFICIENT_FUNDS",
            unapplied_delta_cents=0,
        )

        scheduled = assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "SCHEDULED", "limit": 100}
            ),
            11,
        )
        assert all(row["paid_cents"] == 0 for row in scheduled)
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "PAID", "limit": 100}
            ),
            0,
        )

    def test_reversal_leaves_the_committed_down_payment_alone(self, api):
        """The down payment is committed, so only the reversed cash disappears.

        PRD §3.6: "The agreement's `unapplied_credit_cents` is reduced by the
        payment's `unapplied_delta_cents`, its `paid_total_cents` is reduced by
        the payment's `amount_cents`, and its `payment_status` is recomputed. The
        program's `collected_cents` is recomputed."

        PRD §3.6: "requires that the reversal not undermine a committed down
        payment: the agreement's `paid_total_cents` less the payment's
        `amount_cents` must remain at least its `down_payment_applied_cents`,
        otherwise `ERR_REVERSAL_BREAKS_DOWN_PAYMENT`."

        Design: Difficulty/compensating_invariant/payment_reversal_restores_the_cash_ledger_without_touching_the_down_payment
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Windrose Marine Supply LLC",
                "tin_last4": "4471",
            },
        )
        down_payment_id = ctx["down_payment"]["id"]
        installment_payment = remit_payment(
            api,
            ctx,
            CANONICAL_WATERFALL_PAYMENT_CENTS,
            payment_reference="INST-1-3",
        )
        validate_success(
            api.reverse_payment(
                installment_payment["id"], reverse_payment_payload(), ADMIN_HEADERS
            )
        )

        assert_fields(read_payment(api, down_payment_id), status="APPLIED")
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            paid_total_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            down_payment_applied_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            unapplied_credit_cents=0,
            payment_status="PARTIAL",
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )
        assert_fields(read_plan(api, ctx["payment_plan"]["id"]), status="ACTIVE")
        assert_fields(
            read_program(api, ctx["program"]["id"]),
            collected_cents=CANONICAL_DOWN_PAYMENT_CENTS,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]), status="FILED"
        )
