"""Transfers and gifts, termination settlement, basis relief, fee waiver."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_shares_equal,
    create_active_enrollment,
    create_active_plan,
    create_transfer,
    create_transfer_ok,
    deposit_shares,
    execute_transfer,
    get_enrollment,
    get_tax_report,
    is_iso8601_timestamp,
    list_fees,
    list_ledger_entries,
    list_tax_lots,
    register_participant,
    setup_active_enrollment,
    terminate_enrollment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_two_enrollment_transfer():
    """ACTIVE FIFO plan with two ACTIVE enrollments: e1 holding 20.0000 @1000,
    e2 holding 5.0000 @1000, plus a SUBMITTED TRANSFER of 7.5000 from e1 to e2.
    """
    plan = create_active_plan(issuer_name="Xfer Corp", ticker="XFR",
                              name="XFR DRIP")
    p1 = register_participant("Pat 1", "p1@x.com")
    e1 = create_active_enrollment(plan["id"], p1["id"])
    deposit_shares(e1["id"], 20.0, 1000)
    p2 = register_participant("Pat 2", "p2@x.com")
    e2 = create_active_enrollment(plan["id"], p2["id"])
    deposit_shares(e2["id"], 5.0, 1000)
    instruction = create_transfer_ok(
        e1["id"], p1["id"], transfer_type="TRANSFER", quantity=7.5,
        recipient_enrollment_id=e2["id"])
    return plan, p1, p2, e1, e2, instruction


def _setup_gift_scenario(basis_method="FIFO", email="pq@x.com",
                         issuer="Base Corp", ticker="BAS"):
    """ACTIVE plan with one ACTIVE enrollment holding lots 10.0000 @1000 and
    10.0000 @2000, plus a SUBMITTED GIFT of 4.0000 shares."""
    plan = create_active_plan(issuer_name=issuer, ticker=ticker,
                              name=f"{ticker} DRIP", basis_method=basis_method)
    participant = register_participant("Pat Q", email)
    enrollment = create_active_enrollment(plan["id"], participant["id"])
    deposit_shares(enrollment["id"], 10.0, 1000)
    deposit_shares(enrollment["id"], 10.0, 2000)
    instruction = create_transfer_ok(
        enrollment["id"], participant["id"], transfer_type="GIFT", quantity=4.0,
        recipient_name="Niece Q", recipient_address="2 Way")
    return plan, participant, enrollment, instruction


class TestTransferConservesShareSupply:
    def test_transfer_conserves_plan_share_supply_balances(self, api):
        """PRD §3.8: "A `TRANSFER_OUT` ledger entry is written on the source
        enrollment — negative `quantity`, `price_cents` set to the fair market
        value, `TRANSFER` provenance naming the instruction."
        PRD §3.8: "For `TRANSFER`, a `TRANSFER_IN` ledger entry with the
        positive quantity is written on the recipient enrollment"
        PRD §2.9: "An enrollment's `share_balance` is a derived figure: the sum
        of `quantity` over every ledger entry of the enrollment, kept at four
        decimal places."
        PRD §3.8: "Finally, a fee assessment of type `TRANSFER` with `TRANSFER`
        provenance is created on the source enrollment with `computed_cents`
        equal to the plan's `transfer_fee_cents`, waivable only
        administratively."

        Design: Difficulty/compensating_invariant/transfer_conserves_plan_share_supply
        """
        plan, p1, p2, e1, e2, instruction = _setup_two_enrollment_transfer()
        execute_transfer(instruction["id"], 2500)

        assert_shares_equal(get_enrollment(e1["id"])["share_balance"], "12.5000")
        assert_shares_equal(get_enrollment(e2["id"])["share_balance"], "12.5000")
        # Plan share supply invariant: 20.0000 + 5.0000 == 12.5000 + 12.5000.
        source_entries = list_ledger_entries(e1["id"])
        recipient_entries = list_ledger_entries(e2["id"])
        total = sum(float(str(e["quantity"])) for e in
                    source_entries + recipient_entries)
        assert_shares_equal(total, "25.0000",
                            "the plan-level share supply is unchanged")

        fees = list_fees(e1["id"], fee_type="TRANSFER")
        assert len(fees) == 1
        assert fees[0]["computed_cents"] == 300

    def test_transfer_creates_carryover_tax_lot(self, api):
        """PRD §3.8: "For `TRANSFER`, a `TRANSFER_IN` ledger entry with the
        positive quantity is written on the recipient enrollment, and a
        `TRANSFER_IN` tax lot is created carrying over the per-share basis that
        relief took from the source lots."
        PRD §2.9: "a `TRANSFER_IN` lot carries over the per-share basis relieved
        from the source enrollment's lots"

        Design: Difficulty/compensating_invariant/transfer_conserves_plan_share_supply
        """
        plan, p1, p2, e1, e2, instruction = _setup_two_enrollment_transfer()
        execute_transfer(instruction["id"], 2500)

        out_entries = [e for e in list_ledger_entries(e1["id"])
                       if e["entry_type"] == "TRANSFER_OUT"]
        in_entries = [e for e in list_ledger_entries(e2["id"])
                      if e["entry_type"] == "TRANSFER_IN"]
        assert len(out_entries) == 1 and len(in_entries) == 1
        assert_shares_equal(out_entries[0]["quantity"], "-7.5000")
        assert out_entries[0]["price_cents"] == 2500
        assert_shares_equal(in_entries[0]["quantity"], "7.5000")

        lots = [l for l in list_tax_lots(e2["id"])
                if l["acquisition_type"] == "TRANSFER_IN"]
        assert len(lots) == 1
        assert_shares_equal(lots[0]["quantity"], "7.5000")
        assert lots[0]["cost_per_share_cents"] == 1000, (
            "FIFO relief took from the 1000-cent lot, and that basis carries "
            "over to the recipient's TRANSFER_IN lot")


class TestDispositionConservesCostBasis:
    def test_disposition_conserves_cost_basis_remaining(self, api):
        """PRD §2.9: "An enrollment's `total_cost_basis_cents` is the sum over
        its tax lots of each lot's `remaining_quantity` multiplied by its
        `cost_per_share_cents`, rounded to whole cents, with any rounding
        remainder reconciled on the last lot so the total stays consistent."
        PRD §3.9: "Under `FIFO`, lots are relieved oldest first, ordered by
        `acquired_at` ascending with ties broken by creation timestamp
        ascending; relief takes from each lot the lesser of what is still
        needed and that lot's `remaining_quantity`, continuing until the
        disposed quantity is covered."

        Design: Difficulty/compensating_invariant/disposition_conserves_cost_basis
        """
        plan, participant, enrollment, instruction = _setup_gift_scenario()
        execute_transfer(instruction["id"], 2500)
        fetched = get_enrollment(enrollment["id"])
        assert fetched["total_cost_basis_cents"] == 26000, (
            "FIFO relieves 4.0000 shares from the 1000-cent lot: "
            "6*1000 + 10*2000 == 26000 of the original 30000 remain")
        assert_shares_equal(fetched["share_balance"], "16.0000")

    def test_disposition_conserves_cost_basis_report(self, api):
        """PRD §3.9: "The annual tax report assembles these figures for a
        requested `year`, returning that `year`, the `dividends_cents` declared
        for the year, and the year's disposition totals — `proceeds_cents`,
        `basis_cents`, and `gain_cents` — computed under the plan's basis
        method, plus the `basis_method` in force."
        PRD §3.9: "Each disposition's gain is its proceeds minus the basis
        relieved: proceeds are the disposed quantity times the applicable
        per-share price — the fair market value at transfer execution or the
        sale price at termination — rounded half-up to whole cents, and the
        relieved basis comes from the relief rules above."

        Design: Difficulty/compensating_invariant/disposition_conserves_cost_basis
        """
        plan, participant, enrollment, instruction = _setup_gift_scenario()
        execute_transfer(instruction["id"], 2500)
        report = get_tax_report(enrollment["id"], 2026)
        assert report["proceeds_cents"] == 10000, "4.0000 shares at fmv 2500"
        assert report["basis_cents"] == 4000, "FIFO relief of 4.0000 @ 1000"
        assert report["gain_cents"] == 6000
        # Conservation identity: remaining basis + realized basis == original.
        remaining = get_enrollment(enrollment["id"])["total_cost_basis_cents"]
        assert remaining + report["basis_cents"] == 30000


class TestBasisMethodVariants:
    def test_fifo_report_values(self, api):
        """PRD §3.9: "Under `FIFO`, lots are relieved oldest first, ordered by
        `acquired_at` ascending with ties broken by creation timestamp
        ascending; relief takes from each lot the lesser of what is still
        needed and that lot's `remaining_quantity`, continuing until the
        disposed quantity is covered."
        PRD §3.9: "The basis leaving the enrollment is the sum over the touched
        lots of each taken quantity times that lot's `cost_per_share_cents`,
        rounded half-up to whole cents"

        Design: Difficulty/dual_variant_calc/disposition_basis_fifo_vs_average_cost
        """
        plan, _p, enrollment, instruction = _setup_gift_scenario(
            basis_method="FIFO", email="pf@x.com", issuer="Fifo Corp",
            ticker="FIFO")
        execute_transfer(instruction["id"], 2500)
        report = get_tax_report(enrollment["id"], 2026)
        assert report["basis_method"] == "FIFO"
        assert report["proceeds_cents"] == 10000
        assert report["basis_cents"] == 4000, \
            "FIFO relieves the oldest lot first: 4.0000 @ 1000"
        assert report["gain_cents"] == 6000

    def test_average_cost_report_values_and_divergence(self, api):
        """PRD §3.9: "Under `AVERAGE_COST`, a single weighted-average cost is
        computed once, before any relief, across all lots with shares
        remaining: the sum over those lots of `remaining_quantity` times
        `cost_per_share_cents`, divided by the total remaining quantity,
        rounded half-up to whole cents."
        PRD §3.9: "Identical lots and an identical disposed quantity yield a
        different relieved basis, and therefore a different reported gain,
        under the two methods."

        Design: Difficulty/dual_variant_calc/disposition_basis_fifo_vs_average_cost
        """
        _plan_f, _pf, e_fifo, t_fifo = _setup_gift_scenario(
            basis_method="FIFO", email="pf@x.com", issuer="Fifo Corp",
            ticker="FIFO")
        _plan_a, _pa, e_avg, t_avg = _setup_gift_scenario(
            basis_method="AVERAGE_COST", email="pg@x.com", issuer="Avg Corp",
            ticker="AVG")
        execute_transfer(t_fifo["id"], 2500)
        execute_transfer(t_avg["id"], 2500)

        report_avg = get_tax_report(e_avg["id"], 2026)
        assert report_avg["basis_method"] == "AVERAGE_COST"
        assert report_avg["proceeds_cents"] == 10000
        assert report_avg["basis_cents"] == 6000, (
            "weighted average (10*1000 + 10*2000) / 20 == 1500; "
            "4.0000 * 1500 == 6000")
        assert report_avg["gain_cents"] == 4000

        report_fifo = get_tax_report(e_fifo["id"], 2026)
        assert report_fifo["gain_cents"] != report_avg["gain_cents"], \
            "identical lots, quantity, and fmv must diverge by basis method"


class TestTerminationCascade:
    def test_termination_writes_fractional_sale_and_withdrawal(self, api):
        """PRD §3.9: "When the fractional part is greater than zero, the gross
        proceeds are the fractional shares times `sale_price_cents`, rounded
        half-up to whole cents first; the sale fee is the plan's
        `sale_fee_cents`, recorded as a `SALE` assessment with `TERMINATION`
        provenance and waivable only administratively; and the net proceeds are
        the rounded gross minus the fee."
        PRD §3.9: "A `FRACTIONAL_SALE` ledger entry records the movement —
        negative fractional quantity, `price_cents` set to the sale price,
        `cash_cents` set to the net proceeds, `TERMINATION` provenance."
        PRD §3.9: "Whenever the whole-share part is greater than zero, a
        `WHOLE_SHARE_WITHDRAWAL` entry is written with the negative whole
        quantity and null `price_cents` and `cash_cents`."

        Design: Difficulty/transitive_cascade/enrollment_terminate_cascades_sale_lots_fee
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Term Corp", "ticker": "TRM",
                            "name": "TRM DRIP"},
            participant_email="pt@x.com")
        deposit_shares(enrollment["id"], 10.5, 1000)
        resp = terminate_enrollment(enrollment["id"], participant["id"], 2000)
        terminated = validate_success(resp)
        assert terminated["status"] == "TERMINATED"
        assert_shares_equal(terminated["share_balance"], "0.0000")

        entries = list_ledger_entries(enrollment["id"])
        sales = [e for e in entries if e["entry_type"] == "FRACTIONAL_SALE"]
        withdrawals = [e for e in entries
                       if e["entry_type"] == "WHOLE_SHARE_WITHDRAWAL"]
        assert len(sales) == 1 and len(withdrawals) == 1
        assert_shares_equal(sales[0]["quantity"], "-0.5000")
        assert sales[0]["price_cents"] == 2000
        assert sales[0]["cash_cents"] == 750, \
            "gross 1000 (0.5000 * 2000) minus the 250 sale fee"
        assert_shares_equal(withdrawals[0]["quantity"], "-10.0000")
        assert withdrawals[0]["price_cents"] is None
        assert withdrawals[0]["cash_cents"] is None

    def test_termination_assesses_sale_fee_and_relieves_lots(self, api):
        """PRD §3.9: "the sale fee is the plan's `sale_fee_cents`, recorded as
        a `SALE` assessment with `TERMINATION` provenance and waivable only
        administratively"
        PRD §3.9: "All of the enrollment's tax lots are then relieved in full
        for the disposed quantity, leaving every lot's `remaining_quantity` at
        0, and the enrollment's `terminated_at` is stamped and its `version`
        incremented."

        Design: Difficulty/transitive_cascade/enrollment_terminate_cascades_sale_lots_fee
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Term Corp", "ticker": "TRM",
                            "name": "TRM DRIP"},
            participant_email="pt@x.com")
        deposit_shares(enrollment["id"], 10.5, 1000)
        validate_success(
            terminate_enrollment(enrollment["id"], participant["id"], 2000))

        sale_fees = list_fees(enrollment["id"], fee_type="SALE")
        assert len(sale_fees) == 1
        assert sale_fees[0]["computed_cents"] == 250
        assert sale_fees[0]["charged_cents"] == 250

        lots = list_tax_lots(enrollment["id"])
        assert len(lots) == 1
        assert_shares_equal(lots[0]["remaining_quantity"], "0.0000")

        terminated = get_enrollment(enrollment["id"])
        assert is_iso8601_timestamp(terminated["terminated_at"]), \
            "termination stamps terminated_at"


class TestTerminationZeroFractionalBoundary:
    def test_termination_zero_fractional_skips_sale_entries(self, api):
        """PRD §3.9: "The boundary is exact: when the fractional part is
        exactly 0.0000, no fractional-sale entry is created and no sale fee is
        assessed at all."
        PRD §3.9: "Whenever the whole-share part is greater than zero, a
        `WHOLE_SHARE_WITHDRAWAL` entry is written with the negative whole
        quantity and null `price_cents` and `cash_cents`."

        Design: Difficulty/boundary_precision_check/termination_zero_fractional_skips_sale
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Zero Corp", "ticker": "ZRO",
                            "name": "ZRO DRIP"},
            participant_email="pz@x.com")
        deposit_shares(enrollment["id"], 10.0, 1000)
        validate_success(
            terminate_enrollment(enrollment["id"], participant["id"], 2000))

        entries = list_ledger_entries(enrollment["id"])
        withdrawals = [e for e in entries
                       if e["entry_type"] == "WHOLE_SHARE_WITHDRAWAL"]
        assert len(withdrawals) == 1
        assert_shares_equal(withdrawals[0]["quantity"], "-10.0000")
        assert [e for e in entries if e["entry_type"] == "FRACTIONAL_SALE"] == [], \
            "a 0.0000 fractional part creates no fractional-sale entry"
        assert list_fees(enrollment["id"], fee_type="SALE") == [], \
            "and no sale fee is assessed at the boundary"

    def test_termination_zero_fractional_final_state(self, api):
        """PRD §3.9: "The boundary is exact: when the fractional part is
        exactly 0.0000, no fractional-sale entry is created and no sale fee is
        assessed at all."
        PRD §3.9: "All of the enrollment's tax lots are then relieved in full
        for the disposed quantity, leaving every lot's `remaining_quantity` at
        0, and the enrollment's `terminated_at` is stamped and its `version`
        incremented."

        Design: Difficulty/boundary_precision_check/termination_zero_fractional_skips_sale
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Zero Corp", "ticker": "ZRO",
                            "name": "ZRO DRIP"},
            participant_email="pz@x.com")
        deposit_shares(enrollment["id"], 10.0, 1000)
        terminated = validate_success(
            terminate_enrollment(enrollment["id"], participant["id"], 2000))
        assert terminated["status"] == "TERMINATED"
        assert_shares_equal(terminated["share_balance"], "0.0000")
        assert is_iso8601_timestamp(terminated["terminated_at"])
        for lot in list_tax_lots(enrollment["id"]):
            assert_shares_equal(lot["remaining_quantity"], "0.0000")


class TestGiftExecution:
    def test_gift_execute_creates_only_source_movement(self, api):
        """PRD §3.8: "A `TRANSFER_OUT` ledger entry is written on the source
        enrollment — negative `quantity`, `price_cents` set to the fair market
        value, `TRANSFER` provenance naming the instruction."
        PRD §3.8: "For `GIFT`, no recipient entry exists and the disposition is
        reported at `fmv_per_share_cents`."
        PRD §3.8: "Finally, a fee assessment of type `TRANSFER` with `TRANSFER`
        provenance is created on the source enrollment with `computed_cents`
        equal to the plan's `transfer_fee_cents`, waivable only
        administratively."

        Design: Corner/state_machines/gift_execute_creates_only_source_movement
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Gift Corp", "ticker": "GFT",
                            "name": "GFT DRIP"},
            participant_email="pgf@x.com")
        deposit_shares(enrollment["id"], 10.0, 1000)
        instruction = create_transfer_ok(
            enrollment["id"], participant["id"], transfer_type="GIFT",
            quantity=3.0, recipient_name="Niece G", recipient_address="3 Way")
        executed = execute_transfer(instruction["id"], 2000)
        assert executed["status"] == "EXECUTED"
        assert executed["fmv_per_share_cents"] == 2000

        entries = list_ledger_entries(enrollment["id"])
        out_entries = [e for e in entries if e["entry_type"] == "TRANSFER_OUT"]
        assert len(out_entries) == 1
        assert_shares_equal(out_entries[0]["quantity"], "-3.0000")
        assert out_entries[0]["price_cents"] == 2000
        assert [e for e in entries if e["entry_type"] == "TRANSFER_IN"] == [], \
            "a gift writes no TRANSFER_IN entry anywhere in the plan"
        assert_shares_equal(get_enrollment(enrollment["id"])["share_balance"],
                            "7.0000")

        fees = list_fees(enrollment["id"], fee_type="TRANSFER")
        assert len(fees) == 1
        assert fees[0]["computed_cents"] == 300


class TestTransferCreationValidation:
    def test_transfer_insufficient_shares_rejected(self, api):
        """PRD §3.8: "Two checks guard creation: the quantity must not exceed
        the source enrollment's `share_balance`, else `ERR_INSUFFICIENT_SHARES`
        (HTTP 422)"

        Design: Corner/validations/transfer_insufficient_shares_rejected
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Ins Corp", "ticker": "INS",
                            "name": "INS DRIP"},
            participant_email="pin@x.com")
        deposit_shares(enrollment["id"], 10.0, 1000)
        resp = create_transfer(
            enrollment["id"], participant["id"], transfer_type="GIFT",
            quantity=99.0, recipient_name="Niece I", recipient_address="4 Way")
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SHARES)

    def test_transfer_recipient_not_enrolled_rejected(self, api):
        """PRD §3.8: "and a `TRANSFER`'s recipient enrollment must exist,
        belong to the same plan, and be `ACTIVE`, else
        `ERR_RECIPIENT_NOT_ENROLLED` (HTTP 422)."

        Design: Corner/validations/transfer_recipient_not_enrolled_rejected
        """
        plan_a = create_active_plan(issuer_name="Ra Corp", ticker="RA",
                                    name="RA DRIP")
        plan_b = create_active_plan(issuer_name="Rb Corp", ticker="RB",
                                    name="RB DRIP")
        p_a = register_participant("Pat Ra", "pra@x.com")
        e_a = create_active_enrollment(plan_a["id"], p_a["id"])
        deposit_shares(e_a["id"], 10.0, 1000)
        p_b = register_participant("Pat Rb", "prb@x.com")
        e_b = create_active_enrollment(plan_b["id"], p_b["id"])
        resp = create_transfer(
            e_a["id"], p_a["id"], transfer_type="TRANSFER", quantity=2.0,
            recipient_enrollment_id=e_b["id"])
        # The recipient enrollment belongs to a different plan.
        validate_error(resp, ApiErrorId.ERR_RECIPIENT_NOT_ENROLLED)


class TestAdministrativeFeeWaiver:
    def test_admin_waive_fee_zeroes_charge(self, api):
        """PRD §3.6: "Waiving sets `waived` to true, copies the supplied reason
        into `waived_reason`, zeroes `charged_cents`, and increments the
        assessment's `version`."
        PRD §2.10: "the `computed_cents` produced by the applicable calculation
        before any waiver"

        Design: Corner/errors/admin_waive_fee_zeroes_charge
        """
        plan, participant, enrollment = setup_active_enrollment(
            plan_overrides={"issuer_name": "Wav Corp", "ticker": "WAV",
                            "name": "WAV DRIP"},
            election="CASH_ONLY", participant_email="pwv@x.com")
        fee = list_fees(enrollment["id"])[0]
        assert fee["fee_type"] == "ENROLLMENT"
        assert fee["charged_cents"] == 1000

        waived = validate_success(api.waive_fee(fee["id"], "goodwill", ADMIN))
        assert waived["waived"] is True
        assert waived["waived_reason"] == "goodwill"
        assert waived["charged_cents"] == 0
        assert waived["computed_cents"] == 1000, \
            "the computed fee stays on the assessment for audit"
