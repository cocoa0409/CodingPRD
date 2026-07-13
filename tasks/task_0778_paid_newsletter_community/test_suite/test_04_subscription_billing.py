"""Subscription billing: proration, win-back discount, fee split, tier changes.

Difficulty (queue A): proration provisional remaining-days; win-back nested-max.
Corner (queue B): fee/net split; renewal full price; unverified subscribe;
tier/publication mismatch; immediate balance credit.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_member_headers,
    new_publication, new_tier, new_member, new_free_subscriber,
    new_paid_subscriber, new_trialing_paid_subscriber,
    setup_publication_with_pro_balance, setup_canceled_pro_subscription,
    set_clock, reset_clock, sub_version, find_invoice_by_reason, get_pub,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty A1 — provisional proration bills remaining forward days
# ---------------------------------------------------------------------------

def _setup_plus_active_then_advance(api):
    reset_clock(api)
    pub = new_publication(api, platform_fee_bps=1000)
    plus = new_tier(api, pub["id"], tier_rank=1, monthly_price_cents=1000, name="Plus")
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    bundle = new_paid_subscriber(api, pub["id"], plus["id"])
    set_clock(api, "2026-03-07T00:00:00Z")
    return pub, plus, pro, bundle


def test_change_tier_provisional_proration_amount_due(api):
    """PRD §3.4: "the remaining forward days are the whole days from the change
    instant to `current_period_end` (the day-difference rounded up to a whole
    day), the provisional factor is those remaining days divided by thirty, and
    the provisional charge is the price delta multiplied by that factor, rounded
    half up to whole cents."

    Design: Difficulty/dual_variant_calc/proration_provisional_remaining_days_on_subscription
    """
    _, _, pro, bundle = _setup_plus_active_then_advance(api)
    member, sub = bundle["member"], bundle["subscription"]
    v = sub_version(api, sub["id"], member["id"])
    resp = api.change_tier(
        sub["id"],
        {"new_tier_id": pro["id"], "expected_subscription_version": v},
        make_member_headers(member["id"]),
    )
    validate_success(resp, expected_status=200)
    inv = find_invoice_by_reason(api, sub["id"], "PRORATION_UPGRADE")
    assert inv["amount_due_cents"] == 1200, f"expected 1200, got {inv['amount_due_cents']}"
    assert inv["reason"] == "PRORATION_UPGRADE"


def test_change_tier_upgrade_sets_rank_and_gross_delta(api):
    """PRD §3.4: "A `PRORATION_UPGRADE` invoice carrying this charge is created
    only when the price delta is positive (a genuine upgrade); its `gross_cents`
    is the price delta and its `amount_due_cents` is the provisional charge. The
    change then sets the subscription's `tier_id` to the new tier, recomputes
    `current_tier_rank` ..."

    Design: Difficulty/dual_variant_calc/proration_provisional_remaining_days_on_subscription
    """
    _, _, pro, bundle = _setup_plus_active_then_advance(api)
    member, sub = bundle["member"], bundle["subscription"]
    v = sub_version(api, sub["id"], member["id"])
    resp = api.change_tier(
        sub["id"],
        {"new_tier_id": pro["id"], "expected_subscription_version": v},
        make_member_headers(member["id"]),
    )
    updated = validate_success(resp, expected_status=200)
    assert updated["current_tier_rank"] == 2
    inv = find_invoice_by_reason(api, sub["id"], "PRORATION_UPGRADE")
    assert inv["gross_cents"] == 1500, "gross_cents is the price delta (2500 - 1000)"


# ---------------------------------------------------------------------------
# Difficulty A3 — win-back invoice: nested max over discounted base
# ---------------------------------------------------------------------------

def test_winback_invoice_discount_cents(api):
    """PRD §3.5: "The **win-back discount** is the current tier's
    `monthly_price_cents` multiplied by twenty percent, rounded half up to whole
    cents; it populates the invoice's `discount_cents` ..."

    Design: Difficulty/combinatorial_formula/winback_invoice_nested_max_discount_mode_a
    """
    bundle = setup_canceled_pro_subscription(api)
    member, sub = bundle["member"], bundle["subscription"]
    resp = api.reactivate_subscription(sub["id"], make_member_headers(member["id"]))
    updated = validate_success(resp, expected_status=200)
    assert updated["is_win_back"] is True
    inv = find_invoice_by_reason(api, sub["id"], "WIN_BACK")
    assert inv["discount_cents"] == 500, f"expected 500, got {inv['discount_cents']}"


def test_winback_invoice_amount_due_after_discount(api):
    """PRD §3.4: "The net after discount is the base price minus the discount,
    floored at zero so it can never go negative. The `amount_due_cents` is then
    that net multiplied by the invoice's `proration_factor`, rounded half up to
    whole cents."

    Design: Difficulty/combinatorial_formula/winback_invoice_nested_max_discount_mode_a
    """
    bundle = setup_canceled_pro_subscription(api)
    member, sub = bundle["member"], bundle["subscription"]
    api.reactivate_subscription(sub["id"], make_member_headers(member["id"]))
    inv = find_invoice_by_reason(api, sub["id"], "WIN_BACK")
    assert inv["amount_due_cents"] == 2000, f"expected 2000, got {inv['amount_due_cents']}"


# ---------------------------------------------------------------------------
# Corner — fee/net split on a paid PRO invoice
# ---------------------------------------------------------------------------

def test_single_pro_invoice_fee_and_net(api):
    """PRD §2.6: "The **platform fee** for an invoice equals the invoice's
    `amount_due_cents` multiplied by the owning publication's `platform_fee_bps`,
    divided by ten thousand, rounded half up to whole cents; the result is stored
    as `platform_fee_cents`. The **creator net** is then the invoice's
    `amount_due_cents` minus that `platform_fee_cents`, stored as
    `creator_net_cents`."

    Design: Corner/calculations/single_pro_invoice_fee_and_net
    """
    pub = new_publication(api, platform_fee_bps=1000)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    t = new_trialing_paid_subscriber(api, pub["id"], pro["id"])
    resp = api.simulate_payment(
        {"invoice_id": t["initial_invoice_id"], "outcome": "SUCCEEDED"}, ADMIN
    )
    inv = validate_success(resp, expected_status=200)
    assert inv["platform_fee_cents"] == 250
    assert inv["creator_net_cents"] == 2250


# ---------------------------------------------------------------------------
# Corner — renewal invoice full price, no proration
# ---------------------------------------------------------------------------

def test_renewal_invoice_full_price_no_proration(api):
    """PRD §3.3: "Renewal creates a `RENEWAL` invoice with a proration factor of
    one and no discount, due at the current clock and `OPEN` ..."
    PRD §3.4: "For `INITIAL`, `RENEWAL`, and `WIN_BACK` invoices the
    `proration_factor` is one."

    Design: Corner/calculations/renewal_invoice_full_price_no_proration
    """
    reset_clock(api)
    bundle = setup_publication_with_pro_balance(api)
    sub = bundle["subscription"]
    set_clock(api, "2026-03-31T00:00:00Z")
    resp = api.renew_subscription(sub["id"], ADMIN)
    validate_success(resp, expected_status=200)
    inv = find_invoice_by_reason(api, sub["id"], "RENEWAL")
    assert inv["amount_due_cents"] == 2500
    assert inv["reason"] == "RENEWAL"


# ---------------------------------------------------------------------------
# Corner — subscribe while unverified
# ---------------------------------------------------------------------------

def test_subscribe_unverified_member_rejected(api):
    """PRD §3.2: "only a `VERIFIED` member may subscribe: attempting to subscribe
    while still `PENDING` (or after a bounce has driven the member to `BOUNCED`)
    is rejected with `ERR_MEMBER_NOT_VERIFIED`."

    Design: Corner/validations/subscribe_unverified_member_returns_409
    """
    pub = new_publication(api)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    member = new_member(api, pub["id"])  # still PENDING
    resp = api.create_subscription(
        member["id"], {"tier_id": pro["id"]}, make_member_headers(member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_VERIFIED.value)


# ---------------------------------------------------------------------------
# Corner — change-tier to a tier of a different publication
# ---------------------------------------------------------------------------

def test_change_tier_mismatched_publication_rejected(api):
    """PRD §2.5: "a member is `VERIFIED` before subscribing and the chosen tier
    belongs to the member's publication; otherwise `ERR_MEMBER_NOT_VERIFIED` or
    `ERR_TIER_PUBLICATION_MISMATCH` (409)."
    PRD §3.4: "The new tier must belong to the member's publication."

    Design: Corner/validations/change_tier_mismatched_publication_returns_409
    """
    pub1 = new_publication(api, creator_id="creator_1", name="P1")
    free1 = new_tier(api, pub1["id"], tier_rank=0, monthly_price_cents=0, name="Free")
    pub2 = new_publication(api, creator_id="creator_2", name="P2")
    pro2 = new_tier(api, pub2["id"], tier_rank=2, monthly_price_cents=2500,
                    name="Pro2", creator_id="creator_2")
    bundle = new_free_subscriber(api, pub1["id"], free1["id"])
    member, sub = bundle["member"], bundle["subscription"]
    v = sub_version(api, sub["id"], member["id"])
    resp = api.change_tier(
        sub["id"],
        {"new_tier_id": pro2["id"], "expected_subscription_version": v},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIER_PUBLICATION_MISMATCH.value)


# ---------------------------------------------------------------------------
# Corner — paying the initial invoice credits balance in the same request
# ---------------------------------------------------------------------------

def test_activation_credits_balance_immediately(api):
    """PRD §2.7: "When an invoice is paid, both `lifetime_net_cents` and
    `payout_balance_cents` increase by the invoice's `creator_net_cents`."
    PRD §2.6: two-fifty is the fee on 2500 at 1000 bps, leaving 2250 creator net.

    Design: Corner/consistency_model/subscription_activation_credits_balance_same_request
    """
    pub = new_publication(api, platform_fee_bps=1000)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    t = new_trialing_paid_subscriber(api, pub["id"], pro["id"])
    updated_inv = validate_success(
        api.simulate_payment(
            {"invoice_id": t["initial_invoice_id"], "outcome": "SUCCEEDED"}, ADMIN
        ),
        expected_status=200,
    )
    assert updated_inv["creator_net_cents"] == 2250
    pub_after = get_pub(api, pub["id"])
    assert pub_after["payout_balance_cents"] == 2250
