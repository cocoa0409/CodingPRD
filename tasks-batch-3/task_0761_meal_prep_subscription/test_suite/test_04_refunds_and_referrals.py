"""Box cancellation refunds (pre/post ship), wallet conservation, referral rewards, and the
parallel fulfillment x billing dimensions on a box.

Translates dual-variant, compensating-invariant, transitive-cascade, and non-linear
(parallel-dimension) difficulty instances (queue A) plus a state-machine corner instance.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, make_admin_headers,
    simulate_payment_payload,
    setup_two_boxes_for_refund, setup_pro_box_locked, setup_two_referees_charged,
    setup_referee_box_charged, setup_open_box_no_run,
)

ADMIN = make_admin_headers()


def _referral_by_referee(api, referee_id):
    data, _meta = validate_paginated(
        api.list_referrals(ADMIN, params={"referee_customer_id": referee_id}))
    assert len(data) == 1, f"expected one referral for referee {referee_id}, got {len(data)}"
    return data[0]


# --------------------------- box_refund dual variant ---------------------------

def test_cancel_locked_box_refunds_full_charge_to_original_payment(api):
    """PRD §3.7: "Cancelling a `LOCKED` box before it has shipped is the **pre-ship** refund
    variant and is a `PlatformAdmin` action; it is defined when billing is `CHARGED`, `PENDING`,
    or `CHARGE_FAILED`. The `refund_cents` is the full `total_charged_cents`, and the
    `refund_destination` is `ORIGINAL_PAYMENT` — the entire charge is returned to the original
    payment."

    Design: Difficulty/dual_variant_calc/box_refund_pre_vs_post_ship_on_box_domain
    """
    ctx = setup_two_boxes_for_refund(api)  # box_a LOCKED+CHARGED (pre-ship)
    box = validate_success(api.cancel_box(ctx["box_a_id"], ADMIN), 200)
    assert box["refund_cents"] == 13688
    assert box["refund_destination"] == "ORIGINAL_PAYMENT"


def test_cancel_shipped_box_refunds_meal_value_to_wallet(api):
    """PRD §3.7: "Cancelling a `SHIPPED` box is the **post-ship** refund variant, also a
    `PlatformAdmin` action, defined only when billing is `CHARGED`. Because the meals have
    already been dispatched, shipping and cold-pack costs are non-refundable: the `refund_cents`
    is the `total_charged_cents` minus the `shipping_fee_cents` minus the `cold_pack_fee_cents`,
    leaving only the meal value. This meal-value refund is returned to the wallet — the
    `refund_destination` is `WALLET_CREDIT`".

    Design: Difficulty/dual_variant_calc/box_refund_pre_vs_post_ship_on_box_domain
    """
    ctx = setup_two_boxes_for_refund(api)  # box_b LOCKED+CHARGED+SHIPPED (post-ship)
    box = validate_success(api.cancel_box(ctx["box_b_id"], ADMIN), 200)
    assert box["refund_cents"] == 13188  # 13688 - 0 shipping - 500 cold pack
    assert box["refund_destination"] == "WALLET_CREDIT"


# --------------------------- wallet conservation (apply then restore) ---------------------------

def test_wallet_consumed_when_box_charged(api):
    """PRD §3.5: "When the `outcome` is `SUCCEEDED`, billing moves `PENDING → CHARGED`; at that
    moment the pinned `credit_applied_cents` is consumed from the wallet by appending a negative
    `CREDIT_APPLIED` ledger entry of that amount (written only when `credit_applied_cents` is
    greater than zero)."

    Design: Difficulty/compensating_invariant/wallet_conservation_apply_then_refund_restore
    """
    ctx = setup_pro_box_locked(api, quantity=12, wallet_cents=5000, charge="SUCCEEDED")
    customer = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert customer["wallet_credit_cents"] == 0, "seeded 5000c credit is fully applied at charge"


def test_wallet_restored_on_pre_ship_cancel(api):
    """PRD §3.7: "If the box had reached `CHARGED`, its billing moves `CHARGED → REFUNDED`, and
    any `credit_applied_cents` that had been consumed from the wallet is restored by appending a
    positive `REFUND_CREDIT` ledger entry of that amount so the wallet recovers what it spent."

    Design: Difficulty/compensating_invariant/wallet_conservation_apply_then_refund_restore
    """
    ctx = setup_pro_box_locked(api, quantity=12, wallet_cents=5000, charge="SUCCEEDED")
    box = validate_success(api.cancel_box(ctx["box_id"], ADMIN), 200)
    assert box["refund_cents"] == 8688  # total_charged = gross 13688 - credit 5000
    assert box["refund_destination"] == "ORIGINAL_PAYMENT"
    assert box["billing_status"] == "REFUNDED"
    customer = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert customer["wallet_credit_cents"] == 5000, "applied credit fully restored, no drift"


# --------------------------- referral reward dual variant ---------------------------

def test_referral_reward_premium_referee(api):
    """PRD §3.6: "When it is greater than or equal to 12, the reward is the base plus a premium
    bonus of 1500 cents (`PREMIUM_BONUS_CENTS`), for a total of 3500 cents."
    PRD §3.6: "pays it to the referrer by appending a positive `REFERRAL_REWARD` ledger entry of
    that amount to the referrer's wallet, after which the referrer's `wallet_credit_cents`
    recomputes upward."

    Design: Difficulty/dual_variant_calc/referral_reward_standard_vs_premium_on_customer_domain
    """
    ctx = setup_two_referees_charged(api)
    validate_success(api.ship_box(ctx["box_p_id"], ADMIN), 200)  # PRO (12/wk) referee
    validate_success(api.ship_box(ctx["box_s_id"], ADMIN), 200)  # STARTER (6/wk) referee
    assert _referral_by_referee(api, ctx["p_id"])["reward_cents"] == 3500
    referrer = validate_success(api.get_customer(ctx["r_id"], ADMIN), 200)
    assert referrer["wallet_credit_cents"] == 5500  # 3500 + 2000


def test_referral_reward_standard_referee(api):
    """PRD §3.6: "When that figure is below the premium threshold of 12 meals per week
    (`PREMIUM_MIN_MEALS`), the reward is the base of 2000 cents (`REFERRAL_BASE_CENTS`)."

    Design: Difficulty/dual_variant_calc/referral_reward_standard_vs_premium_on_customer_domain
    """
    ctx = setup_two_referees_charged(api)
    validate_success(api.ship_box(ctx["box_p_id"], ADMIN), 200)
    validate_success(api.ship_box(ctx["box_s_id"], ADMIN), 200)
    assert _referral_by_referee(api, ctx["s_id"])["reward_cents"] == 2000


# --------------------------- ship qualifies referral (transitive cascade depth 2) ---------------------------

def test_ship_first_box_marks_box_shipped(api):
    """PRD §3.6: "A `PlatformAdmin` **ships** a locked box, moving fulfillment
    `LOCKED → SHIPPED`."

    Design: Difficulty/transitive_cascade/box_ship_qualifies_referral_credits_referrer_depth2
    """
    ctx = setup_referee_box_charged(api)
    box = validate_success(api.ship_box(ctx["box_id"], ADMIN), 200)
    assert box["fulfillment_status"] == "SHIPPED"


def test_ship_first_box_rewards_referrer(api):
    """PRD §3.6: "when the customer who owns the shipped first box is the referee of a `PENDING`
    referral and their account is `ACTIVE`, that referral moves `PENDING → REWARDED` in the same
    request. Qualification computes the `reward_cents` and pays it to the referrer by appending
    a positive `REFERRAL_REWARD` ledger entry of that amount to the referrer's wallet, after
    which the referrer's `wallet_credit_cents` recomputes upward."

    Design: Difficulty/transitive_cascade/box_ship_qualifies_referral_credits_referrer_depth2
    """
    ctx = setup_referee_box_charged(api)
    validate_success(api.ship_box(ctx["box_id"], ADMIN), 200)
    assert _referral_by_referee(api, ctx["e_id"])["status"] == "REWARDED"
    referrer = validate_success(api.get_customer(ctx["r_id"], ADMIN), 200)
    assert referrer["wallet_credit_cents"] == 3500  # PRO referee -> premium reward


# --------------------------- parallel fulfillment x billing dimensions ---------------------------

def test_declined_charge_leaves_fulfillment_locked_billing_failed(api):
    """PRD §3.5: "When the `outcome` is `DECLINED`, billing moves `PENDING → CHARGE_FAILED`;
    no wallet credit is consumed and the box stays `LOCKED` in fulfillment."

    Design: Difficulty/non_linear_state_machine/box_parallel_fulfillment_and_billing_dimensions
    """
    ctx = setup_pro_box_locked(api, quantity=12)  # billing PENDING, fulfillment LOCKED
    box = validate_success(
        api.simulate_payment(simulate_payment_payload(ctx["box_id"], "DECLINED"), ADMIN), 200)
    assert box["fulfillment_status"] == "LOCKED"
    assert box["billing_status"] == "CHARGE_FAILED"


def test_charge_failed_box_cannot_ship(api):
    """PRD §3.6: "Shipping requires that billing has reached `CHARGED`; attempting to ship a box
    whose billing is `CHARGE_FAILED` is refused with `ERR_PAYMENT_DECLINED`."

    Design: Difficulty/non_linear_state_machine/box_parallel_fulfillment_and_billing_dimensions
    """
    ctx = setup_pro_box_locked(api, quantity=12, charge="DECLINED")
    resp = api.ship_box(ctx["box_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED.value)


def test_ship_open_box_invalid_transition(api):
    """PRD §2.9: "(4) state validity, that the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE`".
    PRD §3.6: "A `PlatformAdmin` **ships** a locked box, moving fulfillment `LOCKED → SHIPPED`."

    Design: Corner/state_machines/ship_open_box_invalid_transition
    """
    ctx = setup_open_box_no_run(api)  # box is OPEN, never locked
    resp = api.ship_box(ctx["box_id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
