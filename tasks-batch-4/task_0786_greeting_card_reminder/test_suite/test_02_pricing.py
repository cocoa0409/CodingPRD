"""Order pricing: the estimate/final dual variant, the combinatorial final
total, pinned sum-then-round tax, and the postage-tier weight boundary.

Translates queue-A pricing instances plus the queue-B estimate corner. All
expected cent values are copied verbatim from the design index.
"""
from test_helpers import (
    validate_success,
    create_order_payload,
    build_pipeline, new_account, new_contact, new_card, new_gift_item, holder,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]

# Shared pricing scenario: PRO account, CA contact, Card 500/25g, Gift 800/40g qty 2.
_PRO_CARD = {"base_price_cents": 500, "weight_grams": 25}
_PRO_GIFT = {"price_cents": 800, "weight_grams": 40}


def test_estimate_diverges_from_final_total(api):
    """PRD §3.4: "At this estimate stage no subscription discount and no tax are
    applied, so `gift_discount_cents` and `tax_cents` remain zero and
    `final_total_cents` remains null; those are computed only at production."
    PRD §3.6: "The `final_total_cents` is then the postage plus the discounted
    gift line plus the tax".

    Design: Difficulty/dual_variant_calc/order_total_estimate_vs_final_diverges
    """
    ctx = build_pipeline("produced", tier="PRO", region="CA",
                         card_kwargs=_PRO_CARD, gift_kwargs=_PRO_GIFT, gift_quantity=2)
    assert ctx["order"]["estimated_total_cents"] == 2050, "estimate = postage 450 + gift 1600"
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    assert produced["final_total_cents"] == 1823
    assert produced["final_total_cents"] != produced["estimated_total_cents"], \
        "the estimate and final variants diverge on the same order"


def test_estimate_and_final_component_fields(api):
    """PRD §3.4: "The postage tier is the first tier whose weight ceiling the
    total weight does not exceed: 150 cents for a total of at most 30 grams, 250
    cents for at most 60 grams, 450 cents for at most 120 grams, and 800 cents
    for anything heavier."
    PRD §3.6: "the `gift_discount_cents` is that fraction applied to the summed
    gift line and rounded half-up to whole cents in a single rounding step."

    Design: Difficulty/dual_variant_calc/order_total_estimate_vs_final_diverges
    """
    ctx = build_pipeline("produced", tier="PRO", region="CA",
                         card_kwargs=_PRO_CARD, gift_kwargs=_PRO_GIFT, gift_quantity=2)
    assert ctx["order"]["postage_cents"] == 450, "105g total selects the 450-cent tier"
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    assert produced["gift_discount_cents"] == 320, "PRO 0.20 of the 1600 gift line"
    assert produced["tax_cents"] == 93, "CA 0.0725 on the discounted 1280 base"


def test_final_total_combines_tier_discount_and_tax(api):
    """PRD §3.6: "The `final_total_cents` is then the postage plus the discounted
    gift line plus the tax — that is, postage plus the quantity gift price
    reduced by the discount, plus the tax."

    Design: Difficulty/combinatorial_formula/order_final_total_tiered_postage_and_conditional_discount
    """
    ctx = build_pipeline("produced", tier="PRO", region="CA",
                         card_kwargs=_PRO_CARD, gift_kwargs=_PRO_GIFT, gift_quantity=2)
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    assert produced["final_total_cents"] == 1823


def test_final_total_conditional_no_discount_branch(api):
    """PRD §3.6: "The discount fraction is the account's `ACTIVE` subscription
    `discount_pct`, or zero when there is no active subscription".
    PRD §3.1: "the gift-line `discount_pct` (0.0, 0.10, and 0.20 respectively)".

    Design: Difficulty/combinatorial_formula/order_final_total_tiered_postage_and_conditional_discount
    """
    # FREE tier -> discount_pct 0.0, so the discount branch contributes nothing.
    ctx = build_pipeline("produced", tier="FREE", extra_credits=1, region="CA",
                         card_kwargs=_PRO_CARD, gift_kwargs=_PRO_GIFT, gift_quantity=2)
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    assert produced["gift_discount_cents"] == 0, "FREE tier applies no gift discount"
    # postage 450 + gift 1600 + CA tax round(1600*0.0725)=116
    assert produced["final_total_cents"] == 2166


def test_tax_discount_is_sum_then_round(api):
    """PRD §2.7: "the discount is computed on the *summed* gift line and rounded
    once, and the tax is then computed on the *summed, discounted* line and
    rounded once. Rounding each unit individually and then summing is explicitly
    forbidden, because it can yield a different number of cents."

    Design: Difficulty/combinatorial_formula/order_tax_sum_then_round_not_per_unit
    """
    # Gift 333 x qty 3 = 999; PLUS 0.10 -> round(99.9)=100 (per-unit would give 99).
    ctx = build_pipeline("produced", tier="PLUS", region="NY",
                         card_kwargs={"base_price_cents": 100, "weight_grams": 10},
                         gift_kwargs={"price_cents": 333, "weight_grams": 5}, gift_quantity=3)
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    assert produced["gift_discount_cents"] == 100, "sum-then-round yields 100, not the forbidden 99"


def test_tax_on_summed_discounted_line(api):
    """PRD §3.6: "The `tax_cents` is that rate applied to the taxable base and
    rounded half-up to whole cents in a single rounding step."
    PRD §3.6: "0.08875 for NY".

    Design: Difficulty/combinatorial_formula/order_tax_sum_then_round_not_per_unit
    """
    ctx = build_pipeline("produced", tier="PLUS", region="NY",
                         card_kwargs={"base_price_cents": 100, "weight_grams": 10},
                         gift_kwargs={"price_cents": 333, "weight_grams": 5}, gift_quantity=3)
    produced = validate_success(api.get_order(ctx["order_id"], ADMIN), 200)
    # taxable = 999 - 100 = 899; NY 0.08875 -> round(79.786)=80. final = 150 + 899 + 80.
    assert produced["tax_cents"] == 80
    assert produced["final_total_cents"] == 1129


def test_postage_tier_boundary_30_vs_31(api):
    """PRD §3.4: "150 cents for a total of at most 30 grams, 250 cents for at
    most 60 grams".

    Design: Difficulty/boundary_precision_check/postage_tier_weight_boundary_30_vs_31
    """
    account = new_account()
    contact = new_contact(account["id"])
    ah = holder(account["id"])
    card30 = new_card(weight_grams=30)
    card31 = new_card(weight_grams=31)
    o30 = validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card30["id"]), ah), 201)
    o31 = validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card31["id"]), ah), 201)
    assert o30["postage_cents"] == 150, "30g (inclusive) stays in the 150-cent tier"
    assert o31["postage_cents"] == 250, "31g crosses into the 250-cent tier"


def test_postage_tier_boundary_60_vs_61(api):
    """PRD §3.4: "250 cents for at most 60 grams, 450 cents for at most 120
    grams".

    Design: Difficulty/boundary_precision_check/postage_tier_weight_boundary_30_vs_31
    """
    account = new_account()
    contact = new_contact(account["id"])
    ah = holder(account["id"])
    card60 = new_card(weight_grams=60)
    card61 = new_card(weight_grams=61)
    o60 = validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card60["id"]), ah), 201)
    o61 = validate_success(api.create_order(create_order_payload(account["id"], contact["id"], card61["id"]), ah), 201)
    assert o60["postage_cents"] == 250, "60g (inclusive) stays in the 250-cent tier"
    assert o61["postage_cents"] == 450, "61g crosses into the 450-cent tier"


def test_estimate_postage_plus_gift_no_discount(api):
    """PRD §3.4: "The estimated total is this postage plus the gift line — the
    gift's per-unit price multiplied by the gift quantity, or zero when no gift
    is enclosed."

    Design: Corner/calculations/estimate_total_postage_plus_gift_no_discount
    """
    account = new_account()
    contact = new_contact(account["id"])
    ah = holder(account["id"])
    card = new_card(base_price_cents=500, weight_grams=25)
    gift = new_gift_item(price_cents=800, weight_grams=40)
    payload = create_order_payload(account["id"], contact["id"], card["id"],
                                   gift_item_id=gift["id"], gift_quantity=1)
    # weight 25 + 40 = 65 -> tier 450; estimate = 450 + 800 = 1250 (no discount/tax).
    order = validate_success(api.create_order(payload, ah), 201)
    assert order["postage_cents"] == 450
    assert order["estimated_total_cents"] == 1250
