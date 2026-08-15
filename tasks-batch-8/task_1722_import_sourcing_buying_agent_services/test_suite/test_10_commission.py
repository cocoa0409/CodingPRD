"""Commission calculation: provisional vs final tier re-evaluation, the CIF
base and its 12% cap, and the lower-inclusive GMV tier boundary."""
from test_helpers import (
    accept_quotation,
    advance_to_production_complete,
    book_and_pass_psi,
    create_agent,
    create_buyer,
    create_inspector,
    create_quotation,
    create_sourcing_request,
    get_buyer,
    make_grade_a_factory,
    setup_compliance_docs,
    setup_po_scenario,
    ship_and_close,
)


def _gmv_seed_scenario():
    """Buyer with 9,000,000 YTD GMV (a CLOSED 450 x 20,000 PO at factory f2),
    a main APPAREL quotation from f1 at 25,000/unit, and a booster FURNITURE
    quotation from f2 at 600,000/unit ready to accept."""
    buyer = create_buyer("Buyer One")
    a1 = create_agent("Agent One")
    a2 = create_agent("Agent Two")
    inspector = create_inspector("Inspector Zero", "VN-North")
    f1 = make_grade_a_factory(a1["id"], name="Factory One")
    f2 = make_grade_a_factory(a1["id"], name="Factory Two", country_code="VN")
    setup_compliance_docs(f1["id"], a1["id"], "APPAREL")
    setup_compliance_docs(f2["id"], a1["id"], "FURNITURE")

    sr0 = create_sourcing_request(
        buyer["id"], a1["id"], title="PO0 goods", product_category="FURNITURE",
        target_price_cents=20000, quantity=450,
    )
    q0 = create_quotation(sr0["id"], f2["id"], unit_price_cents=20000, moq=1)
    po0 = accept_quotation(buyer["id"], q0, 450, delivery_month="2026-09")
    ctx0 = {"buyer": buyer, "agent": a1, "factory": f2, "po": po0,
            "inspector": inspector}
    advance_to_production_complete(ctx0)
    book_and_pass_psi(ctx0, lot_size=450)
    ship_and_close(ctx0)

    sr1 = create_sourcing_request(
        buyer["id"], a1["id"], title="Main goods", product_category="APPAREL",
        target_price_cents=25000, quantity=20,
    )
    q1 = create_quotation(sr1["id"], f1["id"], unit_price_cents=25000, moq=1)
    srB = create_sourcing_request(
        buyer["id"], a2["id"], title="Booster goods", product_category="FURNITURE",
        target_price_cents=600000, quantity=10,
    )
    qB = create_quotation(srB["id"], f2["id"], unit_price_cents=600000, moq=1)
    return {"buyer": buyer, "a1": a1, "a2": a2, "inspector": inspector,
            "f1": f1, "f2": f2, "q1": q1, "qB": qB}


class TestProvisionalVsFinalVariant:
    def test_provisional_commission_uses_post_accept_basis(self, api):
        """PRD: "For the provisional variant the basis is evaluated **after** the new PO's `total_cents` is included."
        PRD: "- basis below 10,000,000 cents → rate 500 basis points (5%)."
        Basis 9,000,000 + 500,000 = 9,500,000 < 10,000,000 -> 5% of 500,000 = 25,000.

        Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_tier_shift
        """
        sc = _gmv_seed_scenario()
        po1 = accept_quotation(sc["buyer"]["id"], sc["q1"], 20,
                               delivery_month="2026-10")
        assert po1["total_cents"] == 500000
        assert po1["provisional_commission_cents"] == 25000
        assert po1["commission_rate_bp"] == 500
        assert get_buyer(sc["buyer"]["id"])["ytd_gmv_cents"] == 9500000

    def test_final_commission_reevaluates_tier_at_close(self, api):
        """PRD: "For the final variant the basis is re-evaluated at close time, reflecting every PO accepted since."
        PRD: "The two variants share the tiered structure but evaluate their tier basis at different times, so the final figure may differ from the provisional even for identical PO data."
        A 6,000,000 booster PO accepted after PO1 lifts the close-time basis to
        15,500,000 (>= 10,000,000 -> 4%): final 20,000 vs provisional 25,000.

        Design: Difficulty/dual_variant_calc/commission_provisional_vs_final_tier_shift
        """
        sc = _gmv_seed_scenario()
        po1 = accept_quotation(sc["buyer"]["id"], sc["q1"], 20,
                               delivery_month="2026-10")
        assert po1["provisional_commission_cents"] == 25000
        poB = accept_quotation(sc["buyer"]["id"], sc["qB"], 10,
                               delivery_month="2026-10")
        assert poB["total_cents"] == 6000000

        ctx1 = {"buyer": sc["buyer"], "agent": sc["a1"], "factory": sc["f1"],
                "po": po1, "inspector": sc["inspector"]}
        advance_to_production_complete(ctx1)
        book_and_pass_psi(ctx1, lot_size=20)
        ship_and_close(ctx1)
        closed = ctx1["po"]
        assert closed["status"] == "CLOSED"
        assert get_buyer(sc["buyer"]["id"])["ytd_gmv_cents"] == 15500000
        assert closed["commission_rate_bp"] == 400
        assert closed["final_commission_cents"] == 20000


class TestCifCap:
    def test_cif_commission_capped_at_12_percent_of_goods(self, api):
        """PRD: "For `FOB`, the base is `po.total_cents`. For `CIF`, the base is `po.total_cents + po.freight_cents + po.insurance_cents`."
        PRD: "For `CIF` only, the result is then capped at `po.total_cents` multiplied by 0.12, with that cap rounded half-up to integer cents; the commission is the smaller of the two."
        CIF base 100,000 + 300,000 + 0 = 400,000; 5% = 20,000; cap 12,000 binds.

        Design: Difficulty/combinatorial_formula/commission_cif_cap_binds_over_tier_rate
        """
        ctx = setup_po_scenario(
            category="APPAREL", unit_price_cents=10000, ordered_qty=10,
            commission_mode="CIF", freight_cents=300000, insurance_cents=0,
            with_docs=False,
        )
        po = ctx["po"]
        assert po["total_cents"] == 100000
        assert po["commission_rate_bp"] == 500
        assert po["provisional_commission_cents"] == 12000

    def test_fob_commission_ignores_freight_on_identical_goods(self, api):
        """PRD: "For `FOB`, the base is `po.total_cents`. For `CIF`, the base is `po.total_cents + po.freight_cents + po.insurance_cents`."
        PRD: "The commission is `base * rate_bp / 10000`, rounded half-up to 0 decimal places (integer cents)."
        Identical goods and freight under FOB: base is goods only, 5% of
        100,000 = 5,000 — no cap applies outside CIF.

        Design: Difficulty/combinatorial_formula/commission_cif_cap_binds_over_tier_rate
        """
        ctx = setup_po_scenario(
            category="APPAREL", unit_price_cents=10000, ordered_qty=10,
            commission_mode="FOB", freight_cents=300000, insurance_cents=0,
            with_docs=False,
        )
        po = ctx["po"]
        assert po["total_cents"] == 100000
        assert po["commission_rate_bp"] == 500
        assert po["provisional_commission_cents"] == 5000


class TestTierBoundary:
    def _boundary_scenario(self):
        """Buyers A (YTD 9,800,000) and B (YTD 9,799,999), each holding a
        200,000-cent quotation from the same grade-A factory."""
        buyer_a = create_buyer("Buyer A")
        buyer_b = create_buyer("Buyer B")
        agent = create_agent("Agent One")
        factory = make_grade_a_factory(agent["id"])
        result = {}
        for tag, buyer, seed_price in (("A", buyer_a, 9800000), ("B", buyer_b, 9799999)):
            sr_seed = create_sourcing_request(
                buyer["id"], agent["id"], title=f"{tag} seed",
                product_category="FURNITURE", target_price_cents=seed_price,
                quantity=1,
            )
            q_seed = create_quotation(sr_seed["id"], factory["id"],
                                      unit_price_cents=seed_price, moq=1)
            accept_quotation(buyer["id"], q_seed, 1, delivery_month="2026-08")
            sr_main = create_sourcing_request(
                buyer["id"], agent["id"], title=f"{tag} main",
                product_category="APPAREL", target_price_cents=200000, quantity=1,
            )
            result[tag] = (buyer, create_quotation(sr_main["id"], factory["id"],
                                                   unit_price_cents=200000, moq=1))
        return result

    def test_commission_tier_boundary_exact_10m_rates_400bp(self, api):
        """PRD: "- basis at least 10,000,000 and below 50,000,000 cents → rate 400 basis points (4%). A basis of exactly 10,000,000 therefore yields 4%, not 5%."
        9,800,000 + 200,000 = 10,000,000 exactly -> 4% of 200,000 = 8,000.

        Design: Difficulty/boundary_precision_check/commission_tier_boundary_inclusive_lower_edge
        """
        scenario = self._boundary_scenario()
        buyer_a, q_main = scenario["A"]
        po = accept_quotation(buyer_a["id"], q_main, 1, delivery_month="2026-10")
        assert get_buyer(buyer_a["id"])["ytd_gmv_cents"] == 10000000
        assert po["commission_rate_bp"] == 400
        assert po["provisional_commission_cents"] == 8000

    def test_commission_tier_one_cent_below_rates_500bp(self, api):
        """PRD: "- basis below 10,000,000 cents → rate 500 basis points (5%)."
        PRD: "The tier boundaries are inclusive on the lower edge:"
        9,799,999 + 200,000 = 9,999,999 < 10,000,000 -> 5% of 200,000 = 10,000.

        Design: Difficulty/boundary_precision_check/commission_tier_boundary_inclusive_lower_edge
        """
        scenario = self._boundary_scenario()
        buyer_b, q_main = scenario["B"]
        po = accept_quotation(buyer_b["id"], q_main, 1, delivery_month="2026-10")
        assert get_buyer(buyer_b["id"])["ytd_gmv_cents"] == 9999999
        assert po["commission_rate_bp"] == 500
        assert po["provisional_commission_cents"] == 10000
