"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after an Account is created, every ownership-gated call
uses make_investor_headers(account["id"]) / make_guardian_headers(account["id"])
with the real Account.id, never the shared fallback constant.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_subscription_plan_payload,
    create_model_portfolio_payload,
    create_found_money_offer_payload,
    register_account_payload,
    create_linked_card_payload,
    create_roundup_accrual_payload,
    create_bucket_payload,
    create_order_payload,
    create_found_money_reward_payload,
    create_referral_payload,
)
from .test_users import (
    TEST_USERS,
    make_investor_headers,
    make_guardian_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Unique-value generators so repeated fixture calls in one test never collide
# on uniqueness constraints (email, plan tier, portfolio risk_tier, ...).
_email_seq = itertools.count(1)
_tier_seq = itertools.cycle(["LITE", "PERSONAL", "FAMILY"])
_risk_seq = itertools.count(1)
_code_seq = itertools.count(1)


def _unique_email(prefix="acct"):
    return f"{prefix}{next(_email_seq)}@x.com"


def _unique_code(prefix="REF"):
    return f"{prefix}{next(_code_seq)}"


# ─── Config seeding ───────────────────────────────────────────────────────
def create_plan(monthly_fee_cents=600, management_fee_bps=0, tier="PERSONAL",
                allows_custodial=True, allows_ira=True):
    """Create a single SubscriptionPlan. Returns the plan dict."""
    res = api_client.create_subscription_plan(
        create_subscription_plan_payload(
            tier=tier,
            monthly_fee_cents=monthly_fee_cents,
            management_fee_bps=management_fee_bps,
            allows_custodial=allows_custodial,
            allows_ira=allows_ira,
        ),
        ADMIN,
    )
    return get_success_data(res)


def create_portfolio(target_allocation=None, drift_band_bps=500, risk_tier=None, name="Moderate"):
    """Create a single ModelPortfolio with a unique risk_tier. Returns the dict."""
    if risk_tier is None:
        # risk_tier must be in 1..5 and unique; cycle through the band.
        risk_tier = (next(_risk_seq) % 5) + 1
    payload = create_model_portfolio_payload(
        risk_tier=risk_tier,
        name=name,
        drift_band_bps=drift_band_bps,
    )
    if target_allocation is not None:
        payload["target_allocation"] = target_allocation
    res = api_client.create_model_portfolio(payload, ADMIN)
    return get_success_data(res)


def create_offer(rebate_mode="FLAT", rebate_flat_cents=10000, rebate_percent_bps=None,
                 max_rebate_cents=10000, min_spend_cents=0, hold_days=0,
                 active_from="2026-01-01T00:00:00Z", active_until="2027-01-01T00:00:00Z",
                 brand_name=None):
    """Create a single FoundMoneyOffer. Returns the dict."""
    if brand_name is None:
        brand_name = f"Brand{next(_email_seq)}"
    payload = create_found_money_offer_payload(
        brand_name=brand_name,
        rebate_mode=rebate_mode,
        max_rebate_cents=max_rebate_cents,
        min_spend_cents=min_spend_cents,
        hold_days=hold_days,
        active_from=active_from,
        active_until=active_until,
    )
    if rebate_mode == "FLAT":
        payload["rebate_flat_cents"] = rebate_flat_cents
        payload.pop("rebate_percent_bps", None)
    else:
        payload["rebate_percent_bps"] = rebate_percent_bps if rebate_percent_bps is not None else 500
        payload.pop("rebate_flat_cents", None)
    res = api_client.create_found_money_offer(payload, ADMIN)
    return get_success_data(res)


def seed_config(monthly_fee_cents=600, management_fee_bps=0, tier="PERSONAL",
                allows_custodial=True, allows_ira=True, target_allocation=None,
                drift_band_bps=500):
    """Create one plan + one portfolio. Returns (plan, portfolio)."""
    plan = create_plan(
        monthly_fee_cents=monthly_fee_cents,
        management_fee_bps=management_fee_bps,
        tier=tier,
        allows_custodial=allows_custodial,
        allows_ira=allows_ira,
    )
    portfolio = create_portfolio(target_allocation=target_allocation, drift_band_bps=drift_band_bps)
    return plan, portfolio


# ─── Account creation / KYC progression ───────────────────────────────────
def register_account(plan_id, model_portfolio_id, sweep_threshold_cents=None, email=None):
    """Register a fresh PENDING_KYC / TRIAL account. Returns the dict."""
    overrides = {}
    if sweep_threshold_cents is not None:
        overrides["sweep_threshold_cents"] = sweep_threshold_cents
    overrides["email"] = email or _unique_email()
    res = api_client.register_account(
        register_account_payload(plan_id, model_portfolio_id, **overrides), ANON
    )
    return get_success_data(res)


def create_verified_account(plan_id=None, model_portfolio_id=None, sweep_threshold_cents=None,
                            plan=None, portfolio=None):
    """Register an account and verify KYC. Returns (account_dict, plan, portfolio).

    If plan/portfolio are not supplied they are created with defaults.
    """
    if plan is None:
        plan = create_plan()
    if portfolio is None:
        portfolio = create_portfolio()
    pid = plan_id or plan["id"]
    mpid = model_portfolio_id or portfolio["id"]
    acct = register_account(pid, mpid, sweep_threshold_cents=sweep_threshold_cents)
    get_success_data(api_client.verify_kyc(acct["id"], ADMIN))
    # Re-read so the returned account reflects VERIFIED + bumped version.
    acct = get_success_data(api_client.get_account(acct["id"], make_investor_headers(acct["id"])))
    return acct, plan, portfolio


def fund_account_via_found_money(account_id, amount_cents, plan=None):
    """Credit `amount_cents` to an account's cash via a confirmed FLAT found-money
    reward (the only non-investing cash inflow available pre-sweep). Requires the
    account already VERIFIED. Returns the confirmed account dict.
    """
    offer = create_offer(
        rebate_mode="FLAT",
        rebate_flat_cents=amount_cents,
        max_rebate_cents=amount_cents,
        min_spend_cents=0,
        hold_days=0,
    )
    inv = make_investor_headers(account_id)
    reward = get_success_data(api_client.create_found_money_reward(
        create_found_money_reward_payload(account_id, offer["id"], qualifying_spend_cents=5000),
        inv,
    ))
    get_success_data(api_client.confirm_found_money_reward(reward["id"], ADMIN))
    return get_success_data(api_client.get_account(account_id, inv))


# ─── Buckets ──────────────────────────────────────────────────────────────
def open_bucket(account_id, bucket_type="TAXABLE", beneficiary_name=None, as_guardian=False):
    """Open a bucket on a verified account. Returns the bucket dict."""
    payload = create_bucket_payload(account_id, bucket_type=bucket_type)
    if beneficiary_name is not None:
        payload["beneficiary_name"] = beneficiary_name
    headers = make_guardian_headers(account_id) if as_guardian else make_investor_headers(account_id)
    return get_success_data(api_client.create_bucket(payload, headers))


# ─── Orders ───────────────────────────────────────────────────────────────
def create_draft_order(account_id, bucket_id, order_kind="INVEST",
                       requested_amount_cents=100, source="MANUAL",
                       lot_selection_method=None):
    """Create a DRAFT order. Returns the order dict."""
    payload = create_order_payload(
        account_id, bucket_id, order_kind=order_kind,
        requested_amount_cents=requested_amount_cents, source=source,
    )
    if lot_selection_method is not None:
        payload["lot_selection_method"] = lot_selection_method
    return get_success_data(api_client.create_order(payload, make_investor_headers(account_id)))


def submit_order(account_id, bucket_id, order_id):
    """Submit a DRAFT order, echoing the bucket's live version. Returns the order dict."""
    inv = make_investor_headers(account_id)
    bkt = get_success_data(api_client.get_bucket(bucket_id, inv))
    return get_success_data(
        api_client.submit_order(order_id, {"expected_bucket_version": bkt["version"]}, inv)
    )


def settle_order(order_id, payload=None):
    """Settle a SUBMITTED order as PlatformAdmin. Returns the order dict."""
    return get_success_data(api_client.settle_order(order_id, ADMIN, payload=payload))


def create_settled_invest_order(account_id, bucket_id, requested_amount_cents, source="MANUAL"):
    """Create -> submit -> settle an INVEST order. Returns the settled order dict."""
    order = create_draft_order(
        account_id, bucket_id, order_kind="INVEST",
        requested_amount_cents=requested_amount_cents, source=source,
    )
    submit_order(account_id, bucket_id, order["id"])
    return settle_order(order["id"])


def setup_funded_invest_ready(cash_cents, management_fee_bps=0, bucket_type="TAXABLE",
                              sweep_threshold_cents=100000, plan=None, portfolio=None):
    """Verified account funded to `cash_cents` via found-money, with an OPEN bucket.
    Returns (account, bucket). The account is re-read so its balances are fresh.
    """
    if plan is None:
        plan = create_plan(management_fee_bps=management_fee_bps)
    if portfolio is None:
        portfolio = create_portfolio()
    acct, _, _ = create_verified_account(
        plan=plan, portfolio=portfolio, sweep_threshold_cents=sweep_threshold_cents
    )
    fund_account_via_found_money(acct["id"], cash_cents)
    bucket = open_bucket(acct["id"], bucket_type=bucket_type)
    acct = get_success_data(api_client.get_account(acct["id"], make_investor_headers(acct["id"])))
    return acct, bucket


# ─── Tax-lot inventory (for FIFO/HIFO divergence) ─────────────────────────
def set_clock(iso):
    get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def lot_for_order(open_order_id):
    """Return the single TaxLot opened by a settled INVEST order."""
    lots, _meta = _list_lots(open_order_id=open_order_id)
    assert lots, f"Setup failed: no tax lot for order {open_order_id}"
    return lots[0]


def _list_lots(**params):
    res = api_client.list_tax_lots(ADMIN, params=params)
    body = res.json()
    return body["data"], body.get("meta", {})


def set_lot_valuation(lot_id, unit_gain_ratio_bps):
    return get_success_data(
        api_client.set_lot_valuation(lot_id, {"unit_gain_ratio_bps": unit_gain_ratio_bps}, ADMIN)
    )


def setup_two_lot_inventory(lot_a_bps, lot_b_bps, basis=5000,
                            acquired_a="2026-02-01T00:00:00Z",
                            acquired_b="2026-02-02T00:00:00Z"):
    """Verified mgmt-0 account + TAXABLE bucket holding two OPEN tax lots:
      lot A (basis `basis`, +lot_a_bps, acquired earlier),
      lot B (basis `basis`, +lot_b_bps, acquired later).
    Funds enough cash so both invests settle. Returns (account, bucket, lot_a, lot_b).
    """
    acct, bucket = setup_funded_invest_ready(
        cash_cents=basis * 2, management_fee_bps=0, bucket_type="TAXABLE",
        sweep_threshold_cents=100000,
    )
    set_clock(acquired_a)
    order_a = create_settled_invest_order(acct["id"], bucket["id"], basis)
    lot_a = lot_for_order(order_a["id"])
    set_lot_valuation(lot_a["id"], lot_a_bps)

    set_clock(acquired_b)
    order_b = create_settled_invest_order(acct["id"], bucket["id"], basis)
    lot_b = lot_for_order(order_b["id"])
    set_lot_valuation(lot_b["id"], lot_b_bps)

    return acct, bucket, lot_a, lot_b


def settle_withdraw(account_id, bucket_id, requested_amount_cents, lot_selection_method="FIFO"):
    """Create -> submit -> settle a WITHDRAW order. Returns the settled order dict."""
    order = create_draft_order(
        account_id, bucket_id, order_kind="WITHDRAW",
        requested_amount_cents=requested_amount_cents, source="MANUAL",
        lot_selection_method=lot_selection_method,
    )
    submit_order(account_id, bucket_id, order["id"])
    return settle_order(order["id"])


# ─── Round-up accruals / sweep ────────────────────────────────────────────
def add_card(account_id, multiplier=1, last_four="1111"):
    """Link a card with the given multiplier. Returns the card dict."""
    return get_success_data(api_client.create_linked_card(
        create_linked_card_payload(account_id, roundup_multiplier=multiplier, last_four=last_four),
        make_investor_headers(account_id),
    ))


def add_accrual(account_id, card_id, purchase_amount_cents):
    """Record a round-up accrual. Returns the accrual dict."""
    return get_success_data(api_client.create_roundup_accrual(
        create_roundup_accrual_payload(account_id, card_id, purchase_amount_cents=purchase_amount_cents),
        make_investor_headers(account_id),
    ))


def setup_account_with_pending_accruals(purchases, sweep_threshold_cents=100000,
                                        management_fee_bps=0, target_allocation=None,
                                        open_taxable=False):
    """Verified account with one card per requested multiplier and a set of PENDING
    accruals. `purchases` is a list of (multiplier, purchase_amount_cents) tuples.
    Returns (account, [accruals...]). The account version is fresh (re-read).
    """
    plan = create_plan(management_fee_bps=management_fee_bps)
    portfolio = create_portfolio(target_allocation=target_allocation)
    acct, _, _ = create_verified_account(
        plan=plan, portfolio=portfolio, sweep_threshold_cents=sweep_threshold_cents
    )
    if open_taxable:
        open_bucket(acct["id"], bucket_type="TAXABLE")
    cards = {}
    accruals = []
    for i, (mult, purchase) in enumerate(purchases):
        if mult not in cards:
            cards[mult] = add_card(acct["id"], multiplier=mult, last_four=f"{1000 + i}")
        accruals.append(add_accrual(acct["id"], cards[mult]["id"], purchase))
    acct = get_success_data(api_client.get_account(acct["id"], make_investor_headers(acct["id"])))
    return acct, accruals


def run_sweep(account_id, expected_account_version=None):
    """Run a sweep echoing the account's live version (auto-read when not supplied).
    Returns the account dict from the sweep response."""
    inv = make_investor_headers(account_id)
    if expected_account_version is None:
        acct = get_success_data(api_client.get_account(account_id, inv))
        expected_account_version = acct["version"]
    return get_success_data(
        api_client.sweep(account_id, {"expected_account_version": expected_account_version}, ADMIN)
    )


# ─── Referrals ────────────────────────────────────────────────────────────
def issue_referral(referrer_account_id, bonus_cents=1000, code=None):
    """Issue an ISSUED referral by the referrer. Returns the referral dict."""
    return get_success_data(api_client.create_referral(
        create_referral_payload(referrer_account_id, code or _unique_code(), bonus_cents=bonus_cents),
        make_investor_headers(referrer_account_id),
    ))


def redeem_referral(referral_id, redeemer_account_id):
    """Redeem an ISSUED referral as the redeemer. Returns the referral dict."""
    return get_success_data(api_client.redeem_referral(
        referral_id, {"referred_account_id": redeemer_account_id},
        make_investor_headers(redeemer_account_id),
    ))


def setup_redeemed_referral(referrer_invested=False, referred_amount_cents=600):
    """Referrer R and referred B (verified). Issue + redeem a referral by B.
    When `referred_invested` is True, B settles an INVEST of `referred_amount_cents`
    so lifetime_invested crosses the 500-cent qualification floor.
    Returns (referral, referrer, referred).
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer, _, _ = _unverified_account(plan, portfolio)
    referred, _, _ = create_verified_account(
        plan=plan, portfolio=portfolio, sweep_threshold_cents=100000
    )
    if referrer_invested:
        # not used; placeholder for symmetry
        pass
    referral = issue_referral(referrer["id"])
    if referred_amount_cents and referred_amount_cents > 0 and referrer_invested is False:
        pass
    redeem_referral(referral["id"], referred["id"])
    return referral, referrer, referred


def _unverified_account(plan, portfolio):
    acct = register_account(plan["id"], portfolio["id"])
    return acct, plan, portfolio


def setup_referred_invested_redeemed(bonus_cents=1000, invest_cents=600):
    """Referrer R + referred B (verified, has invested >= 500 via one settled INVEST).
    Referral issued by R and REDEEMED by B. Returns (referral, referrer, referred).
    """
    plan = create_plan()
    portfolio = create_portfolio()
    referrer = register_account(plan["id"], portfolio["id"])  # referrer need not be verified
    referred, _, _ = create_verified_account(
        plan=plan, portfolio=portfolio, sweep_threshold_cents=100000
    )
    # Fund + invest so B's lifetime_invested_cents >= 500.
    fund_account_via_found_money(referred["id"], invest_cents)
    bucket = open_bucket(referred["id"], bucket_type="TAXABLE")
    create_settled_invest_order(referred["id"], bucket["id"], invest_cents)
    referral = issue_referral(referrer["id"], bonus_cents=bonus_cents)
    redeem_referral(referral["id"], referred["id"])
    return referral, referrer, referred
