"""Pricing, service fees, tax reconciliation, protection premium, and the
special-order lead-time date — all server-computed integer-cent figures.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS,
    create_customer, create_sofa_product, create_draft_order, add_line,
    pay_in_full, confirm,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


def _velvet_sofa(api):
    return get_success_data(api.create_product({
        "sku": "SOFA-STD", "name": "Aspen Sofa", "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0},
                              {"code": "VELVET", "surcharge_cents": 20000}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}]}, SM))


# ─── Difficulty: grand total — single tax on combined base ────────────────
def test_grand_total_sum_then_round_tax(api):
    """PRD 3.3: "Tax is then computed once on that combined base: the taxable base
    multiplied by 825 basis points (that is, multiplied by 825 and divided by 10,000),
    with the single round-half-up applied to that one product to land on whole cents."
    PRD 3.3: "Finally, order_total_cents is the taxable base plus that tax."

    A VELVET sofa (merch 120000), WHITE_GLOVE (19900) + assembly (4900) -> service 24800,
    taxable base 144800, tax 11946, total 156746.

    Design: Difficulty/combinatorial_formula/order_grand_total_sum_then_round_tax_order
    """
    product = _velvet_sofa(api)
    customer = create_customer()
    order = create_draft_order(customer["id"], delivery_tier="WHITE_GLOVE")
    add_line(order["id"], product["id"], fabric_code="VELVET", size_code="STD",
             quantity=1, add_assembly=True)
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    assert confirmed["merchandise_subtotal_cents"] == 120000
    assert confirmed["service_total_cents"] == 24800
    assert confirmed["order_total_cents"] == 156746


def test_grand_total_components_sum_into_taxable_base(api):
    """PRD 3.3: "It then forms the taxable base as the sum of those two figures."
    PRD 3.3: "Finally, `order_total_cents` is the taxable base plus that tax. Tax is
    never computed component-by-component and then summed; it is computed once, on the
    combined base, after both subtotals are known."

    Second test for this instance: the reported total equals base + the single tax.

    Design: Difficulty/combinatorial_formula/order_grand_total_sum_then_round_tax_order
    """
    product = _velvet_sofa(api)
    customer = create_customer()
    order = create_draft_order(customer["id"], delivery_tier="WHITE_GLOVE")
    add_line(order["id"], product["id"], fabric_code="VELVET", size_code="STD",
             quantity=1, add_assembly=True)
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    base = confirmed["merchandise_subtotal_cents"] + confirmed["service_total_cents"]
    assert base == 144800
    assert confirmed["order_total_cents"] - base == 11946, "single round-half-up tax"


# ─── Corner: service total — white glove with both add-ons ────────────────
def test_service_total_white_glove_with_addons(api):
    """PRD 3.3: "The delivery fee is 19,900 cents when `delivery_tier` is `WHITE_GLOVE`
    and 7,900 cents when it is `THRESHOLD`."
    PRD 3.2: "an assembly charge of 4,900 cents per unit (4,900 multiplied by `quantity`)
    is added, and when `add_haul_away` is set, a haul-away charge of 3,500 cents per unit
    (3,500 multiplied by `quantity`) is added ..."
    PRD 3.3: "`service_total_cents` equals the tier's delivery fee plus that add-on sum."

    19900 + 4900 + 3500 = 28300.

    Design: Corner/calculations/order_service_total_white_glove_with_addons
    """
    product = create_sofa_product()
    customer = create_customer()
    order = create_draft_order(customer["id"], delivery_tier="WHITE_GLOVE")
    add_line(order["id"], product["id"], quantity=1, add_assembly=True, add_haul_away=True)
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    assert confirmed["service_total_cents"] == 28300


# ─── Corner: protection premium BASIC 2yr ─────────────────────────────────
def test_protection_premium_basic_two_year(api):
    """PRD 3.7: "The system takes the covered line's `line_total_cents`, multiplies it by
    the tier's annual rate — ... or 300 basis points for a `BASIC` plan — and multiplies
    by `coverage_years`, applying a single round-half-up across the whole product to land
    on whole cents."

    line_total 100000 * 300/10000 * 2 = 6000.

    Design: Corner/calculations/protection_premium_basic_2yr_computed
    """
    product = get_success_data(api.create_product({
        "sku": "SOFA-STD", "name": "Aspen Sofa", "category": "SOFA",
        "base_price_cents": 100000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "STD", "surcharge_cents": 0}],
        "protection_eligible": True}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    line = add_line(order["id"], product["id"])
    res = api.create_protection_plan(
        {"order_line_id": line["id"], "tier": "BASIC", "coverage_years": 2}, SA)
    plan = validate_success(res, 201)
    assert plan["premium_cents"] == 6000


# ─── Corner: earliest schedulable date from max special-order lead ────────
def test_earliest_schedulable_date_uses_special_order_lead(api):
    """PRD 3.3: "This is the calendar date of the order's creation (`created_at`, UTC date
    component) advanced by the largest `lead_days` found among the order's active
    special-order lines ..."

    Created 2026-03-01 + 14 lead days = 2026-03-15.

    Design: Corner/calculations/earliest_schedulable_date_uses_max_special_order_lead
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T00:00:00Z"}, SM))
    product = get_success_data(api.create_product({
        "sku": "MATT-SPECIAL", "name": "Custom Mattress", "category": "MATTRESS",
        "base_price_cents": 80000,
        "available_fabrics": [{"code": "STANDARD", "surcharge_cents": 0}],
        "available_sizes": [{"code": "QUEEN", "surcharge_cents": 0}],
        "is_special_order": True, "lead_days": 14}, SM))
    customer = create_customer()
    order = create_draft_order(customer["id"])
    add_line(order["id"], product["id"], fabric_code="STANDARD", size_code="QUEEN")
    pay_in_full(order["id"])
    confirmed = confirm(order["id"])
    assert confirmed["earliest_schedulable_date"] is not None
    assert str(confirmed["earliest_schedulable_date"]).startswith("2026-03-15"), \
        f"expected 2026-03-15, got {confirmed['earliest_schedulable_date']}"
