"""Difficulty: dual_variant_calc — settlement provisional-vs-final; review official-vs-strict."""
from test_helpers import (
    TEST_USERS,
    advance_festival,
    api_client,
    assert_settlement_conservation,
    create_settlement,
    finalize_all,
    finalize_settlement,
    get_review_for_assignment,
    issue_fine,
    make_vendor_spec,
    move_to_settlement_phase,
    open_settlements,
    reconcile_all,
    reconcile_settlement,
    report_sale,
    report_sales,
    respond_fine,
    set_clock,
    setup_active_assignment,
    setup_live_multi,
    validate_paginated,
    validate_success,
    waive_fine,
)

FIN1 = TEST_USERS["finance_headers"]
FIN2 = TEST_USERS["finance2_headers"]
VM = TEST_USERS["vendor_manager_headers"]


def _setup_diverging_settlement():
    """LIVE festival; ACTIVE REVENUE_SHARE 1000bp MARGINAL assignment with two
    100000-cent REPORTED sales; settlement reconciled (provisional snapshot);
    then a late 50000-cent sale and a 25000-cent ACKNOWLEDGED fine; festival
    advanced to SETTLEMENT."""
    scen = setup_active_assignment(
        name="Solstice Fest", fee_model="REVENUE_SHARE",
        terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
        power_needed_amps=30,
    )
    asg_id = scen["assignment"]["id"]
    report_sale(asg_id, scen["vendor"], 100000, "s1-t1")
    report_sale(asg_id, scen["vendor"], 100000, "s1-t2", occurred_at="2026-07-10T15:00:00Z")
    stl = create_settlement(asg_id)
    prov = reconcile_settlement(stl["id"])
    # Late in-window report after reconcile; fine acknowledged before finalize.
    report_sale(asg_id, scen["vendor"], 50000, "s1-t3", occurred_at="2026-07-11T13:00:00Z")
    fine = issue_fine(asg_id, type="WASTE_SORTING", amount_cents=25000)
    respond_fine(fine["id"], scen["vendor"], "ACKNOWLEDGED")
    move_to_settlement_phase(scen)
    scen["settlement"] = prov
    return scen


class TestSettlementProvisionalVsFinal:
    def test_provisional_snapshot_vs_final_figures_diverge(self, api):
        """PRD §3.6: "`provisional_gross_cents` is the sum of `amount_cents` over
        the assignment's transactions currently in `REPORTED`, excluding voided
        ones; `provisional_share_cents` is the festival share over that gross
        under the pinned fee terms with no fine deduction; and
        `provisional_payout_cents` is the provisional gross minus the provisional
        share, floored at zero."
        PRD §3.6: "`gross_sales_cents` includes every non-voided transaction whose
        `occurred_at` lies inside the festival window, including late arrivals
        reported after the last reconcile".

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge
        """
        scen = _setup_diverging_settlement()
        prov = scen["settlement"]
        assert prov["provisional_gross_cents"] == 200000
        assert prov["provisional_share_cents"] == 20000
        assert prov["provisional_payout_cents"] == 180000

        fin = finalize_settlement(prov["id"])
        assert fin["status"] == "FINALIZED"
        assert fin["gross_sales_cents"] == 250000, "late in-window arrival included in final gross"
        assert fin["festival_share_cents"] == 25000
        assert fin["fine_deduction_cents"] == 25000, "ACKNOWLEDGED fine deducted"
        assert fin["vendor_payout_cents"] == 200000
        assert fin["vendor_balance_due_cents"] == 0
        assert prov["provisional_gross_cents"] != fin["gross_sales_cents"]
        assert prov["provisional_payout_cents"] != fin["vendor_payout_cents"]
        assert_settlement_conservation(250000, 25000, 200000, 0, 25000)

    def test_finalize_sweeps_transactions_and_autocreates_review(self, api):
        """PRD §3.6: "Finalization also sweeps every remaining `REPORTED`
        transaction of the assignment to `SETTLED`, records the caller as
        `finalized_by_user_id`, and auto-creates a `PerformanceReview` for the
        assignment in `PENDING` status if none exists."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge
        """
        scen = _setup_diverging_settlement()
        fin = finalize_settlement(scen["settlement"]["id"])
        assert fin["finalized_by_user_id"] == "fin-2"

        txns, txn_meta = validate_paginated(
            api.list_transactions(FIN1, params={"assignment_id": scen["assignment"]["id"]})
        )
        assert txn_meta["total_count"] == 3
        assert all(t["status"] == "SETTLED" for t in txns), "all REPORTED swept to SETTLED"

        review = get_review_for_assignment(scen["assignment"]["id"])
        assert review["status"] == "PENDING", "exactly one auto-created review, PENDING"
        assert review["vendor_id"] == scen["vendor"]["id"]


def _setup_scored_pair_with_waived_fine():
    """Two ACTIVE FLAT_FEE 50000 assignments (A gross 200000, B gross 100000);
    A carries one WAIVED 15000-cent WASTE_SORTING fine; both settlements
    FINALIZED (reconciled by fin-1, finalized by fin-2)."""
    specs = [
        make_vendor_spec("Alpha Eats LLC", "FOOD_HOT", flat_fee_cents=50000, power_draw_amps=30),
        make_vendor_spec("Beta Bowls LLC", "FOOD_COLD", flat_fee_cents=50000, power_draw_amps=20),
    ]
    scen = setup_live_multi(specs, name="Score Fest", zone_power=200)
    report_sales(scen, [[{"amount_cents": 200000, "key": "pa1"}],
                        [{"amount_cents": 100000, "key": "pb1"}]])
    fine = issue_fine(scen["assignments"][0]["id"], type="WASTE_SORTING", amount_cents=15000)
    waive_fine(fine["id"])  # issuer sus-1, waver dir-1 — SoD satisfied
    open_settlements(scen)
    reconcile_all(scen)
    move_to_settlement_phase(scen)
    finalize_all(scen)
    return scen


class TestPerformanceOfficialVsStrict:
    def test_official_variant_excludes_waived_fine(self, api):
        """PRD §3.8: "The `compliance_component` starts at 100 and loses 15 points
        for each of the assignment's fines in `ISSUED`, `ACKNOWLEDGED`, or `PAID`,
        floored at zero."
        PRD §3.8: "the population is every assignment of the same festival whose
        settlement is in `FINALIZED` or `PAID` at compute time, the scored
        assignment included".

        Design: Difficulty/dual_variant_calc/performance_score_official_vs_strict_diverge
        """
        scen = _setup_scored_pair_with_waived_fine()
        review = get_review_for_assignment(scen["assignments"][0]["id"])
        scored = validate_success(api.compute_score(review["id"], VM))
        assert scored["sales_percentile"] == 50, "population {A 200000, B 100000}, one peer below"
        assert scored["compliance_component"] == 100, "WAIVED fine excluded from the official component"
        assert scored["operations_component"] == 100
        assert scored["official_score"] == 80, "round_half_up((40*50 + 30*100 + 30*100)/100)"
        assert scored["status"] == "SCORED", "80 >= 70"

    def test_strict_variant_charges_waived_fine_eight_points(self, api):
        """PRD §3.8: "The `strict_score` uses identical weights, but the
        compliance base is additionally reduced by 8 points per `WAIVED` fine,
        floored at zero: a waiver forgives money, not the incident, so identical
        inputs yield a lower strict score whenever waived fines exist."

        Design: Difficulty/dual_variant_calc/performance_score_official_vs_strict_diverge
        """
        scen = _setup_scored_pair_with_waived_fine()
        review = get_review_for_assignment(scen["assignments"][0]["id"])
        scored = validate_success(api.compute_score(review["id"], VM))
        assert scored["strict_score"] == 78, "round_half_up((40*50 + 30*92 + 30*100)/100) = 78"
        assert scored["strict_score"] < scored["official_score"], (
            "identical inputs; the variants diverge exactly by the waived-fine penalty"
        )
