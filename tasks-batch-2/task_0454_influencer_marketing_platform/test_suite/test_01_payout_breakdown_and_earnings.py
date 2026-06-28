"""Payout breakdown, year-to-date earnings, and performance dual variants.

Queue A (Difficulty) translations for dual_variant_calc, combinatorial_formula,
and the YTD boundary, plus the corresponding corner-design empty-set edge.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    make_admin_headers, make_compliance_headers, make_brand_headers,
    setup_active_contract, setup_fulfilled_contract, setup_released_payout,
    create_attribution_asset, ingest_conversion,
    api_client,
)

ADMIN = make_admin_headers()
COMPLIANCE = make_compliance_headers()


class TestPayoutBreakdown:
    def test_payout_w9_creator_zero_withholding_net(self, api):
        """PRD §3.9: "The backup tax withholding, tax_withholding_cents, applies only
        when the creator's tax_id_on_file is false: it is 24% of the gross-minus-platform-fee
        remainder, rounded half up to whole cents once. When tax_id_on_file is true, the
        withholding is 0. The net, net_amount_cents, is the gross minus the platform fee
        minus the tax withholding."
        PRD §3.9: "The first $1,000 of gross (the first 100,000 cents) is charged at 20%".

        gross 80000 (all in tier1) -> platform_fee 16000; W-9 -> withholding 0 -> net 64000.

        Design: Difficulty/dual_variant_calc/payout_breakdown_w9_vs_backup_withholding
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, creator_tax_id_on_file=True)
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]},
            COMPLIANCE,
        )
        payout = validate_success(resp, expected_status=201)
        assert payout["gross_amount_cents"] == 80000
        assert payout["platform_fee_cents"] == 16000
        assert payout["tax_withholding_cents"] == 0
        assert payout["net_amount_cents"] == 64000

    def test_payout_no_w9_creator_backup_withholding_net(self, api):
        """PRD §3.9: "The backup tax withholding, tax_withholding_cents, applies only
        when the creator's tax_id_on_file is false: it is 24% of the gross-minus-platform-fee
        remainder, rounded half up to whole cents once. When tax_id_on_file is true, the
        withholding is 0. The net, net_amount_cents, is the gross minus the platform fee
        minus the tax withholding."

        gross 80000 -> fee 16000; remainder 64000; withholding round(64000*0.24)=15360;
        net 80000-16000-15360 = 48640.

        Design: Difficulty/dual_variant_calc/payout_breakdown_w9_vs_backup_withholding
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, creator_tax_id_on_file=False)
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]},
            COMPLIANCE,
        )
        payout = validate_success(resp, expected_status=201)
        assert payout["gross_amount_cents"] == 80000
        assert payout["platform_fee_cents"] == 16000
        assert payout["tax_withholding_cents"] == 15360
        assert payout["net_amount_cents"] == 48640

    def test_payout_marginal_tier_fee_straddles_tiers(self, api):
        """PRD §3.9: "The first $1,000 of gross (the first 100,000 cents) is charged at 20%;
        the portion of gross between $1,000 and $5,000 (from 100,000 up to 500,000 cents) is
        charged at 15%; and any portion of gross above $5,000 (above 500,000 cents) is charged
        at 10%. Compute each tier's contribution on its own slice of the gross, sum the three
        contributions, and round that sum half up to whole cents exactly once".

        gross 300000 -> 100000*0.20 + 200000*0.15 = 20000 + 30000 = 50000 (not flat 20%);
        W-9 -> withholding 0 -> net 250000.

        Design: Difficulty/combinatorial_formula/payout_marginal_tier_fee_mode_a
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=300_000, creator_tax_id_on_file=True,
                                       campaign_budget_cents=400_000, content_type="VIDEO")
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]},
            COMPLIANCE,
        )
        payout = validate_success(resp, expected_status=201)
        assert payout["gross_amount_cents"] == 300000
        assert payout["platform_fee_cents"] == 50000
        assert payout["tax_withholding_cents"] == 0
        assert payout["net_amount_cents"] == 250000

    def test_payout_single_tier_fee_below_first_cap(self, api):
        """PRD §3.9: "The first $1,000 of gross (the first 100,000 cents) is charged at 20%".
        PRD §3.9: "Compute each tier's contribution on its own slice of the gross, sum the
        three contributions, and round that sum half up to whole cents exactly once".

        A gross entirely within tier 1 (80000) is charged a flat 20% on that slice -> 16000,
        confirming the marginal formula degenerates to the first tier alone below 100000.

        Design: Difficulty/combinatorial_formula/payout_marginal_tier_fee_mode_a
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, creator_tax_id_on_file=True)
        resp = api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]},
            COMPLIANCE,
        )
        payout = validate_success(resp, expected_status=201)
        assert payout["gross_amount_cents"] == 80000
        assert payout["platform_fee_cents"] == 16000
        assert payout["net_amount_cents"] == 64000


class TestYearToDateEarnings:
    def test_ytd_is_sum_of_per_payout_rounded_nets(self, api):
        """PRD §2.6: "The year-to-date total a creator accumulates is the sum of
        already-rounded per-payout net amounts — it must never be re-derived from raw fee
        and withholding fractions and rounded in aggregate, because that would drift by
        accumulated sub-cent remainders."
        PRD §3.9: "the creator's ytd_paid_cents increases by the same net amount."

        Two W-9 payouts: gross 50000 -> net 40000, gross 40000 -> net 32000; ytd == 72000.

        Design: Difficulty/combinatorial_formula/ytd_round_per_payout_then_sum_mode_b
        """
        brand = get_success_data(api.create_brand(
            {"legal_name": "Delta", "contact_email": "d@d.com", "budget_cents": 1_000_000}, ADMIN))
        creator = get_success_data(api.create_creator(
            {"handle": "@ytd_sum", "primary_platform": "INSTAGRAM", "tax_id_on_file": True}, ADMIN))
        get_success_data(api.create_audience_snapshot(creator["id"], {
            "follower_count": 80000, "avg_engagement_rate": 0.05,
            "estimated_reach": 40000, "fake_follower_pct": 0.05}, ADMIN))

        net1 = self._sign_fulfill_settle(api, brand["id"], creator["id"], 50_000,
                                         "C1a", "2026-02-01T00:00:00Z", "2026-02-15T00:00:00Z")
        net2 = self._sign_fulfill_settle(api, brand["id"], creator["id"], 40_000,
                                         "C2a", "2026-04-01T00:00:00Z", "2026-04-15T00:00:00Z")
        assert net1 == 40000
        assert net2 == 32000

        refreshed = get_success_data(api.get_creator(creator["id"], COMPLIANCE))
        assert refreshed["ytd_paid_cents"] == 72000

    def test_ytd_single_settled_payout_equals_its_rounded_net(self, api):
        """PRD §2.6: "The year-to-date total a creator accumulates is the sum of
        already-rounded per-payout net amounts — it must never be re-derived from raw fee
        and withholding fractions and rounded in aggregate".
        PRD §3.9: "the creator's ytd_paid_cents increases by the same net amount."

        A single W-9 payout of gross 50000 nets 40000; after settle, ytd == 40000, i.e. the
        already-rounded per-payout net itself.

        Design: Difficulty/combinatorial_formula/ytd_round_per_payout_then_sum_mode_b
        """
        ctx = setup_released_payout(offer_amount_cents=50_000, campaign_budget_cents=100_000,
                                    content_type="STORY")
        assert ctx["payout"]["net_amount_cents"] == 40000
        validate_success(api.settle_payout(ctx["payout"]["id"], COMPLIANCE))
        creator = get_success_data(api.get_creator(ctx["creator"]["id"], COMPLIANCE))
        assert creator["ytd_paid_cents"] == 40000

    def _sign_fulfill_settle(self, api, brand_id, creator_id, amount, title, starts, ends):
        bh = make_brand_headers(brand_id)
        from test_helpers import make_creator_headers
        ch = make_creator_headers(creator_id)
        camp = get_success_data(api.create_campaign(
            {"brand_id": brand_id, "title": title, "campaign_budget_cents": 100_000,
             "requires_ftc_disclosure": False, "starts_at": starts, "ends_at": ends}, bh))
        deliv = get_success_data(api.create_deliverable(
            camp["id"], {"content_type": "STORY", "quantity": 1,
                         "due_at": starts, "base_rate_cents": amount}, bh))
        get_success_data(api.open_campaign(
            camp["id"], {"expected_campaign_version": camp["version"]}, bh))
        offer = get_success_data(api.create_offer(
            {"campaign_id": camp["id"], "creator_id": creator_id,
             "current_amount_cents": amount, "exclusivity_days": 0}, bh))
        accepted = get_success_data(api.accept_offer(
            offer["id"], {"expected_offer_version": offer["version"]}, ch))
        contract = get_success_data(api.create_contract(
            {"offer_id": offer["id"], "expected_offer_version": accepted["version"]}, bh))
        sub = get_success_data(api.create_content_submission(
            {"deliverable_id": deliv["id"], "contract_id": contract["id"],
             "media_url": "https://x/c", "caption": "ok"}, ch))
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        get_success_data(api.approve_content(sub["id"], COMPLIANCE))
        kv = get_success_data(api.get_contract(contract["id"], COMPLIANCE))["version"]
        payout = get_success_data(api.create_payout(
            {"contract_id": contract["id"], "expected_contract_version": kv}, COMPLIANCE))
        get_success_data(api.release_payout(payout["id"], COMPLIANCE))
        settled = get_success_data(api.settle_payout(payout["id"], COMPLIANCE))
        return get_success_data(api.get_payout(payout["id"], COMPLIANCE))["net_amount_cents"]

    def test_ytd_1099_threshold_triggers_at_exactly_600(self, api):
        """PRD §3.9: "if the creator's post-update ytd_paid_cents is at or above the 1099
        reporting threshold of $600.00 (60,000 cents) and the creator does not yet have a
        1099 form for the current tax year, a TaxForm1099 is auto-generated in GENERATED status."

        gross 75000, W-9 -> fee round(75000*0.20)=15000 -> net 60000 == threshold exactly,
        so a 1099 IS generated.

        Design: Difficulty/boundary_precision_check/ytd_1099_threshold_at_exactly_600
        """
        ctx = setup_released_payout(offer_amount_cents=75_000, content_type="VIDEO")
        settled = validate_success(api.settle_payout(ctx["payout"]["id"], COMPLIANCE))
        creator = get_success_data(api.get_creator(ctx["creator"]["id"], COMPLIANCE))
        assert creator["ytd_paid_cents"] == 60000

        forms = validate_success(api.list_creator_tax_forms(ctx["creator"]["id"], COMPLIANCE))
        assert len(forms) == 1
        assert forms[0]["total_reported_cents"] == 60000
        assert forms[0]["status"] == "GENERATED"

    def test_ytd_1099_threshold_just_below_600_no_form(self, api):
        """PRD §3.9: "if the creator's post-update ytd_paid_cents is at or above the 1099
        reporting threshold of $600.00 (60,000 cents) and the creator does not yet have a
        1099 form for the current tax year, a TaxForm1099 is auto-generated in GENERATED status."

        Boundary X-1: a net of 48640 (gross 80000, no W-9) leaves ytd below 60000, so NO form.

        Design: Difficulty/boundary_precision_check/ytd_1099_threshold_at_exactly_600
        """
        ctx = setup_fulfilled_contract(offer_amount_cents=80_000, creator_tax_id_on_file=False)
        # Put W-9 on file so release/settle is allowed but net stays the below-threshold value
        # already frozen at payout creation.
        payout = get_success_data(api.create_payout(
            {"contract_id": ctx["contract"]["id"],
             "expected_contract_version": ctx["contract_version"]}, COMPLIANCE))
        assert payout["net_amount_cents"] == 48640
        # Update creator to put W-9 on file so the release gate passes.
        creator = get_success_data(api.get_creator(ctx["creator"]["id"], COMPLIANCE))
        get_success_data(api.update_creator(
            ctx["creator"]["id"],
            {"tax_id_on_file": True, "expected_creator_version": creator["version"]},
            ADMIN))
        get_success_data(api.release_payout(payout["id"], COMPLIANCE))
        get_success_data(api.settle_payout(payout["id"], COMPLIANCE))
        refreshed = get_success_data(api.get_creator(ctx["creator"]["id"], COMPLIANCE))
        assert refreshed["ytd_paid_cents"] == 48640
        forms = validate_success(api.list_creator_tax_forms(ctx["creator"]["id"], COMPLIANCE))
        assert len(forms) == 0


class TestPerformanceMetrics:
    def test_performance_estimated_variant_before_settlement(self, api):
        """PRD §3.8: "While the contract's payout is not yet SETTLED, the read uses the
        estimated variant, and the cost basis is the contract's contracted_rate_cents — the
        committed fee before any platform fee or withholding."
        PRD §3.8: "Cost-per-mille is the cost basis converted from cents to dollars (divided
        by 100), divided by the impressions count expressed in thousands (impressions divided
        by 1000), rounded half up to two decimal places."
        PRD §3.8: "Return-on-ad-spend is the sale-revenue in cents divided by the cost basis
        in cents, rounded half up to four decimal places."

        cost_basis 80000c; 100000 impressions, 4000 engagements, 320000c revenue ->
        cpm (800/100)=8.00; cpe 800/4000=0.20; roas 320000/80000=4.0000.

        Design: Difficulty/dual_variant_calc/performance_estimated_vs_actual_on_contract
        """
        ctx = setup_active_contract(offer_amount_cents=80_000, base_rate_cents=80_000,
                                    campaign_budget_cents=500_000)
        asset = create_attribution_asset(ctx["brand"]["id"], ctx["contract"]["id"],
                                         asset_type="TRACKING_LINK", code_or_slug="perf-est")
        ingest_conversion(asset["id"], "IMPRESSION", 100000)
        ingest_conversion(asset["id"], "ENGAGEMENT", 4000)
        ingest_conversion(asset["id"], "SALE", 50, revenue_cents=320000)

        bh = make_brand_headers(ctx["brand"]["id"])
        perf = validate_success(api.get_contract_performance(ctx["contract"]["id"], bh))
        assert perf["variant"] == "estimated"
        assert perf["cost_basis_cents"] == 80000
        assert perf["impressions"] == 100000
        assert perf["engagements"] == 4000
        assert perf["sale_revenue_cents"] == 320000
        assert perf["cpm"] == pytest.approx(8.00, abs=0.001)
        assert perf["cpe"] == pytest.approx(0.20, abs=0.001)
        assert perf["roas"] == pytest.approx(4.0000, abs=0.0001)

    def test_performance_actual_variant_after_settlement(self, api):
        """PRD §3.8: "Once the contract's payout has reached SETTLED, the read switches to
        the actual variant, and the cost basis becomes the payout's net_amount_cents — what
        the brand actually paid out".
        PRD §3.8: "Return-on-ad-spend is the sale-revenue in cents divided by the cost basis
        in cents, rounded half up to four decimal places."

        After settle, net 64000 (W-9, gross 80000); same conversions give cpm 6.40 and
        roas 320000/64000 = 5.0000.

        Design: Difficulty/dual_variant_calc/performance_estimated_vs_actual_on_contract
        """
        ctx = setup_active_contract(offer_amount_cents=80_000, base_rate_cents=80_000,
                                    campaign_budget_cents=500_000, creator_tax_id_on_file=True)
        asset = create_attribution_asset(ctx["brand"]["id"], ctx["contract"]["id"],
                                         asset_type="TRACKING_LINK", code_or_slug="perf-act")
        ingest_conversion(asset["id"], "IMPRESSION", 100000)
        ingest_conversion(asset["id"], "ENGAGEMENT", 4000)
        ingest_conversion(asset["id"], "SALE", 50, revenue_cents=320000)
        # Drive to FULFILLED then settle the payout.
        from test_helpers import make_creator_headers, submit_content, start_review, approve_content
        submit_content(ctx["creator"]["id"], ctx["deliverable"]["id"], ctx["contract"]["id"], caption="ok")
        sub = get_success_data(api.list_content_submissions(
            COMPLIANCE, params={"contract_id": ctx["contract"]["id"]}))[0]
        get_success_data(api.start_review(sub["id"], COMPLIANCE))
        get_success_data(api.approve_content(sub["id"], COMPLIANCE))
        kv = get_success_data(api.get_contract(ctx["contract"]["id"], COMPLIANCE))["version"]
        payout = get_success_data(api.create_payout(
            {"contract_id": ctx["contract"]["id"], "expected_contract_version": kv}, COMPLIANCE))
        get_success_data(api.release_payout(payout["id"], COMPLIANCE))
        get_success_data(api.settle_payout(payout["id"], COMPLIANCE))

        bh = make_brand_headers(ctx["brand"]["id"])
        perf = validate_success(api.get_contract_performance(ctx["contract"]["id"], bh))
        assert perf["variant"] == "actual"
        assert perf["cost_basis_cents"] == 64000
        assert perf["cpm"] == pytest.approx(6.40, abs=0.001)
        assert perf["roas"] == pytest.approx(5.0000, abs=0.0001)

    def test_performance_zero_conversions_empty_set(self, api):
        """PRD §3.8: "impressions is the sum of count over conversion events whose event_type
        is IMPRESSION; engagements is the sum of count over events whose event_type is
        ENGAGEMENT; and sale revenue is the sum of revenue_cents over events whose event_type
        is SALE."
        PRD §3.8: "Return-on-ad-spend is the sale-revenue in cents divided by the cost basis
        in cents, rounded half up to four decimal places."

        With no conversion events, impressions/engagements/sale_revenue are 0 and roas 0.0000.

        Design: Corner/calculations/performance_zero_impressions_empty_set_edge
        """
        ctx = setup_active_contract(offer_amount_cents=60_000, base_rate_cents=60_000)
        create_attribution_asset(ctx["brand"]["id"], ctx["contract"]["id"],
                                 asset_type="TRACKING_LINK", code_or_slug="pz-link")
        bh = make_brand_headers(ctx["brand"]["id"])
        perf = validate_success(api.get_contract_performance(ctx["contract"]["id"], bh))
        assert perf["impressions"] == 0
        assert perf["engagements"] == 0
        assert perf["sale_revenue_cents"] == 0
        assert perf["roas"] == pytest.approx(0.0000, abs=0.0001)
