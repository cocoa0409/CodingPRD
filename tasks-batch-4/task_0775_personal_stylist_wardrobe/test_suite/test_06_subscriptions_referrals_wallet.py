"""Subscriptions and referrals: the flat estimated vs realized referral credit, self-referral
and expiry guards, subscription activation wallet debit and refresh-credit grant, insufficient
wallet, and exhausted refresh credits.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_signed_up_referral_with_issued_invoice, setup_pending_subscription,
    setup_active_subscription, set_clock, register_client,
    create_referral_payload, signup_referral_payload,
    make_client_headers, make_admin_headers,
)


# ─────────────── dual_variant_calc / referral_credit_estimated_vs_realized ───────────────
def test_referral_estimated_credit_is_flat_at_creation(api):
    """PRD §3.9: "The referral is created in PENDING with referee_client_id and
    qualifying_invoice_id unset, its estimated_credit_cents set to the flat projected reward of
    5000 cents, and its expires_at set to ninety days after creation."

    Design: Difficulty/dual_variant_calc/referral_credit_estimated_vs_realized
    """
    referrer = register_client(api)
    refl = validate_success(api.create_referral(
        create_referral_payload(referrer_client_id=referrer["id"], referee_email="prospect@x.com"),
        make_client_headers(referrer["id"])), 201)
    assert refl["status"] == "PENDING"
    assert refl["estimated_credit_cents"] == 5000, f"flat estimate 5000, got {refl['estimated_credit_cents']}"


def test_referral_realized_credit_from_paid_invoice_differs_from_estimate(api):
    """PRD §3.9: "realized_credit_cents is computed as the lesser of the cap of 10000 cents and ten
    percent of the qualifying invoice's total_cents rounded half up." PRD §3.9: "its
    estimated_credit_cents set to the flat projected reward of 5000 cents."

    Design: Difficulty/dual_variant_calc/referral_credit_estimated_vs_realized
    """
    ctx = setup_signed_up_referral_with_issued_invoice(api, clock_iso="2026-03-15T00:00:00Z")
    assert ctx["invoice"]["total_cents"] == 19800, "18000 session + 1800 styling fee"
    validate_success(api.pay_invoice(ctx["invoice"]["id"], make_admin_headers()), 200)
    refl = validate_success(api.get_referral(ctx["referral"]["id"], make_admin_headers()), 200)
    assert refl["status"] == "CREDITED"
    assert refl["realized_credit_cents"] == 1980, f"round(0.10*19800)=1980, got {refl['realized_credit_cents']}"
    assert refl["estimated_credit_cents"] == 5000, "flat estimate is unchanged by realization"


# ─────────────── Corner: create_referral_self_email_rejected ───────────────
def test_create_referral_with_own_email_rejected(api):
    """PRD §3.9: "The referee email must not be the referrer's own email; a self-referral at
    creation is rejected with ERR_SELF_REFERRAL."

    Design: Corner/validations/create_referral_self_email_rejected
    """
    cl = register_client(api, email="self_c@x.com")
    resp = api.create_referral(
        create_referral_payload(referrer_client_id=cl["id"], referee_email="self_c@x.com"),
        make_client_headers(cl["id"]))
    validate_error(resp, ApiErrorId.ERR_SELF_REFERRAL.value)


# ─────────────── Corner: referral_signup_after_expiry_rejected ───────────────
def test_referral_signup_after_expiry_rejected(api):
    """PRD §3.9: "Signup requires the referral to be PENDING ... the logical clock to be at or
    before expires_at (otherwise ERR_REFERRAL_EXPIRED)."

    Design: Corner/validations/referral_signup_after_expiry_rejected
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    referrer = register_client(api)
    referee = register_client(api)
    refl = validate_success(api.create_referral(
        create_referral_payload(referrer_client_id=referrer["id"], referee_email=referee["email"]),
        make_client_headers(referrer["id"])), 201)
    # created 2026-03-01 -> expires 2026-05-30; advance well past expiry.
    set_clock(api, "2026-07-01T00:00:00Z")
    resp = api.signup_referral(refl["id"], signup_referral_payload(referee_client_id=referee["id"]),
                               make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_REFERRAL_EXPIRED.value)


# ─────────────── Corner: subscription_activate_insufficient_wallet_rejected ───────────────
def test_subscription_activate_insufficient_wallet_rejected(api):
    """PRD §3.8: "A PlatformAdmin activates a PENDING subscription, which requires that the
    client's wallet_credit_cents be at least the monthly_fee_cents; if the wallet is short,
    activation is rejected with ERR_INSUFFICIENT_WALLET."

    Design: Corner/validations/subscription_activate_insufficient_wallet_rejected
    """
    ctx = setup_pending_subscription(api, tier="SILVER", monthly_fee_cents=5000, wallet_credit=0)
    resp = api.activate_subscription(ctx["subscription"]["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)


# ─────────────── Corner: redeem_refresh_when_zero_credits_rejected ───────────────
def test_redeem_refresh_when_credits_exhausted_rejected(api):
    """PRD §3.8: "A Client redeems one seasonal-refresh credit at a time against an ACTIVE
    subscription, which requires refresh_credits_remaining to be at least one and decrements it by
    one (it can never go below zero); redeeming with no credits left is rejected with
    ERR_NO_REFRESH_CREDITS."

    Design: Corner/validations/redeem_refresh_when_zero_credits_rejected
    """
    ctx = setup_active_subscription(api, tier="SILVER", monthly_fee_cents=6000, wallet_credit=6000)
    cl_id = ctx["client"]["id"]
    sub_id = ctx["subscription"]["id"]
    # SILVER grants exactly 2 credits; redeem both.
    validate_success(api.redeem_refresh(sub_id, make_client_headers(cl_id)), 200)
    validate_success(api.redeem_refresh(sub_id, make_client_headers(cl_id)), 200)
    resp = api.redeem_refresh(sub_id, make_client_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_NO_REFRESH_CREDITS.value)


# ─────────────── Corner: subscription_activate_debits_wallet_and_grants_gold_credits ───────────────
def test_activate_gold_subscription_debits_wallet_and_grants_four_credits(api):
    """PRD §3.8: "Activation moves the subscription to ACTIVE, debits the monthly_fee_cents from
    the client's wallet, and grants seasonal-refresh credits: a SILVER subscription grants two and
    a GOLD subscription grants four, setting both refresh_credits_total and
    refresh_credits_remaining to that count."

    Design: Corner/cross_cutting/subscription_activate_debits_wallet_and_grants_gold_credits
    """
    ctx = setup_pending_subscription(api, tier="GOLD", monthly_fee_cents=6000, wallet_credit=10000)
    sub = validate_success(api.activate_subscription(ctx["subscription"]["id"], make_admin_headers()), 200)
    assert sub["status"] == "ACTIVE"
    assert sub["refresh_credits_remaining"] == 4, f"GOLD grants 4 credits, got {sub['refresh_credits_remaining']}"
    client = validate_success(api.get_client(ctx["client"]["id"], make_admin_headers()), 200)
    assert client["wallet_credit_cents"] == 4000, f"10000 - 6000 fee = 4000, got {client['wallet_credit_cents']}"
