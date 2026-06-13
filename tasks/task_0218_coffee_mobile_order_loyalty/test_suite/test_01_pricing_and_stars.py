"""Pricing and star-accrual calculations at pay time.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations (reward discount), consistency_model.
"""
from test_helpers import (
    fixtures as fx,
    factories as f,
    validate_success,
    make_member_headers,
)


# ─── dual_variant_calc ────────────────────────────────────────────────────

def test_order_total_capped_reward_variant(api):
    """PRD §3.5: "The `reward_discount_cents` is then the smaller of that cheapest
    eligible unit price and the reward's `max_discount_cents`."
    PRD §3.5: "Fourth, `tax_cents` is that taxable base multiplied by the tax rate
    of 875 basis points, divided by 10000, and rounded half-up to whole cents — this
    is the one and only rounding step, performed once on the post-discount base,
    never per line."

    Two eligible lines (900c + 1100c); FREE_ITEM reward max_discount 700 caps the
    discount below the cheapest unit (900). subtotal 2000, discount 700,
    taxable 1300, tax round_half_up(1300*875/10000)=114, total 1414.

    Design: Difficulty/dual_variant_calc/order_total_no_reward_vs_capped_reward
    """
    ctx = fx.setup_base(item_price=900, item_reward_eligible=True, num_slots=4)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    cb = ctx["item"]  # ColdBrewLg 900
    sp = fx.create_menu_item(store_id, name="SpecialtyLatte",
                             base_price_cents=1100, category="BEVERAGE", reward_eligible=True)
    # Earn 150 stars then mint the FREE_ITEM reward.
    fx.earn_lifetime_stars(mid, store_id, ctx["slots"][0]["id"], dollars=150)
    reward = fx.mint_free_item_reward(mid)

    order = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], cb["id"], quantity=1)
    fx.add_line(mid, order["id"], sp["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))

    assert paid["subtotal_cents"] == 2000, paid
    assert paid["reward_discount_cents"] == 700, paid
    assert paid["tax_cents"] == 114, paid
    assert paid["total_cents"] == 1414, paid


def test_order_total_no_reward_variant(api):
    """PRD §3.5: "if the order carries no `applied_reward_id` it is zero".
    PRD §3.5: "Fourth, `tax_cents` is that taxable base multiplied by the tax rate
    of 875 basis points, divided by 10000, and rounded half-up to whole cents".

    Same two lines (900c + 1100c) but no reward: subtotal 2000, discount 0,
    tax round_half_up(2000*875/10000)=175, total 2175.

    Design: Difficulty/dual_variant_calc/order_total_no_reward_vs_capped_reward
    """
    ctx = fx.setup_base(item_price=900, item_reward_eligible=True, num_slots=2)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    cb = ctx["item"]
    sp = fx.create_menu_item(store_id, name="SpecialtyLatte",
                             base_price_cents=1100, category="BEVERAGE", reward_eligible=True)
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    fx.add_line(mid, order["id"], cb["id"], quantity=1)
    fx.add_line(mid, order["id"], sp["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))

    assert paid["subtotal_cents"] == 2000, paid
    assert paid["reward_discount_cents"] == 0, paid
    assert paid["tax_cents"] == 175, paid
    assert paid["total_cents"] == 2175, paid


def test_stars_earned_gold_stored_value_variant(api):
    """PRD §3.4: "a `GOLD` member paying from the wallet earns 3 stars per eligible
    pre-tax dollar (2 from the tier plus 1 from the stored-value bonus)."
    PRD §2.5: "The member's `tier` is `GOLD` when `lifetime_stars` is at least the
    gold threshold of 200, and `GREEN` otherwise."

    Member at GOLD (200 lifetime) pays a 615c latte from the wallet: total 669,
    pre-tax 615, floor(615/100)=6, 6*3 = 18 stars.

    Design: Difficulty/dual_variant_calc/stars_earned_green_external_vs_gold_storedvalue
    """
    ctx = fx.setup_base(item_price=615, item_reward_eligible=True, num_slots=3)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    # Reach GOLD: 200 lifetime stars via a $200 pretax EXTERNAL order.
    member = fx.earn_lifetime_stars(mid, store_id, ctx["slots"][0]["id"], dollars=200)
    assert member["tier"] == "GOLD", member
    # Fund the wallet.
    card = fx.reload_card(mid, 5000)
    order = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    paid = validate_success(api.pay_order(
        mid, order["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr))

    assert paid["total_cents"] == 669, paid
    assert paid["stars_earned"] == 18, paid
    reread = validate_success(api.get_member(mid, hdr))
    assert reread["tier"] == "GOLD", reread


def test_stars_earned_green_external_variant(api):
    """PRD §3.4: "Concretely, a `GREEN` member paying with an external card earns 1
    star per eligible pre-tax dollar".
    PRD §3.4: "the number of eligible whole dollars is the order's `total_cents`
    minus its `tax_cents`, divided by 100 and floored to a whole number".

    A fresh GREEN member pays a 615c latte by external card: pre-tax 615,
    floor(615/100)=6, 6*1 = 6 stars.

    Design: Difficulty/dual_variant_calc/stars_earned_green_external_vs_gold_storedvalue
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    assert ctx["member"]["tier"] == "GREEN", ctx["member"]
    paid = validate_success(api.pay_order(mid, ctx["order"]["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["total_cents"] == 669, paid
    assert paid["stars_earned"] == 6, paid


# ─── combinatorial_formula ────────────────────────────────────────────────

def test_stars_earned_green_stored_value_nonlinear(api):
    """PRD §3.4: "Paying with the stored-value wallet adds a bonus of 1 star per
    eligible dollar on top of the tier rate, while paying with an external card adds
    no bonus."
    PRD §3.4: "The `stars_earned` figure is that eligible-dollar count multiplied by
    the sum of the tier rate and the method bonus."

    GREEN + STORED_VALUE on a 615c latte (total 669, tax 54): floor(615/100)=6,
    rate = 1 (GREEN) + 1 (SV bonus) = 2, so 6*2 = 12 stars — a non-linear branch
    selecting both the tier rate and the conditional method bonus.

    Design: Difficulty/combinatorial_formula/stars_earned_three_input_nonlinear_mode_a
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    card = fx.reload_card(mid, 5000)
    paid = validate_success(api.pay_order(
        mid, ctx["order"]["id"],
        f.pay_payload("STORED_VALUE", expected_card_version=card["version"]), hdr))
    assert paid["tax_cents"] == 54, paid
    assert paid["total_cents"] == 669, paid
    assert paid["stars_earned"] == 12, paid


def test_stars_earned_nonlinear_projects_to_balance(api):
    """PRD §3.4: "The `stars_earned` figure is that eligible-dollar count multiplied by
    the sum of the tier rate and the method bonus."
    PRD §2.5: "The `star_balance` is the sum of `delta_stars` across all of that
    member's ledger entries regardless of kind."

    The same GREEN+STORED_VALUE 615c latte: the 12-star non-linear result is appended
    as an EARN entry, so the member's star_balance and lifetime_stars both read 12.

    Design: Difficulty/combinatorial_formula/stars_earned_three_input_nonlinear_mode_a
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    card = fx.reload_card(mid, 5000)
    fx.pay(mid, ctx["order"]["id"], "STORED_VALUE", expected_card_version=card["version"])
    member = validate_success(api.get_member(mid, hdr))
    assert member["star_balance"] == 12, member
    assert member["lifetime_stars"] == 12, member


def test_order_total_tax_rounded_once_on_summed_base(api):
    """PRD §2.6: "The single place rounding occurs is the order tax: it is computed
    once, on the post-discount taxable base, using the round-half-up method to the
    nearest whole cent. Tax is never computed per line and never rounded more than
    once".
    PRD §3.5: "First, `subtotal_cents` is the sum of `line_total_cents` over all lines
    at full price".

    Two 305c espresso lines: subtotal 610, tax round_half_up(610*875/10000) =
    round_half_up(53.375) = 53 (per-line rounding would give 27+27=54). total 663.

    Design: Difficulty/combinatorial_formula/order_total_rounding_order_pinned_mode_b
    """
    ctx = fx.setup_base(item_price=305, item_reward_eligible=False, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["subtotal_cents"] == 610, paid
    assert paid["tax_cents"] == 53, paid
    assert paid["total_cents"] == 663, paid


def test_order_total_tax_round_half_up_three_lines(api):
    """PRD §2.6: "it is computed once, on the post-discount taxable base, using the
    round-half-up method to the nearest whole cent. Tax is never computed per line and
    never rounded more than once".
    PRD §3.5: "First, `subtotal_cents` is the sum of `line_total_cents` over all lines
    at full price".

    Three 305c espresso lines: subtotal 915, tax round_half_up(915*875/10000) =
    round_half_up(80.0625) = 80 (per-line would give 27*3 = 81). total 995.

    Design: Difficulty/combinatorial_formula/order_total_rounding_order_pinned_mode_b
    """
    ctx = fx.setup_base(item_price=305, item_reward_eligible=False, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    for _ in range(3):
        fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["subtotal_cents"] == 915, paid
    assert paid["tax_cents"] == 80, paid
    assert paid["total_cents"] == 995, paid


def test_pay_response_carries_finalized_totals(api):
    """PRD §3.5: "Paying is the pivotal operation: it finalizes the order's totals".
    PRD §3.4: "Concretely, a `GREEN` member paying with an external card earns 1 star
    per eligible pre-tax dollar".

    The pay response itself reports finalized subtotal_cents/tax_cents/total_cents/
    stars_earned for a 615c latte: 615 / 54 / 669 / 6.

    Design: Corner/consistency_model/pay_reflects_totals_in_same_response
    """
    ctx = fx.setup_cart_order_with_line(item_price=615)
    mid = ctx["member"]["id"]
    hdr = ctx["member_headers"]
    paid = validate_success(api.pay_order(mid, ctx["order"]["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["subtotal_cents"] == 615, paid
    assert paid["tax_cents"] == 54, paid
    assert paid["total_cents"] == 669, paid
    assert paid["stars_earned"] == 6, paid


def test_reward_full_discount_on_cheapest_eligible_line(api):
    """PRD §3.5: "Among the eligible lines it picks the one with the smallest
    `unit_price_cents`, breaking ties in favor of the earliest `created_at`; the
    discounted unit is a single unit of that line. The `reward_discount_cents` is then
    the smaller of that cheapest eligible unit price and the reward's
    `max_discount_cents`."

    Lines latte 615 and muffin 350 (both eligible), reward max_discount 700:
    cheapest unit is 350, fully covered -> discount 350. subtotal 965, taxable 615,
    tax round_half_up(615*875/10000)=54, total 669.

    Design: Corner/calculations/reward_full_discount_cheapest_eligible_line
    """
    ctx = fx.setup_base(item_price=615, item_reward_eligible=True, num_slots=4)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    muffin = fx.create_menu_item(store_id, name="Muffin", base_price_cents=350,
                                 category="FOOD", reward_eligible=True)
    fx.earn_lifetime_stars(mid, store_id, ctx["slots"][0]["id"], dollars=150)
    reward = fx.mint_free_item_reward(mid)
    order = fx.create_cart_order(mid, store_id, ctx["slots"][1]["id"],
                                 applied_reward_id=reward["id"])
    fx.add_line(mid, order["id"], ctx["item"]["id"], quantity=1)
    fx.add_line(mid, order["id"], muffin["id"], quantity=1)
    paid = validate_success(api.pay_order(mid, order["id"],
                                          f.pay_payload("EXTERNAL_CARD"), hdr))
    assert paid["subtotal_cents"] == 965, paid
    assert paid["reward_discount_cents"] == 350, paid
    assert paid["tax_cents"] == 54, paid
    assert paid["total_cents"] == 669, paid


def test_line_pricing_unit_and_total(api):
    """PRD §3.4: "The price of a single configured unit, `unit_price_cents`, is the
    menu item's `base_price_cents` plus, for each modifier selection on the line, the
    option's `price_delta_cents` multiplied by that selection's `count`, summed across
    all selections. The line's `line_total_cents` is then `unit_price_cents`
    multiplied by the line's `quantity`."

    Latte 545c + oat 70c modifier, qty 2 -> unit 615, line total 1230.

    Design: Corner/entities/line_pricing_computed_field_correct
    """
    ctx = fx.setup_base(item_price=545, item_reward_eligible=True, num_slots=1)
    store_id, mid = ctx["store"]["id"], ctx["member"]["id"]
    hdr = ctx["member_headers"]
    oat = fx.create_modifier(ctx["item"]["id"], group_code="MILK", name="Oat",
                             price_delta_cents=70)
    order = fx.create_cart_order(mid, store_id, ctx["slots"][0]["id"])
    line = validate_success(api.add_order_line(
        mid, order["id"],
        f.add_line_payload(ctx["item"]["id"], quantity=2,
                           modifiers=[{"modifier_option_id": oat["id"], "count": 1}]),
        hdr, ), 201)
    assert line["unit_price_cents"] == 615, line
    assert line["line_total_cents"] == 1230, line
