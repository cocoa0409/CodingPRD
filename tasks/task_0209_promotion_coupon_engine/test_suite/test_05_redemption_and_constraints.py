"""Redemption confirmation cascade, budget/abuse/coupon caps, eligibility,
cross-entity state dependencies, stacking conflicts, and validation precedence.

Translates queue A (Difficulty): dual_variant_calc (budget would-exceed vs
exhausted), transitive_cascade (checkout -> confirm -> budget -> EXHAUSTED),
priority_pair_validation_conflict (both pairs), boundary_precision (abuse count),
cross_entity_state_dependency (both pairs). Translates queue B (Corner):
state_machines (coupon auto-exhaust), validations (fk, disabled, stacking,
exclusion, coupon-cap), errors (not-redeemable draft).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock,
    create_customer,
    create_segment,
    add_membership,
    create_promotion,
    create_coupon,
    activate_promotion,
    pause_promotion,
    create_active_promotion,
    create_exclusion_rule,
    setup_cart_with_lines,
    setup_priced_cart_with_coupon,
    setup_locked_cart_with_coupon,
    create_cart_for,
    add_line,
    apply,
    reprice,
    lock,
    checkout,
    checkout_full,
    get_promotion,
    get_cart_redemption,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_shopper_headers

ADMIN = TEST_USERS["merchant_admin_headers"]


def _checkout_budget_capped(cust_id, code, lines, promo_id):
    """Apply a budget-capped coupon (resolving promo version), reprice, lock, checkout."""
    cart, _ = setup_cart_with_lines(cust_id, lines)
    promo_ver = get_promotion(promo_id)["version"]
    apply(cart["id"], cust_id, code, expected_promotion_version=promo_ver)
    reprice(cart["id"], cust_id)
    locked = lock(cart["id"], cust_id)
    return checkout(cart["id"], cust_id, locked["version"])


# ───────── transitive_cascade: checkout -> confirm -> budget -> EXHAUSTED ───
def test_checkout_confirms_redemption_and_exhausts_budget(api):
    """PRD §3.11: "Each `RESERVED` redemption transitions to `CONFIRMED`. For
    each confirmation the promotion's `budget_consumed_cents` is increased by
    that redemption's `discount_cents`"
    PRD §3.11: "a promotion whose `budget_consumed_cents` has reached its
    `budget_cap_cents` transitions to `EXHAUSTED`"

    Design: Difficulty/transitive_cascade/tc_checkout_confirm_budget_exhaust_depth3
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="TC1")
    promo, _ = create_active_promotion("THRESHOLD", name="TCB",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=1000,
                                       coupon_code="TCB1", coupon_use_mode="SINGLE_USE")
    _checkout_budget_capped(cust["id"], "TCB1", [("S", 5000, 1)], promo["id"])

    redemption = get_cart_redemption_for_customer(api, cust["id"])
    assert redemption["status"] == "CONFIRMED"
    promo_after = get_promotion(promo["id"])
    assert promo_after["budget_consumed_cents"] == 1000
    assert promo_after["status"] == "EXHAUSTED"


def get_cart_redemption_for_customer(api, customer_id):
    """Return the single redemption visible to a customer across their carts."""
    res = api.list_redemptions(ADMIN, params={"customer_id": customer_id})
    data, _ = _maybe_paginated(res)
    return data[0]


def _maybe_paginated(res):
    body = res.json()
    return body["data"], body.get("meta", {})


def test_checkout_increments_budget_consumed(api):
    """PRD §3.11: "For each confirmation the promotion's `budget_consumed_cents`
    is increased by that redemption's `discount_cents`, and where a coupon was
    involved its `redeemed_count` is increased by one."

    Design: Difficulty/transitive_cascade/tc_checkout_confirm_budget_exhaust_depth3
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="TC1b")
    promo, coupon = create_active_promotion("THRESHOLD", name="TCB2",
                                            threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                            budget_cap_cents=5000,
                                            coupon_code="TCB2K", coupon_use_mode="MULTI_USE",
                                            coupon_overrides={"max_total_redemptions": 10})
    _checkout_budget_capped(cust["id"], "TCB2K", [("S", 5000, 1)], promo["id"])
    promo_after = get_promotion(promo["id"])
    assert promo_after["budget_consumed_cents"] == 1000
    coupon_after = validate_success(api.get_coupon(promo["id"], coupon["id"], ADMIN), 200)
    assert coupon_after["redeemed_count"] == 1


# ───────── dual_variant_calc: budget would-exceed vs exhausted ──────────────
def test_budget_exhausted_after_full_consumption(api):
    """PRD §3.3: "when a redemption is confirmed at checkout and that
    confirmation brings `budget_consumed_cents` exactly up to `budget_cap_cents`
    — possible only when a budget cap is set — the promotion transitions from
    `ACTIVE` to `EXHAUSTED`, and every subsequent application against it is
    rejected with `ERR_PROMO_BUDGET_EXHAUSTED`."

    Design: Difficulty/dual_variant_calc/dvc_budget_would_exceed_vs_exhausted
    """
    set_clock("2026-06-15T00:00:00Z")
    c1 = create_customer(display_name="C1")
    promo, _ = create_active_promotion("THRESHOLD", name="BP",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=1000,
                                       coupon_code="BUDGET1", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 100})
    create_coupon(promo["id"], code="BUDGET2", use_mode="MULTI_USE", max_total_redemptions=100)
    _checkout_budget_capped(c1["id"], "BUDGET1", [("S", 5000, 1)], promo["id"])

    promo_after = get_promotion(promo["id"])
    assert promo_after["budget_consumed_cents"] == 1000
    assert promo_after["status"] == "EXHAUSTED"

    # Second customer attempts to apply against the now-exhausted promotion.
    c2 = create_customer(display_name="C2")
    cart2, _ = setup_cart_with_lines(c2["id"], [("S", 5000, 1)])
    promo_ver2 = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart2["id"], {"code": "BUDGET2", "expected_promotion_version": promo_ver2},
                           make_shopper_headers(c2["id"]))
    validate_error(res, "ERR_PROMO_BUDGET_EXHAUSTED", expected_status=409)


def test_budget_would_exceed_distinct_from_exhausted(api):
    """PRD §3.8: "Finally the promotion's budget must have headroom for the
    prospective discount, else `ERR_PROMO_BUDGET_WOULD_EXCEED`; and if the budget
    is already fully consumed (the promotion is `EXHAUSTED`) the application is
    rejected with `ERR_PROMO_BUDGET_EXHAUSTED`."
    PRD §3.8: "a pre-commit rejection distinct from `ERR_PROMO_BUDGET_EXHAUSTED`,
    which fires only when the budget has already been fully spent."

    Design: Difficulty/dual_variant_calc/dvc_budget_would_exceed_vs_exhausted
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="C1we")
    # Budget cap 500 but prospective discount 1000 -> committed(0)+1000 > 500 pre-commit.
    promo, _ = create_active_promotion("THRESHOLD", name="BPwe",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=500,
                                       coupon_code="BUDGETWE", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("S", 5000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart["id"], {"code": "BUDGETWE", "expected_promotion_version": promo_ver},
                           make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_BUDGET_WOULD_EXCEED", expected_status=409)


# ───────── boundary_precision: per-customer abuse count ─────────────────────
def test_abuse_limit_at_count_rejects_next_apply(api):
    """PRD §3.8: "The per-customer abuse limit must not yet be reached, again
    counting `CONFIRMED` and `RESERVED` redemptions of this promotion by this
    customer against `max_redemptions_per_customer`, else
    `ERR_ABUSE_LIMIT_EXCEEDED`."
    PRD §3.8: "The abuse-limit boundary is likewise inclusive: a customer may
    make the use that brings their count up to `max_redemptions_per_customer`,
    but a further use once the count already equals the limit is refused."

    Design: Difficulty/boundary_precision_check/bpc_abuse_count_at_limit_rejects_next
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="B2")
    promo, _ = create_active_promotion("PERCENT_OFF", name="ABU", percent_off=0.10,
                                       max_redemptions_per_customer=1,
                                       coupon_code="ABUC", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 100})
    # First redemption confirmed (count -> 1).
    cart1, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart1["id"], cust["id"], "ABUC")
    reprice(cart1["id"], cust["id"])
    locked = lock(cart1["id"], cust["id"])
    checkout(cart1["id"], cust["id"], locked["version"])

    # Second cart: count already at limit (1) -> next apply rejected.
    cart2, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart2["id"], {"code": "ABUC"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_ABUSE_LIMIT_EXCEEDED", expected_status=409)


def test_abuse_limit_use_up_to_limit_allowed(api):
    """PRD §3.8: "The abuse-limit boundary is likewise inclusive: a customer may
    make the use that brings their count up to `max_redemptions_per_customer`,
    but a further use once the count already equals the limit is refused."

    Design: Difficulty/boundary_precision_check/bpc_abuse_count_at_limit_rejects_next
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="B2ok")
    create_active_promotion("PERCENT_OFF", name="ABUok", percent_off=0.10,
                            max_redemptions_per_customer=1,
                            coupon_code="ABUCOK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    # The first apply brings the per-customer count up to the limit (1) -> allowed.
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "ABUCOK"}, make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["status"] == "APPLIED"


# ───────── priority_pair: not_priced (10) beats not_redeemable (11) ─────────
def test_lock_not_priced_beats_not_redeemable(api):
    """PRD §2.9: "Where a single endpoint is guarded by several of these, they
    fire in exactly this relative order"
    PRD §2.9: "the cart cross-dimension guards (`ERR_CART_NOT_PRICED` and
    `ERR_CART_NOT_OPEN`), redeemability (`ERR_PROMO_NOT_REDEEMABLE`)"
    PRD §3.10: "Locking carries a cross-dimension guard: the cart's
    `pricing_status` must be `PRICED`, else `ERR_CART_NOT_PRICED`"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_priced_beats_not_redeemable
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="PP1")
    promo, _ = create_active_promotion("PERCENT_OFF", name="PP1", percent_off=0.10,
                                       coupon_code="PPC1", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "PPC1")
    reprice(cart["id"], cust["id"])
    # Make pricing STALE (add a line) AND pause the promotion (not redeemable).
    add_line(cart["id"], cust["id"], sku="B", unit_price_cents=500, quantity=1)
    pause_promotion(promo["id"])

    res = api.lock_cart(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_CART_NOT_PRICED", expected_status=409)


def test_lock_priced_cart_surfaces_not_redeemable_when_only_redeemability_fails(api):
    """PRD §2.9: "the cart cross-dimension guards (`ERR_CART_NOT_PRICED` and
    `ERR_CART_NOT_OPEN`), redeemability (`ERR_PROMO_NOT_REDEEMABLE`)"
    PRD §3.10: "Locking carries a cross-dimension guard: the cart's
    `pricing_status` must be `PRICED`, else `ERR_CART_NOT_PRICED`, so a cart can
    only be locked against a freshly computed price."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_priced_beats_not_redeemable
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="PP1b")
    promo, _ = create_active_promotion("PERCENT_OFF", name="PP1b", percent_off=0.10,
                                       coupon_code="PPC1B", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "PPC1B")
    reprice(cart["id"], cust["id"])  # cart stays PRICED (priority-10 guard satisfied)
    pause_promotion(promo["id"])     # only redeemability (priority 11) now fails
    res = api.lock_cart(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)


# ───────── priority_pair: not_eligible (12) beats budget_would_exceed (16) ──
def test_apply_not_eligible_beats_budget_would_exceed(api):
    """PRD §2.9: "Where a single endpoint is guarded by several of these, they
    fire in exactly this relative order"
    PRD §2.9: "eligibility (`ERR_NOT_ELIGIBLE`), stacking legality
    (`ERR_STACKING_CONFLICT`), coupon-cap (`ERR_COUPON_EXHAUSTED`), abuse-limit
    (`ERR_ABUSE_LIMIT_EXCEEDED`), budget-headroom
    (`ERR_PROMO_BUDGET_WOULD_EXCEED`)"
    PRD §3.8: "in `FIRST_ORDER` mode the customer's `order_count` must be zero; a
    failure is `ERR_NOT_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_eligible_beats_budget_would_exceed
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="PP2")
    # Make the customer non-first-order by checking out a prior cart (no promo).
    prior_cart, _ = setup_cart_with_lines(cust["id"], [("X", 1000, 1)])
    reprice(prior_cart["id"], cust["id"])
    plocked = lock(prior_cart["id"], cust["id"])
    checkout(prior_cart["id"], cust["id"], plocked["version"])

    promo, _ = create_active_promotion("THRESHOLD", name="PP2",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       eligibility_mode="FIRST_ORDER", budget_cap_cents=500,
                                       coupon_code="PPC2", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("Y", 4000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart["id"], {"code": "PPC2", "expected_promotion_version": promo_ver},
                           make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_NOT_ELIGIBLE", expected_status=403)


def test_apply_budget_would_exceed_when_eligibility_passes(api):
    """PRD §2.9: "eligibility (`ERR_NOT_ELIGIBLE`), stacking legality
    (`ERR_STACKING_CONFLICT`), coupon-cap (`ERR_COUPON_EXHAUSTED`), abuse-limit
    (`ERR_ABUSE_LIMIT_EXCEEDED`), budget-headroom
    (`ERR_PROMO_BUDGET_WOULD_EXCEED`)"
    PRD §3.8: "Finally the promotion's budget must have headroom for the
    prospective discount, else `ERR_PROMO_BUDGET_WOULD_EXCEED`"

    Design: Difficulty/priority_pair_validation_conflict/ppvc_not_eligible_beats_budget_would_exceed
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="PP2b")
    # FIRST_ORDER eligibility passes (order_count 0) but budget would be exceeded.
    promo, _ = create_active_promotion("THRESHOLD", name="PP2b",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       eligibility_mode="FIRST_ORDER", budget_cap_cents=500,
                                       coupon_code="PPC2B", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("Y", 4000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart["id"], {"code": "PPC2B", "expected_promotion_version": promo_ver},
                           make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_BUDGET_WOULD_EXCEED", expected_status=409)


# ───────── cross_entity_state_dependency: cart lock requires promo ACTIVE ───
def test_cart_lock_requires_promotion_active(api):
    """PRD §3.10: "Locking also re-verifies every `APPLIED` application at the
    moment of lock: each application's promotion must be `ACTIVE`, the clock must
    fall within that promotion's window from `active_from` up to `active_until`,
    and the clock must lie within none of its blackout intervals — any violation
    is `ERR_PROMO_NOT_REDEEMABLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_cart_lock_requires_promotion_active
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CE1")
    promo, _ = create_active_promotion("PERCENT_OFF", name="CE1", percent_off=0.10,
                                       coupon_code="CEC1", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "CEC1")
    reprice(cart["id"], cust["id"])
    pause_promotion(promo["id"])
    res = api.lock_cart(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)


def test_cart_lock_fails_when_promotion_window_closed(api):
    """PRD §3.10: "Locking also re-verifies every `APPLIED` application at the
    moment of lock: each application's promotion must be `ACTIVE`, the clock must
    fall within that promotion's window from `active_from` up to `active_until`,
    and the clock must lie within none of its blackout intervals — any violation
    is `ERR_PROMO_NOT_REDEEMABLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_cart_lock_requires_promotion_active
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CE1b")
    create_active_promotion("PERCENT_OFF", name="CE1b", percent_off=0.10,
                            active_from="2026-06-01T00:00:00Z",
                            active_until="2026-06-20T00:00:00Z",
                            coupon_code="CEC1B", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "CEC1B")
    reprice(cart["id"], cust["id"])
    # Advance clock past the window end (also expires the promotion via the sweep).
    set_clock("2026-06-25T00:00:00Z")
    res = api.lock_cart(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)


# ───────── cross_entity_state_dependency: SEGMENT requires ACTIVE membership ─
def test_segment_apply_requires_active_membership(api):
    """PRD §3.8: "in `SEGMENT` mode the cart's customer must hold an `ACTIVE`
    membership in the promotion's `eligible_segment_id`, and in `FIRST_ORDER`
    mode the customer's `order_count` must be zero; a failure is
    `ERR_NOT_ELIGIBLE`."
    PRD §3.1: "Revoking a membership transitions it from `ACTIVE` to `REVOKED`,
    recomputes the segment's `member_count` downward, and removes that customer's
    segment-based eligibility for any promotion keyed to the segment."

    Design: Difficulty/cross_entity_state_dependency/cesd_segment_apply_requires_active_membership
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CE2")
    seg = create_segment(code="VIP2", name="VIPs")
    mem = add_membership(seg["id"], cust["id"])
    get_success_data(api.revoke_member(seg["id"], mem["id"], ADMIN))
    promo, _ = create_active_promotion("PERCENT_OFF", name="CE2", percent_off=0.10,
                                       eligibility_mode="SEGMENT", eligible_segment_id=seg["id"],
                                       coupon_code="CEC2", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "CEC2"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_NOT_ELIGIBLE", expected_status=403)


def test_segment_apply_succeeds_with_active_membership(api):
    """PRD §3.8: "in `SEGMENT` mode the cart's customer must hold an `ACTIVE`
    membership in the promotion's `eligible_segment_id`, and in `FIRST_ORDER`
    mode the customer's `order_count` must be zero; a failure is
    `ERR_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/cesd_segment_apply_requires_active_membership
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CE2b")
    seg = create_segment(code="VIP3", name="VIPs")
    add_membership(seg["id"], cust["id"])  # ACTIVE membership in place
    create_active_promotion("PERCENT_OFF", name="CE2b", percent_off=0.10,
                            eligibility_mode="SEGMENT", eligible_segment_id=seg["id"],
                            coupon_code="CEC2B", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "CEC2B"}, make_shopper_headers(cust["id"]))
    app = validate_success(res, 201)
    assert app["status"] == "APPLIED"


# ───────── coupon auto-exhaust at cap ───────────────────────────────────────
def test_single_use_coupon_auto_exhausts_at_cap(api):
    """PRD §3.4: "A coupon also ends automatically: when a confirmation at
    checkout brings `redeemed_count` up to its cap — one for a `SINGLE_USE`
    coupon, or `max_total_redemptions` for a `MULTI_USE` coupon — the coupon
    transitions to `EXHAUSTED`"

    Design: Corner/state_machines/coupon_auto_exhausts_at_cap
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="SM7")
    promo, coupon = create_active_promotion("PERCENT_OFF", name="EXC", percent_off=0.10,
                                            coupon_code="EXCK", coupon_use_mode="SINGLE_USE")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "EXCK")
    reprice(cart["id"], cust["id"])
    locked = lock(cart["id"], cust["id"])
    checkout(cart["id"], cust["id"], locked["version"])

    coupon_after = validate_success(api.get_coupon(promo["id"], coupon["id"], ADMIN), 200)
    assert coupon_after["redeemed_count"] == 1
    assert coupon_after["status"] == "EXHAUSTED"


# ───────── validations: fk, disabled, stacking, exclusion, coupon-cap ───────
def test_apply_unknown_coupon_code_returns_fk_not_found(api):
    """PRD §2.9: "body foreign keys are checked against existing rows, yielding
    `ERR_FK_NOT_FOUND` when a referenced row is absent."

    Design: Corner/validations/apply_unknown_coupon_code_returns_fk_not_found
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="V3")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "GHOST"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_FK_NOT_FOUND", expected_status=422)


def test_apply_disabled_coupon_returns_coupon_disabled(api):
    """PRD §3.4: "Disabling moves `status` from `ENABLED` to `DISABLED`, after
    which any application presenting that code is rejected with
    `ERR_COUPON_DISABLED`"

    Design: Corner/validations/apply_disabled_coupon_returns_coupon_disabled
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="V4")
    promo = create_promotion("PERCENT_OFF", name="DIS", percent_off=0.10)
    coupon = create_coupon(promo["id"], code="DISK", use_mode="MULTI_USE", max_total_redemptions=10)
    activate_promotion(promo["id"])
    get_success_data(api.disable_coupon(promo["id"], coupon["id"], ADMIN))
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "DISK"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_COUPON_DISABLED", expected_status=409)


def test_exclusive_promo_with_other_returns_stacking_conflict(api):
    """PRD §3.8: "an `EXCLUSIVE` promotion may not coexist with any other
    `APPLIED` application on the cart, and two `STACKABLE` promotions may not be
    joined by an exclusion edge — either conflict is `ERR_STACKING_CONFLICT`."

    Design: Corner/validations/exclusive_promo_with_other_returns_stacking_conflict
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="V5")
    create_active_promotion("PERCENT_OFF", name="PSTK", percent_off=0.10,
                            stacking_class="STACKABLE",
                            coupon_code="STKK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    create_active_promotion("PERCENT_OFF", name="PEXC", percent_off=0.10,
                            stacking_class="EXCLUSIVE",
                            coupon_code="EXCC", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "STKK")
    res = api.apply_coupon(cart["id"], {"code": "EXCC"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_STACKING_CONFLICT", expected_status=409)


def test_excluded_pair_returns_stacking_conflict(api):
    """PRD §3.5: "A `MerchantAdmin` declares that two promotions may never
    co-apply on a cart by recording an `ExclusionRule`"
    PRD §3.8: "two `STACKABLE` promotions may not be joined by an exclusion edge
    — either conflict is `ERR_STACKING_CONFLICT`."

    Design: Corner/validations/excluded_pair_returns_stacking_conflict
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="V6")
    pa, _ = create_active_promotion("PERCENT_OFF", name="PA", percent_off=0.10,
                                    coupon_code="PAK", coupon_use_mode="MULTI_USE",
                                    coupon_overrides={"max_total_redemptions": 100})
    pb, _ = create_active_promotion("PERCENT_OFF", name="PB", percent_off=0.10,
                                    coupon_code="PBK", coupon_use_mode="MULTI_USE",
                                    coupon_overrides={"max_total_redemptions": 100})
    create_exclusion_rule(pa["id"], pb["id"], note="no combine")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "PAK")
    res = api.apply_coupon(cart["id"], {"code": "PBK"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_STACKING_CONFLICT", expected_status=409)


def test_single_use_coupon_exhausted_second_customer(api):
    """PRD §3.8: "The coupon's usage cap must not yet be reached, counting both
    `CONFIRMED` and `RESERVED` redemptions against a cap of one for `SINGLE_USE`
    or `max_total_redemptions` for `MULTI_USE`, else `ERR_COUPON_EXHAUSTED`."

    Design: Corner/validations/coupon_exhausted_single_use_second_apply
    """
    set_clock("2026-06-15T00:00:00Z")
    c1 = create_customer(display_name="V7a")
    promo, _ = create_active_promotion("PERCENT_OFF", name="SU", percent_off=0.10,
                                       coupon_code="SUK", coupon_use_mode="SINGLE_USE")
    cart1, _ = setup_cart_with_lines(c1["id"], [("A", 2000, 1)])
    apply(cart1["id"], c1["id"], "SUK")
    reprice(cart1["id"], c1["id"])
    locked = lock(cart1["id"], c1["id"])
    checkout(cart1["id"], c1["id"], locked["version"])

    c2 = create_customer(display_name="V7b")
    cart2, _ = setup_cart_with_lines(c2["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart2["id"], {"code": "SUK"}, make_shopper_headers(c2["id"]))
    validate_error(res, "ERR_COUPON_EXHAUSTED", expected_status=409)


# ───────── errors: promo not redeemable when DRAFT ──────────────────────────
def test_apply_draft_promotion_not_redeemable(api):
    """PRD §3.8: "The promotion must be redeemable — `ACTIVE`, with the clock
    inside its window and outside every blackout, and the coupon `ENABLED` —
    else `ERR_PROMO_NOT_REDEEMABLE`."

    Design: Corner/errors/error_promo_not_redeemable_draft
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="E3")
    promo = create_promotion("PERCENT_OFF", name="DR", percent_off=0.10)
    create_coupon(promo["id"], code="DRK", use_mode="MULTI_USE", max_total_redemptions=10)
    # Deliberately NOT activated -> still DRAFT.
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.apply_coupon(cart["id"], {"code": "DRK"}, make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_PROMO_NOT_REDEEMABLE", expected_status=409)
