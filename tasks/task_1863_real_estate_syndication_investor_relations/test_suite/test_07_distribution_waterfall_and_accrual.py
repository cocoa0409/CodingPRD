"""Distribution waterfall (four tiers, GP catch-up, per-line rounding),
pay-time conservation and cascades, and the two preferred-return accrual
variants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    approve_distribution,
    contribution_for,
    create_distribution_payload,
    fund_contribution,
    get_capital_event,
    get_distribution,
    get_offering,
    get_subscription,
    issue_capital_call,
    list_distribution_lines,
    make_executed_capital_event,
    make_published_report,
    set_clock,
    setup_funded_offering,
    setup_offering_with_approved_subscriptions,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


def _lines_by_roc_desc(lines):
    """Attribute lines to LPs without relying on an id field: in these setups
    the larger funded position always has the larger return-of-capital, so
    sorting by return_of_capital_cents descending yields [larger LP, smaller
    LP]."""
    return sorted(lines, key=lambda l: l["return_of_capital_cents"], reverse=True)


def _create_distribution(syn_id, off_id, pool_cents, quarterly_report_id=None,
                         capital_event_id=None):
    return api_client.create_distribution(
        syn_id, off_id,
        create_distribution_payload(
            "QUARTERLY_OPERATING" if quarterly_report_id else "CAPITAL_EVENT",
            pool_cents, quarterly_report_id=quarterly_report_id,
            capital_event_id=capital_event_id),
        SPONSOR)


def _calculate(syn_id, off_id, dist_id):
    return api_client.calculate_distribution(syn_id, off_id, dist_id, SPONSOR)


class TestWaterfallTiers:
    def test_waterfall_full_pool_tiers_exact(self, api):
        """PRD §3.5: "Tier 3 is the GP catch-up: the GP receives one hundred
        percent of the next dollars until the GP's cumulative take equals the
        promote fraction of the sum of the total tier-2 preferred return plus
        the GP's own take. Solving that condition algebraically, the catch-up
        target is the offering's `carried_interest_pct` multiplied by the total
        tier-2 amount and divided by one minus the promote, rounded half-up".
        With A=$60K, B=$40K funded mid-quarter on 2026-02-15, pref 8% simple,
        carry 20%, exactly one full quarter (Q2 2026) elapsed at the
        2026-07-01 calculation, and a 12,000,000c pool: tier-1
        returns 6M/4M, tier-2 accrues 120,000/80,000, tier-3 catch-up is
        round(0.20*200,000/0.80)=50,000 attributed 30,000/20,000, and the
        1,750,000 residual splits 80/20 into LP 1,400,000 (840,000/560,000)
        and GP 350,000 (210,000/140,000).

        Design: Difficulty/combinatorial_formula/waterfall_tier3_gp_catchup_circular
        """
        ctx, calculated = self._run_waterfall(12_000_000)
        assert calculated["status"] == "CALCULATED"
        lines = _lines_by_roc_desc(
            list_distribution_lines(ctx["syn"]["id"], ctx["off"]["id"],
                                    calculated["id"]))
        assert len(lines) == 2
        line_a, line_b = lines
        assert line_a["return_of_capital_cents"] == 6_000_000
        assert line_a["preferred_return_cents"] == 120_000
        assert line_a["profit_split_lp_cents"] == 840_000
        assert line_a["profit_split_gp_cents"] == 240_000
        assert line_a["total_cents"] == 7_200_000
        assert line_b["return_of_capital_cents"] == 4_000_000
        assert line_b["preferred_return_cents"] == 80_000
        assert line_b["profit_split_lp_cents"] == 560_000
        assert line_b["profit_split_gp_cents"] == 160_000
        assert line_b["total_cents"] == 4_800_000

    def test_waterfall_truncated_pool_stops_after_tier2(self, api):
        """PRD §3.5: "The waterfall allocates the pool tier by tier"; tier 1 is
        "the lesser of the total pool and the sum of every LP's
        `unreturned_capital_cents`", tier 2 takes "the lesser of what the pool
        has left after tier 1 and the sum of every LP's accrued preferred
        return", and tiers 3 and 4 allocate only what remains. With exactly
        one full quarter elapsed (funded 2026-02-15 mid-Q1, calculated
        2026-07-01), a pool of
        10,200,000c exactly covers tier 1 (10,000,000) plus tier 2 (200,000),
        so tiers 3 and 4 contribute zero to every line.

        Design: Difficulty/combinatorial_formula/waterfall_tier3_gp_catchup_circular
        """
        ctx, calculated = self._run_waterfall(10_200_000)
        assert calculated["status"] == "CALCULATED"
        lines = _lines_by_roc_desc(
            list_distribution_lines(ctx["syn"]["id"], ctx["off"]["id"],
                                    calculated["id"]))
        assert len(lines) == 2
        line_a, line_b = lines
        assert line_a["return_of_capital_cents"] == 6_000_000
        assert line_a["preferred_return_cents"] == 120_000
        assert line_a["profit_split_lp_cents"] == 0
        assert line_a["profit_split_gp_cents"] == 0
        assert line_a["total_cents"] == 6_120_000
        assert line_b["return_of_capital_cents"] == 4_000_000
        assert line_b["preferred_return_cents"] == 80_000
        assert line_b["profit_split_lp_cents"] == 0
        assert line_b["profit_split_gp_cents"] == 0
        assert line_b["total_cents"] == 4_080_000

    def _run_waterfall(self, pool_cents):
        # Fund mid-quarter (2026-02-15, inside Q1) and calculate at
        # 2026-07-01: exactly one full calendar quarter (Q2 2026) has elapsed
        # between funded_at and calculated_at — Q1 was partial at funding, so
        # the first quarter that can count as full is Q2, whose end the as-of
        # date has passed (PRD §3.8).
        ctx = setup_funded_offering([6_000_000, 4_000_000],
                                    fund_at="2026-02-15T00:00:00Z")
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        set_clock("2026-07-01T00:00:00Z")
        report = make_published_report(syn_id, off_id, report_year=2026,
                                       report_quarter=1, noi_cents=20_000_000)
        dist = validate_success(_create_distribution(
            syn_id, off_id, pool_cents, quarterly_report_id=report["id"]), 201)
        calculated = validate_success(_calculate(syn_id, off_id, dist["id"]))
        return ctx, calculated


class TestDistributionPayConservation:
    def _paid_capital_event_distribution(self):
        """A=$60K / B=$40K funded at 2026-01-01; REFINANCE event executed with
        net 12,000,000c; CAPITAL_EVENT distribution of 12,000,000c paid."""
        ctx = setup_funded_offering([6_000_000, 4_000_000],
                                    fund_at="2026-01-01T00:00:00Z")
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        event = make_executed_capital_event(syn_id, ctx["prop"]["id"],
                                            event_kind="REFINANCE",
                                            gross_proceeds_cents=15_000_000,
                                            debt_payoff_cents=3_000_000)
        set_clock("2026-04-01T00:00:00Z")
        dist = validate_success(_create_distribution(
            syn_id, off_id, 12_000_000, capital_event_id=event["id"]), 201)
        validate_success(_calculate(syn_id, off_id, dist["id"]))
        approve_distribution(syn_id, off_id, dist["id"])
        return ctx, event, dist

    def test_distribution_pay_conserves_pool(self, api):
        """PRD §3.5: "Payment moves it to `PAID` and settles the books in one
        atomic cascade: every line's `paid_at` is stamped; each receiving
        subscription's `accrued_pref_cents` is reduced by the line's
        `preferred_return_cents` and its `unreturned_capital_cents` by the
        line's `return_of_capital_cents`; the offering's
        `total_distributed_cents` grows by `total_distributable_cents`; the
        offering's `unreturned_capital_cents` is recomputed; and if the
        distribution is of kind `CAPITAL_EVENT`, the linked capital event moves
        from `EXECUTED` to `DISTRIBUTED`." PRD §2.6: "the distribution
        waterfall rounds each line individually and sums the rounded lines with
        no reconciliation pass", so the paid lines sum exactly to the pool.

        Design: Difficulty/compensating_invariant/distribution_pay_conserves_pool_across_lines
        """
        ctx, event, dist = self._paid_capital_event_distribution()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        paid = validate_success(api.pay_distribution(syn_id, off_id, dist["id"],
                                                     SPONSOR))
        assert paid["status"] == "PAID"
        lines = list_distribution_lines(syn_id, off_id, dist["id"])
        assert sum(l["total_cents"] for l in lines) == 12_000_000, (
            "sum of line totals must equal total_distributable_cents exactly")
        off_now = get_offering(syn_id, off_id)
        assert off_now["total_distributed_cents"] == 12_000_000

    def test_distribution_pay_debits_subscriptions(self, api):
        """PRD §3.5: "Payment moves it to `PAID` and settles the books in one
        atomic cascade: every line's `paid_at` is stamped; each receiving
        subscription's `accrued_pref_cents` is reduced by the line's
        `preferred_return_cents` and its `unreturned_capital_cents` by the
        line's `return_of_capital_cents`; the offering's
        `total_distributed_cents` grows by `total_distributable_cents`; the
        offering's `unreturned_capital_cents` is recomputed; and if the
        distribution is of kind `CAPITAL_EVENT`, the linked capital event moves
        from `EXECUTED` to `DISTRIBUTED`." Here every LP's unreturned capital
        is fully repaid, so both subscriptions and the offering land at zero
        unreturned capital.

        Design: Difficulty/compensating_invariant/distribution_pay_conserves_pool_across_lines
        """
        ctx, event, dist = self._paid_capital_event_distribution()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b = ctx["subs"]
        validate_success(api.pay_distribution(syn_id, off_id, dist["id"], SPONSOR))

        lines = list_distribution_lines(syn_id, off_id, dist["id"])
        assert len(lines) == 2
        for line in lines:
            assert line["paid_at"], "every line's paid_at must be stamped"
        assert get_subscription(syn_id, off_id,
                                sub_a["id"])["unreturned_capital_cents"] == 0
        assert get_subscription(syn_id, off_id,
                                sub_b["id"])["unreturned_capital_cents"] == 0
        assert get_offering(syn_id, off_id)["unreturned_capital_cents"] == 0


class TestDistributionPayCapitalEventCascade:
    def _approved_sale_distribution(self):
        """One $50K FUNDED subscription; a SALE capital event executed for net
        5,000,000c; an APPROVED CAPITAL_EVENT distribution over the 5,000,000c
        pool."""
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        event = make_executed_capital_event(syn_id, ctx["prop"]["id"],
                                            event_kind="SALE",
                                            gross_proceeds_cents=6_000_000,
                                            debt_payoff_cents=1_000_000)
        dist = validate_success(_create_distribution(
            syn_id, off_id, 5_000_000, capital_event_id=event["id"]), 201)
        validate_success(_calculate(syn_id, off_id, dist["id"]))
        approve_distribution(syn_id, off_id, dist["id"])
        return ctx, event, dist

    def test_distribution_pay_cascades_to_capital_event(self, api):
        """PRD §3.5: "Payment moves it to `PAID` and settles the books in one
        atomic cascade: every line's `paid_at` is stamped; each receiving
        subscription's `accrued_pref_cents` is reduced by the line's
        `preferred_return_cents` and its `unreturned_capital_cents` by the
        line's `return_of_capital_cents`; the offering's
        `total_distributed_cents` grows by `total_distributable_cents`; the
        offering's `unreturned_capital_cents` is recomputed; and if the
        distribution is of kind `CAPITAL_EVENT`, the linked capital event moves
        from `EXECUTED` to `DISTRIBUTED`."

        Design: Difficulty/transitive_cascade/distribution_pay_cascade_to_capital_event
        """
        ctx, event, dist = self._approved_sale_distribution()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        paid = validate_success(api.pay_distribution(syn_id, off_id, dist["id"],
                                                     SPONSOR))
        assert paid["status"] == "PAID"
        event_now = get_capital_event(syn_id, ctx["prop"]["id"], event["id"])
        assert event_now["status"] == "DISTRIBUTED", (
            f"linked capital event must move EXECUTED -> DISTRIBUTED, "
            f"got {event_now['status']}")
        assert get_offering(syn_id, off_id)["total_distributed_cents"] == 5_000_000

    def test_distribution_pay_settles_line_and_subscription(self, api):
        """PRD §3.5: "every line's `paid_at` is stamped; each receiving
        subscription's `accrued_pref_cents` is reduced by the line's
        `preferred_return_cents` and its `unreturned_capital_cents` by the
        line's `return_of_capital_cents`". The single line repays the LP's
        entire 5,000,000c of unreturned capital.

        Design: Difficulty/transitive_cascade/distribution_pay_cascade_to_capital_event
        """
        ctx, event, dist = self._approved_sale_distribution()
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub = ctx["subs"][0]
        validate_success(api.pay_distribution(syn_id, off_id, dist["id"], SPONSOR))

        lines = list_distribution_lines(syn_id, off_id, dist["id"])
        assert len(lines) == 1
        line = lines[0]
        assert line["return_of_capital_cents"] == 5_000_000
        assert line["total_cents"] == 5_000_000
        assert line["paid_at"], "line paid_at must be stamped at payment"
        sub_now = get_subscription(syn_id, off_id, sub["id"])
        assert sub_now["unreturned_capital_cents"] == 0, (
            "unreturned_capital_cents must fall by the line's "
            "return_of_capital_cents")


class TestDistributionInputSetAndLifecycle:
    def test_distribution_calculate_excludes_unfunded(self, api):
        """PRD §3.5: "Calculation stamps `calculated_at` and synthesizes one
        `DistributionLine` per `FUNDED` subscription". A subscription still in
        AWAITING_FUNDING receives no line.

        Design: Corner/calculations/distribution_calculate_excludes_unfunded_subscriptions
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000, 5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub_a, sub_b = ctx["subs"]
        inv_a = ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 10_000_000)
        # Fund only A; B remains AWAITING_FUNDING.
        fund_contribution(syn_id, off_id, call["id"],
                          contribution_for(contribs, sub_a["id"]), inv_a)
        assert get_subscription(syn_id, off_id, sub_b["id"])["status"] == \
            "AWAITING_FUNDING"

        report = make_published_report(syn_id, off_id, report_year=2026,
                                       report_quarter=1, noi_cents=10_000_000)
        dist = validate_success(_create_distribution(
            syn_id, off_id, 1_000_000, quarterly_report_id=report["id"]), 201)
        calculated = validate_success(_calculate(syn_id, off_id, dist["id"]))
        assert calculated["status"] == "CALCULATED"
        lines = list_distribution_lines(syn_id, off_id, dist["id"])
        assert len(lines) == 1, (
            f"exactly one FUNDED subscription means exactly one line, "
            f"got {len(lines)}")
        # The single line is A's: the whole 1,000,000c pool is tier-1 return
        # of capital against A's 5,000,000c unreturned position.
        assert lines[0]["return_of_capital_cents"] == 1_000_000
        assert lines[0]["total_cents"] == 1_000_000

    def test_paid_distribution_cannot_be_approved(self, api):
        """PRD §3.5: "Approval of a `CALCULATED` distribution is the
        OCC-guarded step described in §2.7 — the request must carry
        `expected_distribution_version` matching the distribution's current
        `version`, or it fails with `ERR_STALE_DISTRIBUTION_VERSION` — and
        moves the distribution to `APPROVED`." PRD §2.8: "State-transition
        attempts made against a resource that is not in a state from which the
        requested transition is allowed are rejected with `ERR_INVALID_STATE`
        (HTTP 409)." Approving a PAID distribution is such an attempt.

        Design: Corner/state_machines/terminal_distribution_cannot_be_approved
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        report = make_published_report(syn_id, off_id, report_year=2026,
                                       report_quarter=1, noi_cents=10_000_000)
        dist = validate_success(_create_distribution(
            syn_id, off_id, 1_000_000, quarterly_report_id=report["id"]), 201)
        validate_success(_calculate(syn_id, off_id, dist["id"]))
        approve_distribution(syn_id, off_id, dist["id"])
        paid = validate_success(api.pay_distribution(syn_id, off_id, dist["id"],
                                                     SPONSOR))
        assert paid["status"] == "PAID"

        fresh = get_distribution(syn_id, off_id, dist["id"])
        resp = api.approve_distribution(
            syn_id, off_id, dist["id"],
            {"expected_distribution_version": fresh["version"]}, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_approve_distribution_stale_version(self, api):
        """PRD §2.7: "Approving a distribution requires the request body to
        carry `expected_distribution_version`, holding the distribution's
        `version` as last observed by the approver. If the distribution's
        version has advanced since — for instance because the waterfall was
        recalculated and its distribution lines were regenerated — the approval
        is rejected with `ERR_STALE_DISTRIBUTION_VERSION` (HTTP 412)."

        Design: Corner/errors/error_stale_distribution_version_on_approve
        """
        ctx = setup_funded_offering([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        report = make_published_report(syn_id, off_id, report_year=2026,
                                       report_quarter=1, noi_cents=10_000_000)
        dist = validate_success(_create_distribution(
            syn_id, off_id, 1_000_000, quarterly_report_id=report["id"]), 201)
        stale_version = dist["version"]
        # Calculation advances the distribution's version past the observed one.
        validate_success(_calculate(syn_id, off_id, dist["id"]))
        resp = api.approve_distribution(
            syn_id, off_id, dist["id"],
            {"expected_distribution_version": stale_version}, SPONSOR)
        validate_error(resp, ApiErrorId.ERR_STALE_DISTRIBUTION_VERSION, 412)


class TestPreferredReturnAccrualVariants:
    def test_simple_variant_accrual_exact(self, api):
        """PRD §3.8: "When the offering's `carried_interest_pct` is below 0.25,
        accrual is simple: the annual rate is taken for the fraction of a year
        the capital has been at work — `funded_cents` multiplied by the annual
        rate and by the count of full quarters divided by four, the whole
        product rounded half-up to a whole cent." Funding lands mid-quarter on
        2026-02-15 (inside Q1), so at the 2027-01-01 read the full quarters
        elapsed are Q2, Q3 and Q4 2026: $100,000 at 8% over 3 full quarters
        accrues round(10,000,000 * 0.08 * 3/4) = 600,000c.

        Design: Difficulty/dual_variant_calc/preferred_return_simple_vs_compounding
        """
        ctx = setup_funded_offering([10_000_000], pref=0.08, carry=0.20,
                                    fund_at="2026-02-15T00:00:00Z")
        set_clock("2027-01-01T00:00:00Z")
        sub = get_subscription(ctx["syn"]["id"], ctx["off"]["id"],
                               ctx["subs"][0]["id"])
        assert sub["accrued_pref_cents"] == 600_000, (
            f"simple accrual must be 600000c, got {sub['accrued_pref_cents']}")

    def test_compounding_variant_accrual_exact(self, api):
        """PRD §3.8: "When the `carried_interest_pct` is 0.25 or higher, the
        deal is treated as a high-promote structure and accrual compounds
        quarterly: one plus a quarter of the annual rate is raised to the power
        of the full-quarter count, one is subtracted, the result is multiplied
        by `funded_cents`, and the product is rounded half-up to a whole cent."
        Funding lands mid-quarter on 2026-02-15 (inside Q1), so at the
        2027-01-01 read three full quarters (Q2-Q4 2026) have elapsed:
        $100,000 at 8% accrues round(10,000,000 * (1.02^3 - 1)) = 612,080c.

        Design: Difficulty/dual_variant_calc/preferred_return_simple_vs_compounding
        """
        ctx = setup_funded_offering([10_000_000], pref=0.08, carry=0.30,
                                    fund_at="2026-02-15T00:00:00Z")
        set_clock("2027-01-01T00:00:00Z")
        sub = get_subscription(ctx["syn"]["id"], ctx["off"]["id"],
                               ctx["subs"][0]["id"])
        assert sub["accrued_pref_cents"] == 612_080, (
            f"compounding accrual must be 612080c, "
            f"got {sub['accrued_pref_cents']}")

    def test_variants_diverge_over_three_quarters(self, api):
        """PRD §3.8: "Which of two formulas applies is decided by the deal's
        promote." and "For two or more elapsed quarters the compounding variant
        grows strictly faster than the simple one". Identical principal, rate,
        and three elapsed full quarters (funded mid-quarter 2026-02-15, read
        2027-01-01) diverge by 12,080c solely because one offering chose a
        0.30 promote (compounding) and the other 0.20 (simple).

        Design: Difficulty/dual_variant_calc/preferred_return_simple_vs_compounding
        """
        ctx_a = setup_funded_offering([10_000_000], pref=0.08, carry=0.20,
                                      fund_at="2026-02-15T00:00:00Z")
        ctx_b = setup_funded_offering([10_000_000], pref=0.08, carry=0.30,
                                      fund_at="2026-02-15T00:00:00Z")
        set_clock("2027-01-01T00:00:00Z")
        sub_a = get_subscription(ctx_a["syn"]["id"], ctx_a["off"]["id"],
                                 ctx_a["subs"][0]["id"])
        sub_b = get_subscription(ctx_b["syn"]["id"], ctx_b["off"]["id"],
                                 ctx_b["subs"][0]["id"])
        assert sub_a["accrued_pref_cents"] == 600_000
        assert sub_b["accrued_pref_cents"] == 612_080
        assert sub_b["accrued_pref_cents"] - sub_a["accrued_pref_cents"] == 12_080
