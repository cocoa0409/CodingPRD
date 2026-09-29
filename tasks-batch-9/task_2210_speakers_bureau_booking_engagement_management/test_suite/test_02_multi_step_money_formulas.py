"""Money formulas whose intermediate rounding and ordering are observable.

Each of these amounts can only be produced by combining several rules in the
one order the specification pins: surcharge rounded per line, the goodwill
rebate keyed on the gross retention while the commission is taken on the net,
and a travel ceiling built from a maximum nested inside a minimum.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    assert_client_balance,
    assert_invoice_totals_consistent,
    assert_remittance_nets_out,
    expected_surcharge_cents,
    find_remittances_for,
    read_engagement,
    read_travel_expense,
    round_half_up,
    setup_cancelled_engagement,
    setup_contracted_engagement,
    setup_delivered_engagement_with_travel,
    travel_expense_payload,
    validate_success,
)

BUY_OUT_CONTRACT = {
    "travel_policy_code": "POLICY_A",
    "recording_rights": "FULL_BUY_OUT",
    "recording_fee_cents": 350_000,
    "technical_rider_code": "STAGE_PLUS",
}
ALLOWANCE_OPTION = {"travel_allowance_cents": 70_000}


class TestPerLineSurcharge:
    def test_surcharge_is_the_sum_of_three_separately_rounded_line_products(
        self, api
    ):
        """Three lines whose fractional cents recombine across the half-cent boundary prove the per-line rounding.

        PRD: The processing surcharge is then computed at a rate of 1.75 percent — that is, 0.0175 — and the **order of operations is normative**: the server multiplies each of the three lines by the surcharge rate separately, rounds each of those three products half up to a whole number of cents, and only then adds the three rounded parts together to obtain `surcharge_cents`.
        Design: Difficulty/combinatorial_formula/combinatorial_surcharge_rounds_each_invoice_line_before_summing
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=BUY_OUT_CONTRACT,
            option_overrides=ALLOWANCE_OPTION,
        )
        invoice = bundle["invoice"]

        assert invoice["fee_line_cents"] == 1_275_000
        assert invoice["recording_line_cents"] == 350_000
        assert invoice["travel_line_cents"] == 63_750
        assert invoice["surcharge_cents"] == 29_554
        assert invoice["surcharge_cents"] == 22_313 + 6_125 + 1_116
        assert_invoice_totals_consistent(invoice)

    def test_summing_the_lines_before_rounding_would_understate_the_surcharge(
        self, api
    ):
        """The single-product shortcut yields 29553 for the same three lines, so the invoice must not report it.

        PRD: Summing the three lines first and rounding a single product would yield a different `surcharge_cents` for the same engagement whenever the discarded fractions of the individual lines re-combine across the half-cent boundary, and is wrong.
        Design: Difficulty/combinatorial_formula/combinatorial_surcharge_rounds_each_invoice_line_before_summing
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=BUY_OUT_CONTRACT,
            option_overrides=ALLOWANCE_OPTION,
        )
        invoice = bundle["invoice"]
        lines = (
            invoice["fee_line_cents"],
            invoice["recording_line_cents"],
            invoice["travel_line_cents"],
        )

        assert invoice["surcharge_cents"] == expected_surcharge_cents(*lines)
        assert invoice["surcharge_cents"] != round_half_up(sum(lines) * 0.0175)
        assert round_half_up(sum(lines) * 0.0175) == 29_553

    def test_amount_due_adds_the_per_line_surcharge_to_the_three_lines(self, api):
        """The issued total is the three lines plus the per-line surcharge, with nothing collected yet.

        PRD: `amount_due_cents` is then the sum of `fee_line_cents`, `recording_line_cents`, `travel_line_cents` and `surcharge_cents`; `amount_paid_cents` starts at 0.
        Design: Difficulty/combinatorial_formula/combinatorial_surcharge_rounds_each_invoice_line_before_summing
        """
        bundle = setup_delivered_engagement_with_travel(
            api,
            contract_overrides=BUY_OUT_CONTRACT,
            option_overrides=ALLOWANCE_OPTION,
        )
        invoice = bundle["invoice"]

        assert invoice["kind"] == "ENGAGEMENT_FEE"
        assert invoice["status"] == "ISSUED"
        assert invoice["amount_due_cents"] == 1_718_304
        assert invoice["amount_paid_cents"] == 0
        assert read_travel_expense(api, bundle["travel_expense"]["id"])[
            "reimbursable_cents"
        ] == 63_750


class TestCancellationRebateThenCommission:
    def test_rebate_band_is_keyed_on_the_gross_retention_before_the_net_is_taken(
        self, api
    ):
        """A cancellation twenty days out retains half the fee, and the rebate band reads that gross figure.

        PRD: A goodwill rebate percentage is keyed on the **gross** retention of step 3, not on any later figure: a gross retention of 5,000 dollars or more (500,000 cents or more) earns a rebate of 0.10; a gross retention from 2,000 dollars up to but not including 5,000 dollars (200,000 through 499,999 cents inclusive) earns 0.05; anything below 2,000 dollars (under 200,000 cents) earns nothing, 0.00.
        Design: Difficulty/combinatorial_formula/combinatorial_cancellation_rebate_precedes_commission_on_net
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        engagement = bundle["engagement"]

        assert engagement["cancellation_days_before"] == 20
        assert engagement["cancelled_by"] == "CLIENT"
        gross_retention = round_half_up(1_275_000 * 0.50)
        assert gross_retention == 637_500
        rebate = round_half_up(gross_retention * 0.10)
        assert rebate == 63_750
        assert engagement["retention_net_cents"] == 573_750
        assert engagement["retention_net_cents"] == gross_retention - rebate

    def test_commission_is_taken_on_the_net_retention_never_on_the_gross(self, api):
        """The withheld commission is 143438 on the net figure rather than 159375 on the gross one.

        PRD: `retention_commission_cents` is `retention_net_cents` multiplied by `commission_pct_snapshot`, rounded half up — the bureau commissions the **net** retention, never the gross.
        Design: Difficulty/combinatorial_formula/combinatorial_cancellation_rebate_precedes_commission_on_net
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        engagement = bundle["engagement"]

        assert engagement["retention_commission_cents"] == 143_438
        assert engagement["retention_commission_cents"] == round_half_up(573_750 * 0.25)
        assert engagement["retention_commission_cents"] != round_half_up(
            637_500 * 0.25
        )
        assert round_half_up(637_500 * 0.25) == 159_375

    def test_the_retention_invoice_and_remittance_both_carry_the_pinned_figures(
        self, api
    ):
        """One cancellation produces a retention invoice with no recording line and a matching pending remittance.

        PRD: When `retention_net_cents` plus the engagement's `travel_reimbursable_cents` is greater than 0, an `Invoice` is issued with `kind` `CANCELLATION_RETENTION` and `status` `ISSUED`, and its line composition differs from a fee invoice: `fee_line_cents` is `retention_net_cents`, `recording_line_cents` is always 0 on a retention invoice, and `travel_line_cents` is again the engagement's `travel_reimbursable_cents`.
        Design: Difficulty/combinatorial_formula/combinatorial_cancellation_rebate_precedes_commission_on_net
        """
        bundle = setup_cancelled_engagement(
            api, cancellation_clock_utc="2026-09-25T16:00:00Z"
        )
        engagement = bundle["engagement"]
        assert engagement["booking_status"] == "CANCELLED_BY_CLIENT"
        assert engagement["settlement_status"] == "INVOICED"

        invoice = bundle["retention_invoice"]
        assert invoice is not None
        assert invoice["kind"] == "CANCELLATION_RETENTION"
        assert invoice["status"] == "ISSUED"
        assert invoice["fee_line_cents"] == 573_750
        assert invoice["recording_line_cents"] == 0
        assert invoice["travel_line_cents"] == 0
        assert invoice["surcharge_cents"] == 10_041
        assert invoice["amount_due_cents"] == 583_791
        assert_invoice_totals_consistent(invoice)
        assert_client_balance(bundle["client"], 583_791)

        remittances = find_remittances_for(api, engagement["id"])
        assert len(remittances) == 1
        remittance = remittances[0]
        assert remittance["gross_fee_cents"] == 573_750
        assert remittance["commission_cents"] == 143_438
        assert remittance["travel_passthrough_cents"] == 0
        assert remittance["net_payable_cents"] == 430_312
        assert_remittance_nets_out(remittance)


class TestTravelAllowanceFloorUnderScheduleCeiling:
    def _submit_and_approve(self, api, bundle, **overrides):
        expense = validate_success(
            api.create_travel_expense(
                bundle["engagement"]["id"],
                travel_expense_payload(**overrides),
                bundle["speaker_headers"],
            ),
            expected_status=201,
        )
        validate_success(api.approve_travel_expense(expense["id"], AGENT_HEADERS))
        return read_travel_expense(api, expense["id"])

    def test_a_generous_allowance_lifts_a_stingy_schedule_amount(self, api):
        """A local one-day trip whose schedule amount falls below the negotiated allowance is capped at the allowance.

        PRD: Under this policy the negotiated allowance therefore acts as a floor beneath the ceiling — a generous allowance is honoured even when the mileage schedule is stingy — while the receipts always cap the payout.
        Design: Difficulty/combinatorial_formula/combinatorial_travel_allowance_acts_as_floor_under_schedule_cap
        """
        bundle = setup_contracted_engagement(
            api,
            contract_overrides={"travel_policy_code": "POLICY_A"},
            option_overrides={"travel_allowance_cents": 20_000},
        )
        expense = self._submit_and_approve(
            api,
            bundle,
            receipts_cents=30_000,
            travel_days=1,
            distance_band="LOCAL",
        )

        schedule = round_half_up(15_000 * 1 * 1.25)
        assert schedule == 18_750
        assert expense["status"] == "APPROVED"
        assert expense["reimbursable_cents"] == 20_000
        assert expense["reimbursable_cents"] == min(30_000, max(20_000, schedule))

    def test_a_larger_schedule_amount_overtakes_the_allowance_and_the_receipts_cap(
        self, api
    ):
        """A three-day regional trip is capped by the schedule amount, and the two approvals accumulate on the engagement.

        PRD: The ceiling is then the **greater** of the engagement's `travel_allowance_cents` and that rounded schedule amount, and `reimbursable_cents` is the **lesser** of `receipts_cents` and that ceiling.
        Design: Difficulty/combinatorial_formula/combinatorial_travel_allowance_acts_as_floor_under_schedule_cap
        """
        bundle = setup_contracted_engagement(
            api,
            contract_overrides={"travel_policy_code": "POLICY_A"},
            option_overrides={"travel_allowance_cents": 20_000},
        )
        first = self._submit_and_approve(
            api,
            bundle,
            receipts_cents=30_000,
            travel_days=1,
            distance_band="LOCAL",
        )
        second = self._submit_and_approve(
            api,
            bundle,
            receipts_cents=200_000,
            travel_days=3,
            distance_band="REGIONAL",
        )

        schedule = round_half_up(45_000 * 3 * 1.25)
        assert schedule == 168_750
        assert second["status"] == "APPROVED"
        assert second["reimbursable_cents"] == 168_750
        assert second["reimbursable_cents"] == min(200_000, max(20_000, schedule))
        assert first["reimbursable_cents"] == 20_000

    def test_each_receipt_is_capped_on_its_own_terms_and_the_total_accumulates(
        self, api
    ):
        """Two receipts capped differently sum to 188750 on the engagement's running travel total.

        PRD: Because each approval adds its own `reimbursable_cents` to the engagement's running `travel_reimbursable_cents`, several approved receipts on one engagement accumulate.
        Design: Difficulty/combinatorial_formula/combinatorial_travel_allowance_acts_as_floor_under_schedule_cap
        """
        bundle = setup_contracted_engagement(
            api,
            contract_overrides={"travel_policy_code": "POLICY_A"},
            option_overrides={"travel_allowance_cents": 20_000},
        )
        self._submit_and_approve(
            api, bundle, receipts_cents=30_000, travel_days=1, distance_band="LOCAL"
        )
        self._submit_and_approve(
            api,
            bundle,
            receipts_cents=200_000,
            travel_days=3,
            distance_band="REGIONAL",
        )

        engagement = read_engagement(api, bundle["engagement"]["id"], ADMIN_HEADERS)
        assert engagement["travel_reimbursable_cents"] == 188_750
        assert engagement["travel_reimbursable_cents"] == 20_000 + 168_750
        assert engagement["travel_allowance_cents"] == 20_000
