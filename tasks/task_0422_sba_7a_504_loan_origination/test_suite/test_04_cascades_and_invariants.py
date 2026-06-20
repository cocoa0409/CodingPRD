"""Transitive cascades (liquidation -> outstanding -> purchase cap; servicing accept ->
ongoing fee -> lender pool) and compensating invariants (disbursement reverse; sale
repurchase).

Covers difficulty rules transitive_cascade and compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    reach_authorized, reach_fully_disbursed, reach_defaulted, reach_sold,
    create_and_post_disbursement,
    open_liquidation, file_guaranty_purchase,
    offer_guaranty_sale, settle_guaranty_sale,
    file_and_accept_servicing_report, file_servicing_report,
    TEST_USERS,
)
from test_helpers.api_client import api_client

OFFICER = TEST_USERS["loan_officer_headers"]
SBA = TEST_USERS["sba_officer_headers"]
INVESTOR = TEST_USERS["investor_servicer_headers"]


# ─── transitive_cascade: liquidation settle depth-3 to purchase cap (2 tests) ──

def test_liquidation_settle_reduces_outstanding_then_lowers_purchase_cap(api):
    """PRD §3.10: "Settlement also reduces the application's `outstanding_principal_cents` by the net recovery, which lowers the guaranty-purchase cap downstream."
    PRD §3.10: "the cap is the application's current `outstanding_principal_cents` multiplied by its `guaranty_pct`, rounded half up to whole cents; the base is the smaller of `claimed_principal_cents` and that cap; the SBA recovery credit is the sum of `sba_share_cents` across all `SETTLED` liquidation events on the application; the amount after recovery is the base minus that recovery credit, floored at zero".

    Design: Difficulty/transitive_cascade/liquidation_settle_depth3_to_purchase_cap
    """
    # outstanding 50000000; liquidation recovery 24000000 expense 4000000 -> net 20000000,
    # sba_share 15000000; outstanding -> 30000000; cap=round_half_up(30000000*0.75)=22500000;
    # claimed 30000000 -> base=22500000; minus sba_recovery 15000000 -> 7500000; repair 0.
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    liq = open_liquidation(aid, recovery_cents=24_000_000, expense_cents=4_000_000)
    gp = file_guaranty_purchase(aid, claimed_principal_cents=30_000_000, repair_pct=0)

    settle_res = api.settle_liquidation(liq["id"], OFFICER)
    settled = validate_success(settle_res, 200)
    assert settled["sba_share_cents"] == 15_000_000

    app_mid = validate_success(api.get_application(aid, SBA), 200)
    assert app_mid["outstanding_principal_cents"] == 30_000_000

    pay_res = api.pay_guaranty_purchase(gp["id"], SBA)
    paid = validate_success(pay_res, 200)
    assert paid["approved_amount_cents"] == 7_500_000


def test_liquidation_settle_outstanding_reduction_isolated(api):
    """PRD §3.10: "Settlement also reduces the application's `outstanding_principal_cents` by the net recovery".

    Design: Difficulty/transitive_cascade/liquidation_settle_depth3_to_purchase_cap
    """
    ctx = reach_defaulted()
    aid = ctx["application"]["id"]
    before = validate_success(api.get_application(aid, SBA), 200)
    assert before["outstanding_principal_cents"] == 50_000_000
    liq = open_liquidation(aid, recovery_cents=24_000_000, expense_cents=4_000_000)
    validate_success(api.settle_liquidation(liq["id"], OFFICER), 200)
    after = validate_success(api.get_application(aid, SBA), 200)
    # net recovery = 24000000 - 4000000 = 20000000.
    assert after["outstanding_principal_cents"] == 30_000_000


# ─── transitive_cascade: servicing accept depth-2 to lender pool (2 tests) ────

def test_servicing_accept_accrues_ongoing_fee_into_lender_pool(api):
    """PRD §3.9: "take the application's `outstanding_principal_cents` (pre-this-report) multiplied by its `guaranty_pct`, rounded half up to whole cents, to get the guaranteed outstanding; multiply that by the annual ongoing rate of 0.55 percent, divide by 12 to get the monthly figure, and floor to whole cents."
    PRD §3.9: "that `ongoing_fee_cents` is added to the lender's `ongoing_fee_pool_cents`."

    Design: Difficulty/transitive_cascade/servicing_accept_depth2_to_lender_pool
    """
    # outstanding (pre-report) 50000000, gp 0.75: guaranteed_outstanding=round_half_up(37500000)=37500000;
    # ongoing=floor(37500000*0.0055/12)=floor(17187.5)=17187.
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    lid = ctx["lender"]["id"]
    rpt = file_servicing_report(aid, 0, 0, principal_paid_cents=5_000_000, days_past_due=0)
    accept_res = api.accept_servicing_report(rpt["id"], SBA)
    accepted = validate_success(accept_res, 200)
    assert accepted["ongoing_fee_cents"] == 17_187

    lender = validate_success(api.get_lender(lid, SBA), 200)
    assert lender["ongoing_fee_pool_cents"] == 17_187


def test_servicing_accept_reduces_outstanding_by_principal_paid(api):
    """PRD §3.9: "the report's `principal_paid_cents` is subtracted from the application's `outstanding_principal_cents`."

    Design: Difficulty/transitive_cascade/servicing_accept_depth2_to_lender_pool
    """
    ctx = reach_fully_disbursed()
    aid = ctx["application"]["id"]
    file_and_accept_servicing_report(aid, 0, 0, principal_paid_cents=5_000_000, days_past_due=0)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["outstanding_principal_cents"] == 45_000_000  # 50000000 - 5000000


# ─── compensating_invariant: disbursement reverse conserves balances (2 tests) ─

def test_disbursement_reverse_returns_disbursed_to_pre_post_value(api):
    """PRD §3.7: "Reversal is compensating: it subtracts the draw's `amount_cents` back out of `disbursed_amount_cents` and out of `outstanding_principal_cents`."
    PRD §3.7: "the system adds the draw's `amount_cents` to the application's `disbursed_amount_cents` and adds the same amount to its `outstanding_principal_cents`."

    Design: Difficulty/compensating_invariant/disbursement_reverse_conserves_disbursed_amount
    """
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    disb = create_and_post_disbursement(aid, 10_000_000, 0, 30, label="Draw 1")
    posted = validate_success(api.get_application(aid, SBA), 200)
    assert posted["disbursed_amount_cents"] == 10_000_000
    assert posted["outstanding_principal_cents"] == 10_000_000

    validate_success(api.reverse_disbursement(disb["id"], OFFICER), 200)
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["disbursed_amount_cents"] == 0
    assert after["outstanding_principal_cents"] == 0


def test_disbursement_reverse_terminal_and_outstanding_zeroed(api):
    """PRD §3.7: "it subtracts the draw's `amount_cents` back out of `disbursed_amount_cents` and out of `outstanding_principal_cents`. A reversed draw is terminal."

    Design: Difficulty/compensating_invariant/disbursement_reverse_conserves_disbursed_amount
    """
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    disb = create_and_post_disbursement(aid, 10_000_000, 0, 30, label="Draw 1")
    reversed_draw = validate_success(api.reverse_disbursement(disb["id"], OFFICER), 200)
    assert reversed_draw["status"] == "REVERSED"
    after = validate_success(api.get_application(aid, SBA), 200)
    assert after["outstanding_principal_cents"] == 0


# ─── compensating_invariant: sale repurchase conserves lender pool (2 tests) ──

def test_guaranty_repurchase_returns_lender_pool_to_pre_sale_value(api):
    """PRD §2.7: "The repurchase decrement is exactly the same amount as the prior settle
    increment, so a sell-then-repurchase cycle returns the pool to its pre-sale value."
    PRD §3.8: "Repurchase is compensating: it resets the application's `sold_guaranteed_principal_cents` to 0 and subtracts the sale's `sold_principal_cents` back out of the lender's `sold_guaranty_balance_cents`, returning the pool to its pre-sale value."

    Design: Difficulty/compensating_invariant/guaranty_sale_repurchase_conserves_lender_pool
    """
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    lid = ctx["lender"]["id"]
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]  # 37500000

    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=350)
    settle_guaranty_sale(sale["id"], app_v)
    pool_after_settle = validate_success(api.get_lender(lid, SBA), 200)
    assert pool_after_settle["sold_guaranty_balance_cents"] == 37_500_000

    repurchased = validate_success(api.repurchase_guaranty_sale(sale["id"], OFFICER), 200)
    assert repurchased["status"] == "REPURCHASED"
    pool_after_repurchase = validate_success(api.get_lender(lid, SBA), 200)
    assert pool_after_repurchase["sold_guaranty_balance_cents"] == 0
    app_after = validate_success(api.get_application(aid, SBA), 200)
    assert app_after["sold_guaranteed_principal_cents"] == 0


def test_guaranty_settle_raises_lender_pool_by_sold_principal(api):
    """PRD §3.8: "adds that same `sold_principal_cents` to the selling `Lender`'s `sold_guaranty_balance_cents`".

    Design: Difficulty/compensating_invariant/guaranty_sale_repurchase_conserves_lender_pool
    """
    ctx = reach_authorized()
    aid = ctx["application"]["id"]
    lid = ctx["lender"]["id"]
    before = validate_success(api.get_lender(lid, SBA), 200)
    assert before["sold_guaranty_balance_cents"] == 0
    app_v = ctx["application"]["version"]
    guaranteed = ctx["application"]["guaranteed_amount_cents"]
    sale = offer_guaranty_sale(aid, guaranteed, premium_bps=350)
    settle_guaranty_sale(sale["id"], app_v)
    after = validate_success(api.get_lender(lid, SBA), 200)
    assert after["sold_guaranty_balance_cents"] == 37_500_000
