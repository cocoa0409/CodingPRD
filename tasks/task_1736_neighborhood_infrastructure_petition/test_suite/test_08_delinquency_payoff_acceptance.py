"""Delinquency penalties and cure, payoff quotes, final acceptance, and credit
refunds (PRD §3.7–§3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_change_order,
    assert_assessment_money_identity,
    assert_same_instant,
    billing_run,
    complete_construction,
    complete_phase,
    create_owner,
    drive_to_approved,
    drive_to_billing,
    drive_to_construction,
    finalize_true_up,
    get_assessment,
    get_district,
    list_district_invoices,
    make_property_owner_headers,
    post_payment,
    propose_change_order,
    select_payment_option,
    set_clock,
    api_client,
    validate_error,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]
COUNCIL = TEST_USERS["council_headers"]


def _settlement_due_district(name, prefix, interest_method):
    """District in BILLING whose single assessment is SETTLEMENT_DUE with a
    10,000-cent SUPPLEMENTAL invoice (due 2026-11-19, grace end 2026-12-19):
    owner prepaid the 100,000 preliminary; one approved 10,000 change order."""
    ctx = drive_to_construction(
        name, prefix=prefix, methodology="PER_PARCEL",
        interest_method=interest_method, contract_price_cents=100000,
        contingency_cents=0, venue=f"{name} Hearing Room",
    )
    district_id = ctx["district"]["id"]
    assessment = ctx["assessments"][0]
    owner = ctx["pairs"][0][0]
    select_payment_option(assessment["id"], owner["id"], option="PREPAY_FULL",
                          term_years=None)
    post_payment(assessment["id"], owner["id"], 100000)
    order = propose_change_order(district_id, amount_cents=10000,
                                 phase_id=ctx["phase"]["id"], engineer_id="eng-1")
    approve_change_order(order["id"], engineer_id="eng-2")
    complete_phase(ctx["phase"]["id"], at="2026-10-10T17:00:00Z")
    complete_construction(district_id)
    finalize_true_up(district_id, at="2026-10-20T00:00:00Z")
    return ctx, assessment, owner


def _billing_installments(name, prefix, **overrides):
    """District in BILLING with a 5-year 4% installment schedule on a 100,000
    levy; the year-1 invoice (18,463 principal + 4,000 interest) is issued at
    2027-09-20 and due 2027-10-20 (grace end 2027-11-19)."""
    kwargs = dict(methodology="PER_PARCEL", contract_price_cents=100000,
                  contingency_cents=0, venue=f"{name} Room")
    kwargs.update(overrides)
    ctx = drive_to_billing(name, prefix=prefix, option="INSTALLMENTS",
                           term_years=5, **kwargs)
    set_clock("2027-09-20T00:00:00Z")
    billing_run(ctx["district"]["id"])  # issues the year-1 invoice
    return ctx


class TestDelinquencyPenaltyVariants:
    def test_simple_method_penalty_is_linear(self, api):
        """PRD §3.8: "Under `SIMPLE`, the penalty is the overdue month count
        times one percent of that base, the one-percent figure rounded half-up
        to whole cents before multiplication." PRD §3.8: "The overdue month
        count is the whole thirty-day months elapsed since the grace end".

        Design: Difficulty/dual_variant_calc/delinquency_interest_simple_vs_compound
        """
        ctx, assessment, _owner = _settlement_due_district("DV2-SIM", "sim", "SIMPLE")
        set_clock("2027-03-20T00:00:00Z")  # 91 days past the 2026-12-19 grace end
        result = billing_run(ctx["district"]["id"])
        assert result["newly_delinquent_count"] == 1

        invoice = list_district_invoices(ctx["district"]["id"])[0]
        assert invoice["kind"] == "SUPPLEMENTAL"
        assert_same_instant(invoice["due_date"], "2026-11-19T00:00:00Z",
                            "supplemental due_date")
        assert invoice["status"] == "DELINQUENT"
        # 3 penalty months x round(10,000 x 1%) = 3 x 100 = 300.
        assert invoice["penalty_cents"] == 300

    def test_compound_method_penalty_capitalizes(self, api):
        """PRD §3.8: "Under `COMPOUND`, the months are walked in sequence: each
        month's penalty is one percent of the running balance rounded half-up
        to whole cents, that penalty is added into the balance, and the
        invoice's penalty is the sum of the monthly steps — identical arrears
        and identical elapsed months therefore cost strictly more under
        compounding."

        Design: Difficulty/dual_variant_calc/delinquency_interest_simple_vs_compound
        """
        sim_ctx, _, _ = _settlement_due_district("DV2-SIM", "sim", "SIMPLE")
        # The first district's build left the clock at its true-up instant
        # (2026-10-20); rewind it so the second district's default hearing
        # date satisfies the ten-day statutory notice rule of PRD §3.3 and
        # both districts share an identical timeline (identical arrears and
        # elapsed months, as the comparison requires).
        set_clock("2026-08-01T00:00:00Z")
        com_ctx, _, _ = _settlement_due_district("DV2-COM", "com", "COMPOUND")
        set_clock("2027-03-20T00:00:00Z")
        sim_run = billing_run(sim_ctx["district"]["id"])
        com_run = billing_run(com_ctx["district"]["id"])
        assert sim_run["newly_delinquent_count"] == 1
        assert com_run["newly_delinquent_count"] == 1

        sim_pen = list_district_invoices(sim_ctx["district"]["id"])[0]["penalty_cents"]
        com_pen = list_district_invoices(com_ctx["district"]["id"])[0]["penalty_cents"]
        assert sim_pen == 300
        # 100 capitalized -> 10,100; 101 capitalized -> 10,201; 102 -> 303.
        assert com_pen == 303
        assert com_pen - sim_pen == 3, (
            "identical overdue balance and elapsed months, different penalties "
            "by interest_method"
        )


class TestDelinquencyCureCycle:
    def test_grace_boundary_then_delinquency_flip(self, api):
        """PRD §3.8: "any `ISSUED` or `PARTIALLY_PAID` invoice whose grace
        period has fully elapsed — strictly later than thirty days past its
        `due_date`, so at exactly that thirty-day mark it remains undelinquent
        — becomes `DELINQUENT`, flipping its owning assessment from
        `IN_REPAYMENT` to `DELINQUENT` with it".

        Design: Difficulty/non_linear_state_machine/assessment_delinquency_cure_cycle
        """
        ctx = _billing_installments("DQ", "dq")
        district_id = ctx["district"]["id"]
        assessment = ctx["assessments"][0]

        set_clock("2027-11-19T00:00:00Z")  # exactly due_date + 30 days
        boundary = billing_run(district_id)
        assert boundary["newly_delinquent_count"] == 0, (
            "strictly-greater comparison: not yet delinquent at the mark"
        )

        set_clock("2027-12-19T00:00:00Z")  # one full penalty month
        flipped = billing_run(district_id)
        assert flipped["newly_delinquent_count"] == 1
        invoice = list_district_invoices(district_id)[0]
        assert invoice["status"] == "DELINQUENT"
        # 1% of the unpaid base 22,463 -> 225 (round half-up).
        assert invoice["penalty_cents"] == 225
        assert get_assessment(assessment["id"])["status"] == "DELINQUENT"

    def test_cure_payment_returns_assessment_to_in_repayment(self, api):
        """PRD §3.8: "a `DELINQUENT` invoice that reaches `PAID` triggers the
        cure check: once no delinquent invoice of the assessment remains, the
        assessment itself returns from `DELINQUENT` to `IN_REPAYMENT`." PRD
        §3.8: "Billed invoices are filled first, oldest `due_date` first with
        creation-time tie-breaks, and within each invoice the order is penalty,
        then interest, then principal".

        Design: Difficulty/non_linear_state_machine/assessment_delinquency_cure_cycle
        """
        ctx = _billing_installments("DQ", "dq")
        district_id = ctx["district"]["id"]
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        set_clock("2027-12-19T00:00:00Z")
        billing_run(district_id)

        # Cure the delinquent year-1 invoice: penalty 225 + interest 4,000 +
        # principal 18,463 = 22,688.
        payment = post_payment(assessment["id"], owner["id"], 22688)
        assert payment["applied_penalty_cents"] == 225
        assert payment["applied_interest_cents"] == 4000
        assert payment["applied_principal_cents"] == 18463

        invoice = list_district_invoices(district_id)[0]
        assert invoice["status"] == "PAID"
        assert get_assessment(assessment["id"])["status"] == "IN_REPAYMENT", (
            "cure closes the delinquency cycle"
        )

    def test_penalty_recomputed_idempotently_month_over_month(self, api):
        """PRD §3.8: "Either way, `penalty_cents` is recomputed idempotently
        from the overdue month count at every run and never incremented
        piecemeal, so repeated runs at the same clock reading are no-ops."

        Design: Corner/calculations/c_delinquency_second_month_idempotent_recompute
        """
        ctx = _billing_installments("DQR", "dqr")
        district_id = ctx["district"]["id"]

        set_clock("2027-12-19T00:00:00Z")  # 1 penalty month
        billing_run(district_id)
        assert list_district_invoices(district_id)[0]["penalty_cents"] == 225

        set_clock("2028-01-18T00:00:00Z")  # 2 penalty months
        second = billing_run(district_id)
        assert second["newly_delinquent_count"] == 0, "already delinquent"
        assert list_district_invoices(district_id)[0]["penalty_cents"] == 450, (
            "2 x 225 recomputed from months_overdue"
        )

        repeat = billing_run(district_id)
        assert repeat["newly_delinquent_count"] == 0
        assert list_district_invoices(district_id)[0]["penalty_cents"] == 450, (
            "a repeated run at the same clock changes nothing"
        )


class TestPayoffQuote:
    def test_payoff_quote_with_accrued_interest(self, api):
        """PRD §3.8: "The payoff quote ... reporting `payoff_cents` as the sum
        of `principal_balance_cents`, accrued-unpaid interest as of the quote
        instant, and unpaid penalty". PRD §3.8: "Accrued interest ... runs
        simple actual/365 on outstanding principal: principal-change events —
        the true-up and each payment — are walked in chronological order with
        creation-time tie-breaks, and each segment contributes its balance
        times the annual rate times its day count divided by 365, rounded
        half-up to whole cents; the accrued-unpaid figure is the summed accrual
        less interest already paid".

        Design: Corner/calculations/c_payoff_quote_with_accrued_interest
        """
        ctx = drive_to_billing("POQ", prefix="poq", methodology="PER_PARCEL",
                               contract_price_cents=2775000, contingency_cents=0,
                               venue="POQ Room", option="INSTALLMENTS", term_years=5)
        district_id = ctx["district"]["id"]
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        set_clock("2027-09-20T00:00:00Z")
        billing_run(district_id)
        set_clock("2027-10-20T00:00:00Z")
        # Year-1 invoice: interest 111,000 + principal 512,340.
        post_payment(assessment["id"], owner["id"], 623340)

        set_clock("2027-12-04T00:00:00Z")  # 45 days after the payment
        quote = validate_success(
            api_client.payoff_quote(assessment["id"],
                                    make_property_owner_headers(owner["id"]))
        )
        assert quote["principal_balance_cents"] == 2262660
        # round(2,262,660 x 0.04 x 45 / 365) = 11,158.
        assert quote["accrued_interest_cents"] == 11158
        assert quote["billed_unpaid_cents"] == 0
        assert quote["penalty_unpaid_cents"] == 0
        assert quote["payoff_cents"] == 2273818

    def test_payoff_quote_role_paths(self, api):
        """PRD §3.8: "The payoff quote, available to the owning owner and to
        the `FinanceOfficer`". PRD §2.1: "ownership checks on any resource that
        references a property owner — a signature's parcel, an objection's
        parcel, an assessment's parcel — compare the resource's owner-of-record
        field to `X-User-ID`, and a mismatch is rejected with
        `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/endpoints/ep_payoff_quote_role_paths
        """
        ctx = _billing_installments("PQR", "pqr")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        other_owner = create_owner(full_name="Owner pqr9", email="pqr-o9@x.test")

        set_clock("2027-10-20T00:00:00Z")  # one full 365-day year since true-up
        owner_quote = validate_success(
            api_client.payoff_quote(assessment["id"],
                                    make_property_owner_headers(owner["id"]))
        )
        assert owner_quote["payoff_cents"] == 104000, (
            "principal 100,000 + accrued interest 4,000"
        )

        validate_error(
            api_client.payoff_quote(assessment["id"],
                                    make_property_owner_headers(other_owner["id"])),
            ApiErrorId.ERR_NOT_RESOURCE_OWNER,
        )

        finance_quote = validate_success(
            api_client.payoff_quote(assessment["id"], FINANCE)
        )
        assert finance_quote["payoff_cents"] == 104000


class TestWaterfallToDistrictCompletion:
    def _paid_off_district(self):
        ctx = _billing_installments("TC2", "tc2")
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        set_clock("2027-10-20T00:00:00Z")  # year-1 due date
        # Payoff quote: principal 100,000 + accrued interest 4,000 = 104,000.
        payment = post_payment(assessment["id"], owner["id"], 104000)
        return ctx, assessment, payment

    def test_waterfall_split_and_invoice_states(self, api):
        """PRD §3.8: "Billed invoices are filled first, oldest `due_date` first
        with creation-time tie-breaks, and within each invoice the order is
        penalty, then interest, then principal". PRD §3.8: "Whatever then
        remains settles accrued-but-unbilled interest, and any final remainder
        prepays principal. When the principal balance reaches zero with nothing
        billed-and-unpaid and nothing accrued-and-unpaid outstanding, the
        assessment becomes `PAID_OFF`, its still-`SCHEDULED` future invoices
        are `VOIDED`".

        Design: Difficulty/transitive_cascade/payment_waterfall_to_district_completion_flag
        """
        ctx, assessment, payment = self._paid_off_district()
        assert payment["applied_penalty_cents"] == 0
        assert payment["applied_interest_cents"] == 4000, "year-1 billed interest"
        assert payment["applied_principal_cents"] == 100000, (
            "18,463 billed principal + 81,537 principal prepayment"
        )

        invoices = list_district_invoices(ctx["district"]["id"])
        assert invoices[0]["status"] == "PAID", "hop 1: year-1 invoice filled"
        assert invoices[1]["status"] == "VOIDED"
        assert invoices[4]["status"] == "VOIDED"

    def test_assessment_paid_off_and_district_accepted(self, api):
        """PRD §3.8: "the district's `paid_assessment_count`,
        `total_assessment_count`, and `all_assessments_paid` are recomputed —
        the last of these true exactly when at least one assessment exists
        outside `REMOVED` and `SUPERSEDED` and every such assessment is
        `PAID_OFF`." PRD §3.9: "It requires the district to be in `BILLING`
        (`ERR_DISTRICT_NOT_ACCEPTABLE`) and every assessment settled —
        `all_assessments_paid` must be true".

        Design: Difficulty/transitive_cascade/payment_waterfall_to_district_completion_flag
        """
        ctx, assessment, _payment = self._paid_off_district()
        district_id = ctx["district"]["id"]

        after = get_assessment(assessment["id"])
        assert after["status"] == "PAID_OFF", "hop 2"
        assert after["principal_balance_cents"] == 0

        district = get_district(district_id)
        assert district["paid_assessment_count"] == 1, "hop 3"
        assert district["total_assessment_count"] == 1
        assert district["all_assessments_paid"] is True

        accepted = validate_success(
            api_client.accept_district(district_id, COUNCIL)
        )
        assert accepted["status"] == "ACCEPTED"


class TestAcceptanceGates:
    def test_accept_with_unpaid_assessments_rejected(self, api):
        """PRD §3.9: "It requires the district to be in `BILLING`
        (`ERR_DISTRICT_NOT_ACCEPTABLE`) and every assessment settled —
        `all_assessments_paid` must be true, meaning at least one assessment
        exists outside `REMOVED` and `SUPERSEDED` and all of them are
        `PAID_OFF`, with a shortfall rejected as
        `ERR_ASSESSMENTS_NOT_ALL_PAID`."

        Design: Corner/state_machines/sm_accept_with_unpaid_assessments_rejected
        """
        ctx = drive_to_billing("SAU", prefix="sau", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="SAU Room", option="INSTALLMENTS", term_years=5)
        validate_error(
            api_client.accept_district(ctx["district"]["id"], COUNCIL),
            ApiErrorId.ERR_ASSESSMENTS_NOT_ALL_PAID,
        )
        district = get_district(ctx["district"]["id"])
        assert district["all_assessments_paid"] is False
        assert district["status"] == "BILLING", "district unchanged"

    def test_accept_requires_billing(self, api):
        """PRD §3.9: "It requires the district to be in `BILLING`
        (`ERR_DISTRICT_NOT_ACCEPTABLE`)".

        Design: Corner/errors/err_accept_requires_billing
        """
        ctx = drive_to_approved("EAB", prefix="eab", methodology="PER_PARCEL",
                                contract_price_cents=100000, contingency_cents=0,
                                venue="EAB Room")
        validate_error(
            api_client.accept_district(ctx["district"]["id"], COUNCIL),
            ApiErrorId.ERR_DISTRICT_NOT_ACCEPTABLE,
        )


class TestRefundCreditConservation:
    def _paid_off_with_credit(self, name, prefix):
        """Prepay 120,000 against a final levy of 100,000 (contingency excluded
        at true-up) -> PAID_OFF with a 20,000 credit balance."""
        return drive_to_billing(
            name, prefix=prefix, methodology="PER_PARCEL",
            contract_price_cents=100000, contingency_cents=20000,
            venue=f"{name} Room", option="PREPAY_FULL",
        )

    def test_trueup_credit_and_money_identity(self, api):
        """PRD §3.7: "when the final levy is equal to or less than what was
        paid, the assessment moves straight to `PAID_OFF`, and when it is
        strictly less, the overage is parked as a refundable
        `credit_balance_cents` equal to the shortfall." PRD §3.7: "the
        `contingency_cents` allowance is deliberately excluded from the final
        basis."

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        ctx = self._paid_off_with_credit("CI1", "ci1")
        assessment = get_assessment(ctx["assessments"][0]["id"])
        assert assessment["status"] == "PAID_OFF"
        assert assessment["final_levy_cents"] == 100000, (
            "final basis = contract price only (contingency excluded)"
        )
        assert assessment["total_paid_cents"] == 120000
        assert assessment["total_refunded_cents"] == 0
        assert assessment["credit_balance_cents"] == 20000
        assert_assessment_money_identity(assessment)  # 120,000 - 0 == 100,000 + 20,000

    def test_refund_restores_exact_balance(self, api):
        """PRD §3.8: "A payout lowers `credit_balance_cents` and raises
        `total_refunded_cents` by the same figure and advances the assessment's
        `version`; the money identity is conserved at every step".

        Design: Difficulty/compensating_invariant/payment_refund_money_conservation
        """
        ctx = self._paid_off_with_credit("CI1", "ci1")
        assessment_id = ctx["assessments"][0]["id"]
        refunded = validate_success(
            api_client.refund_credit(assessment_id, {"amount_cents": 20000}, FINANCE)
        )
        assert refunded["credit_balance_cents"] == 0
        assert refunded["total_refunded_cents"] == 20000
        after = get_assessment(assessment_id)
        # Net money received (100,000) now equals the final levy with no
        # credit outstanding: 120,000 - 20,000 == 100,000 + 0.
        assert_assessment_money_identity(after)
        assert after["total_paid_cents"] == 120000

    def test_refund_exceeding_credit_rejected(self, api):
        """PRD §3.8: "When a true-up has left money with the owner, a
        `FinanceOfficer` pays out against a positive `credit_balance_cents`;
        the requested `amount_cents` must be positive and no greater than the
        credit, failing with `ERR_REFUND_EXCEEDS_CREDIT` otherwise."

        Design: Corner/validations/v_refund_exceeding_credit_rejected
        """
        ctx = self._paid_off_with_credit("VRC", "vrc")
        assessment_id = ctx["assessments"][0]["id"]
        before = get_assessment(assessment_id)
        assert before["credit_balance_cents"] == 20000

        validate_error(
            api_client.refund_credit(assessment_id, {"amount_cents": 20001}, FINANCE),
            ApiErrorId.ERR_REFUND_EXCEEDS_CREDIT,
        )

        refunded = validate_success(
            api_client.refund_credit(assessment_id, {"amount_cents": 20000}, FINANCE)
        )
        assert refunded["credit_balance_cents"] == 0
        assert refunded["total_refunded_cents"] == 20000
