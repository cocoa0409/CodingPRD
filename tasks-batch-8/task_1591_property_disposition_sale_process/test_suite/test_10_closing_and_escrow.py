"""Closing: tiered commission variants and boundaries, proration day-count
conventions, the settlement waterfall evaluation order, closing gates, the
statement review loop, record-closing cascades, and the post-closing escrow."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    alpha_asset_payload,
    assert_escrow_partition_identity,
    assert_timestamp_prefix,
    create_approved_statement,
    create_asset_payload,
    create_confirmed_payoff,
    create_statement_payload,
    delta_asset_payload,
    edge_asset_payload,
    file_dd_item,
    gamma_asset_payload,
    get_asset,
    make_co_headers,
    pipeline_to_binding,
    pipeline_to_bid,
    pipeline_to_dd_active,
    pipeline_to_executed,
    pipeline_to_psa_draft,
    retail_pair_payload,
    set_clock,
    setup_closed_delta_deal,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
CO = TEST_USERS["co_headers"]


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------

def _alpha_retraded_deal(api):
    """Alpha pipeline: DD_ACTIVE at price 5,000,000,000, then two accepted
    retrades (60,000,000 and 200,000,000 capped to 98,800,000 by the per-item
    cap on the reduced price) leaving the price at 4,841,200,000. Returns
    (workspace, commission_provisional_cents as captured right after
    execution)."""
    ws = pipeline_to_dd_active(asset_payload=alpha_asset_payload())
    engagements = validate_success(
        api.list_asset_engagements(ws["asset"]["id"], DM))
    commission_at_execute = engagements[0]["commission_provisional_cents"]

    item1 = file_dd_item(ws["psa"]["id"], 60_000_000, ws["buyer_headers"],
                         category="PHYSICAL", description="roof")
    accepted1 = validate_success(api.respond_dd_item(item1["id"], "ACCEPT", DM))
    assert accepted1["accepted_reduction_cents"] == 60_000_000
    item2 = file_dd_item(ws["psa"]["id"], 200_000_000, ws["buyer_headers"],
                         category="FINANCIAL", description="cam audit")
    accepted2 = validate_success(api.respond_dd_item(item2["id"], "ACCEPT", DM))
    assert accepted2["accepted_reduction_cents"] == 98_800_000, \
        "per-item cap is 2% of the current 4,940,000,000 price"

    ws["psa"] = validate_success(api.get_psa(ws["psa"]["id"], DM))
    return ws, commission_at_execute


def _delta_executed(api):
    return pipeline_to_executed(
        asset_payload=delta_asset_payload(),
        analysis_overrides={"cap_rate_bps": 650, "exit_cap_rate_bps": 700,
                            "est_sale_price_cents": 1_900_000_000,
                            "est_selling_costs_cents": 50_000_000},
        proof_of_funds=500_000_000,
        price_cents=1_800_000_000,
        deposit_cents=54_000_000,
        dd_period_days=20,
        closing_date="2026-10-15T00:00:00Z",
    )


def _proration_statement(api, psa_id):
    payload = create_statement_payload(
        psa_id, property_tax_annual_cents=18_250_000,
        tax_period_start="2026-01-01T00:00:00Z",
        rent_monthly_cents=4_960_000, cam_annual_cents=7_300_000)
    return validate_success(api.create_statement(payload, CO), 201)


def _proration_pair(api):
    """Two identical unlevered retail assets through the bid pipeline to
    EXECUTED PSAs (closing 2026-10-15), one per proration convention, then a
    statement with identical proration inputs on each. Both pipelines advance
    past the offers deadline before either PSA is created so the shared
    logical clock never outruns an open round."""
    def bid_stage(name):
        return pipeline_to_bid(
            asset_payload=retail_pair_payload(name),
            analysis_overrides={"cap_rate_bps": 500,
                                "est_sale_price_cents": 2_100_000_000,
                                "est_selling_costs_cents": 0},
            proof_of_funds=600_000_000,
            price_cents=2_000_000_000,
            deposit_cents=60_000_000,
            dd_period_days=20,
        )

    ws1 = bid_stage("P1")
    ws2 = bid_stage("P2")
    ws1 = pipeline_to_psa_draft(ws1, convention="ACTUAL_365")
    ws2 = pipeline_to_psa_draft(ws2, convention="BANKERS_360")
    ws1 = pipeline_to_executed(ws1, closing_date="2026-10-15T00:00:00Z")
    ws2 = pipeline_to_executed(ws2, closing_date="2026-10-15T00:00:00Z")
    st1 = _proration_statement(api, ws1["psa"]["id"])
    st2 = _proration_statement(api, ws2["psa"]["id"])
    return st1, st2


def _delta_statement_after_retrade(api):
    """Delta pipeline: DD_ACTIVE at 1,800,000,000; one 20,000,000 retrade
    accepted (price 1,780,000,000); payoff CONFIRMED (total 833,833,333);
    statement created after both, while deposits remain frozen at the amounts
    scheduled on the original price."""
    ws = pipeline_to_dd_active(
        asset_payload=delta_asset_payload(),
        analysis_overrides={"cap_rate_bps": 650, "exit_cap_rate_bps": 700,
                            "est_sale_price_cents": 1_900_000_000,
                            "est_selling_costs_cents": 50_000_000},
        proof_of_funds=500_000_000,
        price_cents=1_800_000_000,
        deposit_cents=54_000_000,
        dd_period_days=20,
        closing_date="2026-10-15T00:00:00Z",
    )
    item = file_dd_item(ws["psa"]["id"], 20_000_000, ws["buyer_headers"],
                        category="PHYSICAL", description="dock doors")
    accepted = validate_success(api.respond_dd_item(item["id"], "ACCEPT", DM))
    assert accepted["accepted_reduction_cents"] == 20_000_000
    payoff = create_confirmed_payoff(ws["asset"]["id"])
    statement = _proration_statement(api, ws["psa"]["id"])
    return ws, payoff, statement


# ---------------------------------------------------------------------------
# Tiered commission variants
# ---------------------------------------------------------------------------

class TestCommissionProvisionalVsFinal:
    def test_commission_provisional_at_execute(self, api):
        """PRD: "`commission_provisional_cents` is computed on the agreement's
        price at execution, remains null until a purchase agreement is
        executed, and is recomputed on every accepted or rescinded retrade so
        it always tracks the live price."
        PRD: "The first 1,500,000,000 cents of price earn two hundred basis
        points; the next 1,500,000,000 cents — the second fifteen-million-dollar
        slice — earn one hundred fifty basis points; and everything above
        3,000,000,000 cents earns one hundred basis points."

        Design: Difficulty/dual_variant_calc/broker_commission_provisional_vs_final
        """
        ws, commission_at_execute = _alpha_retraded_deal(api)
        assert commission_at_execute == 72_500_000, \
            "tiered commission on the 5,000,000,000 execution price"
        assert ws["psa"]["price_cents"] == 4_841_200_000

        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 70_912_000, \
            "recomputed after the two retrades"

    def test_commission_final_and_closing_end_state(self, api):
        """PRD: "`commission_final_cents` is computed once, on the final price
        at closing, and remains null until then; when retrades moved the price
        between execution and closing, the final figure differs from the last
        provisional one."
        PRD: "A successful recording does everything at once, atomically: every
        `POSTED` deposit becomes `APPLIED`; the `APPROVED` statement becomes
        `FINALIZED`; an EscrowHoldback is auto-created in `HELD` status with
        `purpose` `INDEMNITY`, `amount_cents` equal to the statement's
        `holdback_cents`, and `release_date` exactly 365 days after
        `closing_date`; the asset's `deal_status` becomes `SOLD` with
        `final_sale_price_cents` recorded from the agreement's `price_cents`;
        and the `ACTIVE` BrokerEngagement becomes `COMPLETED` with
        `commission_final_cents` computed on that final price."

        Design: Difficulty/dual_variant_calc/broker_commission_provisional_vs_final
        """
        ws, commission_at_execute = _alpha_retraded_deal(api)
        assert commission_at_execute == 72_500_000

        payoff = create_confirmed_payoff(
            ws["asset"]["id"], reinvestment_rate_bps=400, accrued_days=12,
            anticipated_settlement_date="2026-10-30T00:00:00Z")
        statement = create_approved_statement(ws["psa"]["id"])

        set_clock("2026-10-17T00:00:00Z")
        validate_success(api.lapse_dd(ws["psa"]["id"], DM))
        validate_success(api.begin_closing(ws["psa"]["id"], DM))
        validate_success(api.settle_payoff(payoff["id"], CO))
        closed = validate_success(api.record_closing(ws["psa"]["id"], CO))
        assert closed["status"] == "CLOSED"

        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        engagement = engagements[0]
        assert engagement["status"] == "COMPLETED"
        assert engagement["commission_final_cents"] == 70_912_000
        assert engagement["commission_provisional_cents"] == 70_912_000
        assert engagement["commission_final_cents"] != commission_at_execute, \
            "retrades moved the price, so the final variant differs from the " \
            "at-execution provisional (72,500,000)"

        statements = validate_success(
            api.list_psa_statements(ws["psa"]["id"], DM))
        assert statements[0]["id"] == statement["id"]
        assert statements[0]["status"] == "FINALIZED"
        assert statements[0]["buyer_due_cents"] == 4_591_200_000
        assert statements[0]["seller_net_cents"] == 1_473_449_178

        escrows = validate_success(api.list_psa_escrows(ws["psa"]["id"], DM))
        assert len(escrows) == 1
        assert escrows[0]["amount_cents"] == 24_206_000, \
            "0.5% of the 4,841,200,000 closing price"
        assert escrows[0]["status"] == "HELD"

        deposits = validate_success(api.list_psa_deposits(ws["psa"]["id"], CO))
        assert [d["status"] for d in deposits] == ["APPLIED", "APPLIED"]

        asset = get_asset(ws["asset"]["id"])
        assert asset["deal_status"] == "SOLD"
        assert asset["final_sale_price_cents"] == 4_841_200_000


class TestTierStraddleAndFloor:
    def test_tiered_commission_straddle_delta(self, api):
        """PRD: "The first 1,500,000,000 cents of price earn two hundred basis
        points; the next 1,500,000,000 cents — the second fifteen-million-dollar
        slice — earn one hundred fifty basis points; and everything above
        3,000,000,000 cents earns one hundred basis points. Each tier's amount
        is rounded half up to whole cents individually, the three rounded tiers
        are summed"

        Design: Difficulty/combinatorial_formula/tiered_commission_straddle_and_floor
        """
        ws = _delta_executed(api)
        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 34_500_000, (
            "price 1,800,000,000 straddles tiers 1-2: 30,000,000 on the first "
            "1.5B slice + 4,500,000 on the next 0.3B; tier 3 zero")

    def test_tiered_commission_min_fee_floor(self, api):
        """PRD: "only then is a minimum-fee floor applied: if the summed
        commission is below 25,000,000 cents, it is raised to 25,000,000
        cents."

        Design: Difficulty/combinatorial_formula/tiered_commission_straddle_and_floor
        """
        ws = pipeline_to_executed(
            asset_payload=create_asset_payload(
                name="Floor", market="Tulsa", asset_type="RETAIL",
                noi_cents=60_000_000, noi_growth_bps=100,
                book_value_cents=800_000_000,
                guidance_price_cents=1_000_000_000),
            analysis_overrides={"cap_rate_bps": 500,
                                "est_sale_price_cents": 1_260_000_000,
                                "est_selling_costs_cents": 0},
            proof_of_funds=300_000_000,
            price_cents=1_000_000_000,
            deposit_cents=30_000_000,
            dd_period_days=20,
            closing_date="2026-10-15T00:00:00Z",
        )
        engagements = validate_success(
            api.list_asset_engagements(ws["asset"]["id"], DM))
        assert engagements[0]["commission_provisional_cents"] == 25_000_000, (
            "raw tiers give 20,000,000 on a 1,000,000,000 price; the floor "
            "applied after the tier sum lifts it to the 25,000,000 minimum")


class TestTierBoundary:
    def test_commission_tier_boundary_exact_15m(self, api):
        """PRD: "The first 1,500,000,000 cents of price earn two hundred basis
        points; the next 1,500,000,000 cents — the second fifteen-million-dollar
        slice — earn one hundred fifty basis points"
        PRD: "Each tier's amount is rounded half up to whole cents individually,
        the three rounded tiers are summed"

        Design: Corner/cross_cutting_layers/commission_tier_boundary_exact_15m
        """
        def bid_stage(name, price, deposit):
            return pipeline_to_bid(
                asset_payload=edge_asset_payload(name),
                analysis_overrides={"cap_rate_bps": 500,
                                    "est_sale_price_cents": 1_580_000_000,
                                    "est_selling_costs_cents": 0},
                proof_of_funds=400_000_000,
                price_cents=price,
                deposit_cents=deposit,
                dd_period_days=20,
            )

        # Both rounds are opened before the shared logical clock advances past
        # their common deadline.
        ws1 = bid_stage("Edge", 1_500_000_000, 45_000_000)
        ws2 = bid_stage("Edge2", 1_500_000_100, 45_000_003)
        ws1 = pipeline_to_executed(pipeline_to_psa_draft(ws1),
                                   closing_date="2026-10-15T00:00:00Z")
        ws2 = pipeline_to_executed(pipeline_to_psa_draft(ws2),
                                   closing_date="2026-10-15T00:00:00Z")

        engagements1 = validate_success(
            api.list_asset_engagements(ws1["asset"]["id"], DM))
        assert engagements1[0]["commission_provisional_cents"] == 30_000_000, \
            "price exactly 1,500,000,000 sits entirely within tier 1"
        engagements2 = validate_success(
            api.list_asset_engagements(ws2["asset"]["id"], DM))
        assert engagements2[0]["commission_provisional_cents"] == 30_000_002, (
            "100 cents spill into tier 2: round_half_up of 100 x 150bps = 2, "
            "summed with the tier-1 30,000,000")


# ---------------------------------------------------------------------------
# Proration conventions
# ---------------------------------------------------------------------------

class TestProrationConventions:
    def test_proration_actual_365_literals(self, api):
        """PRD: "Under `ACTUAL_365`, real calendar day counts and a 365-day year
        apply: the tax seller share counts calendar days from
        `tax_period_start` through the day before closing and is the annual tax
        times those days over 365; the rent buyer share counts calendar days
        from the closing date through the last day of the closing month and is
        the monthly rent times those days over the actual number of days in the
        closing month; the CAM buyer share takes the remaining days of the
        tax-year-aligned period — 365 minus the tax seller days — and is the
        annual CAM times those days over 365."
        PRD: "The statement copies its `convention` and `closing_date` from the
        agreement"

        Design: Difficulty/dual_variant_calc/proration_day_count_conventions_diverge
        """
        st1, _st2 = _proration_pair(api)
        assert st1["convention"] == "ACTUAL_365"
        # Tax: 287 actual days (Jan 1 .. Oct 14) x 18,250,000 / 365
        #     = 14,350,000; rent: 17 of 31 October days x 4,960,000 = 2,720,000.
        assert st1["proration_buyer_credit_cents"] == 17_070_000
        # CAM: (365 - 287) = 78 days x 7,300,000 / 365 = 1,560,000.
        assert st1["proration_buyer_debit_cents"] == 1_560_000

    def test_proration_bankers_360_diverges(self, api):
        """PRD: "Under `BANKERS_360`, every month has 30 days and the year 360:
        the tax seller share is thirty times the number of full months elapsed
        before the closing month plus the closing day minus one, times the
        annual tax over 360; the rent buyer share is thirty minus the closing
        day plus one, times the monthly rent over 30; and the CAM buyer share is
        360 minus the tax seller days, times the annual CAM over 360."
        PRD: "The two conventions produce different cents for identical inputs,
        so the convention copied from the agreement genuinely controls the
        money."

        Design: Difficulty/dual_variant_calc/proration_day_count_conventions_diverge
        """
        st1, st2 = _proration_pair(api)
        # Tax: (30 x 9 full months + 14) = 284 banker days x 18,250,000 / 360
        #     = 14,397,222; rent: (30 - 15 + 1) = 16 banker days x 4,960,000 /
        #     30 = 2,645,333.
        assert st2["proration_buyer_credit_cents"] == 17_042_555
        # CAM: (360 - 284) = 76 banker days x 7,300,000 / 360 = 1,541,111.
        assert st2["proration_buyer_debit_cents"] == 1_541_111

        assert st1["proration_buyer_credit_cents"] != \
            st2["proration_buyer_credit_cents"]
        assert st1["proration_buyer_debit_cents"] != \
            st2["proration_buyer_debit_cents"]


# ---------------------------------------------------------------------------
# Settlement waterfall evaluation order
# ---------------------------------------------------------------------------

class TestClosingTotalsEvaluationOrder:
    def test_closing_totals_components_post_retrade(self, api):
        """PRD: "The settlement waterfall then evaluates in a pinned order.
        First, the price is the agreement's current `price_cents`, after all
        accepted retrades. Second, `commission_cents` is the tiered commission
        of §3.2 computed on that price at statement creation. Third,
        `payoff_total_cents` is the `total_estimated_cost_cents` of the asset's
        `CONFIRMED` payoff, or 0 when none is confirmed. Fourth, `holdback_cents`
        is the greater of fifty basis points of the price, rounded half up, and
        a floor of 1,000,000 cents. Fifth, `deposits_applied_cents` is the sum
        of the agreement's `POSTED` deposits at creation time."
        PRD: "Frozen means frozen: later retrades move the agreement's price but
        never re-amount these deposits."

        Design: Difficulty/combinatorial_formula/closing_totals_evaluation_order
        """
        ws, _payoff, statement = _delta_statement_after_retrade(api)
        psa = validate_success(api.get_psa(ws["psa"]["id"], DM))
        assert psa["price_cents"] == 1_780_000_000

        assert statement["commission_cents"] == 34_200_000, \
            "tiered commission on the post-retrade price"
        assert statement["holdback_cents"] == 8_900_000, \
            "0.5% of the post-retrade price"
        assert statement["payoff_total_cents"] == 833_833_333, \
            "CONFIRMED payoff total (800,000,000 + 32,000,000 + 1,833,333)"
        assert statement["deposits_applied_cents"] == 90_000_000, \
            "frozen at execution on the original price (54,000,000 + 36,000,000)"

    def test_closing_totals_buyer_due_seller_net(self, api):
        """PRD: "Sixth, `buyer_due_cents` is the price plus the buyer debit
        minus the buyer credit minus the deposits applied. Seventh,
        `seller_net_cents` is the price plus the buyer debit minus the buyer
        credit, minus commission, minus the payoff total, minus the holdback."

        Design: Difficulty/combinatorial_formula/closing_totals_evaluation_order
        """
        _ws, _payoff, statement = _delta_statement_after_retrade(api)
        assert statement["proration_buyer_credit_cents"] == 17_070_000
        assert statement["proration_buyer_debit_cents"] == 1_560_000
        # 1,780,000,000 + 1,560,000 - 17,070,000 - 90,000,000
        assert statement["buyer_due_cents"] == 1_674_490_000
        # 1,780,000,000 + 1,560,000 - 17,070,000 - 34,200,000
        #   - 833,833,333 - 8,900,000
        assert statement["seller_net_cents"] == 887_556_667


# ---------------------------------------------------------------------------
# Closing gates and the statement review loop
# ---------------------------------------------------------------------------

class TestClosingGates:
    def test_begin_closing_payoff_gate_first(self, api):
        """PRD: "Three gates apply in this order: when the asset's
        `loan_balance_cents` is positive, a `CONFIRMED` LoanPayoff must exist
        (`ERR_PAYOFF_NOT_CONFIRMED`); an `APPROVED` ClosingStatement must exist
        for the agreement (`ERR_STATEMENT_NOT_APPROVED`); and every deposit of
        the agreement must be `POSTED` (`ERR_DEPOSIT_NOT_POSTED`)."

        Design: Difficulty/cross_entity_state_dependency/begin_closing_requires_payoff_and_statement
        """
        ws = pipeline_to_binding(asset_payload=alpha_asset_payload())
        # Alpha (leveraged); both deposits POSTED. No payoff exists, so the
        # first gate fires.
        validate_error(api.begin_closing(ws["psa"]["id"], DM),
                       ApiErrorId.ERR_PAYOFF_NOT_CONFIRMED)

    def test_begin_closing_statement_gate_second(self, api):
        """PRD: "Three gates apply in this order: when the asset's
        `loan_balance_cents` is positive, a `CONFIRMED` LoanPayoff must exist
        (`ERR_PAYOFF_NOT_CONFIRMED`); an `APPROVED` ClosingStatement must exist
        for the agreement (`ERR_STATEMENT_NOT_APPROVED`); and every deposit of
        the agreement must be `POSTED` (`ERR_DEPOSIT_NOT_POSTED`)."

        Design: Difficulty/cross_entity_state_dependency/begin_closing_requires_payoff_and_statement
        """
        ws = pipeline_to_binding()
        create_confirmed_payoff(
            ws["asset"]["id"], reinvestment_rate_bps=400, accrued_days=12,
            anticipated_settlement_date="2026-10-30T00:00:00Z")
        # Payoff gate now passes; the statement gate is the next in order.
        validate_error(api.begin_closing(ws["psa"]["id"], DM),
                       ApiErrorId.ERR_STATEMENT_NOT_APPROVED)


class TestStatementReviewLoop:
    def test_statement_dispute_resubmit_cycle(self, api):
        """PRD: "The preparing `ClosingOfficer` submits the statement — from
        `DRAFT`, `DISPUTED`, or `STALE` — into `PENDING_REVIEW`"
        PRD: "The buyer may instead dispute a `PENDING_REVIEW` statement —
        ownership checked against `buyer_bidder_id`, else `ERR_FORBIDDEN_ROLE`
        — moving it to `DISPUTED`, from which the officer revises and
        resubmits."
        PRD: "A `DispositionManager` approves a `PENDING_REVIEW` statement into
        `APPROVED`, recording `approved_by_user_id`, and the approver must
        differ from the preparer (`ERR_SEGREGATION_OF_DUTIES`)."

        Design: Corner/state_machines/statement_dispute_resubmit_cycle
        """
        ws = pipeline_to_executed(
            asset_payload=gamma_asset_payload(),
            analysis_overrides={"cap_rate_bps": 500,
                                "est_sale_price_cents": 2_200_000_000,
                                "est_selling_costs_cents": 0},
            proof_of_funds=600_000_000,
            price_cents=2_000_000_000,
            deposit_cents=60_000_000,
            dd_period_days=20,
            closing_date="2026-10-15T00:00:00Z",
        )
        payload = create_statement_payload(
            ws["psa"]["id"], property_tax_annual_cents=18_250_000,
            tax_period_start="2026-01-01T00:00:00Z",
            rent_monthly_cents=4_960_000, cam_annual_cents=7_300_000)
        statement = validate_success(api.create_statement(payload, CO), 201)
        assert statement["status"] == "DRAFT"
        submitted = validate_success(api.submit_statement(statement["id"], CO))
        assert submitted["status"] == "PENDING_REVIEW"

        disputed = validate_success(
            api.dispute_statement(statement["id"], ws["buyer_headers"]))
        assert disputed["status"] == "DISPUTED"

        resubmitted = validate_success(api.submit_statement(statement["id"], CO))
        assert resubmitted["status"] == "PENDING_REVIEW"
        assert resubmitted["prepared_by_user_id"] == "co-1"

        approved = validate_success(api.approve_statement(statement["id"], DM))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dm-1"

    def test_rbac_closer_cannot_approve_statement(self, api):
        """PRD: "A request whose role is not authorized for the targeted
        operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD: "Role authorization and entity-backed ownership come second"
        PRD Endpoint Definitions: statement approval is authorized for
        `DispositionManager` only.

        Design: Corner/rbac/rbac_closer_cannot_approve_statement
        """
        ws = pipeline_to_executed(
            asset_payload=gamma_asset_payload(),
            analysis_overrides={"cap_rate_bps": 500,
                                "est_sale_price_cents": 2_200_000_000,
                                "est_selling_costs_cents": 0},
            proof_of_funds=600_000_000,
            price_cents=2_000_000_000,
            deposit_cents=60_000_000,
            dd_period_days=20,
            closing_date="2026-10-15T00:00:00Z",
        )
        payload = create_statement_payload(
            ws["psa"]["id"], property_tax_annual_cents=18_250_000,
            tax_period_start="2026-01-01T00:00:00Z",
            rent_monthly_cents=4_960_000, cam_annual_cents=7_300_000)
        statement = validate_success(api.create_statement(payload, CO), 201)
        validate_success(api.submit_statement(statement["id"], CO))

        # A ClosingOfficer caller never reaches the segregation check.
        validate_error(api.approve_statement(statement["id"],
                                             make_co_headers("co-2")),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)
        statements = validate_success(
            api.list_psa_statements(ws["psa"]["id"], DM))
        assert statements[0]["status"] == "PENDING_REVIEW"


# ---------------------------------------------------------------------------
# Post-closing escrow
# ---------------------------------------------------------------------------

class TestEscrow:
    def test_escrow_claim_exhaustion_exact_boundary(self, api):
        """PRD: "an EscrowHoldback is auto-created in `HELD` status with
        `purpose` `INDEMNITY`, `amount_cents` equal to the statement's
        `holdback_cents`, and `release_date` exactly 365 days after
        `closing_date`"
        PRD: "`PAY` requires a `paid_amount_cents` greater than zero and no
        greater than the smaller of the claim's own `amount_cents` and the
        escrow's current `available_cents`"
        PRD: "whenever the available balance reaches zero by any path, release
        or payouts — moves the escrow to terminal `RELEASED`"
        PRD: "`amount_cents` always equals `available_cents` plus
        `released_to_seller_cents` plus `paid_to_claims_cents`"

        Design: Corner/state_machines/escrow_claim_exhaustion_exact_boundary
        """
        ws = setup_closed_delta_deal()
        escrow = ws["escrow"]
        assert escrow["amount_cents"] == 9_000_000
        assert escrow["status"] == "HELD"
        assert_timestamp_prefix(escrow["release_date"], "2027-10-15T00:00:00")
        assert_escrow_partition_identity(escrow)

        headers = ws["buyer_headers"]
        after_file = validate_success(
            api.file_claim(escrow["id"], 4_000_000, "roof warranty", headers),
            201)
        assert after_file["claims"][0]["claim_id"] == "C1"
        assert after_file["claims"][0]["claim_status"] == "FILED"

        after_pay1 = validate_success(
            api.decide_claim(escrow["id"], "C1", "PAY", DM,
                             paid_amount_cents=4_000_000))
        assert after_pay1["available_cents"] == 5_000_000
        assert after_pay1["status"] == "HELD"
        assert_escrow_partition_identity(after_pay1)

        # Filed at exactly the remaining available balance: <= is inclusive.
        validate_success(
            api.file_claim(escrow["id"], 5_000_000, "environmental", headers),
            201)
        after_pay2 = validate_success(
            api.decide_claim(escrow["id"], "C2", "PAY", DM,
                             paid_amount_cents=5_000_000))
        assert after_pay2["available_cents"] == 0
        assert after_pay2["status"] == "RELEASED"
        assert after_pay2["released_to_seller_cents"] == 0
        assert after_pay2["paid_to_claims_cents"] == 9_000_000
        assert_escrow_partition_identity(after_pay2)

    def test_escrow_release_blocked_by_filed_claim(self, api):
        """PRD: "no release proceeds while any claim is `FILED`
        (`ERR_RELEASE_BLOCKED_BY_CLAIMS`, HTTP 409)."
        PRD: "The buyer — ownership checked against `buyer_bidder_id` — files a
        claim with a positive `amount_cents` and a `reason`; filing is barred
        once the escrow is `RELEASED` or the clock has passed `release_date`
        (`ERR_INVALID_STATE_TRANSITION`), and an amount exceeding
        `available_cents` is rejected with `ERR_CLAIM_EXCEEDS_AVAILABLE`
        (HTTP 422)."
        PRD: "`DENY` moves the claim to `DENIED` and no money moves"
        PRD: "A positive amount strictly below `available_cents` moves the
        escrow to `PARTIALLY_RELEASED` and accumulates into
        `released_to_seller_cents`"

        Design: Corner/state_machines/escrow_release_blocked_by_filed_claim
        """
        ws = setup_closed_delta_deal()
        escrow = ws["escrow"]
        headers = ws["buyer_headers"]

        validate_error(api.file_claim(escrow["id"], 0, "zero", headers),
                       ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(api.file_claim(escrow["id"], 9_000_001, "too big", headers),
                       ApiErrorId.ERR_CLAIM_EXCEEDS_AVAILABLE)

        validate_success(api.file_claim(escrow["id"], 2_000_000,
                                        "tax reproration", headers), 201)
        validate_error(api.release_escrow(escrow["id"], DM, amount_cents=1_000_000),
                       ApiErrorId.ERR_RELEASE_BLOCKED_BY_CLAIMS)

        denied = validate_success(api.decide_claim(escrow["id"], "C1", "DENY", DM))
        assert denied["claims"][0]["claim_status"] == "DENIED"
        assert denied["paid_to_claims_cents"] == 0, "no money moves on a denial"

        released = validate_success(
            api.release_escrow(escrow["id"], DM, amount_cents=3_000_000))
        assert released["status"] == "PARTIALLY_RELEASED"
        assert released["available_cents"] == 6_000_000
        assert released["released_to_seller_cents"] == 3_000_000
        assert_escrow_partition_identity(released)

    def test_escrow_auto_release_at_release_date(self, api):
        """PRD: "Independently, the clock sweep performs a full automatic
        release once `release_date` is reached or passed with no `FILED` claims
        outstanding."
        PRD: "fully releases any escrow holdback whose `release_date` has been
        reached or passed, provided no claim on that escrow is still `FILED`,
        moving it to `RELEASED` with the remaining balance paid out to the
        seller."

        Design: Corner/state_machines/escrow_auto_release_at_release_date
        """
        ws = setup_closed_delta_deal()
        escrow = ws["escrow"]
        assert escrow["status"] == "HELD"

        set_clock("2027-10-15T00:00:00Z")
        swept = validate_success(api.get_escrow(escrow["id"], DM))
        assert swept["status"] == "RELEASED"
        assert swept["available_cents"] == 0
        assert swept["released_to_seller_cents"] == 9_000_000
        assert_escrow_partition_identity(swept)
