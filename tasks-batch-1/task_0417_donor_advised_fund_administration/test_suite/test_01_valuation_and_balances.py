"""Valuation, balance derivation, and conserved-quantity tests for the DAF API.

Covers fair-market valuation variants, grantable-balance variants, pool-unit arithmetic,
quarterly admin-fee rounding order, the payout waterfall, and the compensating invariants.
"""
from test_helpers import (
    validate_success, get_success_data, fixtures, factories,
)
from test_helpers.fixtures import (
    SPONSOR_ADMIN, COMPLIANCE, CONTRIB_ADMIN, advisor_headers, officer_headers,
)


# ===========================================================================
# Dual-variant: contribution fair-market value (MEAN_HIGH_LOW vs CLOSING_PRICE)
# ===========================================================================
def test_securities_fmv_mean_high_low_vs_closing_price_diverge(api):
    """PRD 3.3: "The standard valuation (the **MEAN_HIGH_LOW** variant, used when `thinly_traded` is false) multiplies the share count by the average of the gift-date high and low — that is, by the sum of `high_price_cents` and `low_price_cents` divided by 2 — and rounds the result half up to whole cents."
    PRD 3.3: "For a thinly-traded name (the **CLOSING_PRICE** variant, used when `thinly_traded` is true), the share count is instead multiplied by `closing_price_cents` and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/contribution_fmv_mean_high_low_vs_closing_price
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-1")

    mhl = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100000, ticker="ACME",
            high_price_cents=1100, low_price_cents=900, closing_price_cents=1050,
            thinly_traded=False),
        advisor_headers("adv-1")))
    close = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100000, ticker="THIN",
            high_price_cents=1100, low_price_cents=900, closing_price_cents=1050,
            thinly_traded=True),
        advisor_headers("adv-1")))

    mhl_settled = validate_success(api.settle_contribution(mhl["id"], CONTRIB_ADMIN))
    close_settled = validate_success(api.settle_contribution(close["id"], CONTRIB_ADMIN))

    assert mhl_settled["fair_market_value_cents"] == 100000
    assert close_settled["fair_market_value_cents"] == 105000
    assert close_settled["fair_market_value_cents"] - mhl_settled["fair_market_value_cents"] == 5000


def test_securities_fmv_mean_high_low_alone(api):
    """PRD 3.3: "The standard valuation (the **MEAN_HIGH_LOW** variant, used when `thinly_traded` is false) multiplies the share count by the average of the gift-date high and low — that is, by the sum of `high_price_cents` and `low_price_cents` divided by 2 — and rounds the result half up to whole cents."

    Design: Difficulty/dual_variant_calc/contribution_fmv_mean_high_low_vs_closing_price
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-1")
    contrib = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100000, ticker="ACME",
            high_price_cents=1100, low_price_cents=900, thinly_traded=False),
        advisor_headers("adv-1")))
    settled = validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    # round_half_up(100 * (1100+900)/2) = 100 * 1000 = 100000
    assert settled["fair_market_value_cents"] == 100000


# ===========================================================================
# Dual-variant: grantable balance SETTLED vs PROJECTED
# ===========================================================================
def test_grantable_balance_settled_excludes_pending(api):
    """PRD 3.4: "The default reading (the **SETTLED** variant, used when no `projection` is supplied) counts only settled contributions, which are already folded into cash and investments, and excludes pending contributions entirely."

    Design: Difficulty/dual_variant_calc/grantable_balance_settled_vs_projected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-2")
    fixtures.fund_account_with_cash(account["id"], 500000, "adv-2")
    # Add a PENDING crypto contribution that must NOT count in the settled view.
    get_success_data(api.create_contribution(
        factories.create_crypto_contribution_payload(account["id"], 2500, 3000000, ticker="BTC"),
        advisor_headers("adv-2")))

    summary = validate_success(api.get_account_summary(account["id"], advisor_headers("adv-2")))
    assert summary["grantable_balance_cents"] == 500000


def test_grantable_balance_projected_adds_pending_provisional(api):
    """PRD 3.4: "The **PROJECTED** variant (used when `projection` equals `PROJECTED`) takes the same settled grantable balance and adds, for every contribution on the account still in `PENDING` status, a provisional value computed by applying the same fair-market-value formula to that pending contribution's current pricing inputs; the projected figure therefore exceeds the settled figure by the sum of those pending provisional valuations."

    Design: Difficulty/dual_variant_calc/grantable_balance_settled_vs_projected
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-2")
    fixtures.fund_account_with_cash(account["id"], 500000, "adv-2")
    get_success_data(api.create_contribution(
        factories.create_crypto_contribution_payload(account["id"], 2500, 3000000, ticker="BTC"),
        advisor_headers("adv-2")))

    settled = validate_success(api.get_account_summary(account["id"], advisor_headers("adv-2")))
    projected = validate_success(api.get_account_summary(
        account["id"], advisor_headers("adv-2"), params={"projection": "PROJECTED"}))
    # provisional crypto FMV = floor(2.5 * 3000000) = 7500000
    assert settled["grantable_balance_cents"] == 500000
    assert projected["grantable_balance_cents"] == 8000000
    assert projected["grantable_balance_cents"] - settled["grantable_balance_cents"] == 7500000


# ===========================================================================
# Combinatorial: pool_unit_delta BUY floor / REDEEM ceil
# ===========================================================================
def test_pool_buy_floors_units(api):
    """PRD 3.4: "On a **buy**, the number of micro-units added is the floor of the `amount_cents` multiplied by 1,000,000 and divided by the target pool's `nav_per_unit_cents` — flooring so the fund never credits a fractional unit beyond the cash paid"

    Design: Difficulty/combinatorial_formula/pool_unit_delta_buy_floor_redeem_ceil_asymmetry
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=3, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-3b")
    fixtures.fund_account_with_cash(account["id"], 10, "adv-3b")
    fixtures.buy_into_pool(account["id"], pool["id"], 10, "adv-3b", target_pct_bps=5000)
    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-3b"), params={"donor_account_id": account["id"]}))
    assert allocs[0]["units_micro"] == 3333333


# ===========================================================================
# Combinatorial: quarterly admin fee — round per allocation THEN sum
# ===========================================================================
def test_admin_fee_round_per_allocation_then_sum(api):
    """PRD 3.7: "The **quarterly admin fee** is computed per account by summing rounded per-allocation fees, and the rounding order is pinned: round each allocation's fee first, then sum — never sum first and round once."
    PRD 3.7: "The per-allocation quarterly fee is then that invested value multiplied by the pool's `fee_bps` and divided by 40,000 — where 40,000 is the basis-point scale of 10,000 multiplied by the 4 quarters in a year — and rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/quarterly_admin_fee_round_per_allocation_then_sum
    """
    sponsor = fixtures.create_sponsor()
    # Two SEPARATE pools so each buy lands in its OWN ACTIVE allocation (PRD 3.4: a
    # buy into a pool the account already holds merges into the existing allocation,
    # so distinct allocations require distinct pools).
    pool_a = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    pool_b = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-4")
    fixtures.fund_account_with_cash(account["id"], 165600, "adv-4")
    # Two buys of 82800 into two pools -> two ACTIVE allocations each invested_value 82800.
    fixtures.buy_into_pool(account["id"], pool_a["id"], 82800, "adv-4", target_pct_bps=5000)
    fixtures.buy_into_pool(account["id"], pool_b["id"], 82800, "adv-4", target_pct_bps=5000)

    validate_success(api.close_quarter(sponsor["id"], SPONSOR_ADMIN))

    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    # round_half_up(50*82800/40000)=104 each, summed 208 (not 207 from sum-then-round)
    assert acct["admin_fee_accrued_cents"] == 208
    assert acct["admin_fee_accrued_cents"] != 207

    ledger = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "ADMIN_FEE"}))
    assert len(ledger) == 1
    assert ledger[0]["signed_amount_cents"] == -208


def test_admin_fee_ledger_entry_appended_negative(api):
    """PRD 3.7: "That sum is added to the account's `admin_fee_accrued_cents`, a `LedgerEntry` of `entry_type` `ADMIN_FEE` is appended with `signed_amount_cents` equal to the negative fee, and the account's `grantable_balance_cents` is recomputed."

    Design: Difficulty/combinatorial_formula/quarterly_admin_fee_round_per_allocation_then_sum
    """
    sponsor = fixtures.create_sponsor()
    # Two SEPARATE pools so each buy lands in its OWN ACTIVE allocation (PRD 3.4).
    pool_a = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    pool_b = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    account = fixtures.create_account(sponsor["id"], "adv-4b")
    fixtures.fund_account_with_cash(account["id"], 165600, "adv-4b")
    fixtures.buy_into_pool(account["id"], pool_a["id"], 82800, "adv-4b", target_pct_bps=5000)
    fixtures.buy_into_pool(account["id"], pool_b["id"], 82800, "adv-4b", target_pct_bps=5000)
    validate_success(api.close_quarter(sponsor["id"], SPONSOR_ADMIN))
    ledger = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "ADMIN_FEE"}))
    assert len(ledger) == 1
    assert ledger[0]["signed_amount_cents"] == -208


# ===========================================================================
# Compensating invariant #1: grant payout redeem leg conserves cash+invested
# ===========================================================================
def test_grant_payout_redeem_conserves_cash_plus_invested(api):
    """PRD 3.6: "Because for the redeem legs the cash credited equals the invested value debited at each allocation's NAV, the sum of cash and invested value is unchanged by redemption itself; the only net reduction is the grant debit, which equals exactly the `amount_cents`."

    Design: Difficulty/compensating_invariant/grant_payout_redeem_conserves_cash_plus_invested
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=180000, advisor_user_id="adv-15")
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    fixtures.buy_into_pool(account["id"], pool["id"], 100000, "adv-15", target_pct_bps=6000)
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-15", target_pct_bps=4000)

    before = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert before["cash_balance_cents"] + before["invested_value_cents"] == 180000

    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-15", officer_user_id="officer-9")
    validate_success(api.pay_grant(grant["id"], officer_headers("officer-9")))

    after = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert after["cash_balance_cents"] == 0
    assert after["invested_value_cents"] == 80000
    assert after["cash_balance_cents"] + after["invested_value_cents"] == 80000 == 180000 - 100000


def test_grant_payout_net_reduction_equals_amount(api):
    """PRD 3.6: "the only net reduction is the grant debit, which equals exactly the `amount_cents`."

    Design: Difficulty/compensating_invariant/grant_payout_redeem_conserves_cash_plus_invested
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=180000, advisor_user_id="adv-15b")
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    fixtures.buy_into_pool(account["id"], pool["id"], 100000, "adv-15b", target_pct_bps=6000)
    fixtures.buy_into_pool(account["id"], pool["id"], 50000, "adv-15b", target_pct_bps=4000)
    before = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    sum_before = before["cash_balance_cents"] + before["invested_value_cents"]
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-15b", officer_user_id="officer-9b")
    validate_success(api.pay_grant(grant["id"], officer_headers("officer-9b")))
    after = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    sum_after = after["cash_balance_cents"] + after["invested_value_cents"]
    assert sum_before - sum_after == 100000


# ===========================================================================
# Compensating invariant #2: legacy split largest-remainder conserves residual
# ===========================================================================
def test_legacy_split_largest_remainder_conserves_residual(api):
    """PRD 3.8: "For each beneficiary, the floor share is the floor of the residual multiplied by that beneficiary's `share_bps` and divided by 10,000. The leftover — the residual minus the sum of all floor shares — is then distributed one extra cent at a time to beneficiaries ordered by the fractional part of (residual multiplied by `share_bps` divided by 10,000) descending, with ties broken by the beneficiary charity row's `created_at` ascending."
    PRD 3.8: "For each beneficiary, a `LedgerEntry` of `entry_type` `LEGACY_DISBURSEMENT` is appended with `signed_amount_cents` equal to the negative of that beneficiary's share, and the account's `cash_balance_cents` is drained to 0."

    Design: Difficulty/compensating_invariant/legacy_split_largest_remainder_conserves_residual
    """
    sponsor = fixtures.create_sponsor()
    ben1 = fixtures.create_vetted_charity(sponsor["id"])
    ben2 = fixtures.create_vetted_charity(sponsor["id"])
    ben3 = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-16")
    fixtures.fund_account_with_cash(account["id"], 100001, "adv-16")
    beneficiaries = [
        {"charity_id": ben1["id"], "share_bps": 3334},
        {"charity_id": ben2["id"], "share_bps": 3333},
        {"charity_id": ben3["id"], "share_bps": 3333},
    ]
    plan = fixtures.create_confirmed_legacy_plan(account["id"], beneficiaries, "adv-16")
    get_success_data(api.wind_down_account(account["id"], SPONSOR_ADMIN))

    closed = validate_success(api.execute_succession(account["id"], SPONSOR_ADMIN))
    assert closed["status"] == "CLOSED"
    assert closed["cash_balance_cents"] == 0

    ledger = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "LEGACY_DISBURSEMENT"}))
    assert len(ledger) == 3
    amounts = sorted(e["signed_amount_cents"] for e in ledger)
    # floors [33340,33330,33330] sum 100000; leftover cent to highest fractional (index 0)
    assert amounts == [-33341, -33330, -33330]
    assert sum(e["signed_amount_cents"] for e in ledger) == -100001

    refreshed_plan = get_success_data(api.get_succession_plan(plan["id"], SPONSOR_ADMIN))
    assert refreshed_plan["status"] == "EXECUTED"


def test_legacy_split_sum_equals_residual_exactly(api):
    """PRD 3.8: "The sum of the final shares therefore equals the residual exactly — no cent is created or destroyed."

    Design: Difficulty/compensating_invariant/legacy_split_largest_remainder_conserves_residual
    """
    sponsor = fixtures.create_sponsor()
    ben1 = fixtures.create_vetted_charity(sponsor["id"])
    ben2 = fixtures.create_vetted_charity(sponsor["id"])
    ben3 = fixtures.create_vetted_charity(sponsor["id"])
    account = fixtures.create_account(sponsor["id"], "adv-16b")
    fixtures.fund_account_with_cash(account["id"], 100001, "adv-16b")
    beneficiaries = [
        {"charity_id": ben1["id"], "share_bps": 3334},
        {"charity_id": ben2["id"], "share_bps": 3333},
        {"charity_id": ben3["id"], "share_bps": 3333},
    ]
    fixtures.create_confirmed_legacy_plan(account["id"], beneficiaries, "adv-16b")
    get_success_data(api.wind_down_account(account["id"], SPONSOR_ADMIN))
    validate_success(api.execute_succession(account["id"], SPONSOR_ADMIN))
    ledger = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "LEGACY_DISBURSEMENT"}))
    assert abs(sum(e["signed_amount_cents"] for e in ledger)) == 100001


# ===========================================================================
# Corner: calculations
# ===========================================================================
def test_cash_contribution_fmv_equals_amount(api):
    """PRD 3.3: "For a **cash** gift, the fair market value is simply `cash_amount_cents`."

    Design: Corner/calculations/cash_contribution_fmv_equals_amount
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-k1")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 250000),
        advisor_headers("adv-k1")))
    settled = validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    assert settled["fair_market_value_cents"] == 250000
    acct = get_success_data(api.get_account(account["id"], SPONSOR_ADMIN))
    assert acct["cash_balance_cents"] == 250000


def test_crypto_contribution_fmv_floor(api):
    """PRD 3.3: "For a **crypto** gift, derive the quantity by dividing `quantity_milli` by 1000, multiply it by `spot_price_cents`, and take the floor — crypto valuations are rounded down to whole cents."

    Design: Corner/calculations/crypto_contribution_fmv_floor_precision
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-k2")
    contrib = get_success_data(api.create_contribution(
        factories.create_crypto_contribution_payload(account["id"], 2500, 3000001, ticker="ETH"),
        advisor_headers("adv-k2")))
    settled = validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    # floor(2.5 * 3000001) = 7500002 (not rounded up to 7500003)
    assert settled["fair_market_value_cents"] == 7500002


def test_securities_mean_high_low_round_half_up(api):
    """PRD 3.3: "The standard valuation (the **MEAN_HIGH_LOW** variant, used when `thinly_traded` is false) multiplies the share count by the average of the gift-date high and low — that is, by the sum of `high_price_cents` and `low_price_cents` divided by 2 — and rounds the result half up to whole cents."

    Design: Corner/calculations/securities_mean_high_low_round_half_up
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-k3")
    contrib = get_success_data(api.create_contribution(
        factories.create_securities_contribution_payload(
            account["id"], 100000, ticker="MEAN",
            high_price_cents=1001, low_price_cents=900, thinly_traded=False),
        advisor_headers("adv-k3")))
    settled = validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    # round_half_up(100 * (1901/2)) = round_half_up(95050.0) = 95050
    assert settled["fair_market_value_cents"] == 95050


def test_waterfall_redemption_order_by_target_pct_desc(api):
    """PRD 3.6: "the account's `ACTIVE` pool allocations that still hold units (those with `units_micro` greater than 0) are processed in a fixed order — by `target_pct_bps` descending, and within equal target weight by `created_at` ascending (never by id)."

    Design: Corner/calculations/waterfall_redemption_order_by_target_pct_desc
    """
    sponsor, charity, account = fixtures.setup_funded_account_with_vetted_charity(
        cash_amount_cents=180000, advisor_user_id="adv-k4")
    # Two SEPARATE pools so the two buys form two distinct ACTIVE allocations with
    # distinct target_pct_bps (PRD 3.4: a buy into a pool the account already holds
    # merges into the existing allocation, so distinct allocations need distinct pools).
    pool_hi = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    pool_lo = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    # high-target allocation (6000) value 100000, low-target (4000) value 50000
    fixtures.buy_into_pool(account["id"], pool_hi["id"], 100000, "adv-k4", target_pct_bps=6000)
    fixtures.buy_into_pool(account["id"], pool_lo["id"], 50000, "adv-k4", target_pct_bps=4000)
    grant = fixtures.create_scheduled_grant(
        account["id"], charity["id"], 100000, "adv-k4", officer_user_id="officer-k4")
    validate_success(api.pay_grant(grant["id"], officer_headers("officer-k4")))

    allocs = get_success_data(api.list_allocations(
        advisor_headers("adv-k4"), params={"donor_account_id": account["id"]}))
    by_target = {a["target_pct_bps"]: a for a in allocs}
    # cash 30000 covers 30000; need 70000 drawn entirely from the high-target allocation
    # (value 100000): redeem 70000 -> 28000000 micro -> 40000000-28000000 = 12000000 left.
    assert by_target[6000]["units_micro"] == 12000000
    assert by_target[4000]["units_micro"] == 20000000  # untouched

    redeems = get_success_data(api.list_ledger_entries(
        SPONSOR_ADMIN, params={"donor_account_id": account["id"], "entry_type": "POOL_REDEEM"}))
    assert len(redeems) == 1


def test_nav_period_disjoint_windows_both_accepted(api):
    """PRD 3.1: "Because the interval is half-open, two windows that merely touch at a boundary — where one window's `to_quarter` equals the other's `from_quarter` — do **not** collide."

    Design: Corner/calculations/nav_period_disjoint_windows_both_accepted
    """
    sponsor = fixtures.create_sponsor()
    pool = fixtures.create_pool(sponsor["id"], nav_per_unit_cents=2500, fee_bps=50)
    get_success_data(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 0, 3, nav_per_unit_cents=2500),
        SPONSOR_ADMIN))
    np2 = validate_success(api.create_nav_period(
        factories.create_nav_period_payload(pool["id"], 5, 8, nav_per_unit_cents=2700),
        SPONSOR_ADMIN), expected_status=201)
    assert np2["status"] == "ACTIVE"


# ===========================================================================
# Corner: derived-field reconciliation + immediate consistency
# ===========================================================================
def test_grantable_recomputed_after_settle(api):
    """PRD 2.7: "Whenever an operation changes cash, investments, commitments, or accrued fees, the affected account's derived figures are recomputed in that same operation so the stored values always reconcile with the ledger."

    Design: Corner/cross_cutting_complexity_layers/derived_field_grantable_recomputed_after_settle
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-cc3")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 400000),
        advisor_headers("adv-cc3")))
    validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    acct = validate_success(api.get_account(account["id"], advisor_headers("adv-cc3")))
    assert acct["grantable_balance_cents"] == 400000
    assert acct["cash_balance_cents"] == 400000


def test_immediate_consistency_settle_visible_in_same_read(api):
    """PRD 2.7: "Whenever an operation changes cash, investments, commitments, or accrued fees, the affected account's derived figures are recomputed in that same operation so the stored values always reconcile with the ledger."

    Design: Corner/consistency_model/immediate_consistency_settle_visible_in_same_response
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-cm1")
    contrib = get_success_data(api.create_contribution(
        factories.create_cash_contribution_payload(account["id"], 250000),
        advisor_headers("adv-cm1")))
    validate_success(api.settle_contribution(contrib["id"], CONTRIB_ADMIN))
    acct = validate_success(api.get_account(account["id"], advisor_headers("adv-cm1")))
    assert acct["cash_balance_cents"] == 250000
    assert acct["grantable_balance_cents"] == 250000


# ===========================================================================
# Corner: endpoint computed reads + close_quarter
# ===========================================================================
def test_close_quarter_advances_quarter_index(api):
    """PRD 2.10: "quarters advance only when the sponsor's quarter is closed, which increments `current_quarter_index` by one and runs the per-account fee accrual and inactivity evaluation described in Section 3."

    Design: Corner/endpoints/close_quarter_advances_quarter_index
    """
    sponsor = fixtures.create_sponsor()
    updated = validate_success(api.close_quarter(sponsor["id"], SPONSOR_ADMIN))
    assert updated["current_quarter_index"] == 1


def test_account_summary_settled_equals_cash(api):
    """PRD 3.4: "The account's settled grantable balance is its `cash_balance_cents` plus this `invested_value_cents` minus `committed_grants_cents` minus `admin_fee_accrued_cents`."

    Design: Corner/endpoints/account_summary_computed_read_settled
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-e2")
    fixtures.fund_account_with_cash(account["id"], 600000, "adv-e2")
    summary = validate_success(api.get_account_summary(account["id"], advisor_headers("adv-e2")))
    assert summary["grantable_balance_cents"] == 600000
    assert summary["cash_balance_cents"] == 600000


def test_ledger_entries_reverse_reachable_by_account(api):
    """PRD 3.3: "A `LedgerEntry` of `entry_type` `CONTRIBUTION_SETTLED` is appended with `signed_amount_cents` equal to the positive fair market value, and the account's `grantable_balance_cents` is recomputed."

    Design: Corner/endpoints/ledger_entries_reverse_reachable_by_account
    """
    sponsor = fixtures.create_sponsor()
    account = fixtures.create_account(sponsor["id"], "adv-e3")
    fixtures.fund_account_with_cash(account["id"], 700000, "adv-e3")
    entries = get_success_data(api.list_ledger_entries(
        COMPLIANCE, params={"donor_account_id": account["id"], "entry_type": "CONTRIBUTION_SETTLED"}))
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "CONTRIBUTION_SETTLED"
    assert entries[0]["signed_amount_cents"] == 700000
    assert entries[0]["donor_account_id"] == account["id"]
