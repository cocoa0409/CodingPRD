"""Settlement statements: period windows, the pinned money-field evaluation
order, margin tiers and promo drag, provisional-vs-final shrink variants, the
finalize/dispute/revise cycle, SoD on approval, and the payout floor."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_markdown,
    apply_markdown,
    audit_counted_line,
    certify_audit,
    create_settlement_statement_payload,
    finalize_statement,
    get_audit,
    get_statement,
    make_jobber_admin_headers,
    make_jobber_finance_headers,
    make_retailer_manager_headers,
    new_active_agreement,
    new_markdown,
    new_price_directive,
    new_product,
    new_program,
    new_promotion,
    new_route,
    new_statement,
    new_store,
    post_matched_sale,
    run_restock_visit,
    schedule_promotion,
    set_clock,
    setup_shop,
    setup_certified_audit,
    setup_stocked_shop,
    setup_submitted_audit,
    approve_statement,
    pay_statement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["jobber_admin_headers"]
FINANCE = TEST_USERS["jobber_finance_headers"]


class TestStatementReadModel:
    def test_computed_money_fields_for_simple_period(self, api):
        """PRD section 3.9: "Fifth, `net_sales_cents` is gross minus the
        markdown credit."
        PRD section 3.9: "Seventh, `retailer_margin_cents` is
        `net_sales_cents` multiplied by `margin_pct`, rounded half-up — and
        note the tier thresholds read net sales from step five, never gross."
        PRD section 3.9: "Tenth, `net_payable_to_jobber_cents` is
        `net_sales_cents` minus `retailer_margin_cents` plus
        `shrink_retailer_charge_cents` minus `teardown_penalty_cents`."
        PRD section 3.9: "The statement is born `PROVISIONAL`, records the
        generator in `created_by_user_id`, and computes every money field under
        the `PROVISIONAL` variant, recorded in `variant_used`."

        Design: Corner/endpoints/computed_read_settlement_fields
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="rd-1")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        read = get_statement(statement["id"])
        assert read["gross_scanned_sales_cents"] == 2000
        assert read["markdown_credit_cents"] == 0
        assert read["net_sales_cents"] == 2000
        assert read["margin_pct"] == 0.25
        assert read["retailer_margin_cents"] == 500
        assert read["shrink_retailer_charge_cents"] == 0
        assert read["teardown_penalty_cents"] == 0
        assert read["net_payable_to_jobber_cents"] == 1500
        assert read["variant_used"] == "PROVISIONAL"
        assert read["period_start"] == "2026-08-01"
        assert read["period_end"] == "2026-08-08"


class TestPeriodWindow:
    def test_period_end_is_exclusive(self, api):
        """PRD section 3.9: "With a weekly cadence anchored on 2026-08-01,
        period 0 runs from 2026-08-01 up to but not including 2026-08-08. A
        scan timestamped exactly at a period's end belongs to the next
        period."

        Design: Corner/calculations/period_window_half_open_membership
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 1, "2026-08-07T23:59:59Z",
                          client_event_id="ho-a")
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 2, "2026-08-08T00:00:00Z",
                          client_event_id="ho-b")
        s0 = new_statement(ctx["agreement"]["id"], period_index=0)
        assert s0["period_start"] == "2026-08-01"
        assert s0["period_end"] == "2026-08-08"
        assert s0["gross_scanned_sales_cents"] == 200, (
            "only the 2026-08-07T23:59:59Z scan is inside [08-01, 08-08)")
        set_clock("2026-08-08T00:00:00Z")
        s1 = new_statement(ctx["agreement"]["id"], period_index=1)
        assert s1["gross_scanned_sales_cents"] == 400, (
            "the scan at exactly period_end falls into period 1")


class TestMarginTierBrackets:
    def _tier_scenario(self, api, units, store_name, store_code):
        set_clock()
        program = new_program(name="TierEdge")
        store = new_store(name=store_name, store_code=store_code)
        agreement = new_active_agreement(
            program["id"], store["id"], estimated_shrink_rate=0.0)
        product = new_product(program["id"], sku="TE-001", name="Tier Item")
        new_price_directive(agreement["id"], product["id"], price_cents=200)
        post_matched_sale(agreement["id"], product["id"], store["id"], units,
                          "2026-08-01T10:00:00Z", client_event_id="te-sale")
        return agreement

    def test_net_below_tier1_uses_base_margin(self, api):
        """PRD section 3.9: "Sixth, the margin: when net sales reach or exceed
        `tier2_threshold_cents` the uplift is `tier2_uplift_pct`; otherwise,
        when they reach or exceed `tier1_threshold_cents`, it is
        `tier1_uplift_pct`; otherwise there is no uplift — the tiers replace
        rather than stack."

        Design: Corner/calculations/margin_tier_threshold_brackets
        """
        agreement = self._tier_scenario(api, 499, "TierStore1", "TE1")
        statement = new_statement(agreement["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 99800
        assert statement["margin_pct"] == 0.25, "99800 < 100000: no uplift"
        assert statement["retailer_margin_cents"] == 24950

    def test_net_exactly_at_tier1_takes_uplift(self, api):
        """PRD section 3.9: "Sixth, the margin: when net sales reach or exceed
        `tier2_threshold_cents` the uplift is `tier2_uplift_pct`; otherwise,
        when they reach or exceed `tier1_threshold_cents`, it is
        `tier1_uplift_pct`; otherwise there is no uplift — the tiers replace
        rather than stack."

        Design: Corner/calculations/margin_tier_threshold_brackets
        """
        agreement = self._tier_scenario(api, 500, "TierStore2", "TE2")
        statement = new_statement(agreement["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 100000
        assert statement["margin_pct"] == 0.26, (
            "100000 >= 100000: the boundary is inclusive")
        assert statement["retailer_margin_cents"] == 26000


class TestTierDragClampCombination:
    def _promo_mix_scenario(self, api):
        """240 promo units (depth 0.10, window 08-01..08-05) plus 360
        full-price units: gross 115200, promo share 0.40."""
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        promo = new_promotion(ctx["program"]["id"], ctx["product"]["id"],
                              name="Kickoff 10pct", depth_pct=0.10,
                              jobber_funding_pct=0.5,
                              start_date="2026-08-01", end_date="2026-08-05")
        schedule_promotion(promo["id"])
        promo_scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            240, "2026-08-02T10:00:00Z", client_event_id="s-promo")
        regular_scan = post_matched_sale(
            ctx["agreement"]["id"], ctx["product"]["id"], ctx["store"]["id"],
            360, "2026-08-06T10:00:00Z", client_event_id="s-regular")
        return ctx, promo_scan, regular_scan

    def test_promo_and_regular_scan_pricing(self, api):
        """PRD section 3.6: "The system then looks for a promotion on the
        scan's program and product that is `ACTIVE` with the `scanned_at`
        calendar date inside its closed window".
        PRD section 3.9: "Second, `scanned_units` nets the window's unit
        movement — sales add, returns subtract, and voids reverse their
        target's quantity — and `promo_scan_units` counts the units scanned at
        promo price."

        Design: Difficulty/combinatorial_formula/margin_tier_drag_clamp_combinatorial
        """
        ctx, promo_scan, regular_scan = self._promo_mix_scenario(api)
        assert promo_scan["unit_price_cents"] == 180, (
            "round_half_up(200 * 0.9)")
        assert regular_scan["unit_price_cents"] == 200
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 115200
        assert statement["scanned_units"] == 600
        assert statement["promo_scan_units"] == 240
        assert statement["promo_jobber_funding_cents"] == 2400, (
            "round((200 - 180) * 240 * 0.5)")

    def test_tier_uplift_drag_and_clamp_resolve(self, api):
        """PRD section 3.9: "Sixth, the margin: when net sales reach or exceed
        `tier2_threshold_cents` the uplift is `tier2_uplift_pct`; otherwise,
        when they reach or exceed `tier1_threshold_cents`, it is
        `tier1_uplift_pct`; otherwise there is no uplift — the tiers replace
        rather than stack. The promo drag then applies: the promo share is
        `promo_scan_units` divided by `scanned_units`, taken as 0.0 when
        `scanned_units` is zero, and a share strictly greater than 0.30
        subtracts a drag of 0.01. The resulting `margin_pct` is
        `base_margin_pct` plus the tier uplift minus the drag, clamped so it
        never falls below `min_margin_pct` nor exceeds `max_margin_pct`; it is
        held as an exact decimal, unrounded."

        Design: Difficulty/combinatorial_formula/margin_tier_drag_clamp_combinatorial
        """
        ctx, _, _ = self._promo_mix_scenario(api)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["margin_pct"] == 0.25, (
            "base 0.25 + tier1 0.01 (115200 >= 100000) - drag 0.01 "
            "(240/600 = 0.40 > 0.30)")
        assert statement["retailer_margin_cents"] == 28800
        assert statement["net_payable_to_jobber_cents"] == 86400


class TestEvaluationOrder:
    def _markdown_scenario(self, api):
        """1000 units @200 (gross 200000) plus a 2-unit markdown at 190,
        SHARED 0.5: raw credit 10, far under the gross-keyed cap."""
        ctx = setup_shop(agreement_overrides={
            "estimated_shrink_rate": 0.0, "markdown_liability": "SHARED",
            "markdown_jobber_share_pct": 0.5})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 1000, "2026-08-01T10:00:00Z",
                          client_event_id="s-big")
        markdown = new_markdown(ctx["agreement"]["id"], ctx["product"]["id"],
                                auth_type="MARKDOWN", units=2,
                                markdown_price_cents=190)
        approve_markdown(markdown["id"], ctx["store"]["id"])
        apply_markdown(markdown["id"])
        return ctx

    def test_markdown_cap_keyed_on_gross(self, api):
        """PRD section 3.9: "Fourth, the markdown credit: the raw figure sums
        `credit_cents` of `MARKDOWN` authorizations applied in the window, and
        `markdown_credit_cents` is the lesser of that raw figure and the
        agreement's `markdown_cap_pct_of_gross` multiplied by the gross sales
        of step one, rounded half-up — the cap is keyed on gross, never on
        net. Fifth, `net_sales_cents` is gross minus the markdown credit."

        Design: Difficulty/combinatorial_formula/settlement_eval_order_net_sales_before_tier
        """
        ctx = self._markdown_scenario(api)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["gross_scanned_sales_cents"] == 200000
        assert statement["markdown_credit_cents"] == 10, (
            "min(raw 10, round(0.08 * 200000) = 16000)")
        assert statement["net_sales_cents"] == 199990

    def test_tier_keyed_on_net_not_gross(self, api):
        """PRD section 3.9: "Seventh, `retailer_margin_cents` is
        `net_sales_cents` multiplied by `margin_pct`, rounded half-up — and
        note the tier thresholds read net sales from step five, never gross."
        PRD section 3.9: "Tenth, `net_payable_to_jobber_cents` is
        `net_sales_cents` minus `retailer_margin_cents` plus
        `shrink_retailer_charge_cents` minus `teardown_penalty_cents`."

        Design: Difficulty/combinatorial_formula/settlement_eval_order_net_sales_before_tier
        """
        ctx = self._markdown_scenario(api)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["margin_pct"] == 0.26, (
            "tier1 selected on NET 199990; keying on GROSS 200000 would "
            "wrongly give tier2 0.27")
        assert statement["retailer_margin_cents"] == 51997, (
            "round_half_up(199990 * 0.26)")
        assert statement["net_payable_to_jobber_cents"] == 147993


class TestProvisionalVsFinalVariants:
    def _variant_scenario(self, api):
        """Restock 1050 confirmed; SALE 1000 @200; audit counted 30 certified
        at 2026-08-02 (chargeable 10 after the 10-unit free allowance)."""
        ctx = setup_stocked_shop(
            restock_units=1050,
            agreement_overrides={"estimated_shrink_rate": 0.02,
                                 "restock_value_cap_cents": 200000})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 1000, "2026-08-01T10:00:00Z",
                          client_event_id="s-1")
        set_clock("2026-08-02T00:00:00Z")
        audit = setup_certified_audit(
            ctx["agreement"]["id"],
            [audit_counted_line(ctx["product"]["id"], 30)])
        return ctx, audit

    def test_provisional_variant_estimates_shrink(self, api):
        """PRD section 3.9: "Eighth, the shrink charge, which is where the two
        variants diverge: the `PROVISIONAL` variant estimates —
        `scanned_units` multiplied by the agreement's `estimated_shrink_rate`,
        rounded half-up to a whole unit, multiplied by the window's average
        jobber cost, multiplied by `shrink_retailer_share_pct`, rounded half-up
        to a whole cent — where the average jobber cost is the sum over the
        window's scan lines of each line's `quantity` times its product's
        `jobber_cost_cents`, divided by `scanned_units`, rounded half-up, and
        taken as zero when `scanned_units` is zero; audits are ignored
        entirely."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_shrink_basis
        """
        ctx, _ = self._variant_scenario(api)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        assert statement["variant_used"] == "PROVISIONAL"
        assert statement["gross_scanned_sales_cents"] == 200000
        assert statement["retailer_margin_cents"] == 54000, (
            "tier2: 200000 >= 200000 -> margin_pct 0.27")
        assert statement["shrink_retailer_charge_cents"] == 1000, (
            "round(1000 * 0.02) = 20 units * avg cost 100 * share 0.5")
        assert statement["net_payable_to_jobber_cents"] == 147000

    def test_final_variant_uses_certified_audits(self, api):
        """PRD section 3.9: "The `FINAL` variant instead sums
        `retailer_charge_cents` over the agreement's audits in `CERTIFIED` or
        `LOCKED` status whose `certified_at` falls in the window, ignoring
        `estimated_shrink_rate` — identical scan data therefore yields a
        different payable whenever the estimate disagrees with certified
        actuals."
        PRD section 3.9: "On success the statement moves to `FINALIZED`,
        recomputes every money field under the `FINAL` variant, stamps
        `settled_in_statement_id` onto each matched scan it includes, and locks
        each included `CERTIFIED` audit into `LOCKED`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_shrink_basis
        """
        ctx, audit = self._variant_scenario(api)
        assert audit["retailer_charge_cents"] == 500, (
            "chargeable 10 * cost 100 * share 0.5")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        provisional_payable = statement["net_payable_to_jobber_cents"]
        set_clock("2026-08-08T00:00:00Z")
        finalized = finalize_statement(statement["id"])
        assert finalized["variant_used"] == "FINAL"
        assert finalized["shrink_retailer_charge_cents"] == 500
        assert finalized["net_payable_to_jobber_cents"] == 146500
        assert provisional_payable != finalized["net_payable_to_jobber_cents"],\
            "the variants diverge by exactly 500 on identical scan data"


class TestFinalizeDisputeReviseCycle:
    def _statement_with_sales(self, api):
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="s-1")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        set_clock("2026-08-08T00:00:00Z")
        return ctx, statement

    def test_cycle_status_and_variant_path(self, api):
        """PRD section 3.9: "From `FINALIZED`, the retailer's `RetailerManager`
        may dispute — `FINALIZED` to `DISPUTED`, optional `reason`,
        store-identity rule — and a `JobberFinance` revise returns `DISPUTED`
        to `PROVISIONAL`, recomputing the money fields under the `PROVISIONAL`
        variant so the cycle can run again."

        Design: Difficulty/non_linear_state_machine/settlement_finalize_dispute_revise_cycle
        """
        ctx, statement = self._statement_with_sales(api)
        v1 = statement["version"]
        finalized = finalize_statement(statement["id"],
                                       expected_version=v1)
        assert finalized["status"] == "FINALIZED"
        assert finalized["variant_used"] == "FINAL"
        assert finalized["version"] == v1 + 1
        disputed = validate_success(api.dispute_settlement_statement(
            statement["id"], {"reason": "retailer disputes shrink line"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        assert disputed["status"] == "DISPUTED"
        assert disputed["version"] == v1 + 2
        revised = validate_success(api.revise_settlement_statement(
            statement["id"], FINANCE), 200)
        assert revised["status"] == "PROVISIONAL"
        assert revised["variant_used"] == "PROVISIONAL", (
            "revise recomputes under the PROVISIONAL variant")
        assert revised["version"] == v1 + 3
        refinalized = finalize_statement(statement["id"],
                                         expected_version=v1 + 3)
        assert refinalized["status"] == "FINALIZED"
        assert refinalized["version"] == v1 + 4, (
            "version increments by exactly one per transition")

    def test_recomputation_is_stable_across_cycle(self, api):
        """PRD section 3.9: "On success the statement moves to `FINALIZED`,
        recomputes every money field under the `FINAL` variant, stamps
        `settled_in_statement_id` onto each matched scan it includes, and locks
        each included `CERTIFIED` audit into `LOCKED`."
        PRD section 3.9: "a `JobberFinance` revise returns `DISPUTED` to
        `PROVISIONAL`, recomputing the money fields under the `PROVISIONAL`
        variant so the cycle can run again."

        Design: Difficulty/non_linear_state_machine/settlement_finalize_dispute_revise_cycle
        """
        ctx, statement = self._statement_with_sales(api)
        first = finalize_statement(statement["id"])
        assert first["net_payable_to_jobber_cents"] == 1500, (
            "gross 2000 - margin 500, no shrink, no penalties")
        validate_success(api.dispute_settlement_statement(
            statement["id"], {"reason": "re-check"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        validate_success(
            api.revise_settlement_statement(statement["id"], FINANCE), 200)
        second = finalize_statement(statement["id"])
        assert second["net_payable_to_jobber_cents"] == 1500, (
            "recomputation is stable across the cycle")


class TestFinalizeAuditGate:
    def _statement_with_open_audit(self, api):
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="s-1")
        set_clock("2026-08-02T00:00:00Z")
        audit = setup_submitted_audit(
            ctx["agreement"]["id"],
            [audit_counted_line(ctx["product"]["id"], 0)])
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        set_clock("2026-08-08T00:00:00Z")
        return ctx, audit, statement

    def test_finalize_blocked_by_uncertified_audit(self, api):
        """PRD section 3.9: "Finalization further requires the period to be
        fully closed, the clock date no earlier than `period_end`
        (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED` otherwise), and every audit of the
        agreement whose `submitted_at` falls in the window to be in `CERTIFIED`
        or `LOCKED` (`ERR_AUDIT_NOT_CERTIFIED` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_certified_audits
        """
        ctx, audit, statement = self._statement_with_open_audit(api)
        res = api.finalize_settlement_statement(
            statement["id"],
            {"expected_settlement_statement_version": statement["version"]},
            FINANCE)
        validate_error(res, ApiErrorId.ERR_AUDIT_NOT_CERTIFIED)
        after = get_statement(statement["id"])
        assert after["status"] == "PROVISIONAL"
        assert after["variant_used"] == "PROVISIONAL"
        assert get_audit(audit["id"])["status"] == "SUBMITTED", (
            "no auto-certify side effect")

    def test_finalize_succeeds_once_audit_certified(self, api):
        """PRD section 3.9: "Finalization further requires the period to be
        fully closed, the clock date no earlier than `period_end`
        (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED` otherwise), and every audit of the
        agreement whose `submitted_at` falls in the window to be in `CERTIFIED`
        or `LOCKED` (`ERR_AUDIT_NOT_CERTIFIED` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/settlement_finalize_requires_certified_audits
        """
        ctx, audit, statement = self._statement_with_open_audit(api)
        certify_audit(audit["id"])
        finalized = finalize_statement(statement["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["variant_used"] == "FINAL"


class TestStatementUniquenessAndClosure:
    def test_duplicate_period_rejected(self, api):
        """PRD section 3.9: "A `JobberFinance` operator generates a
        **SettlementStatement** by naming `store_agreement_id` and a zero-based
        `period_index`, unique per agreement — a second statement for the same
        pair is rejected with `ERR_SETTLEMENT_ALREADY_EXISTS`."

        Design: Corner/validations/settlement_duplicate_period_rejected
        """
        ctx = setup_shop(with_product=False)
        new_statement(ctx["agreement"]["id"], period_index=0)
        res = api.create_settlement_statement(
            create_settlement_statement_payload(ctx["agreement"]["id"], 0),
            FINANCE)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_ALREADY_EXISTS)

    def test_finalize_before_period_closed_rejected(self, api):
        """PRD section 3.9: "Finalization further requires the period to be
        fully closed, the clock date no earlier than `period_end`
        (`ERR_SETTLEMENT_PERIOD_NOT_CLOSED` otherwise), and every audit of the
        agreement whose `submitted_at` falls in the window to be in `CERTIFIED`
        or `LOCKED` (`ERR_AUDIT_NOT_CERTIFIED` otherwise)."

        Design: Corner/validations/settlement_period_not_closed_rejected
        """
        ctx = setup_shop(with_product=False)
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        res = api.finalize_settlement_statement(
            statement["id"],
            {"expected_settlement_statement_version": statement["version"]},
            FINANCE)
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_PERIOD_NOT_CLOSED)
        assert get_statement(statement["id"])["status"] == "PROVISIONAL"


class TestPayGate:
    def test_pay_before_approve_rejected(self, api):
        """PRD section 3.9: "Payment is the last step and carries the program's
        payout floor: a `JobberFinance` pay moves `APPROVED` to `PAID`, the
        terminal state, only when `net_payable_to_jobber_cents` is at least the
        program's `min_payout_cents` — a smaller payable is rejected with
        `ERR_PAYOUT_BELOW_MINIMUM` — and stamps `paid_at` with the clock."
        PRD section 2.8: "From-state validity: the target resource must be in a
        state from which the requested transition exists, failing with
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/settlement_pay_before_approve_rejected
        """
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="sk-1")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        set_clock("2026-08-08T00:00:00Z")
        finalize_statement(statement["id"])
        res = api.pay_settlement_statement(statement["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_statement(statement["id"])["status"] == "FINALIZED", (
            "the approval chain cannot be skipped")

    def test_paid_is_terminal(self, api):
        """PRD section 3.9: "Payment is the last step and carries the program's
        payout floor: a `JobberFinance` pay moves `APPROVED` to `PAID`, the
        terminal state".
        PRD section 2.8: "Terminality: an action addressed to a resource
        already in a terminal state fails with `ERR_ALREADY_TERMINAL`
        (HTTP 409)."

        Design: Corner/errors/terminal_pay_lockdown
        """
        ctx = setup_shop(program_overrides={"min_payout_cents": 100},
                         agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="pd-1")
        statement = new_statement(ctx["agreement"]["id"], period_index=0)
        set_clock("2026-08-08T00:00:00Z")
        finalize_statement(statement["id"])
        approve_statement(statement["id"])
        paid = pay_statement(statement["id"])
        assert paid["status"] == "PAID", "1500 >= 100: the floor is met"
        res = api.pay_settlement_statement(statement["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert get_statement(statement["id"])["status"] == "PAID"


class TestPayoutFloorBoundary:
    def _exact_payout_scenario(self, api):
        """Agreement E1: restock 100, SALE 25 @200, certified audit chargeable
        25 -> retailer charge 1250; FINAL payable exactly 5000."""
        set_clock()
        program = new_program(name="PayTest")
        store1 = new_store(name="Store E1", store_code="SE1",
                           total_facings=60)
        agr1 = new_active_agreement(
            program["id"], store1["id"], restock_value_cap_cents=50000,
            shrink_suspend_ratio=0.30, estimated_shrink_rate=0.0)
        product = new_product(program["id"], sku="TEA-001", name="Iced Tea")
        new_price_directive(agr1["id"], product["id"], price_cents=200)
        route = new_route(program["id"])
        run_restock_visit(route["id"], agr1["id"], store1["id"],
                          product["id"], 100)
        post_matched_sale(agr1["id"], product["id"], store1["id"], 25,
                          "2026-08-01T10:00:00Z", client_event_id="e1-sale")
        set_clock("2026-08-02T00:00:00Z")
        setup_certified_audit(
            agr1["id"], [audit_counted_line(product["id"], 50)])
        statement = new_statement(agr1["id"], period_index=0)
        set_clock("2026-08-08T00:00:00Z")
        return program, product, store1, statement

    def test_payable_exactly_at_minimum_pays(self, api):
        """PRD section 3.9: "Payment is the last step and carries the program's
        payout floor: a `JobberFinance` pay moves `APPROVED` to `PAID`, the
        terminal state, only when `net_payable_to_jobber_cents` is at least the
        program's `min_payout_cents` — a smaller payable is rejected with
        `ERR_PAYOUT_BELOW_MINIMUM` — and stamps `paid_at` with the clock."

        Design: Difficulty/boundary_precision_check/payout_minimum_exact_cents
        """
        _, _, _, statement = self._exact_payout_scenario(api)
        finalized = finalize_statement(statement["id"])
        assert finalized["net_sales_cents"] == 5000
        assert finalized["retailer_margin_cents"] == 1250
        assert finalized["shrink_retailer_charge_cents"] == 1250
        assert finalized["net_payable_to_jobber_cents"] == 5000
        approve_statement(statement["id"])
        paid = pay_statement(statement["id"])
        assert paid["status"] == "PAID", "5000 >= 5000: equality pays"

    def test_payable_one_notch_below_minimum_rejected(self, api):
        """PRD section 3.9: "Payment is the last step and carries the program's
        payout floor: a `JobberFinance` pay moves `APPROVED` to `PAID`, the
        terminal state, only when `net_payable_to_jobber_cents` is at least the
        program's `min_payout_cents` — a smaller payable is rejected with
        `ERR_PAYOUT_BELOW_MINIMUM` — and stamps `paid_at` with the clock."

        Design: Difficulty/boundary_precision_check/payout_minimum_exact_cents
        """
        program, product, _, _ = self._exact_payout_scenario(api)
        # Second store/agreement anchored at 2026-08-08: 33 units @200 ->
        # gross 6600, margin 1650, no audits -> payable 4950 < 5000.
        store2 = new_store(name="Store E2", store_code="SE2", total_facings=60)
        agr2 = new_active_agreement(
            program["id"], store2["id"], restock_value_cap_cents=50000,
            estimated_shrink_rate=0.0)
        new_price_directive(agr2["id"], product["id"], price_cents=200,
                            effective_from="2026-08-08T00:00:00Z")
        post_matched_sale(agr2["id"], product["id"], store2["id"], 33,
                          "2026-08-08T12:00:00Z", client_event_id="e2-sale")
        stmt2 = new_statement(agr2["id"], period_index=0)
        set_clock("2026-08-15T00:00:00Z")
        finalized2 = finalize_statement(stmt2["id"])
        assert finalized2["net_payable_to_jobber_cents"] == 4950
        approve_statement(stmt2["id"])
        res = api.pay_settlement_statement(stmt2["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_PAYOUT_BELOW_MINIMUM)
        assert get_statement(stmt2["id"])["status"] == "APPROVED", (
            "4950 < 5000: a smaller payable is rejected")


class TestSettlementSodAndOcc:
    def _finalized_statement(self, api, finance_id="fin-1"):
        ctx = setup_shop(agreement_overrides={"estimated_shrink_rate": 0.0})
        post_matched_sale(ctx["agreement"]["id"], ctx["product"]["id"],
                          ctx["store"]["id"], 10, "2026-08-01T10:00:00Z",
                          client_event_id="sd-1")
        statement = new_statement(ctx["agreement"]["id"], period_index=0,
                                  finance_id=finance_id)
        set_clock("2026-08-08T00:00:00Z")
        finalize_statement(statement["id"], finance_id=finance_id)
        return ctx, statement

    def test_finance_cannot_approve(self, api):
        """PRD section 2.1: "The `JobberFinance` operator generates, finalizes,
        revises, and pays settlement statements but may never approve them."
        PRD section 4: POST /settlement-statements/{id}/approve lists
        JobberAdmin as its only authorized role.

        Design: Corner/rbac/rbac_jobber_finance_cannot_approve_settlement
        """
        _, statement = self._finalized_statement(api)
        res = api.approve_settlement_statement(
            statement["id"], make_jobber_finance_headers("fin-2"))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert get_statement(statement["id"])["status"] == "FINALIZED"

    def test_approver_cannot_be_creator(self, api):
        """PRD section 2.9: "A settlement statement records its generator as
        `created_by_user_id`; approval must come from a `JobberAdmin` whose
        `X-User-ID` differs from `created_by_user_id`, failing with
        `ERR_SOD_APPROVER_IS_CREATOR` (HTTP 403)."

        Design: Corner/rbac/sod_approver_cannot_be_creator
        """
        _, statement = self._finalized_statement(api, finance_id="fin-9")
        res = api.approve_settlement_statement(
            statement["id"], make_jobber_admin_headers("fin-9"))
        validate_error(res, ApiErrorId.ERR_SOD_APPROVER_IS_CREATOR)
        assert get_statement(statement["id"])["status"] == "FINALIZED"

    def test_finalize_with_stale_version_rejected(self, api):
        """PRD section 3.9: "A `JobberFinance` operator finalizes a
        `PROVISIONAL` statement — the second OCC-guarded write on this entity —
        carrying `expected_settlement_statement_version` equal to the
        statement's current `version`, failing with `ERR_STALE_VERSION` when a
        revise cycle or another write has advanced it."

        Design: Corner/cross_cutting_complexity/occ_settlement_finalize_stale_rejected
        """
        ctx, statement = self._finalized_statement(api)
        stale_version = statement["version"]
        validate_success(api.dispute_settlement_statement(
            statement["id"], {"reason": "re-check shrink"},
            make_retailer_manager_headers(ctx["store"]["id"])), 200)
        revised = validate_success(api.revise_settlement_statement(
            statement["id"], FINANCE), 200)
        assert revised["version"] > stale_version
        res = api.finalize_settlement_statement(
            statement["id"],
            {"expected_settlement_statement_version": stale_version},
            FINANCE)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)
        after = get_statement(statement["id"])
        assert after["status"] == "PROVISIONAL"
        assert after["gross_scanned_sales_cents"] == 2000, (
            "money fields unchanged by the rejected finalize")
