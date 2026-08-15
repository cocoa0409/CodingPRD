"""Cost-reimbursable receivables: accrual-basis billing, aging buckets, late
interest with grace and dispute pause, the payment waterfall, and the LOC vs
INVOICE basis split (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_receivable_payload, create_drawdown_request_payload,
    create_report_requirement_payload, create_cost_transfer_payload,
    setup_sponsor_pi, create_active_award, post_expenditure,
    setup_transfer_pair, create_submitted_transfer, make_sponsor,
    make_person, get_award_version,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
GA9 = TEST_USERS["accountant_9_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def _setup_invoice_award(api, award_number, apr_bps=1000, obligated=425_000):
    """ACTIVE COST_REIMBURSABLE_INVOICE award with three postings
    (TRAVEL 100000 cash, SUPPLIES 50000 not disbursed, EQUIPMENT 200000 cash).
    Returns (award, lines)."""
    sponsor = make_sponsor(name="NIH-INV",
                           payment_method="COST_REIMBURSABLE_INVOICE",
                           late_payment_apr_bps=apr_bps)
    pi = make_person()
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number,
        [
            {"category": "TRAVEL", "authorized_cents": 100_000},
            {"category": "MATERIALS_SUPPLIES", "authorized_cents": 50_000},
            {"category": "EQUIPMENT", "authorized_cents": 200_000},
        ],
        obligated)
    post_expenditure(award["id"], lines["TRAVEL"]["id"],
                     amount_cents=100_000, cash_disbursed=True)
    post_expenditure(award["id"], lines["MATERIALS_SUPPLIES"]["id"],
                     expenditure_type="SUPPLIES", amount_cents=50_000,
                     cash_disbursed=False)
    post_expenditure(award["id"], lines["EQUIPMENT"]["id"],
                     expenditure_type="EQUIPMENT", amount_cents=200_000,
                     cash_disbursed=True)
    return award, lines


def _bill(api, award_id):
    return validate_success(api.create_receivable(
        create_receivable_payload(award_id), GA), 201)


class TestLocCashBasisVsInvoiceAccrualBasis:
    """Difficulty instance: the same postings yield different figures under
    the cash-basis (LOC) and accrual-basis (invoice) conventions."""

    def _setup(self, api):
        # LOC twin
        sp_l = make_sponsor(name="NSF-LOC")
        sp_i = make_sponsor(name="NIH-INV",
                            payment_method="COST_REIMBURSABLE_INVOICE",
                            late_payment_apr_bps=1000)
        pi = make_person()
        lines_spec = [
            {"category": "TRAVEL", "authorized_cents": 100_000},
            {"category": "MATERIALS_SUPPLIES", "authorized_cents": 50_000},
            {"category": "EQUIPMENT", "authorized_cents": 200_000},
        ]
        aw_l, lines_l = create_active_award(sp_l["id"], pi["id"], "L-001",
                                            lines_spec, 425_000)
        aw_i, lines_i = create_active_award(sp_i["id"], pi["id"], "I-001",
                                            lines_spec, 425_000)
        for lines, aw in ((lines_l, aw_l), (lines_i, aw_i)):
            post_expenditure(aw["id"], lines["TRAVEL"]["id"],
                             amount_cents=100_000, cash_disbursed=True)
            post_expenditure(aw["id"], lines["MATERIALS_SUPPLIES"]["id"],
                             expenditure_type="SUPPLIES", amount_cents=50_000,
                             cash_disbursed=False)
            post_expenditure(aw["id"], lines["EQUIPMENT"]["id"],
                             expenditure_type="EQUIPMENT", amount_cents=200_000,
                             cash_disbursed=True)
        return aw_l, aw_i, lines_i

    def test_loc_pool_is_cash_basis(self, api):
        """PRD §3.6: "The letter-of-credit pool is cash-basis. Its eligible
        pool is the sum of `amount_cents` over the award's `POSTED`,
        non-cost-share expenditures with `cash_disbursed` true, plus the F&A
        share computed as the award's `f_and_a_rate_bps` over ten thousand
        times the sum of `mtdc_eligible_cents` over that same cash-disbursed
        set, rounded half-up; undisbursed costs are not drawable."

        Design: Difficulty/dual_variant_calc/loc_cash_basis_vs_invoice_accrual_basis
        """
        aw_l, _aw_i, _lines_i = self._setup(api)
        award = validate_success(api.get_award(aw_l["id"], GA), 200)
        # (100000 + 200000) + round(0.5 * 100000) = 350000; the undisbursed
        # SUPPLIES 50000 and its F&A share are excluded.
        assert award["available_draw_pool_cents"] == 350_000

    def test_invoice_amount_is_accrual_basis(self, api):
        """PRD §3.6: "Cost-reimbursable invoicing is accrual-basis."
        PRD §3.6: "The invoice amount is computed over the award's `POSTED`,
        non-cost-share expenditures whose `transaction_date` falls inside the
        closed billing window and whose `invoiced_receivable_id` is still null
        — regardless of `cash_disbursed`: the amount is the sum of
        `amount_cents` over that set plus the F&A share (rate over ten thousand
        times the set's `mtdc_eligible_cents` sum, rounded half-up)."

        Design: Difficulty/dual_variant_calc/loc_cash_basis_vs_invoice_accrual_basis
        """
        aw_l, aw_i, lines_i = self._setup(api)
        receivable = _bill(api, aw_i["id"])
        # (100000 + 50000 + 200000) + round(0.5 * 150000) = 425000: accrual
        # includes the undisbursed SUPPLIES charge.
        assert receivable["amount_cents"] == 425_000
        loc_pool = validate_success(api.get_award(aw_l["id"], GA), 200)[
            "available_draw_pool_cents"]
        assert loc_pool != receivable["amount_cents"]
        # The undisbursed invoice-side expenditure is stamped as billed.
        supplies = validate_success(api.list_expenditures(
            GA, params={"award_id": aw_i["id"],
                        "expenditure_type": "SUPPLIES"}), 200)
        assert supplies[0]["invoiced_receivable_id"] == receivable["id"]


class TestAgingBucketDay30VsDay31:
    def _setup(self, api):
        sponsor = make_sponsor(name="NIH-INV",
                               payment_method="COST_REIMBURSABLE_INVOICE",
                               late_payment_apr_bps=0)
        pi = make_person()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "AG-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        post_expenditure(award["id"], lines["TRAVEL"]["id"], amount_cents=100_000)
        receivable = _bill(api, award["id"])
        return award, receivable

    def test_amount_and_day30_current(self, api):
        """PRD §3.6: "The `aging_bucket` boundaries are pinned: `CURRENT`
        covers 30 days or fewer, `D31_60` covers 31 through 60, `D61_90` covers
        61 through 90, `D91_120` covers 91 through 120, and `OVER_120` covers
        121 and beyond — so day 30 is `CURRENT`, day 31 is `D31_60`, day 60 is
        `D31_60`, and day 61 is `D61_90`."

        Design: Corner/calculations/aging_bucket_day30_vs_day31
        """
        award, receivable = self._setup(api)
        assert receivable["amount_cents"] == 150_000  # 100000 + round(0.5*100000)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-31T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["days_outstanding"] == 30
        assert r["aging_bucket"] == "CURRENT"

    def test_day31_flips_bucket(self, api):
        """PRD §3.6: "The `aging_bucket` boundaries are pinned: `CURRENT`
        covers 30 days or fewer, `D31_60` covers 31 through 60, `D61_90` covers
        61 through 90, `D91_120` covers 91 through 120, and `OVER_120` covers
        121 and beyond — so day 30 is `CURRENT`, day 31 is `D31_60`, day 60 is
        `D31_60`, and day 61 is `D61_90`."

        Design: Corner/calculations/aging_bucket_day30_vs_day31
        """
        award, receivable = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-31T00:00:00Z"}, ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["days_outstanding"] == 31
        assert r["aging_bucket"] == "D31_60"


class TestInterestGraceDay60VsDay61:
    """Difficulty instance: 60-day grace boundary and the one-day accrual."""

    def _setup(self, api):
        award, _lines = _setup_invoice_award(api, "I2-001")
        return _bill(api, award["id"])      # 425000, invoice_date 2026-08-01

    def test_day60_within_grace_accrues_nothing(self, api):
        """PRD §3.6: "Late interest accrues only after a 60-day grace: the
        billable days are `days_outstanding` minus 60 minus
        `total_disputed_days`, floored at zero — exactly 60 days outstanding
        accrues nothing, day 61 accrues one day."

        Design: Difficulty/boundary_precision_check/interest_grace_day60_vs_day61
        """
        receivable = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-09-30T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["days_outstanding"] == 60
        assert r["aging_bucket"] == "D31_60"
        assert r["accrued_interest_cents"] == 0

    def test_day61_accrues_one_day_and_flips_bucket(self, api):
        """PRD §3.6: "The accrual is the outstanding principal (`amount_cents`
        minus `principal_paid_cents`) multiplied by the sponsor's
        `late_payment_apr_bps` over ten thousand, divided by 365, multiplied by
        billable days, rounded half-up to cents once per receivable."

        Design: Difficulty/boundary_precision_check/interest_grace_day60_vs_day61
        """
        receivable = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-09-30T00:00:00Z"}, ADMIN))
        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["days_outstanding"] == 61
        assert r["aging_bucket"] == "D61_90"
        # round(425000 * 0.10 / 365 * 1) = round(116.438) = 116
        assert r["accrued_interest_cents"] == 116


class TestDisputePausesInterestAccrual:
    def _setup(self, api):
        award, _lines = _setup_invoice_award(api, "DP-001")
        receivable = _bill(api, award["id"])
        # Day 61: one day of interest (116) accrued before the dispute opens.
        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN))
        return receivable

    def test_interest_frozen_while_disputed(self, api):
        """PRD §3.6: "While the receivable is `DISPUTED` accrual pauses:
        `accrued_interest_cents` stays frozen at the value computed when the
        dispute opened, and dispute days never accrue even after resolution."

        Design: Corner/calculations/dispute_pauses_interest_accrual
        """
        receivable = self._setup(api)
        disputed = validate_success(api.dispute_receivable(
            receivable["id"],
            {"dispute_reason": "sponsor queries equipment allowability"}, GA), 200)
        assert disputed["status"] == "DISPUTED"
        get_success_data(api.set_clock({"to_iso8601": "2026-10-11T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["accrued_interest_cents"] == 116   # 10 dispute days add nothing

    def test_resolve_resumes_with_dispute_days_excluded(self, api):
        """PRD §3.6: "resolving the dispute returns it to `OPEN`, with the days
        spent disputed accumulated into `total_disputed_days` and excluded from
        interest thereafter." PRD §3.6: "the billable days are
        `days_outstanding` minus 60 minus `total_disputed_days`, floored at
        zero..."

        Design: Corner/calculations/dispute_pauses_interest_accrual
        """
        receivable = self._setup(api)
        api.dispute_receivable(receivable["id"],
                               {"dispute_reason": "sponsor queries equipment allowability"}, GA)
        get_success_data(api.set_clock({"to_iso8601": "2026-10-11T00:00:00Z"}, ADMIN))
        resolved = validate_success(api.resolve_dispute(receivable["id"], GA), 200)
        assert resolved["status"] == "OPEN"
        get_success_data(api.set_clock({"to_iso8601": "2026-10-16T00:00:00Z"}, ADMIN))
        r = validate_success(api.get_receivable(receivable["id"], GA), 200)
        assert r["total_disputed_days"] == 10
        # billable = 76 - 60 - 10 = 6: round(425000 * 0.10/365 * 6) = 699
        assert r["accrued_interest_cents"] == 699


class TestReceivablePayments:
    def test_receivable_overpayment_rejected(self, api):
        """PRD §3.6: "Recording a payment of `amount_cents` against an `OPEN`
        or `PARTIALLY_PAID` receivable first checks that the payment does not
        exceed `outstanding_total_cents` (`ERR_RECEIVABLE_OVERPAYMENT`)."

        Design: Corner/errors/receivable_overpayment_rejected
        """
        award, _lines = _setup_invoice_award(api, "OP-001", apr_bps=0)
        receivable = _bill(api, award["id"])
        res = api.record_payment(receivable["id"], {"amount_cents": 425_001}, GA)
        validate_error(res, ApiErrorId.ERR_RECEIVABLE_OVERPAYMENT.value)
        paid = validate_success(api.record_payment(
            receivable["id"], {"amount_cents": 425_000}, GA), 200)
        assert paid["status"] == "PAID"
        assert paid["outstanding_total_cents"] == 0

    def test_payment_waterfall_interest_before_principal(self, api):
        """PRD §3.6: "Payments allocate by waterfall."
        PRD §3.6: "The interest portion is the lesser of the payment and the
        unpaid interest (`accrued_interest_cents` minus `interest_paid_cents`);
        the remainder goes to principal."
        PRD §3.6: "`interest_paid_cents` and `principal_paid_cents` accumulate
        their shares, the principal portion adds to the award's
        `cumulative_drawn_cents`, and the status becomes `PAID` when the
        outstanding total reaches zero, else `PARTIALLY_PAID` (including a
        `PARTIALLY_PAID → PARTIALLY_PAID` step when a partial payment still
        leaves a balance)."

        Design: Corner/errors/payment_waterfall_interest_before_principal
        """
        award, _lines = _setup_invoice_award(api, "WF-001")
        receivable = _bill(api, award["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN))
        paid = validate_success(api.record_payment(
            receivable["id"], {"amount_cents": 50_000}, GA), 200)
        assert paid["interest_paid_cents"] == 116
        assert paid["principal_paid_cents"] == 49_884
        assert paid["status"] == "PARTIALLY_PAID"
        # After the payment, accrued recomputes on the reduced outstanding
        # principal per PRD §3.6 ("The accrual is the outstanding principal
        # (amount_cents minus principal_paid_cents) multiplied by ..."):
        # round(375116 * 0.10 / 365 * 1) = 103, so outstanding_total_cents =
        # 425000 + 103 - 116 - 49884 = 375103.
        assert paid["outstanding_total_cents"] == 375_103


class TestReceivableCreationGuards:
    def test_no_uninvoiced_costs_and_double_billing(self, api):
        """PRD §3.6: "A window containing no uninvoiced posted costs is
        rejected with `ERR_NO_UNINVOICED_COSTS`."
        PRD §3.6: "every included expenditure's `invoiced_receivable_id` is set
        — preventing double-billing —..."

        Design: Corner/errors/receivable_no_uninvoiced_costs_and_double_billing
        """
        sponsor = make_sponsor(name="NIH-INV",
                               payment_method="COST_REIMBURSABLE_INVOICE",
                               late_payment_apr_bps=0)
        pi = make_person()
        award, lines = create_active_award(
            sponsor["id"], pi["id"], "DB-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        e = post_expenditure(award["id"], lines["TRAVEL"]["id"],
                             amount_cents=100_000)
        r1 = _bill(api, award["id"])
        res = api.create_receivable(create_receivable_payload(award["id"]), GA)
        validate_error(res, ApiErrorId.ERR_NO_UNINVOICED_COSTS.value)
        e_after = validate_success(api.get_expenditure(e["id"], GA), 200)
        assert e_after["invoiced_receivable_id"] == r1["id"]


class TestPaymentMethodMismatch:
    def _setup(self, api):
        sp_l = make_sponsor(name="NSF-LOC", payment_method="LETTER_OF_CREDIT",
                            late_payment_apr_bps=0)
        sp_i = make_sponsor(name="NIH-INV",
                            payment_method="COST_REIMBURSABLE_INVOICE",
                            late_payment_apr_bps=0)
        sp_f = make_sponsor(name="IndCo", sponsor_type="INDUSTRY",
                            payment_method="FIXED_PRICE_SCHEDULE",
                            f_and_a_rate_bps=0)
        pi = make_person()
        aw_l, _ = create_active_award(sp_l["id"], pi["id"], "PM-L",
                                      [{"category": "TRAVEL",
                                        "authorized_cents": 100_000}], 150_000)
        aw_i, _ = create_active_award(sp_i["id"], pi["id"], "PM-I",
                                      [{"category": "TRAVEL",
                                        "authorized_cents": 100_000}], 150_000)
        aw_f, _ = create_active_award(sp_f["id"], pi["id"], "PM-F",
                                      [{"category": "TRAVEL",
                                        "authorized_cents": 100_000}], 100_000)
        return aw_l, aw_i, aw_f

    def test_drawdown_on_invoice_award_and_receivable_on_loc_award(self, api):
        """PRD §3.6: "drawdowns are only valid on `LETTER_OF_CREDIT` awards,
        receivables only on `COST_REIMBURSABLE_INVOICE` awards, and either
        against the wrong method — or anything at all on
        `FIXED_PRICE_SCHEDULE` — returns `ERR_PAYMENT_METHOD_MISMATCH`."

        Design: Corner/errors/payment_method_mismatch_both_directions
        """
        aw_l, aw_i, _aw_f = self._setup(api)
        res1 = api.create_drawdown_request(
            create_drawdown_request_payload(
                aw_i["id"], 1000, get_award_version(aw_i["id"])), GA)
        validate_error(res1, ApiErrorId.ERR_PAYMENT_METHOD_MISMATCH.value)
        res2 = api.create_receivable(create_receivable_payload(aw_l["id"]), GA)
        validate_error(res2, ApiErrorId.ERR_PAYMENT_METHOD_MISMATCH.value)

    def test_fixed_price_schedule_supports_neither(self, api):
        """PRD §3.6: "drawdowns are only valid on `LETTER_OF_CREDIT` awards,
        receivables only on `COST_REIMBURSABLE_INVOICE` awards, and either
        against the wrong method — or anything at all on
        `FIXED_PRICE_SCHEDULE` — returns `ERR_PAYMENT_METHOD_MISMATCH`."

        Design: Corner/errors/payment_method_mismatch_both_directions
        """
        _aw_l, _aw_i, aw_f = self._setup(api)
        res3 = api.create_drawdown_request(
            create_drawdown_request_payload(
                aw_f["id"], 1000, get_award_version(aw_f["id"])), GA)
        validate_error(res3, ApiErrorId.ERR_PAYMENT_METHOD_MISMATCH.value)
        res4 = api.create_receivable(create_receivable_payload(aw_f["id"]), GA)
        validate_error(res4, ApiErrorId.ERR_PAYMENT_METHOD_MISMATCH.value)


class TestReceivablesAgingComputedRead:
    def test_aging_read_aggregates_buckets_and_interest(self, api):
        """PRD §3.6: "A computed aging read for one award returns the bucket
        sums of per-receivable principal outstanding — `current_cents`,
        `d31_60_cents`, `d61_90_cents`, `d91_120_cents`, `over_120_cents` —
        plus `total_outstanding_cents` and `total_accrued_interest_cents`,
        summing the per-receivable rounded interest values rather than rounding
        the fleet total."

        Design: Corner/endpoints/receivables_aging_computed_read
        """
        award, _lines = _setup_invoice_award(api, "AR-001")
        _bill(api, award["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN))
        aging = validate_success(api.get_receivables_aging(award["id"], GA), 200)
        assert aging["current_cents"] == 0
        assert aging["d61_90_cents"] == 425_000     # 61 days outstanding
        assert aging["total_accrued_interest_cents"] == 116
        assert aging["total_outstanding_cents"] == 425_116


class TestTransferApproveGatedByTargetAwardFrozen:
    """Difficulty instance: the TARGET award's FROZEN posture gates transfer
    approval."""

    def _setup(self, api):
        (_sp, _pi, a1, l1, a2, l2, e) = setup_transfer_pair(
            source_number="A1-777", target_number="A2-777",
            source_travel=200_000, target_travel=200_000,
            source_obligated=300_000, target_obligated=300_000)
        get_success_data(api.create_report_requirement(
            create_report_requirement_payload(
                a2["id"], report_type="FINAL_TECHNICAL",
                due_date="2026-08-10T00:00:00Z"), SPO))
        tr = create_submitted_transfer(e, a2, l2)
        return a2, l2, tr

    def test_target_frozen_blocks_approval(self, api):
        """PRD §3.3: "The target award must have posture other than
        `FROZEN` (`ERR_AWARD_FROZEN`) and `status` either `ACTIVE` or
        `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_ACTIVE`), and the target line must
        fit — its `spent_cents` plus the transferred amount must not exceed
        `authorized_cents` (`ERR_BUDGET_LINE_EXCEEDED`)."

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_gated_by_target_award_frozen
        """
        a2, l2, tr = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, ADMIN))
        a2_after = validate_success(api.get_award(a2["id"], GA), 200)
        assert a2_after["posture"] == "FROZEN"
        res = api.approve_cost_transfer(tr["id"], GA9)
        validate_error(res, ApiErrorId.ERR_AWARD_FROZEN.value)

    def test_failed_approval_leaves_transfer_submitted(self, api):
        """PRD §3.3: "Approval enforces segregation of duties: the
        approving accountant's `X-User-ID` must differ from
        `submitted_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403)."
        PRD §3.3: "The target award must have posture other than `FROZEN`
        (`ERR_AWARD_FROZEN`) and `status` either `ACTIVE` or
        `CLOSEOUT_PENDING` (`ERR_AWARD_NOT_ACTIVE`), and the target line must
        fit — its `spent_cents` plus the transferred amount must not exceed
        `authorized_cents` (`ERR_BUDGET_LINE_EXCEEDED`)." A rejected approval
        applies no transition.

        Design: Difficulty/cross_entity_state_dependency/transfer_approve_gated_by_target_award_frozen
        """
        a2, l2, tr = self._setup(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, ADMIN))
        api.approve_cost_transfer(tr["id"], GA9)
        tr_after = validate_success(api.get_cost_transfer(tr["id"], GA), 200)
        assert tr_after["status"] == "SUBMITTED"
