"""Payment gating, loyalty (committed vs preview), reorder, and immediate confirm totals."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success, validate_error,
    create_shop, create_customer, create_product, create_order, add_line,
    read_order_version, confirm_order, pin_clock,
    setup_confirmable_copies_order,
    TEST_USERS, make_customer_headers, ApiErrorId,
)

STAFF = TEST_USERS["shop_staff_headers"]
OPERATOR = TEST_USERS["production_operator_headers"]


# ─── Difficulty: dual_variant_calc (committed loyalty vs provisional preview) ─
def test_loyalty_committed_zero_while_preview_projects_one(api):
    """PRD §3.7: "the customer's committed `loyalty_score` and `loyalty_tier` are recomputed
    from realized history. That committed score is a weighted blend — the
    `completed_order_count` weighted by 1.0 plus the `lifetime_paid_cents` (converted to
    dollars by dividing by ten thousand) weighted by 0.5 — rounded half up to one decimal
    place." PRD §3.7: "which projects the score forward as if the customer's
    confirmed-but-not-yet-fulfilled orders had already completed."

    Design: Difficulty/dual_variant_calc/loyalty_score_committed_vs_provisional_preview_diverge
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Loyal Shop"}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    # Confirm but do NOT fulfill: committed loyalty stays at its default.
    validate_success(confirm_order(ctx["order"]["id"], cust["id"], ctx["version"]), 200)
    cust_now = get_success_data(api.get_customer(cust["id"], cust_headers))
    assert cust_now["loyalty_score"] == 0.0
    assert cust_now["loyalty_tier"] == "NONE"
    preview = get_success_data(api.get_loyalty_preview(cust["id"], cust_headers))
    # PRD §3.7 names a forward projection over confirmed-but-not-yet-fulfilled orders
    # but does not pin whether "as if completed" also folds in the order's payment
    # (completion presupposes payment), so the exact projected value (1.0 vs 1.3) is not
    # uniquely PRD-derivable. The committed-vs-preview divergence IS: the projection moves
    # the score forward of the committed 0.0 because completed_order_count would increment.
    assert preview["projected_loyalty_score"] > preview["committed_loyalty_score"], \
        "1 confirmed order projected as completed lifts the score above committed"
    assert preview["committed_loyalty_score"] == 0.0, "committed unchanged until hand-off"


def test_loyalty_committed_unchanged_by_confirm(api):
    """PRD §3.7: "the customer's committed `loyalty_score` and `loyalty_tier` are recomputed
    from realized history" (only at hand-off). PRD §3.6: confirmation "is not recomputed
    here" — confirm uses the committed tier as it stands going into confirm.

    Design: Difficulty/dual_variant_calc/loyalty_score_committed_vs_provisional_preview_diverge
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "Loyal Shop 2"}, quantity=10)
    cust = ctx["customer"]
    cust_headers = make_customer_headers(cust["id"])
    before = get_success_data(api.get_customer(cust["id"], cust_headers))
    assert before["loyalty_score"] == 0.0
    validate_success(confirm_order(ctx["order"]["id"], cust["id"], ctx["version"]), 200)
    after = get_success_data(api.get_customer(cust["id"], cust_headers))
    assert after["loyalty_score"] == 0.0, "committed score not bumped by confirm"
    assert after["completed_order_count"] == 0, "completed count not bumped until hand-off"


# ─── Difficulty: cross_entity_state_dependency (start-production payment gate) ─
def test_start_production_blocked_when_unpaid(api):
    """PRD §3.7: "a `ProductionOperator` starts production on a confirmed order, which is
    permitted only when `production_status` is `CONFIRMED` and `payment_status` is one of
    `INVOICED` or `PAID`". PRD §3.9: "State validity comes fifth, yielding
    `ERR_INVALID_STATE` when a target is not in a state that permits the requested
    transition."

    Design: Difficulty/cross_entity_state_dependency/start_production_requires_order_payment_invoiced_or_paid
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "XDep Shop"}, quantity=10)
    cust = ctx["customer"]
    validate_success(confirm_order(ctx["order"]["id"], cust["id"], ctx["version"]), 200)
    # Order is CONFIRMED but still UNPAID (not invoiced).
    res = api.start_production(ctx["order"]["id"], OPERATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_start_production_allowed_once_invoiced(api):
    """PRD §3.7: "starts production on a confirmed order, which is permitted only when
    `production_status` is `CONFIRMED` and `payment_status` is one of `INVOICED` or `PAID`;
    this advances `production_status` from `CONFIRMED` to `IN_PRODUCTION`."

    Design: Difficulty/cross_entity_state_dependency/start_production_requires_order_payment_invoiced_or_paid
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "XDep Shop 2"}, quantity=10)
    cust = ctx["customer"]
    order_id = ctx["order"]["id"]
    validate_success(confirm_order(order_id, cust["id"], ctx["version"]), 200)
    get_success_data(api.invoice_order(order_id, STAFF))
    started = validate_success(api.start_production(order_id, OPERATOR), 200)
    assert started["production_status"] == "IN_PRODUCTION"


# ─── Reorder and loyalty-preview endpoints ───────────────────────────────────
def test_reorder_clones_lines_into_new_draft(api):
    """PRD §3.8: "It creates a new order whose `reordered_from_order_id` points at the
    source, in `production_status` `DRAFT`, and clones each source line's `product_id`,
    `quantity`, `finishing_codes`, and `service_level` into fresh `OPEN` lines on the new
    order."

    Design: Corner/endpoints/reorder_clones_lines_into_new_draft
    """
    shop = create_shop(name="S27")
    cust = create_customer(shop["id"], email="s27@x.com")
    cust_headers = make_customer_headers(cust["id"])
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    src = create_order(shop["id"], cust["id"])
    add_line(src["id"], prod["id"], 10, cust["id"])
    src_v = read_order_version(src["id"], cust["id"])
    new_order = validate_success(
        api.reorder(src["id"], {"expected_order_version": src_v}, cust_headers), 201)
    assert new_order["production_status"] == "DRAFT"
    assert new_order["reordered_from_order_id"] == src["id"]
    new_lines = get_success_data(api.list_order_lines(cust_headers, params={"order_id": new_order["id"]}))
    assert len(new_lines) == 1
    assert new_lines[0]["product_id"] == prod["id"]
    assert new_lines[0]["status"] == "OPEN"


def test_loyalty_preview_for_fresh_customer_is_zero(api):
    """PRD §3.7: "The preview returns a `projected_loyalty_score` and `projected_loyalty_tier`
    computed by that forward projection, alongside the `committed_loyalty_score` as it
    stands today." PRD §3.2: customer loyalty fields "always start at their defaults:
    `completed_order_count` (starting at 0), `lifetime_paid_cents` (0), `loyalty_score` (0),
    and `loyalty_tier` (`NONE`)."

    Design: Corner/endpoints/loyalty_preview_computed_read_returns_projection
    """
    shop = create_shop(name="S28")
    cust = create_customer(shop["id"], email="s28@x.com")
    preview = get_success_data(api.get_loyalty_preview(cust["id"], make_customer_headers(cust["id"])))
    assert preview["projected_loyalty_score"] == 0.0
    assert preview["committed_loyalty_score"] == 0.0


# ─── Immediate consistency of confirm totals ─────────────────────────────────
def test_confirm_response_carries_computed_total(api):
    """PRD §3.6: "Finally the `total_cents` is the taxable base plus the `rush_fee_cents`
    plus the `tax_cents` plus the order's fulfillment shipping fee (which is 0 for a
    pickup)." PRD §2.2: "operations that create or modify a resource will return the created
    or updated resource object in the data field."

    Design: Corner/consistency_model/immediate_visibility_of_confirm_totals
    """
    ctx = setup_confirmable_copies_order(shop_overrides={"name": "S34"}, quantity=10)
    cust = ctx["customer"]
    confirmed = validate_success(confirm_order(ctx["order"]["id"], cust["id"], ctx["version"]), 200)
    assert confirmed["total_cents"] == 5000, "base 500 * qty 10, no tax/rush/ship"
    assert confirmed["production_status"] == "CONFIRMED"
