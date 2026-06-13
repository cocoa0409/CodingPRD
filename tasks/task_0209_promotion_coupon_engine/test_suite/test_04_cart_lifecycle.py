"""Cart lifecycle: parallel pricing/checkout dimensions, OCC on checkout,
compensation on unlock/abandon, derived-field reconciliation, computed fields,
and cart endpoint behaviors.

Translates queue A (Difficulty): non_linear_state_machine (cart parallel
dimensions), compensating_invariant (budget across lock/unlock, redeemed_count
across lock/abandon). Translates queue B (Corner): state_machines (cart invalid
transitions, terminal lockdown, reprice-on-locked), entities (subtotal computed),
endpoints (remove app, patch line, empty auto-apply), cross_cutting (OCC stale/
correct cart version, derived member_count).
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
    create_active_promotion,
    setup_cart_with_lines,
    create_cart_for,
    add_line,
    apply,
    reprice,
    lock,
    unlock,
    abandon,
    checkout,
    get_promotion,
    get_cart_redemption,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import make_shopper_headers

ADMIN = TEST_USERS["merchant_admin_headers"]


# ───────── non_linear_state_machine: cart parallel dimensions ───────────────
def test_cart_parallel_pricing_checkout_dimensions(api):
    """PRD §3.6: "These last two are independent dimensions that evolve on
    different triggers, and a cart's full condition is the pair of them."
    PRD §3.6: "Whenever a line is added, updated, or removed, or whenever an
    application is added or removed, a cart that was previously `PRICED`
    automatically drops to `STALE` — the previously computed totals are retained
    as-is until the next reprice."

    Design: Difficulty/non_linear_state_machine/nlsm_cart_parallel_pricing_checkout
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="N2")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    cart = reprice(cart["id"], cust["id"])
    assert cart["pricing_status"] == "PRICED"
    assert cart["checkout_status"] == "OPEN"

    add_line(cart["id"], cust["id"], sku="B", unit_price_cents=500, quantity=1)
    after = validate_success(api.get_cart(cart["id"], make_shopper_headers(cust["id"])), 200)
    assert after["pricing_status"] == "STALE", "adding a line flips PRICED -> STALE"
    assert after["checkout_status"] == "OPEN", "checkout dimension unchanged by line add"


def test_cart_line_add_stales_only_pricing_dimension(api):
    """PRD §3.6: "a cart that was previously `PRICED` automatically drops to
    `STALE` — the previously computed totals are retained as-is until the next
    reprice."

    Design: Difficulty/non_linear_state_machine/nlsm_cart_parallel_pricing_checkout
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="N2b")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    priced = reprice(cart["id"], cust["id"])
    retained_subtotal = priced["subtotal_cents"]
    add_line(cart["id"], cust["id"], sku="C", unit_price_cents=700, quantity=2)
    after = validate_success(api.get_cart(cart["id"], make_shopper_headers(cust["id"])), 200)
    assert after["pricing_status"] == "STALE"
    assert after["subtotal_cents"] == retained_subtotal, "totals retained until next reprice"


# ───────── invalid cart transitions / lockdown / precondition ───────────────
def test_checkout_from_open_returns_invalid_state(api):
    """PRD §3.11: "Checkout completes the cart, moving `checkout_status` from
    `LOCKED` to the terminal `CHECKED_OUT`."
    PRD §3.10: "A transition requested from a state that does not admit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/checkout_from_open_returns_invalid_state
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="SM4")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    cart = reprice(cart["id"], cust["id"])
    res = api.checkout_cart(cart["id"], {"expected_cart_version": cart["version"]},
                            make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_unlock_checked_out_cart_returns_invalid_state(api):
    """PRD §3.10: "Unlocking is the compensation path: it moves `checkout_status`
    from `LOCKED` back to `OPEN`"
    PRD §3.10: "A transition requested from a state that does not admit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_checked_out_cart_rejects_unlock
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="SM5")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    cart = reprice(cart["id"], cust["id"])
    locked = lock(cart["id"], cust["id"])
    checkout(cart["id"], cust["id"], locked["version"])
    res = api.unlock_cart(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_reprice_on_locked_cart_returns_not_open(api):
    """PRD §3.6: "Repricing is what moves `pricing_status` to `PRICED` — from
    `UNPRICED` on the first pricing and from `STALE` on every subsequent one —
    and it is permitted only while `checkout_status` is `OPEN`, else
    `ERR_CART_NOT_OPEN`."

    Design: Corner/state_machines/reprice_on_locked_cart_returns_not_open
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="SM6")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    cart = reprice(cart["id"], cust["id"])
    lock(cart["id"], cust["id"])
    res = api.reprice(cart["id"], make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_CART_NOT_OPEN", expected_status=409)


# ───────── compensating_invariant: budget across lock/unlock ────────────────
def test_budget_consumed_unchanged_across_lock_unlock(api):
    """PRD §2.5: "A `Promotion`'s `budget_consumed_cents` is the sum of
    `discount_cents` over every `CONFIRMED` redemption beneath it"
    PRD §3.10: "Unlocking is the compensation path: it moves `checkout_status`
    from `LOCKED` back to `OPEN` and releases every `RESERVED` redemption for the
    cart, moving each to `RELEASED` so the provisional counters it held are
    restored. A released redemption no longer counts against any cap and leaves
    the `CONFIRMED`-derived figures untouched."

    Design: Difficulty/compensating_invariant/ci_budget_consumed_unchanged_lock_unlock
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CI1")
    promo, _ = create_active_promotion("THRESHOLD", name="CIB",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=5000,
                                       coupon_code="CIBC", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    cart, _ = setup_cart_with_lines(cust["id"], [("S", 5000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    apply(cart["id"], cust["id"], "CIBC", expected_promotion_version=promo_ver)
    reprice(cart["id"], cust["id"])
    lock(cart["id"], cust["id"])
    unlock(cart["id"], cust["id"])

    promo_after = get_promotion(promo["id"])
    assert promo_after["budget_consumed_cents"] == 0, "CONFIRMED-only figure unchanged"
    redemption = get_cart_redemption(cart["id"], cust["id"])
    assert redemption is not None
    assert redemption["status"] == "RELEASED"


def test_budget_consumed_zero_before_lock_and_after_unlock(api):
    """PRD §2.5: "A `Promotion`'s `budget_consumed_cents` is the sum of
    `discount_cents` over every `CONFIRMED` redemption beneath it"
    PRD §3.10: "A `RESERVED` redemption counts provisionally against the
    per-customer abuse limit, the coupon cap, and the promotion budget, which is
    how a locked-but-not-checked-out cart still holds its share of a finite
    budget."

    Design: Difficulty/compensating_invariant/ci_budget_consumed_unchanged_lock_unlock
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CI1b")
    promo, _ = create_active_promotion("THRESHOLD", name="CIBb",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 1000}],
                                       budget_cap_cents=5000,
                                       coupon_code="CIBCB", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 10})
    before = get_promotion(promo["id"])["budget_consumed_cents"]
    assert before == 0
    cart, _ = setup_cart_with_lines(cust["id"], [("S", 5000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    apply(cart["id"], cust["id"], "CIBCB", expected_promotion_version=promo_ver)
    reprice(cart["id"], cust["id"])
    lock(cart["id"], cust["id"])
    unlock(cart["id"], cust["id"])
    after = get_promotion(promo["id"])["budget_consumed_cents"]
    assert after == before, "CONFIRMED-only budget unchanged across lock+unlock (no drift)"


# ───────── compensating_invariant: redeemed_count across lock/abandon ───────
def test_coupon_redeemed_count_unchanged_across_lock_abandon(api):
    """PRD §2.5: "a `Coupon`'s `redeemed_count` is the count of `CONFIRMED`
    redemptions referencing it; both are reconciled on every confirm and every
    release."
    PRD §3.10: "Abandoning a cart is terminal and may happen from either `OPEN`
    or `LOCKED`: it moves `checkout_status` to `ABANDONED` and sets every
    `APPLIED` application to `REMOVED`; when abandoned from `LOCKED` it
    additionally releases all `RESERVED` redemptions to `RELEASED`."

    Design: Difficulty/compensating_invariant/ci_coupon_redeemed_count_unchanged_lock_abandon
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CI2")
    promo, coupon = create_active_promotion("PERCENT_OFF", name="CIC", percent_off=0.10,
                                            coupon_code="CICK", coupon_use_mode="MULTI_USE",
                                            coupon_overrides={"max_total_redemptions": 5})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "CICK")
    reprice(cart["id"], cust["id"])
    lock(cart["id"], cust["id"])
    abandon(cart["id"], cust["id"])

    coupon_after = validate_success(api.get_coupon(promo["id"], coupon["id"], ADMIN), 200)
    assert coupon_after["redeemed_count"] == 0, "CONFIRMED-only count unchanged after abandon"
    redemption = get_cart_redemption(cart["id"], cust["id"])
    assert redemption is not None
    assert redemption["status"] == "RELEASED"


def test_coupon_redeemed_count_zero_before_lock_and_after_abandon(api):
    """PRD §2.5: "a `Coupon`'s `redeemed_count` is the count of `CONFIRMED`
    redemptions referencing it; both are reconciled on every confirm and every
    release."
    PRD §3.10: "when abandoned from `LOCKED` it additionally releases all
    `RESERVED` redemptions to `RELEASED`."

    Design: Difficulty/compensating_invariant/ci_coupon_redeemed_count_unchanged_lock_abandon
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="CI2b")
    promo, coupon = create_active_promotion("PERCENT_OFF", name="CICb", percent_off=0.10,
                                            coupon_code="CICKB", coupon_use_mode="MULTI_USE",
                                            coupon_overrides={"max_total_redemptions": 5})
    before = validate_success(api.get_coupon(promo["id"], coupon["id"], ADMIN), 200)["redeemed_count"]
    assert before == 0
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    apply(cart["id"], cust["id"], "CICKB")
    reprice(cart["id"], cust["id"])
    lock(cart["id"], cust["id"])
    abandon(cart["id"], cust["id"])
    after = validate_success(api.get_coupon(promo["id"], coupon["id"], ADMIN), 200)["redeemed_count"]
    assert after == before, "CONFIRMED-only count unchanged across lock+abandon (no drift)"


# ───────── computed: subtotal from lines ────────────────────────────────────
def test_cart_subtotal_computed_from_lines(api):
    """PRD §3.6: "A reprice first recomputes `subtotal_cents` as the sum over
    every line of its `unit_price_cents` multiplied by its `quantity`."

    Design: Corner/entities/cart_subtotal_computed_from_lines
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="Sub")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 1000, 2), ("B", 500, 3)])
    cart = reprice(cart["id"], cust["id"])
    assert cart["subtotal_cents"] == 3500


# ───────── endpoints ────────────────────────────────────────────────────────
def test_remove_application_sets_removed_and_stale(api):
    """PRD §3.8: "An application can be removed, moving its `status` from
    `APPLIED` to `REMOVED` and dropping the cart's `pricing_status` to `STALE`;
    a removed application no longer contributes to the cart total."

    Design: Corner/endpoints/remove_application_sets_removed_and_stale
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="EP1")
    create_active_promotion("PERCENT_OFF", name="RM", percent_off=0.10,
                            coupon_code="RMK", coupon_use_mode="MULTI_USE",
                            coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    app = apply(cart["id"], cust["id"], "RMK")
    reprice(cart["id"], cust["id"])

    res = api.remove_application(cart["id"], app["id"], make_shopper_headers(cust["id"]))
    removed = validate_success(res, 200)
    assert removed["status"] == "REMOVED"
    cart_after = validate_success(api.get_cart(cart["id"], make_shopper_headers(cust["id"])), 200)
    assert cart_after["pricing_status"] == "STALE"


def test_auto_apply_empty_candidate_set_no_application(api):
    """PRD §3.9: "If the candidate pool is empty, no application is created and
    the cart is returned unchanged with no error — a 200 response with null data
    rather than the 201 a successful auto-apply produces."

    Design: Corner/endpoints/auto_apply_empty_candidate_set_no_application
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="EP2")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    res = api.auto_apply(cart["id"], make_shopper_headers(cust["id"]))
    assert res.status_code == 200, f"expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["data"] is None, "empty candidate pool returns null data"
    apps = get_success_data(api.list_applications(cart["id"], make_shopper_headers(cust["id"])))
    assert apps == [], "no application created for the cart"


def test_patch_cart_line_recomputes_and_stales(api):
    """PRD §3.6: "A line may be updated to change its `quantity` and/or
    `unit_price_cents`, or removed entirely. Whenever a line is added, updated,
    or removed, or whenever an application is added or removed, a cart that was
    previously `PRICED` automatically drops to `STALE`"
    PRD §3.6: "Each line's `line_total_cents` is its `unit_price_cents`
    multiplied by its `quantity`."

    Design: Corner/endpoints/patch_cart_line_recomputes_and_stales
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="EP3")
    cart, lines = setup_cart_with_lines(cust["id"], [("A", 1000, 1)])
    reprice(cart["id"], cust["id"])
    line_id = lines[0]["id"]
    res = api.update_line(cart["id"], line_id, {"quantity": 3}, make_shopper_headers(cust["id"]))
    updated = validate_success(res, 200)
    assert updated["line_total_cents"] == 3000
    cart_after = validate_success(api.get_cart(cart["id"], make_shopper_headers(cust["id"])), 200)
    assert cart_after["pricing_status"] == "STALE"


# ───────── OCC on cart version at checkout ──────────────────────────────────
def test_checkout_stale_cart_version_rejected(api):
    """PRD §2.7: "Checking out a cart requires `expected_cart_version` to match
    the target `Cart`'s current `version`. A reprice, a line edit, an
    application change, or an unlock-then-relock between the client's last read
    and this checkout will have bumped the cart's `version`; the client's
    snapshot of the discount is therefore stale, and the checkout is rejected
    with `ERR_STALE_CART_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_cart_version_on_checkout
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="O1")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    reprice(cart["id"], cust["id"])
    locked = lock(cart["id"], cust["id"])  # lock bumps version
    res = api.checkout_cart(cart["id"], {"expected_cart_version": locked["version"] - 1},
                            make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_STALE_CART_VERSION", expected_status=412)


def test_checkout_correct_cart_version_succeeds_and_bumps_version(api):
    """PRD §3.11: "Checkout completes the cart, moving `checkout_status` from
    `LOCKED` to the terminal `CHECKED_OUT`. The request must carry
    `expected_cart_version` matching the cart's current `version`"
    PRD §3.11: "The cart's `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_cart_version_checkout_succeeds
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="O2")
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    reprice(cart["id"], cust["id"])
    locked = lock(cart["id"], cust["id"])
    res = api.checkout_cart(cart["id"], {"expected_cart_version": locked["version"]},
                            make_shopper_headers(cust["id"]))
    done = validate_success(res, 200)
    assert done["checkout_status"] == "CHECKED_OUT"
    assert done["version"] == locked["version"] + 1


def test_stale_promotion_version_on_budget_apply(api):
    """PRD §2.7: "Applying a budget-capped promotion to a cart requires
    `expected_promotion_version` to match the target `Promotion`'s current
    `version`."
    PRD §2.7: "that application is rejected with `ERR_STALE_PROMOTION_VERSION`
    (HTTP 412) so the new application is always priced against a current
    remaining-budget figure."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_promotion_version_on_budget_apply
    """
    set_clock("2026-06-15T00:00:00Z")
    cust = create_customer(display_name="O3")
    promo, _ = create_active_promotion("THRESHOLD", name="SPV",
                                       threshold_tiers=[{"min_subtotal_cents": 0, "discount_cents": 100}],
                                       budget_cap_cents=5000,
                                       coupon_code="SPVK", coupon_use_mode="MULTI_USE",
                                       coupon_overrides={"max_total_redemptions": 100})
    cart, _ = setup_cart_with_lines(cust["id"], [("A", 2000, 1)])
    promo_ver = get_promotion(promo["id"])["version"]
    res = api.apply_coupon(cart["id"], {"code": "SPVK", "expected_promotion_version": promo_ver - 1},
                           make_shopper_headers(cust["id"]))
    validate_error(res, "ERR_STALE_PROMOTION_VERSION", expected_status=412)


# ───────── derived: member_count decrements on revoke ───────────────────────
def test_member_count_decrements_on_revoke(api):
    """PRD §2.5: "A `Segment`'s `member_count` always equals the number of
    memberships referencing it whose `status` is `ACTIVE`; revoking a membership
    recomputes it downward."
    PRD §3.1: "Revoking a membership transitions it from `ACTIVE` to `REVOKED`,
    recomputes the segment's `member_count` downward"

    Design: Corner/cross_cutting_complexity_layers/derived_member_count_decrements_on_revoke
    """
    cust = create_customer(display_name="DFR")
    seg = create_segment(code="SEG1", name="Seg One")
    mem = add_membership(seg["id"], cust["id"])
    seg_before = validate_success(api.get_segment(seg["id"], ADMIN), 200)
    assert seg_before["member_count"] == 1
    get_success_data(api.revoke_member(seg["id"], mem["id"], ADMIN))
    seg_after = validate_success(api.get_segment(seg["id"], ADMIN), 200)
    assert seg_after["member_count"] == 0
