"""Withdrawal modeling variants, staleness loops, and settlement (PRD §3.6)."""
from test_helpers import (
    ADVISOR,
    ApiErrorId,
    add_position,
    create_active_client,
    create_portfolio_payload,
    create_restriction,
    create_security,
    create_withdrawal,
    create_withdrawal_request_payload,
    deposit,
    get_success_data,
    model_withdrawal,
    reprice,
    setup_active_portfolio,
    setup_three_lot_portfolio,
    settle_modeled_withdrawal,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_cash,
)

T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]
T_US_ONLY = [
    {"asset_class": "US_EQUITY", "target_pct": 100.00, "band_pct": 50.00},
]


class TestWithdrawalCreation:
    def test_withdrawal_amount_must_be_positive(self, api):
        """PRD §3.6: "Either an `Advisor` or the owning `Client` creates the
        request with a `portfolio_id`, an `amount_cents` greater than 0, and a
        `funding_mode` of `CASH_FIRST`, `PRO_RATA`, or `TAX_AWARE`, which
        selects the impact-model variant used later"
        PRD §2.7: "required fields present; types valid; enum values within
        their declared sets; ranges enforced (risk scores between 1 and 100
        inclusive; `target_pct` greater than 0 and at most 100; `band_pct`
        greater than 0 and at most 50; quantities at least 1 on intake;
        `amount_cents` greater than 0; price inputs at least 1;
        `review_cadence_months` between 1 and 24 inclusive; dates in
        `YYYY-MM-DD` form; datetimes in ISO 8601 UTC); a duplicate
        `asset_class` inside a `targets` array; unknown request fields — all
        rejected as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/validations/withdrawal_amount_must_be_positive
        """
        client = create_active_client(full_name="Amt", risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="P"), ADVISOR))
        validate_error(
            api.create_withdrawal_request(create_withdrawal_request_payload(
                portfolio["id"], amount_cents=0, funding_mode="PRO_RATA"), ADVISOR),
            ApiErrorId.ERR_INVALID_REQUEST)
        validate_error(
            api.create_withdrawal_request(create_withdrawal_request_payload(
                portfolio["id"], amount_cents=-5, funding_mode="PRO_RATA"), ADVISOR),
            ApiErrorId.ERR_INVALID_REQUEST)
        ok = validate_success(api.create_withdrawal_request(
            create_withdrawal_request_payload(portfolio["id"], amount_cents=1,
                                              funding_mode="PRO_RATA"), ADVISOR), 201)
        assert ok["status"] == "SUBMITTED"


class TestCashFirstBranch:
    def _setup(self, api):
        return setup_three_lot_portfolio()

    def test_cash_first_empty_plan_within_cash(self, api):
        """PRD §3.6: "Under `CASH_FIRST`, the plan is empty and raises nothing
        — cash alone carries the withdrawal."
        PRD §3.6: "`modeled_cash_used_cents` is the smaller of the requested
        amount and the cash on hand"

        Design: Difficulty/combinatorial_formula/withdrawal_model_mode_a_branch_interaction
        """
        fx = self._setup(api)
        w = create_withdrawal(fx["portfolio"]["id"], 80000, "CASH_FIRST")
        modeled = validate_success(api.model_withdrawal(w["id"], ADVISOR))
        assert modeled["status"] == "MODELED"
        assert modeled["modeled_plan"] == [], "cash covers all: no liquidation"
        assert modeled["modeled_proceeds_cents"] == 0
        assert modeled["modeled_tax_cost_cents"] == 0
        assert modeled["modeled_cash_used_cents"] == 80000

    def test_cash_first_rejects_amount_above_cash(self, api):
        """PRD §3.6: "under `CASH_FIRST` the portfolio's cash must cover the
        full `amount_cents`, else `ERR_INSUFFICIENT_CASH`" — even though the
        total value (400000) covers 150000, CASH_FIRST forbids selling.

        Design: Difficulty/combinatorial_formula/withdrawal_model_mode_a_branch_interaction
        """
        fx = self._setup(api)
        w = create_withdrawal(fx["portfolio"]["id"], 150000, "CASH_FIRST")
        validate_error(api.model_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_INSUFFICIENT_CASH)
        assert validate_success(api.get_withdrawal_request(w["id"], ADVISOR))[
            "status"] == "SUBMITTED"


class TestVariantDivergence:
    def _setup_modeled_pair(self, api):
        fx = setup_three_lot_portfolio()
        p = fx["portfolio"]["id"]
        w_pr = create_withdrawal(p, 150000, "PRO_RATA")
        model_withdrawal(w_pr["id"])
        w_ta = create_withdrawal(p, 150000, "TAX_AWARE")
        model_withdrawal(w_ta["id"])
        return fx, w_pr, w_ta

    def test_pro_rata_plan_math(self, api):
        """PRD §3.6: "Under `PRO_RATA`, sells spread proportionally across
        positions without regard to gains."
        PRD §3.6: "The invested sleeve is `total_value_cents` minus
        `cash_balance_cents`; positions are visited in `created_at` ascending
        order while the amount raised remains below the need; each visited
        position's proportional share of the need is the need times the
        position's `market_value_cents` divided by the invested sleeve, and the
        position sells the smaller of its full `quantity` and that share
        divided by the security's current price rounded up to whole units —
        rounding up so proceeds meet the need, capped at the holding."
        Here: need 50000 over an invested sleeve of 300000 -> 17 + 17 + 34
        units, proceeds 51000, per-lot tax 340 + 2040 + 0 = 2380 (TAXABLE).

        Design: Difficulty/dual_variant_calc/withdrawal_pro_rata_vs_tax_aware_divergence
        """
        fx, w_pr, _w_ta = self._setup_modeled_pair(api)
        pr = validate_success(api.get_withdrawal_request(w_pr["id"], ADVISOR))
        assert pr["status"] == "MODELED"
        assert pr["modeled_cash_used_cents"] == 100000
        assert pr["modeled_proceeds_cents"] == 51000
        assert pr["modeled_tax_cost_cents"] == 2380
        plan = pr["modeled_plan"]
        assert [lot["position_id"] for lot in plan] == [
            fx["positions"]["LOT1"]["id"], fx["positions"]["LOT2"]["id"],
            fx["positions"]["LOT3"]["id"]]
        assert [lot["quantity"] for lot in plan] == [17, 17, 34]
        assert [lot["est_proceeds_cents"] for lot in plan] == [17000, 17000, 17000]

    def test_tax_aware_plan_math_and_divergence(self, api):
        """PRD §3.6: "Under `TAX_AWARE`, the candidate lots are positions with
        more than zero units whose security carries no `ACTIVE` `NO_TRADE`
        restriction, ranked by unrealized gain per unit ascending — losses
        first" — here the EIB loss lot (-50/unit) alone covers the need:
        100 units, proceeds 50000, and a realized loss draws zero tax.
        PRD §2.6: "it accrues only against portfolios whose `tax_status` is
        `TAXABLE`; `TAX_DEFERRED` and `TAX_EXEMPT` portfolios accrue zero."

        Design: Difficulty/dual_variant_calc/withdrawal_pro_rata_vs_tax_aware_divergence
        """
        fx, w_pr, w_ta = self._setup_modeled_pair(api)
        ta = validate_success(api.get_withdrawal_request(w_ta["id"], ADVISOR))
        assert ta["status"] == "MODELED"
        assert ta["modeled_proceeds_cents"] == 50000
        assert ta["modeled_tax_cost_cents"] == 0, "a -5000 loss is not taxed"
        plan = ta["modeled_plan"]
        assert len(plan) == 1
        assert plan[0]["position_id"] == fx["positions"]["LOT3"]["id"]
        assert plan[0]["quantity"] == 100
        assert plan[0]["est_proceeds_cents"] == 50000
        assert plan[0]["est_gain_cents"] == -5000
        # The two variants diverge on identical inputs.
        pr = validate_success(api.get_withdrawal_request(w_pr["id"], ADVISOR))
        assert pr["modeled_proceeds_cents"] != ta["modeled_proceeds_cents"]
        assert pr["modeled_tax_cost_cents"] != ta["modeled_tax_cost_cents"]

    def test_tax_deferred_portfolio_gates_tax_to_zero(self, api):
        """PRD §2.6: "The capital-gains rate used for every tax estimate and
        accrual is 2,000 basis points — twenty percent of the realized gain —
        and it accrues only against portfolios whose `tax_status` is `TAXABLE`;
        `TAX_DEFERRED` and `TAX_EXEMPT` portfolios accrue zero."

        Design: Corner/calculations/tax_deferred_portfolio_gates_tax_to_zero
        """
        fx = setup_three_lot_portfolio(tax_status="TAX_DEFERRED")
        w = create_withdrawal(fx["portfolio"]["id"], 150000, "PRO_RATA")
        modeled = validate_success(api.model_withdrawal(w["id"], ADVISOR))
        assert modeled["modeled_proceeds_cents"] == 51000, (
            "identical plan math to the TAXABLE case")
        assert modeled["modeled_tax_cost_cents"] == 0, (
            "TAX_DEFERRED gates the 2000bps rate off")

    def test_tax_aware_model_excludes_no_trade_restricted_lots(self, api):
        """PRD §3.6: "the candidate lots are positions with more than zero
        units whose security carries no `ACTIVE` `NO_TRADE` restriction, ranked
        by unrealized gain per unit ascending — losses first" — the EIB loss
        lot is excluded by its ACTIVE NO_TRADE window, so the plan sells 50
        units of EQA instead (proceeds 50000, relief 45000, gain 5000, tax
        1000).

        Design: Corner/calculations/tax_aware_model_excludes_no_trade_restricted_lots
        """
        fx = setup_three_lot_portfolio()
        create_restriction(fx["securities"]["EIB"]["id"], level="NO_TRADE",
                           effective_from="2026-08-01T00:00:00Z",
                           effective_to="2026-09-01T00:00:00Z")
        w = create_withdrawal(fx["portfolio"]["id"], 150000, "TAX_AWARE")
        modeled = validate_success(api.model_withdrawal(w["id"], ADVISOR))
        plan = modeled["modeled_plan"]
        assert len(plan) == 1
        assert plan[0]["position_id"] == fx["positions"]["LOT1"]["id"], (
            "the EIB loss lot is excluded despite the lowest gain-per-unit")
        assert plan[0]["quantity"] == 50
        assert plan[0]["est_proceeds_cents"] == 50000
        assert modeled["modeled_proceeds_cents"] == 50000
        assert modeled["modeled_tax_cost_cents"] == 1000


class TestValueBoundary:
    def test_withdrawal_amount_equal_to_total_value_modeled(self, api):
        """PRD §3.6: "under every mode the amount may not exceed the
        portfolio's `total_value_cents`, else `ERR_WITHDRAWAL_EXCEEDS_VALUE`" —
        equality is permitted: 400000 == 400000 fully liquidates the book.
        PRD §3.6: "when the projected total is zero the projection is
        `WITHIN_BANDS`"

        Design: Difficulty/boundary_precision_check/withdrawal_amount_equals_total_value_boundary
        """
        fx = setup_three_lot_portfolio()
        w = create_withdrawal(fx["portfolio"]["id"], 400000, "TAX_AWARE")
        modeled = validate_success(api.model_withdrawal(w["id"], ADVISOR))
        assert modeled["status"] == "MODELED"
        assert modeled["modeled_cash_used_cents"] == 100000
        assert modeled["modeled_proceeds_cents"] == 300000, "full liquidation"
        assert modeled["post_withdrawal_drift_status"] == "WITHIN_BANDS", (
            "projected total 0 is vacuous")

    def test_withdrawal_one_cent_over_total_value_rejected(self, api):
        """PRD §3.6: "under every mode the amount may not exceed the
        portfolio's `total_value_cents`, else `ERR_WITHDRAWAL_EXCEEDS_VALUE`" —
        400001 exceeds 400000 by one cent.

        Design: Difficulty/boundary_precision_check/withdrawal_amount_equals_total_value_boundary
        """
        fx = setup_three_lot_portfolio()
        w = create_withdrawal(fx["portfolio"]["id"], 400001, "TAX_AWARE")
        validate_error(api.model_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_EXCEEDS_VALUE)
        assert validate_success(api.get_withdrawal_request(w["id"], ADVISOR))[
            "status"] == "SUBMITTED"


class TestStalenessLoop:
    def _setup(self, api):
        fx = setup_three_lot_portfolio()
        w = create_withdrawal(fx["portfolio"]["id"], 150000, "TAX_AWARE")
        model_withdrawal(w["id"])
        return fx, w

    def test_reprice_reverts_modeled_withdrawal_to_submitted(self, api):
        """PRD §3.6: "Any portfolio-affecting mutation — a reprice touching a
        held position, a trade execution or void, a cash movement, a position
        creation, or a settlement — reverts every `MODELED` request of that
        portfolio back to `SUBMITTED`, clearing `modeled_plan`, the three
        modeled totals, `post_withdrawal_drift_status`, and `modeled_at`."

        Design: Difficulty/non_linear_state_machine/withdrawal_remodel_loop_after_staleness_revert
        """
        fx, w = self._setup(api)
        first = validate_success(api.get_withdrawal_request(w["id"], ADVISOR))
        assert first["status"] == "MODELED"
        assert first["modeled_proceeds_cents"] == 50000
        reprice(fx["securities"]["EIB"]["id"], 600)
        reverted = validate_success(api.get_withdrawal_request(w["id"], ADVISOR))
        assert reverted["status"] == "SUBMITTED", "the loop returned to SUBMITTED"
        # §3.6 pins `modeled_at` as "null until the request reaches MODELED";
        # the null/empty rendering of the other cleared fields is not pinned.
        assert reverted["modeled_at"] is None

    def test_remodel_after_revert_produces_new_plan(self, api):
        """PRD §3.6: "Walking that ranking while the need remains, each lot
        sells the smaller of its `quantity` and the still-unfunded need divided
        by the current price rounded up." — at the new price 600 the same need
        (50000) draws ceil(50000/600) = 84 units: proceeds 50400, relief
        46200, gain 4200, tax 840.

        Design: Difficulty/non_linear_state_machine/withdrawal_remodel_loop_after_staleness_revert
        """
        fx, w = self._setup(api)
        reprice(fx["securities"]["EIB"]["id"], 600)
        remodeled = validate_success(api.model_withdrawal(w["id"], ADVISOR))
        assert remodeled["status"] == "MODELED", "the loop completed twice"
        assert remodeled["modeled_proceeds_cents"] == 50400
        assert remodeled["modeled_tax_cost_cents"] == 840
        plan = remodeled["modeled_plan"]
        assert len(plan) == 1
        assert plan[0]["position_id"] == fx["positions"]["LOT3"]["id"]
        assert plan[0]["quantity"] == 84


class TestSettlement:
    def test_withdrawal_state_guards_and_cash_first_settlement(self, api):
        """PRD §3.6: "An `Advisor` models the impact of a `SUBMITTED` request
        (any other state yields `ERR_WITHDRAWAL_INVALID_STATE`)"
        PRD §3.6: "each lot appends a `SETTLEMENT_PROCEEDS` event with its
        positive proceeds, `source_type` of `WITHDRAWAL`, and `source_id` set
        to the request's id, and the realized gains accrue into
        `lifetime_realized_gains_cents`. After the lots settle, a
        `WITHDRAWAL_DISBURSEMENT` event appends with the requested amount as a
        negative amount and the same provenance."

        Design: Corner/state_machines/withdrawal_state_guards_and_cash_first_settlement
        """
        fx = setup_active_portfolio(targets=T_CASH, tax_status="TAX_EXEMPT",
                                    client_name="Wd")
        p = fx["portfolio"]["id"]
        deposit(p, 100000)
        w = create_withdrawal(p, 50000, "CASH_FIRST")
        # Approve from SUBMITTED: wrong from-state.
        validate_error(api.approve_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE)
        model_withdrawal(w["id"])
        get_success_data(api.approve_withdrawal(w["id"], ADVISOR))
        # Model from APPROVED: wrong from-state.
        validate_error(api.model_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE)
        settled = validate_success(api.settle_withdrawal(w["id"], ADVISOR))
        assert settled["status"] == "SETTLED"
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["cash_balance_cents"] == 50000
        # The empty plan posts exactly one disbursement and no proceeds.
        disb, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "WITHDRAWAL_DISBURSEMENT"}))
        assert len(disb) == 1
        assert disb[0]["amount_cents"] == -50000
        assert disb[0]["source_type"] == "WITHDRAWAL"
        assert disb[0]["source_id"] == w["id"]
        proceeds, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "SETTLEMENT_PROCEEDS"}))
        assert proceeds == []
        # SETTLED is terminal.
        validate_error(api.settle_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE)

    def test_settle_wrong_state_and_overdrawn_state_beats_fiscal(self, api):
        """PRD §2.7: "Checks run in a fixed priority order, and when several
        checks would fail, the request is rejected with the error from the
        earliest category" — lifecycle state (7) precedes fiscal rules (13).
        PRD §3.6: settle requires `APPROVED`; the reverted request stands in
        `SUBMITTED`, and its amount (300000) also exceeds the portfolio's
        total value (220000 after the repricing).

        Design: Difficulty/priority_pair_validation_conflict/settle_wrong_state_and_overdrawn_state_beats_fiscal
        """
        fx = setup_three_lot_portfolio()
        p = fx["portfolio"]["id"]
        w = create_withdrawal(p, 300000, "TAX_AWARE")
        model_withdrawal(w["id"])
        # Cash movement reverts the model (MODELED -> SUBMITTED).
        withdraw_cash(p, 100000)
        # Reprice EQA down: total_value 220000 < amount 300000.
        reprice(fx["securities"]["EQA"]["id"], 200)
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["total_value_cents"] == 220000
        validate_error(api.settle_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE)

    def test_settle_wrong_state_leaves_no_side_effects(self, api):
        """PRD §3.6: "The request lands in `SETTLED`, terminal" only on a
        successful settle — the rejected settle appends no ledger events and
        leaves the request SUBMITTED.

        Design: Difficulty/priority_pair_validation_conflict/settle_wrong_state_and_overdrawn_state_beats_fiscal
        """
        fx = setup_three_lot_portfolio()
        p = fx["portfolio"]["id"]
        w = create_withdrawal(p, 300000, "TAX_AWARE")
        model_withdrawal(w["id"])
        withdraw_cash(p, 100000)
        reprice(fx["securities"]["EQA"]["id"], 200)
        validate_error(api.settle_withdrawal(w["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE)
        assert validate_success(api.get_withdrawal_request(w["id"], ADVISOR))[
            "status"] == "SUBMITTED"
        proceeds, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "SETTLEMENT_PROCEEDS"}))
        disb, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "WITHDRAWAL_DISBURSEMENT"}))
        assert proceeds == [] and disb == [], "the failed settle appended nothing"

    def test_settlement_plan_infeasible_after_position_drained(self, api):
        """PRD §3.6: "every lot of the `modeled_plan` must still be feasible,
        meaning each planned lot's current position `quantity` is at least the
        planned quantity, else `ERR_WITHDRAWAL_PLAN_INFEASIBLE`."

        Design: Corner/validations/withdrawal_settlement_plan_infeasible_after_position_drained
        """
        fx = setup_three_lot_portfolio()
        p = fx["portfolio"]["id"]
        lot3 = fx["positions"]["LOT3"]
        # W2 approved with plan LOT3 x100.
        w2 = create_withdrawal(p, 150000, "TAX_AWARE")
        model_withdrawal(w2["id"])
        get_success_data(api.approve_withdrawal(w2["id"], ADVISOR))
        # W3 settles first and drains LOT3 (200 units @ 500 -> +100000).
        w3 = create_withdrawal(p, 200000, "TAX_AWARE")
        model_withdrawal(w3["id"])
        settle_modeled_withdrawal(w3["id"])
        lot3_after = validate_success(api.get_position(lot3["id"], ADVISOR))
        assert lot3_after["quantity"] == 0
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["cash_balance_cents"] == 0
        assert portfolio["total_value_cents"] == 200000
        # W2's fiscal gate still passes (150000 <= 200000); feasibility fails.
        validate_error(api.settle_withdrawal(w2["id"], ADVISOR),
                       ApiErrorId.ERR_WITHDRAWAL_PLAN_INFEASIBLE)
        assert validate_success(api.get_withdrawal_request(w2["id"], ADVISOR))[
            "status"] == "APPROVED"

    def test_tax_lot_relief_rounding_dust_conserved_over_partial_exits(self, api):
        """PRD §3.5: "the relief is the lot's `cost_basis_cents` times the
        units sold divided by the lot's prior `quantity`, rounded half-up once;
        the realized gain is the units times the executed price minus that
        pinned relief; the lot's `cost_basis_cents` falls by the relief and its
        `quantity` by the units sold — and a full exit relieves the entire
        basis exactly, leaving no dust."
        Four one-unit exits from a 4-unit lot with basis 100001 draw reliefs of
        25000, 25000, 25001 (half-up of 25000.5), and 25000 — summing to the
        original basis exactly.

        Design: Corner/calculations/tax_lot_relief_rounding_dust_conserved_over_partial_exits
        """
        fx = setup_active_portfolio(targets=T_US_ONLY, tax_status="TAXABLE",
                                    client_name="Dust")
        p = fx["portfolio"]["id"]
        security = create_security("EQA", "US_EQUITY", 1000)
        position = add_position(p, security["id"], 4, 100001)
        expected_basis = [75001, 50001, 25000, 0]
        for expected in expected_basis:
            w = create_withdrawal(p, 1000, "TAX_AWARE")
            model_withdrawal(w["id"])
            settle_modeled_withdrawal(w["id"])
            current = validate_success(api.get_position(position["id"], ADVISOR))
            assert current["cost_basis_cents"] == expected
        final_position = validate_success(api.get_position(position["id"], ADVISOR))
        assert final_position["quantity"] == 0
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        # 4 x 1000 proceeds - 100001 total relief.
        assert portfolio["lifetime_realized_gains_cents"] == -96001
        assert portfolio["total_value_cents"] == 0
        assert portfolio["drift_status"] == "WITHIN_BANDS", "vacuous zero total"
