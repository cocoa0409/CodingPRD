"""Checkout money math: provisional vs final charge, buy-the-look discount, the
net-based free-shipping tier, regional tax, the styling-fee ledger, the inclusive
try-at-home deadline, and the auto-checkout sweep.

All expected cent values are pinned to the PRD's charge algorithm (§3.6).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_client_headers,
    setup_delivered_fix, setup_preview_fix, set_clock, get_fix,
)

OPS = TEST_USERS["ops_headers"]


def _checkout(api, ctx, kept_item_ids, item_feedback=None):
    payload = {"kept_item_ids": kept_item_ids}
    if item_feedback is not None:
        payload["item_feedback"] = item_feedback
    return api.checkout_fix(ctx["fix_id"], payload, headers=make_client_headers(ctx["client_id"]))


# ------------------------------- Difficulty: provisional vs final charge diverge
def test_provisional_charge_assumes_keep_all_at_delivery(api):
    """PRD §3.5: "Delivery also computes a provisional charge that assumes the
    subscriber keeps everything: the estimated total is written to
    estimated_charge_cents, and shipping_fee_cents and tax_cents are set for that
    provisional total."

    Design: Difficulty/dual_variant_calc/fix_charge_provisional_vs_final_diverge
    """
    ctx = setup_delivered_fix(prices=[3200, 4500, 2800, 6000, 3500], region_code="CA")
    assert ctx["fix"]["estimated_charge_cents"] == 13943


def test_final_charge_over_kept_subset_diverges_from_provisional(api):
    """PRD §3.6: "The evaluated set differs by moment: the provisional computation at
    delivery uses all items of the fix (assuming keep-all), while the final
    computation at checkout uses only the items that transitioned to KEPT."

    Design: Difficulty/dual_variant_calc/fix_charge_provisional_vs_final_diverge
    """
    ctx = setup_delivered_fix(prices=[3200, 4500, 2800, 6000, 3500], region_code="CA")
    estimated = ctx["fix"]["estimated_charge_cents"]
    kept = [ctx["item_ids"][0], ctx["item_ids"][2]]  # 3200 + 2800
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["charge_cents"] == 5143
    assert data["charge_cents"] != estimated


# ------------------------ Difficulty: keep-all buy-the-look nested conditionals
def test_keep_all_applies_buy_the_look_and_free_shipping(api):
    """PRD §3.6: "A buy-the-look discount applies only when every item of the fix is
    kept and the fix holds at least one item; in that case buy_the_look_applied is
    true and the discount equals 25 percent of the subtotal, rounded half up to a
    whole number of cents; otherwise the discount is zero."

    Design: Difficulty/combinatorial_formula/fix_charge_keepall_buy_the_look_mode_a
    """
    ctx = setup_delivered_fix(prices=[3200, 4500, 2800, 6000, 3500], region_code="CA")
    kept = list(ctx["item_ids"])
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["buy_the_look_applied"] is True
    assert data["shipping_fee_cents"] == 0


def test_keep_all_charge_taxed_on_net(api):
    """PRD §3.6: "The taxable base is the net amount plus the shipping fee, and
    tax_cents equals that taxable base multiplied by the client's regional rate —
    7.25 percent for region CA, 4 percent for NY, and 0 percent for OR — rounded half
    up in a single rounding on the aggregate base."

    Design: Difficulty/combinatorial_formula/fix_charge_keepall_buy_the_look_mode_a
    """
    ctx = setup_delivered_fix(prices=[3200, 4500, 2800, 6000, 3500], region_code="CA")
    kept = list(ctx["item_ids"])
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["tax_cents"] == 943
    assert data["charge_cents"] == 13943


# --------------------------- Difficulty: free-ship tier keyed on net (mode c)
def test_free_shipping_when_net_meets_threshold(api):
    """PRD §3.6: "Shipping is resolved on that net amount, and never on a total that
    already includes shipping. If the evaluated set holds no items, shipping_fee_cents
    is 0. Otherwise, if the net amount is at least 7500 cents, shipping is waived to
    0; below that threshold, shipping is 795 cents."

    Design: Difficulty/combinatorial_formula/shipping_fee_free_ship_tier_mode_c
    """
    ctx = setup_delivered_fix(prices=[5000, 4500, 2000], region_code="CA")
    kept = [ctx["item_ids"][0], ctx["item_ids"][1]]  # 5000 + 4500 → net 7500
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["shipping_fee_cents"] == 0
    assert data["buy_the_look_applied"] is False


def test_partial_keep_free_ship_charge(api):
    """PRD §3.6: "The final total is the taxable base plus tax; it is stored as
    estimated_charge_cents for the provisional computation at delivery, and as
    charge_cents for the final computation at checkout."

    Design: Difficulty/combinatorial_formula/shipping_fee_free_ship_tier_mode_c
    """
    ctx = setup_delivered_fix(prices=[5000, 4500, 2000], region_code="CA")
    kept = [ctx["item_ids"][0], ctx["item_ids"][1]]
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["charge_cents"] == 8044


# ------------------------ Difficulty: styling-fee ledger conservation (keep none)
def test_keep_none_forfeits_styling_fee(api):
    """PRD §3.6: "When nothing is kept, styling_fee_credit_cents is 0 and the full
    charged fee becomes styling_fee_forfeited_cents."

    Design: Difficulty/compensating_invariant/ship_then_keepnone_conserves_styling_fee
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    data = validate_success(_checkout(api, ctx, []), 200)
    assert data["styling_fee_charged_cents"] == 2000
    assert data["styling_fee_credit_cents"] == 0
    assert data["styling_fee_forfeited_cents"] == 2000


def test_keep_none_charge_is_zero(api):
    """PRD §3.6: "The net amount is the subtotal minus the discount minus the credit,
    floored at zero so it is never negative."

    Design: Difficulty/compensating_invariant/ship_then_keepnone_conserves_styling_fee
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    data = validate_success(_checkout(api, ctx, []), 200)
    assert data["charge_cents"] == 0


# ------------------------------------ Difficulty: inclusive try-at-home deadline
def test_checkout_at_exact_deadline_succeeds(api):
    """PRD §3.6: "the current clock is on or before checkout_deadline (the boundary
    instant is still allowed, and a later attempt is rejected with
    ERR_CHECKOUT_WINDOW_CLOSED)"

    Design: Difficulty/boundary_precision_check/checkout_at_exact_deadline_inclusive
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    set_clock(ctx["fix"]["checkout_deadline"])
    data = validate_success(_checkout(api, ctx, [ctx["item_ids"][0]]), 200)
    assert data["status"] == "CHECKED_OUT"


def test_checkout_at_boundary_computes_final_charge(api):
    """PRD §3.5: "Delivery sets delivered_at to the current clock and computes
    checkout_deadline as delivered_at plus a three-day try-at-home window (the
    deadline instant is inclusive)."

    Design: Difficulty/boundary_precision_check/checkout_at_exact_deadline_inclusive
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    set_clock(ctx["fix"]["checkout_deadline"])
    data = validate_success(_checkout(api, ctx, [ctx["item_ids"][0]]), 200)
    assert data["charge_cents"] is not None, "checkout at the inclusive boundary must complete"


# ----------------------- Difficulty: ship depends on owning client being ACTIVE
def test_ship_rejected_when_client_paused(api):
    """PRD §3.5: "Shipping requires the owning client to be ACTIVE and the item count
    to be at least three and at most five"
    PRD §2.10: "State — the target is in a valid state for the requested transition;
    otherwise the appropriate 409 state error (ERR_FIX_NOT_STYLING, ERR_FIX_NOT_PREVIEW,
    ERR_FIX_NOT_SHIPPED, ERR_FIX_NOT_DELIVERED, ERR_FIX_TERMINAL, ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_CANCELLED, ERR_STYLEPROFILE_EXISTS, ERR_NO_PENDING_FIX, or
    ERR_RETURN_NOT_RECEIVABLE). Applies to all state-transition endpoints."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_owning_client_active
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    validate_success(api.pause_client(ctx["client_id"], headers=make_client_headers(ctx["client_id"])), 200)
    resp = api.ship_fix(ctx["fix_id"], headers=OPS)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)


def test_ship_rejected_leaves_fix_in_preview(api):
    """PRD §3.5: "Shipping requires the owning client to be ACTIVE and the item count
    to be at least three and at most five"
    PRD §3.2: "Pausing an ACTIVE subscription moves the client to PAUSED."

    Design: Difficulty/cross_entity_state_dependency/ship_requires_owning_client_active
    """
    ctx = setup_preview_fix(prices=[3000, 3000, 3000])
    validate_success(api.pause_client(ctx["client_id"], headers=make_client_headers(ctx["client_id"])), 200)
    api.ship_fix(ctx["fix_id"], headers=OPS)
    assert get_fix(ctx["fix_id"])["status"] == "PREVIEW", "rejected ship must leave the fix unchanged"


# ----------------------------------------------------- Corner: NY tax partial keep
def test_ny_partial_keep_charge(api):
    """PRD §3.6: "tax_cents equals that taxable base multiplied by the client's
    regional rate — 7.25 percent for region CA, 4 percent for NY, and 0 percent for
    OR — rounded half up in a single rounding on the aggregate base."

    Design: Corner/calculations/keep_partial_ny_tax_charge
    """
    ctx = setup_delivered_fix(prices=[3200, 4500, 2800, 6000, 3500], region_code="NY")
    kept = [ctx["item_ids"][0], ctx["item_ids"][2]]  # 3200 + 2800 → net 4000
    data = validate_success(_checkout(api, ctx, kept), 200)
    assert data["shipping_fee_cents"] == 795
    assert data["tax_cents"] == 192
    assert data["charge_cents"] == 4987


# ------------------------------------------------------ Corner: deadline exceeded
def test_checkout_after_deadline_rejected(api):
    """PRD §3.6: "the current clock is on or before checkout_deadline (the boundary
    instant is still allowed, and a later attempt is rejected with
    ERR_CHECKOUT_WINDOW_CLOSED)"

    Design: Corner/validations/checkout_past_deadline_returns_window_closed
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    set_clock("2026-05-05T00:00:00Z")  # deadline was 2026-05-04
    resp = _checkout(api, ctx, [ctx["item_ids"][0]])
    validate_error(resp, ApiErrorId.ERR_CHECKOUT_WINDOW_CLOSED.value)


# ------------------------------------------------- Corner: foreign kept item id
def test_checkout_with_non_item_id_rejected(api):
    """PRD §3.6: "every id in kept_item_ids is a SELECTED item of this fix (any id
    that is not is rejected with ERR_KEEP_ITEM_INVALID)."

    Design: Corner/validations/checkout_with_foreign_item_id_returns_keep_invalid
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    resp = _checkout(api, ctx, [ctx["product_ids"][0]])  # a product id, not a fix item id
    validate_error(resp, ApiErrorId.ERR_KEEP_ITEM_INVALID.value)


# ------------------------------------------------- Corner: auto-checkout sweep
def test_run_checkout_sweep_keeps_all_and_closes(api):
    """PRD §3.9: "An operational sweep processes every fix still in DELIVERED whose
    current clock has passed its checkout_deadline, auto-checking it out as keep-all:
    every SELECTED item transitions to KEPT (selling its product — reserved_count down
    one, sold_count up one) and buy_the_look_applied becomes true."
    PRD §3.9: "Since nothing is returned, returned_count is zero, so the fix moves
    immediately to CLOSED with no return shipment and no feedback created."

    Design: Corner/state_machines/run_checkout_sweep_autocheckout_keepall
    """
    ctx = setup_delivered_fix(prices=[3000, 3000, 3000], region_code="CA")
    set_clock("2026-05-10T00:00:00Z")  # past the 2026-05-04 deadline
    validate_success(api.run_checkout_sweep(headers=OPS), 200)
    fix = get_fix(ctx["fix_id"])
    assert fix["status"] == "CLOSED"
    assert fix["buy_the_look_applied"] is True
    assert fix["kept_count"] == 3
    assert fix["returned_count"] == 0
