"""Corner: settlement math, tier boundaries, voided input filtering, percentile edge, water budget."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    advance_festival,
    api_client,
    assert_settlement_conservation,
    create_assignment,
    create_booth,
    get_review_for_assignment,
    get_transaction,
    get_zone,
    issue_fine,
    make_vendor_headers,
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
    setup_curated_with_booth,
    setup_finalized_multi,
    setup_finalized_settlement,
    setup_live_multi,
    setup_open_festival,
    setup_submitted_application,
    start_review,
    submit_application,
    create_vendor,
    validate_error,
    validate_success,
)

FIN1 = TEST_USERS["finance_headers"]
FIN2 = TEST_USERS["finance2_headers"]
VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]


class TestFlatFeeSettlement:
    def test_flat_fee_settlement_math(self, api):
        """PRD §3.6: "Under `FLAT_FEE`, it is simply the pinned `flat_fee_cents`."
        PRD §3.6: "Consequently, gross plus balance due always equals share plus
        payout plus deductions applied, exactly."

        Design: Corner/calculations/flat_fee_settlement_math
        """
        scen = setup_finalized_settlement(
            sale_amounts=[300000], fee_model="FLAT_FEE",
            terms={"flat_fee_cents": 120000}, name="Flat Fest",
        )
        stl = scen["settlement"]
        assert stl["gross_sales_cents"] == 300000
        assert stl["festival_share_cents"] == 120000
        assert stl["fine_deduction_cents"] == 0
        assert stl["vendor_payout_cents"] == 180000
        assert stl["vendor_balance_due_cents"] == 0
        assert_settlement_conservation(300000, 120000, 180000, 0, 0)


class TestHybridFee:
    def test_hybrid_fee_guarantee_floor_and_variable(self, api):
        """PRD §3.6: "Under `HYBRID`, the variable component is the pinned
        `revenue_share_pct_bp` multiplied by the excess of gross over
        `free_allowance_cents` (zero when gross does not exceed the allowance),
        divided by 10,000 and rounded half-up to whole cents; the festival share
        is the greater of `minimum_guarantee_cents` and `flat_fee_cents` plus the
        variable component — the allowance gates the variable part while the
        guarantee floors the total."

        Design: Corner/calculations/hybrid_fee_guarantee_floor_and_variable
        """
        hybrid_terms = {"flat_fee_cents": 100000, "revenue_share_pct_bp": 1000,
                        "minimum_guarantee_cents": 150000, "free_allowance_cents": 200000}
        specs = [
            make_vendor_spec("Hybrid X", "FOOD_HOT", fee_model="HYBRID", **hybrid_terms),
            make_vendor_spec("Hybrid Y", "FOOD_COLD", fee_model="HYBRID", **hybrid_terms),
        ]
        sales = [[{"amount_cents": 500000, "key": "hx1"}], [{"amount_cents": 1000000, "key": "hy1"}]]
        scen = setup_finalized_multi(specs, sales, name="Hybrid Fest", zone_power=200)
        stl_x = scen["settlements"][0]
        stl_y = scen["settlements"][1]
        # X: variable 30000, flat+var 130000 < guarantee 150000 -> guarantee binds.
        assert stl_x["festival_share_cents"] == 150000
        assert stl_x["vendor_payout_cents"] == 350000
        # Y: variable 80000, flat+var 180000 >= guarantee -> variable path.
        assert stl_y["festival_share_cents"] == 180000
        assert stl_y["vendor_payout_cents"] == 820000


class TestWholeTierBoundary:
    def test_whole_tier_selection_boundary_at_t1(self, api):
        """PRD §3.6: "Under `WHOLE_TIER` mode, a single multiplier is chosen once
        per transaction — the tier in which the running gross sits after the
        transaction is added (first tier when the new running gross is at most
        500,000 cents, second when at most 2,000,000, otherwise third) — and the
        whole transaction amount is charged at that tier's effective rate."

        Design: Corner/calculations/whole_tier_selection_boundary_at_t1
        """
        specs = [
            make_vendor_spec("T1 X", "FOOD_HOT", fee_model="REVENUE_SHARE",
                             revenue_share_pct_bp=2000, tier_mode="WHOLE_TIER"),
            make_vendor_spec("T1 Y", "FOOD_COLD", fee_model="REVENUE_SHARE",
                             revenue_share_pct_bp=2000, tier_mode="WHOLE_TIER"),
        ]
        scen = setup_live_multi(specs, name="T1 Fest", zone_power=200)
        report_sales(scen, [[{"amount_cents": 500000, "key": "tx1"}],
                            [{"amount_cents": 500001, "key": "ty1"}]])
        settlements = open_settlements(scen)
        rec_x = reconcile_settlement(settlements[0]["id"])
        rec_y = reconcile_settlement(settlements[1]["id"])
        assert rec_x["provisional_share_cents"] == 100000, "running == T1 selects tier 1 (<=)"
        assert rec_y["provisional_share_cents"] == 150000, (
            "running == T1+1 selects tier 2: round_half_up(500001 * 3000 / 10000) = 150000"
        )


class TestVoidedExcluded:
    def test_voided_transaction_excluded_from_gross(self, api):
        """PRD §3.6: "`gross_sales_cents` includes every non-voided transaction
        whose `occurred_at` lies inside the festival window, including late
        arrivals reported after the last reconcile".
        PRD §3.6: "Finalization also sweeps every remaining `REPORTED` transaction
        of the assignment to `SETTLED`".

        Design: Corner/calculations/voided_transaction_excluded_from_gross
        """
        scen = setup_active_assignment(
            name="Void Fest", fee_model="REVENUE_SHARE",
            terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
        )
        asg_id = scen["assignment"]["id"]
        t1 = report_sale(asg_id, scen["vendor"], 100000, "vd1")
        t2 = report_sale(asg_id, scen["vendor"], 70000, "vd2",
                         occurred_at="2026-07-10T15:00:00Z")
        stl = api_client.create_settlement({"assignment_id": asg_id}, FIN1)
        stl = validate_success(stl, expected_status=201)

        voided = validate_success(
            api.void_transaction(t2["id"], {"expected_settlement_version": stl["version"]}, FIN1)
        )
        assert voided["status"] == "VOIDED"

        set_clock("2026-07-13T00:00:00Z")
        advance_festival(scen["festival"]["id"], "SETTLEMENT")
        rec = reconcile_settlement(stl["id"])
        assert rec["provisional_gross_cents"] == 100000, "voided sale excluded from provisional gross"
        fin = validate_success(api.finalize_settlement(stl["id"], FIN2))
        assert fin["gross_sales_cents"] == 100000, "voided sale excluded from final gross"
        assert fin["festival_share_cents"] == 10000
        assert fin["vendor_payout_cents"] == 90000
        assert get_transaction(t1["id"])["status"] == "SETTLED", "survivor swept at finalize"


class TestSingletonPercentile:
    def test_singleton_population_percentile_zero(self, api):
        """PRD §3.8: "the percentile is one hundred times the number of population
        members whose final gross is strictly less than this assignment's final
        gross, divided by the population size, rounded half-up to an integer
        between 0 and 100."
        PRD §3.8: "If the `official_score` is below 70, the review moves directly
        to `INELIGIBLE` rather than `SCORED`."

        Design: Corner/calculations/singleton_population_percentile_zero
        """
        scen = setup_finalized_settlement(sale_amounts=[80000], name="Solo Fest")
        review = get_review_for_assignment(scen["assignment"]["id"])
        scored = validate_success(api.compute_score(review["id"], VM))
        assert scored["sales_percentile"] == 0, "N == 1: no peer is strictly below"
        assert scored["official_score"] == 60, "round_half_up((0 + 3000 + 3000)/100)"
        assert scored["status"] == "INELIGIBLE", "60 < 70 auto-threshold"


class TestWaterBudgetBoundary:
    def test_water_hookup_budget_boundary(self, api):
        """PRD §3.3: "Zone utility admission is inclusive at the boundary. The
        create is rejected with `ERR_POWER_CAPACITY_EXCEEDED` only when the zone's
        `reserved_power_amps` plus the new `power_draw_amps` would exceed
        `power_capacity_amps` — landing exactly on capacity is allowed — and with
        `ERR_WATER_CAPACITY_EXCEEDED` only when the assignment requires water and
        `reserved_water_hookups` plus one would exceed `water_hookup_total`."

        Design: Corner/calculations/water_hookup_budget_boundary
        """
        base = setup_open_festival(name="Water Fest", zone_power=200, zone_water=1)
        fest_id = base["festival"]["id"]
        va = create_vendor(legal_name="Water A", contact_email="a@water.com")
        vb = create_vendor(legal_name="Water B", contact_email="b@water.com")
        appa = submit_application(va, fest_id, category="FOOD_HOT", requires_water=True)
        appb = submit_application(vb, fest_id, category="FOOD_COLD", requires_water=True)
        start_review(appa["id"])
        accept_application(appa["id"], "FLAT_FEE", flat_fee_cents=50000)
        start_review(appb["id"])
        accept_application(appb["id"], "FLAT_FEE", flat_fee_cents=50000)
        advance_festival(fest_id, "CURATED")
        b1 = create_booth(base["zone"]["id"], label="N-01", has_water_hookup=True)
        b2 = create_booth(base["zone"]["id"], label="N-02", has_water_hookup=True)

        first = create_assignment(appa["id"], b1["id"], power_draw_amps=20, requires_water=True)
        assert first["status"] == "RESERVED"
        assert get_zone(base["zone"]["id"])["reserved_water_hookups"] == 1, "1 == water_hookup_total, inclusive"

        resp = api.create_assignment(
            {"application_id": appb["id"], "booth_id": b2["id"],
             "power_draw_amps": 20, "requires_water": True},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_WATER_CAPACITY_EXCEEDED)
