"""Retail-sale pricing: the pinned round-per-unit-then-multiply discount order."""
from test_helpers import (
    validate_success,
    setup_studio,
    create_product,
    create_and_activate_membership,
    book_and_complete_walk_in,
    attach_retail_sale,
    get_room_version,
    TEST_USERS,
)

FRONT = TEST_USERS["front_desk_headers"]


def test_retail_discount_rounds_per_unit_then_multiplies(api):
    """PRD 3.7: "The per-unit discount in cents is the product's `unit_price_cents`
    multiplied by its `member_discount_pct`, rounded half up to a whole cent; the
    total `discount_cents` is that per-unit discount multiplied by the
    `quantity` — the multiplication happens only after the per-unit rounding,
    never the other way around. The `gross_cents` is the `unit_price_cents`
    multiplied by the `quantity`, and the `net_cents` is the `gross_cents` minus
    the `discount_cents`, never below zero."

    unit_price 1295, pct 0.10, qty 3 for an ACTIVE member:
    per_unit = round_half_up(129.5) = 130; discount = 130*3 = 390;
    gross = 3885; net = 3495 (the pinned round-per-unit-then-sum result, not 3496).

    Design: Difficulty/combinatorial_formula/retail_net_round_per_unit_then_sum
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Retailtown"},
        service_overrides={"name": "Underarm", "duration_minutes": 30,
                           "list_price_cents": 1800, "credit_cost": 1},
    )
    member = studio["member"]
    product = create_product(name="Smooth Wash", unit_price_cents=1295,
                             member_discount_pct=0.10, stock_qty=100)
    create_and_activate_membership(member["id"], tier="PLUS",
                                   monthly_credit_grant=4, monthly_fee_cents=6000)
    res = book_and_complete_walk_in(studio, start_utc="2026-06-16T10:00:00Z",
                                    checkin_clock="2026-06-16T09:45:00Z")
    sale = attach_retail_sale(member, res["id"], product["id"], quantity=3)
    confirmed = validate_success(api.confirm_retail_sale(
        sale["id"], {"expected_product_version": product["version"]}, FRONT), 200)
    assert confirmed["gross_cents"] == 3885, f"gross expected 3885, got {confirmed['gross_cents']}"
    assert confirmed["discount_cents"] == 390, f"discount expected 390, got {confirmed['discount_cents']}"
    assert confirmed["net_cents"] == 3495, f"net expected 3495, got {confirmed['net_cents']}"
    assert confirmed["status"] == "CONFIRMED"


def test_retail_confirm_finalizes_active_member_discount(api):
    """PRD 3.7: "The member discount applies only when the buyer holds a
    membership whose `status` is `ACTIVE` at confirm time".
    PRD 3.7: "the total `discount_cents` is that per-unit discount multiplied by
    the `quantity` — the multiplication happens only after the per-unit
    rounding, never the other way around."

    With an ACTIVE membership the discount is applied (per-unit-rounded), so a
    3-unit confirm at unit 1295/pct 0.10 yields a non-zero discount of 390 and
    moves the sale to CONFIRMED.

    Design: Difficulty/combinatorial_formula/retail_net_round_per_unit_then_sum
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Retailtown2"},
        service_overrides={"name": "Underarm", "duration_minutes": 30,
                           "list_price_cents": 1800, "credit_cost": 1},
    )
    member = studio["member"]
    product = create_product(name="Smooth Wash 2", unit_price_cents=1295,
                             member_discount_pct=0.10, stock_qty=100)
    create_and_activate_membership(member["id"], tier="PLUS",
                                   monthly_credit_grant=4, monthly_fee_cents=6000)
    res = book_and_complete_walk_in(studio, start_utc="2026-06-16T10:00:00Z",
                                    checkin_clock="2026-06-16T09:45:00Z")
    sale = attach_retail_sale(member, res["id"], product["id"], quantity=3)
    confirmed = validate_success(api.confirm_retail_sale(
        sale["id"], {"expected_product_version": product["version"]}, FRONT), 200)
    assert confirmed["discount_cents"] == 390
    assert confirmed["status"] == "CONFIRMED"
