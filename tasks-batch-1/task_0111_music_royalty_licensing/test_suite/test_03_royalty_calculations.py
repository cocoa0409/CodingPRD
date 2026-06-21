"""Royalty and pricing calculation claims (PRD §3.7) plus the finalize-time
withholding/carry-forward consequences (PRD §3.6).

Covers the performance pool, mechanical statutory tiers, sync quote pricing engine,
provisional-vs-final accounting, and boundary precision at the duration and subtotal
tier crossings.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_sync_license_payload,
    setup_allocated_performance,
    setup_two_holder_mechanical,
    setup_locked_physical_recording_with_mechanical_window,
    ingest_mechanical_usage,
    setup_sync_catalog,
    set_clock,
)

OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Difficulty queue A — dual_variant_calc
# =============================================================================

class TestProvisionalVsFinalPerformance:
    def test_provisional_royalty_exposed_on_event_while_draft(self, api):
        """PRD §3.7: "That raw pool is rounded half up exactly once to produce the
        event's royalty_cents."

        Design: Difficulty/dual_variant_calc/performance_royalty_provisional_vs_final
        """
        ctx = setup_allocated_performance()
        ue = ctx["usage_event"]
        assert ue["royalty_cents"] == 112000, (
            f"Expected 112000 (200000*0.5 + 1000*12*1.0), got {ue['royalty_cents']}"
        )

    def test_lifetime_earned_excludes_provisional_until_finalize(self, api):
        """PRD §2.5: "lifetime_earned_cents is the sum of all EARNING ledger amounts
        across that rightsholder's finalized statements"
        PRD §3.6: "This is the moment at which provisional earnings become final: the
        same EARNING entries that were merely estimates while the statement was DRAFT
        now count toward lifetime_earned_cents."

        Design: Difficulty/dual_variant_calc/performance_royalty_provisional_vs_final
        """
        ctx = setup_allocated_performance()
        holder_id = ctx["holder"]["id"]
        stmt = ctx["statement"]

        before = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert before["lifetime_earned_cents"] == 0, (
            "EARNING on a DRAFT statement is provisional and must not count"
        )

        current = get_success_data(api.get_statement(stmt["id"], OPERATOR))
        validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": current["version"]}, OPERATOR)
        )

        after = get_success_data(api.get_rightsholder(holder_id, OPERATOR))
        assert after["lifetime_earned_cents"] == 112000, (
            "After finalize the same 112000 EARNING now counts toward lifetime_earned_cents"
        )


class TestAdvanceRecoupmentPartialVsFull:
    def test_partial_recoupment_leaves_advance_active(self, api):
        """PRD §3.7: "The eligible share that this advance may take is the current
        remaining gross multiplied by that advance's recoupment_pct, rounded down
        (floored) to whole cents, which guarantees total recoupment never exceeds gross."

        Design: Difficulty/dual_variant_calc/advance_recoupment_full_vs_partial
        """
        # gross = 176000*0.5 + 1000*12*1.0 = 88000 + 12000 = 100000
        ctx = setup_allocated_performance(
            clock="2026-03-15T00:00:00.000Z",
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-04-01T00:00:00.000Z",
            occurred_at="2026-03-15T00:00:00.000Z",
            gross_revenue_cents=176000,
        )
        holder_id = ctx["holder"]["id"]
        adv = get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 80000, "recoupment_pct": 0.5}, TEST_USERS["administrator_headers"]))

        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        assert stmt["gross_earnings_cents"] == 100000, (
            f"perf pool 176000*0.5 + 1000*12 = 100000, got {stmt['gross_earnings_cents']}"
        )
        finalized = validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert finalized["recoupment_applied_cents"] == 50000, (
            "PARTIAL: floor(100000*0.5)=50000 < outstanding 80000"
        )
        assert finalized["net_payable_cents"] == 50000, "100000 - 50000 - 0 withholding"

        adv_after = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after["recouped_cents"] == 50000
        assert adv_after["status"] == "ACTIVE", "partial view: advance stays ACTIVE"

    def test_full_recoupment_marks_advance_recouped(self, api):
        """PRD §3.7: "When the remaining gross fully absorbs all outstanding principal,
        every touched advance reaches RECOUPED"

        Design: Difficulty/dual_variant_calc/advance_recoupment_full_vs_partial
        """
        ctx = setup_allocated_performance(
            clock="2026-03-15T00:00:00.000Z",
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-04-01T00:00:00.000Z",
            occurred_at="2026-03-15T00:00:00.000Z",
        )  # gross 112000
        holder_id = ctx["holder"]["id"]
        adv = get_success_data(api.create_advance(
            {"rightsholder_id": holder_id, "principal_cents": 50000, "recoupment_pct": 1.0}, TEST_USERS["administrator_headers"]))
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        finalized = validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert finalized["recoupment_applied_cents"] == 50000, "full: floor(112000*1.0) capped at outstanding 50000"
        adv_after = get_success_data(api.get_advance(adv["id"], OPERATOR))
        assert adv_after["recouped_cents"] == 50000
        assert adv_after["status"] == "RECOUPED", "full view: advance reaches RECOUPED"


# =============================================================================
# Difficulty queue A — combinatorial_formula
# =============================================================================

class TestSyncQuotePricing:
    def test_sync_quote_circular_territory_tier(self, api):
        """PRD §3.7: "the territory multiplier is selected: if the territory is WW it is
        a flat 2.5 regardless of the subtotal; otherwise, for a single territory, it is
        1.0 when the subtotal is at least 500000 cents (large deals carry no surcharge)
        and 1.2 when the subtotal is below 500000 cents (small deals carry a surcharge)."

        Design: Difficulty/combinatorial_formula/sync_quote_circular_territory_tier_mode_c
        """
        ctx = setup_sync_catalog()
        # base 100000 FILM (2.0) -> sub 200000 (<500000 -> 1.2); 24mo (>=12 -> 1.3)
        # 200000 * 1.2 * 1.3 = 312000
        sl = validate_success(api.create_sync_license(
            create_sync_license_payload(recording_id=ctx["recording"]["id"], licensee_id=ctx["licensee"]["id"],
                                        media_type="FILM", territory="US", term_months=24, base_fee_cents=100000),
            OPERATOR), expected_status=201)
        assert sl["quoted_fee_cents"] == 312000, (
            f"subtotal 200000 -> terr 1.2 -> *term 1.3 = 312000, got {sl['quoted_fee_cents']}"
        )
        assert sl["status"] == "DRAFT"

    def test_sync_quote_worldwide_territory_flat_multiplier(self, api):
        """PRD §3.7: "if the territory is WW it is a flat 2.5 regardless of the subtotal"

        Design: Difficulty/combinatorial_formula/sync_quote_circular_territory_tier_mode_c
        """
        ctx = setup_sync_catalog()
        # base 100000 FILM (2.0) -> sub 200000; WW -> terr 2.5; 24mo -> term 1.3
        # 200000 * 2.5 * 1.3 = 650000
        sl = validate_success(api.create_sync_license(
            create_sync_license_payload(recording_id=ctx["recording"]["id"], licensee_id=ctx["licensee"]["id"],
                                        media_type="FILM", territory="WW", term_months=24, base_fee_cents=100000),
            OPERATOR), expected_status=201)
        assert sl["quoted_fee_cents"] == 650000, (
            f"WW terr flat 2.5: 200000*2.5*1.3 = 650000, got {sl['quoted_fee_cents']}"
        )

    def test_mechanical_pinned_rounding_order(self, api):
        """PRD §3.7: "As with performance, this pool total is rounded once, and only
        then distributed to the recording's master share holders, each receiving the
        pool total multiplied by that holder's split_bps divided by 10000, rounded half
        up once per holder."

        Design: Difficulty/combinatorial_formula/mechanical_rounding_order_mode_b
        """
        ctx = setup_two_holder_mechanical()
        allocated = validate_success(api.allocate_usage_event(ctx["usage_event"]["id"], OPERATOR))
        assert allocated["royalty_cents"] == 11988, (
            f"pool rounded once: rate 12 * qty 999 = 11988, got {allocated['royalty_cents']}"
        )
        stmt_a = get_success_data(api.get_statement(ctx["statement_a"]["id"], OPERATOR))
        stmt_b = get_success_data(api.get_statement(ctx["statement_b"]["id"], OPERATOR))
        assert stmt_a["gross_earnings_cents"] == 3996, (
            "round_half_up(11988*3333/10000) = round(3995.6) = 3996"
        )
        assert stmt_b["gross_earnings_cents"] == 7992, (
            "round_half_up(11988*6667/10000) = round(7992.4) = 7992"
        )
        assert stmt_a["gross_earnings_cents"] + stmt_b["gross_earnings_cents"] == 11988, (
            "holder allocations sum to the once-rounded pool total"
        )

    def test_mechanical_streaming_pool_rounded_once(self, api):
        """PRD §3.7: "for a STREAMING release it is the rate multiplied by quantity
        multiplied by a stream factor of 0.01 (streams pay one percent of the physical
        penny rate per stream), rounded half up"

        Design: Difficulty/combinatorial_formula/mechanical_rounding_order_mode_b
        """
        # A STREAMING recording forces the fractional pool to be rounded once at the
        # pool total: rate 12 * qty 999 * 0.01 = 119.88 -> round_half_up = 120.
        from test_helpers import (
            create_rightsholder, create_registered_work, create_locked_recording,
            grant_window, open_statement,
        )
        set_clock("2026-04-10T00:00:00.000Z")
        holder = create_rightsholder(legal_name="Label Stream", party_type="LABEL", minimum_payout_cents=1)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="STREAMING",
                                       duration_seconds=200)
        grant_window(rec["id"], "MECHANICAL", "2026-04-01T00:00:00.000Z", "2026-05-01T00:00:00.000Z")
        stmt = open_statement(holder["id"], "2026-04-01T00:00:00.000Z", "2026-05-01T00:00:00.000Z")
        ue = ingest_mechanical_usage(rec["id"], "2026-04-10T00:00:00.000Z", quantity=999)
        allocated = validate_success(api.allocate_usage_event(ue["id"], OPERATOR))
        assert allocated["royalty_cents"] == 120, (
            f"round_half_up(12 * 999 * 0.01) = round(119.88) = 120, got {allocated['royalty_cents']}"
        )
        stmt = get_success_data(api.get_statement(stmt["id"], OPERATOR))
        assert stmt["gross_earnings_cents"] == 120, "single 100% holder gets the once-rounded pool"


# =============================================================================
# Difficulty queue A — boundary_precision_check
# =============================================================================

class TestMechanicalDurationTierBoundary:
    def test_duration_360_yields_rate_12(self, api):
        """PRD §3.7: "If duration_seconds is greater than 300, the recording enters the
        long-song tier: the rate is the larger of the 12-cent baseline and 2 cents
        multiplied by the number of started minutes, where started minutes is the
        duration_seconds divided by 60 and rounded up to the next whole minute."

        Design: Difficulty/boundary_precision_check/mechanical_duration_tier_boundary_360_vs_361
        """
        ctx = setup_locked_physical_recording_with_mechanical_window(
            clock="2026-09-10T00:00:00.000Z",
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-10-01T00:00:00.000Z",
            rec_duration=360,
        )
        ue = ingest_mechanical_usage(ctx["recording"]["id"], "2026-09-10T00:00:00.000Z", quantity=100)
        allocated = validate_success(api.allocate_usage_event(ue["id"], OPERATOR))
        # ceil(360/60)=6, rate=max(12, 2*6)=12; 12*100 = 1200
        assert allocated["royalty_cents"] == 1200, (
            f"rate 12 * qty 100 = 1200, got {allocated['royalty_cents']}"
        )

    def test_duration_361_crosses_to_rate_14(self, api):
        """PRD §3.7: "If duration_seconds is greater than 300, the recording enters the
        long-song tier: the rate is the larger of the 12-cent baseline and 2 cents
        multiplied by the number of started minutes, where started minutes is the
        duration_seconds divided by 60 and rounded up to the next whole minute."

        Design: Difficulty/boundary_precision_check/mechanical_duration_tier_boundary_360_vs_361
        """
        ctx = setup_locked_physical_recording_with_mechanical_window(
            clock="2026-09-10T00:00:00.000Z",
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-10-01T00:00:00.000Z",
            rec_duration=361,
        )
        ue = ingest_mechanical_usage(ctx["recording"]["id"], "2026-09-10T00:00:00.000Z", quantity=100)
        allocated = validate_success(api.allocate_usage_event(ue["id"], OPERATOR))
        # ceil(361/60)=7, rate=max(12, 2*7)=14; 14*100 = 1400
        assert allocated["royalty_cents"] == 1400, (
            f"rate 14 * qty 100 = 1400 (tier crosses at 361s), got {allocated['royalty_cents']}"
        )


class TestSyncSubtotalTierBoundary:
    def test_subtotal_exactly_500000_takes_large_deal_tier(self, api):
        """PRD §3.7: "it is 1.0 when the subtotal is at least 500000 cents (large deals
        carry no surcharge) and 1.2 when the subtotal is below 500000 cents (small deals
        carry a surcharge)."

        Design: Difficulty/boundary_precision_check/sync_subtotal_tier_boundary_500000
        """
        ctx = setup_sync_catalog()
        # base 250000 FILM (2.0) -> subtotal 500000 (>= 500000 -> terr 1.0); 1mo -> term 1.0
        # 500000 * 1.0 * 1.0 = 500000
        sl = validate_success(api.create_sync_license(
            create_sync_license_payload(recording_id=ctx["recording"]["id"], licensee_id=ctx["licensee"]["id"],
                                        media_type="FILM", territory="US", term_months=1, base_fee_cents=250000),
            OPERATOR), expected_status=201)
        assert sl["quoted_fee_cents"] == 500000, (
            f"subtotal exactly 500000 hits the >= tier -> terr 1.0, got {sl['quoted_fee_cents']}"
        )

    def test_subtotal_just_below_500000_takes_small_deal_tier(self, api):
        """PRD §3.7: "it is 1.0 when the subtotal is at least 500000 cents (large deals
        carry no surcharge) and 1.2 when the subtotal is below 500000 cents (small deals
        carry a surcharge)."

        Design: Difficulty/boundary_precision_check/sync_subtotal_tier_boundary_500000
        """
        ctx = setup_sync_catalog()
        # base 249999 FILM (2.0) -> subtotal 499998 (<500000 -> terr 1.2); 1mo -> term 1.0
        # round_half_up(499998 * 1.2 * 1.0) = round(599997.6) = 599998
        sl = validate_success(api.create_sync_license(
            create_sync_license_payload(recording_id=ctx["recording"]["id"], licensee_id=ctx["licensee"]["id"],
                                        media_type="FILM", territory="US", term_months=1, base_fee_cents=249999),
            OPERATOR), expected_status=201)
        assert sl["quoted_fee_cents"] == 599998, (
            f"subtotal 499998 below tier -> terr 1.2 -> 599998, got {sl['quoted_fee_cents']}"
        )


# =============================================================================
# Corner queue B — validations: withholding, carry-forward; consistency: immediate
# =============================================================================

class TestFinalizeAccountingCorners:
    def test_withholding_applied_on_finalize(self, api):
        """PRD §3.6: "The system then computes withholding_cents as the gross earnings
        minus the recoupment applied, multiplied by the rightsholder's withholding_pct,
        rounded half up, and appends a WITHHOLDING ledger entry (with source_type
        STATEMENT). It computes net_payable_cents as the gross earnings minus recoupment
        applied minus withholding, floored at 0."

        Design: Corner/validations/withholding_applied_on_finalize
        """
        ctx = setup_allocated_performance(
            clock="2026-09-15T00:00:00.000Z",
            period_start="2026-09-01T00:00:00.000Z",
            period_end="2026-10-01T00:00:00.000Z",
            occurred_at="2026-09-15T00:00:00.000Z",
            withholding_pct=0.10,
        )  # gross 112000
        stmt = get_success_data(api.get_statement(ctx["statement"]["id"], OPERATOR))
        finalized = validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert finalized["withholding_cents"] == 11200, "round_half_up(112000 * 0.10)"
        assert finalized["net_payable_cents"] == 100800, "112000 - 0 recoupment - 11200"

    def test_minimum_payout_carry_forward(self, api):
        """PRD §3.6: "if net_payable_cents is below the rightsholder's
        minimum_payout_cents, that amount is moved into carried_forward_cents and
        net_payable_cents is set to 0"

        Design: Corner/validations/minimum_payout_carry_forward
        """
        # A LABEL holder with the default minimum_payout_cents=5000; a small mechanical
        # gross of 1200 (PHYSICAL rate 12 * qty 100) falls below the threshold.
        from test_helpers import (
            create_rightsholder, create_registered_work, create_locked_recording,
            grant_window, open_statement,
        )
        set_clock("2026-08-15T00:00:00.000Z")
        holder = create_rightsholder(legal_name="RCarry", party_type="LABEL",
                                     minimum_payout_cents=5000, withholding_pct=0)
        work = create_registered_work(holder["id"], pro_affiliation="NONE",
                                       duration_seconds=200, role="PUBLISHER")
        rec = create_locked_recording(work["id"], holder["id"], release_type="PHYSICAL",
                                       duration_seconds=200)
        grant_window(rec["id"], "MECHANICAL", "2026-08-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z")
        stmt = open_statement(holder["id"], "2026-08-01T00:00:00.000Z", "2026-09-01T00:00:00.000Z")
        ue = ingest_mechanical_usage(rec["id"], "2026-08-15T00:00:00.000Z", quantity=100)
        validate_success(api.allocate_usage_event(ue["id"], OPERATOR))

        stmt = get_success_data(api.get_statement(stmt["id"], OPERATOR))
        assert stmt["gross_earnings_cents"] == 1200, "PHYSICAL rate 12 * qty 100"
        finalized = validate_success(
            api.finalize_statement(stmt["id"], {"expected_statement_version": stmt["version"]}, OPERATOR)
        )
        assert finalized["net_payable_cents"] == 0, "1200 is below minimum 5000"
        assert finalized["carried_forward_cents"] == 1200, "carried, not paid"

    def test_allocate_response_shows_royalty_and_status_immediately(self, api):
        """PRD §3.3: "The event's allocated_holder_count is set to the number of distinct
        holders that received an entry, and its status becomes ALLOCATED."

        Design: Corner/consistency_model/allocate_changes_visible_same_response
        """
        ctx = setup_locked_physical_recording_with_mechanical_window(
            clock="2026-01-20T00:00:00.000Z",
            period_start="2026-01-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            rec_duration=200,
        )
        ue = ingest_mechanical_usage(ctx["recording"]["id"], "2026-01-20T00:00:00.000Z", quantity=50)
        allocated = validate_success(api.allocate_usage_event(ue["id"], OPERATOR))
        assert allocated["royalty_cents"] == 600, "rate 12 * qty 50 = 600 (PHYSICAL)"
        assert allocated["status"] == "ALLOCATED", "status visible immediately in the allocate response"
