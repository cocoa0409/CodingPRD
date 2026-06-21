"""Calculations: guaranty fee tiers, secondary-market premium, collateral coverage,
liquidation split, and guaranty-purchase payout (clean vs repaired).

Covers difficulty rules dual_variant_calc and combinatorial_formula, plus corner
calculations instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    reach_authorized, reach_approved, reach_sold, reach_defaulted,
    reach_pending_approval,
    offer_guaranty_sale, settle_guaranty_sale,
    open_liquidation, file_guaranty_purchase,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
APPROVER = TEST_USERS["credit_approver_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


# ─── guaranty_fee tiered schedule (corner calculations) ───────────────────────

def test_guaranty_fee_tier_boundary_at_tier1(api):
    """PRD §3.6: "The tier boundaries are inclusive at the lower tier: a gross amount
    sitting exactly at 15,000,000 cents lies wholly in the first band and attracts only
    the 2.00 percent rate, and the first cent above a threshold is the first to attract
    the next band's higher rate."
    PRD §3.6: "the first band uses a rate of 2.00 percent".

    Design: Corner/calculations/guaranty_fee_tier_boundary_at_tier1
    """
    # gross exactly 15000000, gp 0.80; short-term (maturity 60) collateral EQUIPMENT
    # 16000000 net floor(16000000*0.5)=8000000 >= required floor(15000000*0.5)=7500000.
    ctx = reach_approved(
        app_overrides={"requested_amount_cents": 15_000_000, "guaranty_pct": 0.80, "maturity_months": 60},
        borrower_overrides={"naics_code": "333120"},
        proceeds_amount=15_000_000,
        collateral_specs=[{"asset_type": "EQUIPMENT", "appraised_value_cents": 16_000_000}],
    )
    res = api.authorize_application(ctx["application"]["id"], SBA)
    app = validate_success(res, 200)
    assert app["guaranty_fee_cents"] == 240_000  # floor(15000000*0.80*0.02)
    assert app["guaranteed_amount_cents"] == 12_000_000  # round_half_up(15000000*0.80)


def test_guaranty_fee_crosses_into_band2(api):
    """PRD §3.6: "the second band is the portion of the gross from above 15,000,000 cents
    up to and including 70,000,000 cents".
    PRD §3.6: "the second band 3.00 percent".

    Design: Corner/calculations/guaranty_fee_crosses_into_band2
    """
    # gross 20000000 (5000000 above TIER1), gp 0.80: 240000 band1 + floor(5000000*0.80*0.03)=120000.
    ctx = reach_approved(
        app_overrides={"requested_amount_cents": 20_000_000, "guaranty_pct": 0.80, "maturity_months": 60},
        borrower_overrides={"naics_code": "333120"},
        proceeds_amount=20_000_000,
        collateral_specs=[{"asset_type": "EQUIPMENT", "appraised_value_cents": 22_000_000}],
    )
    res = api.authorize_application(ctx["application"]["id"], SBA)
    app = validate_success(res, 200)
    assert app["guaranty_fee_cents"] == 360_000  # 240000 + 120000


# ─── dual_variant_calc: guaranty fee is sale-independent (2 tests) ─────────────

def test_guaranty_fee_unchanged_by_settled_secondary_sale(api):
    """PRD §3.6: "This upfront guaranty fee is permanently sale-independent. Selling the guaranty on the secondary market later does not rebate, reduce, or otherwise alter the `guaranty_fee_cents` frozen at authorization; the fee is billed on the full guaranteed portion and stays fixed regardless of any later guaranty sale."

    Design: Difficulty/dual_variant_calc/guaranty_fee_sale_independent_on_application
    """
    ctx = reach_sold(premium_bps=350)  # gp 0.75, requested 50000000 -> fee frozen 1012500, then SOLD
    aid = ctx["application"]["id"]
    app = validate_success(api.get_application(aid, SBA), 200)
    assert app["guaranty_status"] == "SOLD"
    assert app["guaranty_fee_cents"] == 1_012_500


def test_guaranty_fee_frozen_value_equals_authorized_value_after_sale(api):
    """PRD §3.6: "Selling the guaranty on the secondary market later does not rebate, reduce, or otherwise alter the `guaranty_fee_cents` frozen at authorization".

    Design: Difficulty/dual_variant_calc/guaranty_fee_sale_independent_on_application
    """
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    fee_at_authorize = ctx["application"]["guaranty_fee_cents"]
    assert fee_at_authorize == 1_012_500
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=350)
    settle_guaranty_sale(sale["id"], app_v)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["guaranty_fee_cents"] == fee_at_authorize == 1_012_500


# ─── dual_variant_calc: guaranty purchase payout repair vs clean (2 tests) ────

def test_guaranty_purchase_payout_repaired_applies_repair_last(api):
    """PRD §3.10: "and `approved_amount_cents` is the floor of the after-recovery amount multiplied by one minus `repair_pct`."
    PRD §3.10: "When `repair_pct` is greater than zero or a settled liquidation has credited the SBA, both deductions stack, with the repair reduction applied last."

    Design: Difficulty/dual_variant_calc/guaranty_purchase_payout_repair_vs_clean
    """
    # gp 0.75, outstanding 50000000 -> cap round_half_up(50000000*0.75)=37500000;
    # claimed 10000000 -> base=min(10000000,37500000)=10000000; no settled liquidation;
    # repair 0.10 -> floor(10000000*0.90)=9000000.
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    gp = file_guaranty_purchase(aid, claimed_principal_cents=10_000_000, repair_pct=0.10)
    res = api.pay_guaranty_purchase(gp["id"], SBA)
    paid = validate_success(res, 200)
    assert paid["approved_amount_cents"] == 9_000_000
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["guaranty_status"] == "PURCHASED_BY_SBA"


def test_guaranty_purchase_payout_clean_pays_full_capped_claim(api):
    """PRD §3.10: "When `repair_pct` is 0 and no prior liquidation has been settled, this collapses to simply the lesser of the claim and the cap — the SBA pays the full capped claim."

    Design: Difficulty/dual_variant_calc/guaranty_purchase_payout_repair_vs_clean
    """
    # Same loan shape; repair_pct 0, no settled liquidation -> approved == min(claimed, cap).
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    gp = file_guaranty_purchase(aid, claimed_principal_cents=10_000_000, repair_pct=0)
    res = api.pay_guaranty_purchase(gp["id"], SBA)
    paid = validate_success(res, 200)
    assert paid["approved_amount_cents"] == 10_000_000  # min(10000000, 37500000)


# ─── combinatorial_formula: secondary premium nonlinear branch (2 tests) ──────

def test_secondary_premium_above_floor_nonlinear_branch(api):
    """PRD §3.8: "If the gross premium is less than or equal to the retained floor, the SBA's cut is zero. Otherwise the SBA's cut is the floor of half of the amount by which the gross premium exceeds the retained floor — the SBA takes 50 percent of the premium above the floor. The net `premium_cents` credited to the lender is the gross premium minus the SBA's cut. Each step is floored, in exactly the order stated."

    Design: Difficulty/combinatorial_formula/secondary_premium_three_input_nonlinear_branch
    """
    # sold 37500000, bps 350: gross=floor(37500000*350/10000)=1312500;
    # floor=floor(37500000*100/10000)=375000; sba_cut=floor((1312500-375000)*0.5)=468750;
    # net=1312500-468750=843750.
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=350)
    res = api.settle_guaranty_sale(sale["id"], {"expected_application_version": app_v}, INVESTOR)
    settled = validate_success(res, 200)
    assert settled["premium_cents"] == 843_750


def test_secondary_premium_below_floor_no_sba_cut(api):
    """PRD §3.8: "the lender always keeps premium up to 1.00 percent of par. If the gross
    premium is less than or equal to the retained floor, the SBA's cut is zero."

    Design: Difficulty/combinatorial_formula/secondary_premium_three_input_nonlinear_branch
    """
    # sold 37500000, bps 100 (== retained floor rate): gross=floor(37500000*100/10000)=375000;
    # floor=375000; gross <= floor -> sba_cut=0 -> net=375000 (whole gross premium kept).
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=100)
    res = api.settle_guaranty_sale(sale["id"], {"expected_application_version": app_v}, INVESTOR)
    settled = validate_success(res, 200)
    assert settled["premium_cents"] == 375_000


# ─── combinatorial_formula: collateral floor-per-item-then-sum (2 tests) ──────

def test_collateral_floor_per_item_then_sum_short_term_shortfall(api):
    """PRD §3.4: "The coverage test sums the `discounted_value_cents` of every collateral item on the application — each already floored per item and floored at zero as described in §3.2".
    PRD §3.4: "For a loan whose `maturity_months` is 120 or less, the required coverage is the floor of half the `requested_amount_cents` (50 percent)."
    PRD §3.4: "the discounted collateral coverage must meet the requirement for the loan's maturity bucket, or the submit is rejected with `ERR_COLLATERAL_SHORTFALL`".

    Design: Difficulty/combinatorial_formula/collateral_floor_per_item_then_sum_order
    """
    # requested 25000002, gp 0.75, maturity 60 -> required floor(25000002*0.5)=12500001.
    # Two EQUIPMENT items each appraised 12500001: floor(12500001*0.5)=6250000 each, sum 12500000.
    # 12500000 < 12500001 -> shortfall (round-per-item-then-sum; sum-then-round would over-credit by 1).
    # Build up to the credit-memo submit (which is the failing trigger).
    from test_helpers import create_underwriting_application, add_collateral, cleared_form_package, author_credit_memo
    built = create_underwriting_application(
        app_overrides={"requested_amount_cents": 25_000_002, "guaranty_pct": 0.75, "maturity_months": 60},
        borrower_overrides={"naics_code": "333120"},
        proceeds_amount=25_000_002,
    )
    aid = built["application"]["id"]
    add_collateral(aid, asset_type="EQUIPMENT", appraised_value_cents=12_500_001)
    add_collateral(aid, asset_type="EQUIPMENT", appraised_value_cents=12_500_001)
    cleared_form_package(aid, character_cleared=True)
    memo = author_credit_memo(aid, recommendation="APPROVE", dscr=1.30, risk_rating=4)
    res = api.submit_credit_memo(memo["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_COLLATERAL_SHORTFALL.value)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["status"] == "UNDERWRITING"


def test_collateral_discounted_value_floored_per_item(api):
    """PRD §3.2: "it multiplies the appraised value by the discount rate for that asset class — 80 percent for `REAL_ESTATE`, 50 percent for `EQUIPMENT`, 30 percent for `INVENTORY`, and 50 percent for `RECEIVABLES` — takes the floor of that product, subtracts the prior lien, and floors the result at zero so a fully encumbered asset contributes nothing."

    Design: Difficulty/combinatorial_formula/collateral_floor_per_item_then_sum_order
    """
    # A single EQUIPMENT item appraised 12500001 -> discounted floor(12500001*0.5)=6250000.
    from test_helpers import create_lender, create_borrower, create_application
    lender = create_lender(name="CollItem CDC")
    borrower = create_borrower(lender["id"], legal_name="CollItem LLC", naics_code="333120")
    app = create_application(borrower["id"], maturity_months=60)
    res = api.create_collateral(
        {"application_id": app["id"], "asset_type": "EQUIPMENT", "appraised_value_cents": 12_500_001},
        OFFICER)
    item = validate_success(res, 201)
    assert item["discounted_value_cents"] == 6_250_000


# ─── liquidation_split conservation (corner calculations) ─────────────────────

def test_liquidation_split_conserves_net_recovery(api):
    """PRD §3.10: "the SBA's share `sba_share_cents` is the net recovery multiplied by the application's `guaranty_pct`, rounded half up to whole cents; and the lender's share `lender_share_cents` is the remainder, the net recovery minus the SBA share. Splitting this way conserves the net recovery exactly — the SBA share plus the lender share always equals the net recovery."

    Design: Corner/calculations/liquidation_split_conserves_net_recovery
    """
    # recovery 24000000, expense 4000000 -> net 20000000;
    # sba_share=round_half_up(20000000*0.75)=15000000; lender=remainder 5000000; sum=20000000.
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    liq = open_liquidation(aid, recovery_cents=24_000_000, expense_cents=4_000_000)
    res = api.settle_liquidation(liq["id"], OFFICER)
    settled = validate_success(res, 200)
    assert settled["sba_share_cents"] == 15_000_000
    assert settled["lender_share_cents"] == 5_000_000
    assert settled["sba_share_cents"] + settled["lender_share_cents"] == 20_000_000
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["servicing_status"] == "LIQUIDATED"
