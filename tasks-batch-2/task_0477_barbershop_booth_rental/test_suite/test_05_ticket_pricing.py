"""Ticket pricing at checkout (PRD §3.6).

Covers the combinatorial service/add-on net (per-line membership rounding),
the sum-then-round tax rule, the non-member full-price path, the zero-line
boundary, and immediate visibility of computed totals.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_ticket,
    setup_shop_with_barber_chair_shift,
    setup_shop_with_active_barber,
    checked_in_ticket,
    served_walkin_ticket,
    set_lines,
    checkout,
    TEST_USERS,
)

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]


def test_member_addon_pricing_per_line_rounding(api):
    """PRD §3.6: "if it is `ACTIVE`, the applicable percentage is the add-on's own
    `membership_discount_pct` when that is greater than zero, otherwise the
    customer's plan `addon_discount_pct`, and the add-on contributes its
    `price_cents` reduced by that percentage, with each add-on line rounded
    half-up to a whole cent individually before any add-on lines are summed."

    Design: Difficulty/combinatorial_formula/member_addon_pricing_per_line_rounding_mode_a
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Member Shop", "tax_rate_pct": 8.5},
        service_overrides={"name": "Haircut", "price_cents": 3000,
                           "duration_minutes": 30, "membership_included": True},
    )
    shop = ctx["shop"]
    plan = get_success_data(api_client.create_membership(
        {"shop_id": shop["id"], "name": "Gold", "monthly_fee_cents": 4000,
         "addon_discount_pct": 15}, OWNER))
    shave = get_success_data(api_client.create_service(
        {"shop_id": shop["id"], "name": "Shave", "price_cents": 2000, "duration_minutes": 20},
        OWNER))
    addon_a = get_success_data(api_client.create_addon(
        {"shop_id": shop["id"], "name": "AddA", "price_cents": 1010, "extra_minutes": 5}, OWNER))
    addon_b = get_success_data(api_client.create_addon(
        {"shop_id": shop["id"], "name": "AddB", "price_cents": 1010, "extra_minutes": 5}, OWNER))
    get_success_data(api_client.subscribe_customer(
        ctx["customer"]["id"], {"membership_id": plan["id"]}, RECEPTION))

    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(
        ticket["id"],
        service_line_ids=[ctx["service"]["id"], shave["id"]],
        addon_line_ids=[addon_a["id"], addon_b["id"]],
    )
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    assert_ticket(paid)
    # Haircut included -> 0; Shave 2000; each addon 1010*0.85=858.5 -> 859, sum 1718
    assert paid["service_net_cents"] == 3718, paid
    assert paid["tax_cents"] == 316
    assert paid["total_due_cents"] == 4034


def test_member_included_service_waived_to_zero(api):
    """PRD §3.6: "The gross service amount is the sum over `service_line_ids` of
    each item's `price_cents`, except that an item whose `membership_included` is
    true contributes zero whenever the customer's `membership_status` is `ACTIVE`."

    Design: Difficulty/combinatorial_formula/member_addon_pricing_per_line_rounding_mode_a
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Member Shop", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000,
                           "duration_minutes": 30, "membership_included": True},
    )
    shop = ctx["shop"]
    plan = get_success_data(api_client.create_membership(
        {"shop_id": shop["id"], "name": "Gold", "monthly_fee_cents": 4000,
         "addon_discount_pct": 15}, OWNER))
    get_success_data(api_client.subscribe_customer(
        ctx["customer"]["id"], {"membership_id": plan["id"]}, RECEPTION))
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(ticket["id"], service_line_ids=[ctx["service"]["id"]])
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    # Included service fully waived for an ACTIVE member.
    assert paid["service_net_cents"] == 0, paid
    assert paid["total_due_cents"] == 0, paid


def test_tax_sum_then_round(api):
    """PRD §3.6: "the taxable base is `service_net_cents` plus `product_net_cents`,
    summed first; the `tax_cents` is that single summed base multiplied by the
    shop's `tax_rate_pct` divided by 100, rounded half-up once on the summed base
    rather than per line."

    Design: Difficulty/combinatorial_formula/ticket_tax_sum_then_round_mode_b
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Tax Shop", "tax_rate_pct": 8.5},
        service_overrides={"name": "Trim", "price_cents": 850, "duration_minutes": 20},
    )
    comb = get_success_data(api_client.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Comb", "price_cents": 850, "stock_qty": 5}, OWNER))
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(
        ticket["id"],
        service_line_ids=[ctx["service"]["id"]],
        product_lines=[{"product_sku_id": comb["id"], "qty": 1}],
    )
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    # base 850+850=1700; 1700*0.085=144.5 -> 145 (sum-then-round, not 72+72=144)
    assert paid["service_net_cents"] == 850
    assert paid["product_net_cents"] == 850
    assert paid["tax_cents"] == 145, paid
    assert paid["total_due_cents"] == 1845


def test_tax_total_includes_untaxed_tip(api):
    """PRD §3.6: "The `total_due_cents` is `service_net_cents` plus
    `product_net_cents` plus `tax_cents` plus `tip_cents`. The tip is never taxed
    and is never shared with the shop".

    Design: Difficulty/combinatorial_formula/ticket_tax_sum_then_round_mode_b
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "Tax Shop", "tax_rate_pct": 8.5},
        service_overrides={"name": "Trim", "price_cents": 850, "duration_minutes": 20},
    )
    comb = get_success_data(api_client.create_product(
        {"shop_id": ctx["shop"]["id"], "name": "Comb", "price_cents": 850, "stock_qty": 5}, OWNER))
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(
        ticket["id"],
        service_line_ids=[ctx["service"]["id"]],
        product_lines=[{"product_sku_id": comb["id"], "qty": 1}],
        tip_cents=300,
    )
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    # base 1700 -> tax 145 (sum-then-round); tip 300 added untaxed.
    assert paid["tax_cents"] == 145, paid
    assert paid["total_due_cents"] == 850 + 850 + 145 + 300, paid


def test_nonmember_addon_full_price_no_discount(api):
    """PRD §3.6: "if the customer's `membership_status` is not `ACTIVE`, the add-on
    contributes its full `price_cents`".

    Design: Corner/calculations/nonmember_addon_full_price_no_discount
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    addon = get_success_data(api_client.create_addon(
        {"shop_id": ctx["shop"]["id"], "name": "AddA", "price_cents": 1010,
         "extra_minutes": 5, "membership_discount_pct": 50}, OWNER))
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(
        ticket["id"],
        service_line_ids=[ctx["service"]["id"]],
        addon_line_ids=[addon["id"]],
    )
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    # Non-member: discount ignored -> 3000 + 1010 = 4010
    assert paid["service_net_cents"] == 4010, paid


def test_zero_line_ticket_prices_to_zero(api):
    """PRD §3.7: "Even a ticket with no service and no product lines still earns
    its punch."
    PRD §3.6: "Finally, `service_net_cents` is the gross service amount plus the
    gross add-on amount minus the waiver, floored at zero so it can never go
    negative."

    Design: Difficulty/boundary_precision_check/zero_line_ticket_checkout_earns_punch_boundary
    """
    ctx = setup_shop_with_active_barber(
        shop_overrides={"name": "Zero Shop", "tax_rate_pct": 0, "punch_reward_threshold": 10},
    )
    _, ticket = served_walkin_ticket(ctx)
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    assert paid["service_net_cents"] == 0, paid
    assert paid["product_net_cents"] == 0
    assert paid["total_due_cents"] == 0


def test_zero_line_ticket_still_earns_punch(api):
    """PRD §3.7: "On every checkout — after pricing is complete — the customer's
    `punch_count` is incremented by one." "Even a ticket with no service and no
    product lines still earns its punch."

    Design: Difficulty/boundary_precision_check/zero_line_ticket_checkout_earns_punch_boundary
    """
    ctx = setup_shop_with_active_barber(
        shop_overrides={"name": "Zero Shop", "tax_rate_pct": 0, "punch_reward_threshold": 10},
    )
    _, ticket = served_walkin_ticket(ctx)
    validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OWNER), 200)
    assert cust["punch_count"] == 1, cust


def test_checkout_total_visible_in_same_response(api):
    """PRD §3.6: "The `total_due_cents` is `service_net_cents` plus
    `product_net_cents` plus `tax_cents` plus `tip_cents`." "Once these pass, the
    ticket is priced as described below, the ticket moves `OPEN → PAID`".

    Design: Corner/consistency_model/checkout_totals_visible_in_same_response
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(ticket["id"], service_line_ids=[ctx["service"]["id"]])
    paid = validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    assert paid["total_due_cents"] == 3000, paid
    assert paid["status"] == "PAID"


def test_barber_unsettled_revenue_reconciled_on_checkout(api):
    """PRD §3.6: "The barber's `unsettled_revenue_cents` is increased by
    `service_net_cents`, and the barber's `version` is incremented by one."

    Design: Corner/cross_cutting_complexity_layers/barber_unsettled_revenue_reconciled_on_checkout
    """
    ctx = setup_shop_with_barber_chair_shift(
        shop_overrides={"name": "S", "tax_rate_pct": 0},
        service_overrides={"name": "Haircut", "price_cents": 3000, "duration_minutes": 30},
    )
    _, ticket = checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z")
    set_lines(ticket["id"], service_line_ids=[ctx["service"]["id"]])
    validate_success(api.checkout_ticket(ticket["id"], RECEPTION), 200)
    barber = validate_success(api.get_barber(ctx["barber"]["id"], OWNER), 200)
    assert barber["unsettled_revenue_cents"] == 3000, barber
