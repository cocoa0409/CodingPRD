"""Referral-credit amounts and lifecycle, plus the optimistic-concurrency guard on the two
OCC-protected subscription writes."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    setup_active_subscription,
    setup_referral_pair,
    setup_referred_with_active_subscription,
    generate_order,
    resize_payload,
    redeem_preview_payload,
    get_subscription_version,
    ApiErrorId,
)

BILLING = TEST_USERS["billing_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_referral_credit_amounts_pending_at_signup(api):
    """PRD §3.8: "The `referred_grant_cents` — the welcome credit to the new account — is a flat
    2000 cents. The `referrer_grant_cents` — the reward to the referrer — is the smaller of a flat
    1500 cents and the room remaining under the referrer's annual cap".
    PRD §3.8: "Both signup rows remain `PENDING` until the referred account's first `PAID` order".

    Design: Difficulty/dual_variant_calc/referral_credit_amount_vs_cycle_price_different_domains
    """
    referrer, referred = setup_referral_pair("ref-r@x.com", "ref-f@x.com")
    data_referrer, _ = _credits(
        api, referred_account_id=referred["id"], beneficiary="REFERRER"
    )
    data_referred, _ = _credits(
        api, referred_account_id=referred["id"], beneficiary="REFERRED"
    )
    assert data_referrer and data_referrer[0]["amount_cents"] == 1500
    assert data_referred and data_referred[0]["amount_cents"] == 2000
    assert data_referrer[0]["status"] == "PENDING"
    assert data_referred[0]["status"] == "PENDING"


def test_redeem_preview_uncapped_amounts(api):
    """PRD §3.8: "The anonymous redeem-preview endpoint computes the same `referrer_grant_cents`
    and `referred_grant_cents` for a supplied `referral_code` (honoring the referrer's cap) and
    returns them alongside the resolving `referrer_account_id`, without registering anything or
    minting rows."

    Design: Corner/calculations/referrer_grant_capped_at_lifetime_limit
    """
    set_clock("2026-01-01T00:00:00Z")
    referrer = register_account("ca-2r@x.com", full_name="R")
    res = api.redeem_preview(redeem_preview_payload(referrer["referral_code"]), ANON)
    preview = validate_success(res, 200)
    # lifetime 0 -> uncapped: min(1500, 9000-0) == 1500; referred flat 2000.
    assert preview["referrer_grant_cents"] == 1500, preview["referrer_grant_cents"]
    assert preview["referred_grant_cents"] == 2000, preview["referred_grant_cents"]


def test_cancel_before_paid_order_revokes_pending_signup_credits(api):
    """PRD §3.6: "if the owning account has no `PAID` order across any of its subscriptions, the
    account's `PENDING` `SIGNUP` referral-credit rows on which it is the `referred_account_id` are
    moved to `REVOKED`".

    Design: Corner/state_machines/cancel_before_first_paid_order_revokes_pending_signup_credits
    """
    referrer, referred, pet, recipe, sub = setup_referred_with_active_subscription(
        "rev-r@x.com", "rev-f@x.com"
    )
    headers = make_pet_parent_headers(referred["id"])
    cancelled = validate_success(api.cancel_subscription(sub["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED", cancelled["status"]

    data, _ = _credits(api, referred_account_id=referred["id"])
    signup_rows = [c for c in data if c["reason"] == "SIGNUP"]
    assert signup_rows, "two SIGNUP rows should exist for this pair"
    assert all(c["status"] == "REVOKED" for c in signup_rows), [c["status"] for c in signup_rows]

    acc_r = get_success_data(api.get_account(referrer["id"], BILLING))
    acc_f = get_success_data(api.get_account(referred["id"], BILLING))
    assert acc_r["wallet_credit_cents"] == 0
    assert acc_f["wallet_credit_cents"] == 0


def test_resize_with_stale_version_rejected(api):
    """PRD §2.8: "If another writer has staged a resize or generated an order in the meantime (both
    bump the version), the grams and price the current request computed against the prior snapshot
    are stale, and the resize is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_subscription_version_on_resize_returns_412
    """
    account, pet, recipe, sub = setup_active_subscription("cc-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    v_act = sub["version"]
    # Generating an order bumps the version, making v_act stale.
    generate_order(sub["id"], v_act)
    res = api.resize_subscription(sub["id"], resize_payload(v_act), headers)
    validate_error(res, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value)


def test_order_generate_with_current_version_succeeds_and_bumps(api):
    """PRD §2.8: "When generating the next cycle's order, the request must include
    `expected_subscription_version` equal to the target subscription's current `version`."
    PRD §3.6: "Generating the order increments the subscription's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_on_order_generate_succeeds_and_bumps_version
    """
    account, pet, recipe, sub = setup_active_subscription(
        "cc-2@x.com", sub_overrides={"cadence_days": 28}
    )
    v_now = get_subscription_version(sub["id"])
    res = api.generate_order(sub["id"], {"expected_subscription_version": v_now}, BILLING)
    validate_success(res, 201)
    v_after = get_subscription_version(sub["id"])
    assert v_after == v_now + 1, (v_after, v_now)


def _credits(api, **params):
    resp = api.list_referral_credits(BILLING, params=params)
    body = resp.json()
    return body.get("data", []), body.get("meta", {})
