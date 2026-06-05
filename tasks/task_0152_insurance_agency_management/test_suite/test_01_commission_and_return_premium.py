"""Depth tests for the dual-variant return-premium and tiered commission-accrual math.

Queue A (Difficulty) translations for: dual_variant_calc, combinatorial_formula,
and the commission-tier boundary instance of boundary_precision_check.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    make_producer_headers,
    setup_active_policy,
    setup_active_policy_no_split,
    setup_compliant_writer,
    create_quoted_policy,
    add_writing_split,
    bind_policy,
    activate_policy,
    open_statement,
    get_statement,
    finalize_statement,
    set_clock,
    create_account,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


# ===========================================================================
# Rule: dual_variant_calc / return_premium_pro_rata_vs_short_rate
# ===========================================================================
class TestReturnPremiumDualVariant:
    def test_pro_rata_refunds_full_unearned_fraction(self, api):
        """PRD §3.6: "Under the `PRO_RATA` variant, the return premium is the policy's
        `annual_premium_cents` multiplied by the unearned days and divided by the term days,
        with that single result rounded half-up to whole cents; the full unearned fraction
        is refunded with no penalty."

        Design: Difficulty/dual_variant_calc/return_premium_pro_rata_vs_short_rate
        """
        set_clock("2026-07-01T00:00:00Z")
        s = setup_active_policy_no_split(
            ctx=setup_compliant_writer(product_overrides={"cancellation_basis": "PRO_RATA"}),
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            },
        )
        policy = s["policy"]
        resp = api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2026-07-01T00:00:00Z",
                "cancellation_reason": "INSURED_REQUEST",
            },
            MANAGER(),
        )
        data = validate_success(resp, 200)
        assert data["return_premium_cents"] == 604932, data
        assert data["earned_premium_cents"] == 595068, data

    def test_short_rate_retains_ten_percent_penalty(self, api):
        """PRD §3.6: "Under the `SHORT_RATE` variant, the carrier retains a short-rate
        penalty: first take the same pro-rata unearned amount (annual premium times
        unearned days divided by term days), multiply it by one minus the short-rate
        penalty of 0.10 — that is, refund ninety percent of the pro-rata unearned amount —
        and round that result half-up to whole cents once at the end."

        Design: Difficulty/dual_variant_calc/return_premium_pro_rata_vs_short_rate
        """
        set_clock("2026-07-01T00:00:00Z")
        s = setup_active_policy_no_split(
            ctx=setup_compliant_writer(product_overrides={"cancellation_basis": "SHORT_RATE"}),
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-01-01T00:00:00Z",
                "expiration_date": "2027-01-01T00:00:00Z",
            },
        )
        policy = s["policy"]
        resp = api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2026-07-01T00:00:00Z",
                "cancellation_reason": "INSURED_REQUEST",
            },
            MANAGER(),
        )
        data = validate_success(resp, 200)
        assert data["return_premium_cents"] == 544438, data
        assert data["earned_premium_cents"] == 655562, data


# ===========================================================================
# Rule: dual_variant_calc / statement_open_live_vs_finalized_frozen
# ===========================================================================
class TestStatementFrozenVsLive:
    def _setup_finalizable_active_policy(self):
        """Activate a policy 2026-02-01 with a single WRITING split 1.0 (annual 1.2M,
        product new_business 0.20) and open an OPEN statement over [2026-02-01,2026-02-28)."""
        set_clock("2026-02-01T00:00:00Z")
        ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
        )
        s = setup_active_policy(
            ctx=ctx,
            policy_overrides={
                "annual_premium_cents": 1_200_000,
                "effective_date": "2026-02-01T00:00:00Z",
                "expiration_date": "2027-02-01T00:00:00Z",
            },
        )
        stmt = open_statement(ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        return ctx, s["policy"], stmt

    def test_open_statement_gross_reflects_tiered_accrual(self, api):
        """PRD §3.5: "the post-tier agency commission is the previously rounded agency
        commission multiplied by the chosen multiplier, rounded half-up to whole cents
        again."

        Design: Difficulty/dual_variant_calc/statement_open_live_vs_finalized_frozen
        """
        ctx, policy, stmt = self._setup_finalizable_active_policy()
        set_clock("2026-03-01T00:00:00Z")
        data = get_statement(stmt["id"])
        # 1_200_000 * 0.20 = 240000 agency; * 1.10 tier = 264000; * 1.0 split.
        assert data["gross_commission_cents"] == 264000, data
        assert data["net_payable_cents"] == 264000, data

    def test_finalized_figures_frozen_against_later_cancel(self, api):
        """PRD §3.10: "A statement is **finalized** by a `TrustAccountant`, transitioning
        `OPEN → FINALIZED`; this freezes `gross_commission_cents`, `chargeback_cents`, and
        `net_payable_cents` at their currently computed values so they no longer move even
        if underlying policies later cancel."

        Design: Difficulty/dual_variant_calc/statement_open_live_vs_finalized_frozen
        """
        ctx, policy, stmt = self._setup_finalizable_active_policy()
        set_clock("2026-03-01T00:00:00Z")
        finalized = finalize_statement(stmt["id"], stmt["version"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["net_payable_cents"] == 264000, finalized
        # An in-window cancel after finalize must NOT move the frozen figures.
        get_success_data(
            api_client.cancel_policy(
                policy["id"],
                {
                    "expected_policy_version": policy["version"],
                    "cancellation_date": "2026-02-15T00:00:00Z",
                    "cancellation_reason": "INSURED_REQUEST",
                },
                MANAGER(),
            )
        )
        after = get_statement(stmt["id"])
        assert after["net_payable_cents"] == 264000, after
        assert after["status"] == "FINALIZED", after


# ===========================================================================
# Rule: combinatorial_formula / accrual_tiered_rate_with_term_kind_branch
# ===========================================================================
class TestAccrualTieredRateTermKind:
    def _setup_two_split_policy(self):
        """New-business policy annual 1_200_000, product new_business 0.20, WRITING 0.7
        (writer) + SERVICING 0.3 (servicer), activated; OPEN statements for each producer."""
        set_clock("2026-02-01T00:00:00Z")
        ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"},
            producer_overrides={"default_split_pct": 0.7},
        )
        servicer = get_success_data(
            api_client.create_producer(
                factories.create_producer_payload(full_name="Servicer", default_split_pct=0.3),
                ADMIN(),
            )
        )
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=1_200_000,
            effective_date="2026-02-01T00:00:00Z",
            expiration_date="2027-02-01T00:00:00Z",
        )
        wsplit, v_after_w = add_writing_split(ctx, policy, split_pct=0.7, role="WRITING")
        policy_w = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        ssplit, v_after_s = add_writing_split(
            ctx, policy_w, split_pct=0.3, role="SERVICING", producer_id=servicer["id"]
        )
        policy_s = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        bound = bind_policy(ctx, policy["id"], policy_s["version"])
        activate_policy(policy["id"], bound["version"])
        return ctx, servicer, wsplit, ssplit, policy

    def test_writing_split_locks_on_activation(self, api):
        """PRD §3.4: "all of the policy's commission-split rows transition from `DRAFT` to
        `LOCKED` (a cascade down to the splits, each becoming immutable)".

        Design: Difficulty/combinatorial_formula/accrual_tiered_rate_with_term_kind_branch
        """
        ctx, servicer, wsplit, ssplit, policy = self._setup_two_split_policy()
        split = get_success_data(api_client.get_commission_split(wsplit["id"], ADMIN()))
        assert split["status"] == "LOCKED", split

    def test_writing_and_servicing_accrual_via_statement_gross(self, api):
        """PRD §3.5: "each producer's per-split accrual is that post-tier agency commission
        multiplied by the split's `split_pct`, rounded half-up to whole cents independently
        for each split line."

        Design: Difficulty/combinatorial_formula/accrual_tiered_rate_with_term_kind_branch
        """
        ctx, servicer, wsplit, ssplit, policy = self._setup_two_split_policy()
        set_clock("2026-03-01T00:00:00Z")
        # Agency commission 1_200_000 * 0.20 = 240000, * 1.10 tier = 264000.
        w_stmt = open_statement(ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        s_stmt = open_statement(servicer["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        w_data = get_statement(w_stmt["id"])
        s_data = get_statement(s_stmt["id"])
        assert w_data["gross_commission_cents"] == 184800, w_data  # 264000 * 0.7
        assert s_data["gross_commission_cents"] == 79200, s_data   # 264000 * 0.3


# ===========================================================================
# Rule: combinatorial_formula / statement_round_per_line_then_sum_order
# ===========================================================================
class TestStatementRoundPerLineThenSum:
    def _activate_policy_with_writing_half_split(self, ctx, servicer, annual):
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=annual,
            effective_date="2026-02-01T00:00:00Z",
            expiration_date="2027-02-01T00:00:00Z",
        )
        _, v_w = add_writing_split(ctx, policy, split_pct=0.5, role="WRITING")
        policy_w = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        add_writing_split(ctx, policy_w, split_pct=0.5, role="SERVICING", producer_id=servicer["id"])
        policy_s = get_success_data(
            api_client.get_policy(policy["id"], make_producer_headers(ctx["producer"]["id"]))
        )
        bound = bind_policy(ctx, policy["id"], policy_s["version"])
        activate_policy(policy["id"], bound["version"])
        return policy

    def _setup_two_policies_and_statement(self):
        """Two policies (annual 600007, 600008), writer rate 0.077 (carrier default,
        no product override), each WRITING 0.5 + SERVICING 0.5, both activated in the
        window; OPEN statement for the WRITING producer over [2026-02-01,2026-02-28)."""
        set_clock("2026-02-05T00:00:00Z")
        ctx = setup_compliant_writer(
            carrier_overrides={
                "default_new_business_commission_pct": 0.077,
                "default_renewal_commission_pct": 0.05,
            },
            product_overrides={"cancellation_basis": "PRO_RATA"},
            producer_overrides={"default_split_pct": 0.5},
        )
        servicer = get_success_data(
            api_client.create_producer(
                factories.create_producer_payload(full_name="Servicer R", default_split_pct=0.5),
                ADMIN(),
            )
        )
        self._activate_policy_with_writing_half_split(ctx, servicer, 600007)
        self._activate_policy_with_writing_half_split(ctx, servicer, 600008)
        stmt = open_statement(ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        return ctx, stmt

    def test_round_per_line_yields_higher_total_than_sum_then_round(self, api):
        """PRD §3.5: "Because every line is rounded on its own before any summation, a
        statement that later totals a producer's lines sums already-rounded figures rather
        than rounding a grand total."

        Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_order
        """
        ctx, stmt = self._setup_two_policies_and_statement()
        set_clock("2026-03-01T00:00:00Z")
        data = get_statement(stmt["id"])
        # Each writing line = round(round(round(annual*0.077)*1.10)*0.5) = round(25410.5) = 25411.
        # Round-per-line: 25411 + 25411 = 50822 (NOT sum-then-round 50821).
        assert data["gross_commission_cents"] == 50822, data

    def test_per_line_writing_accrual_is_25411(self, api):
        """PRD §3.10: "The `gross_commission_cents` is the sum, over the producer's
        `LOCKED` splits whose policy became `ACTIVE` within the period ... of each split's
        per-line producer accrual computed exactly as in §3.5 — already-rounded per-line
        figures summed, not a re-rounded total."

        Design: Difficulty/combinatorial_formula/statement_round_per_line_then_sum_order
        """
        ctx, stmt = self._setup_two_policies_and_statement()
        set_clock("2026-03-01T00:00:00Z")
        data = get_statement(stmt["id"])
        # Two identical 25411 lines summed.
        assert data["gross_commission_cents"] == 25411 * 2, data


# ===========================================================================
# Rule: boundary_precision_check / commission_tier_boundary_at_exactly_500000
# ===========================================================================
class TestCommissionTierBoundary:
    def _activate_priced_policy(self, ctx, annual):
        policy = create_quoted_policy(
            ctx,
            annual_premium_cents=annual,
            effective_date="2026-02-01T00:00:00Z",
            expiration_date="2027-02-01T00:00:00Z",
        )
        _, v = add_writing_split(ctx, policy, split_pct=1.0, role="WRITING")
        bound = bind_policy(ctx, policy["id"], v)
        activate_policy(policy["id"], bound["version"])
        return policy

    def _setup(self):
        set_clock("2026-02-01T00:00:00Z")
        ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
        )
        high = self._activate_priced_policy(ctx, 500000)
        low = self._activate_priced_policy(ctx, 499999)
        return ctx, high, low

    def test_at_boundary_500000_uses_top_tier(self, api):
        """PRD §3.5: "when it is at least five thousand dollars (500,000 cents or more, with
        the boundary value of exactly 500,000 cents falling in this top tier) the multiplier
        is 1.10".

        Design: Difficulty/boundary_precision_check/commission_tier_boundary_at_exactly_500000
        """
        # Activate the 500000 policy *inside* the statement period so its activation
        # timestamp falls at/after period_start and strictly before period_end
        # (PRD §3.10). The clock is only advanced past period_end afterwards, when
        # the statement is read.
        set_clock("2026-02-01T00:00:00Z")
        high_only_ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
        )
        hp = self._activate_priced_policy(high_only_ctx, 500000)
        # gross = round(round(500000*0.20)*1.10) = round(100000*1.10) = 110000.
        set_clock("2026-03-01T00:00:00Z")
        hs = open_statement(high_only_ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        hdata = get_statement(hs["id"])
        assert hdata["gross_commission_cents"] == 110000, hdata

    def test_below_boundary_499999_uses_middle_tier(self, api):
        """PRD §3.5: "when it is at least one thousand dollars but below five thousand
        dollars (at least 100,000 cents and below 500,000 cents) the multiplier is 1.05".

        Design: Difficulty/boundary_precision_check/commission_tier_boundary_at_exactly_500000
        """
        set_clock("2026-02-01T00:00:00Z")
        low_ctx = setup_compliant_writer(
            product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
        )
        lp = self._activate_priced_policy(low_ctx, 499999)
        set_clock("2026-03-01T00:00:00Z")
        ls = open_statement(low_ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
        ldata = get_statement(ls["id"])
        # round(round(499999*0.20)*1.05) = round(100000*1.05) = 105000.
        assert ldata["gross_commission_cents"] == 105000, ldata
