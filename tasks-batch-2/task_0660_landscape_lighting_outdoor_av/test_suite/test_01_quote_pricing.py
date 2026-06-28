"""Quote pricing: tiered-rate selection, pinned rounding order, and the
acceptance wallet debit. Translates the combinatorial-formula difficulty
instances plus the quote-accept side-effect corner instance.
"""
from test_helpers import (
    validate_success,
    setup_project_with_transformer_and_zone,
    assign_fixtures_to_zone,
    lock_design,
    build_draft_quote_with_lines,
    send_quote,
    make_customer_headers,
    api_client,
    TEST_USERS,
)

DESIGNER = TEST_USERS["lighting_designer_headers"]


def _design_locked_project():
    """A DESIGN_LOCKED project with one assigned PATH-3W fixture."""
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4500}])
    lock_design(ctx["project_id"])
    return ctx


def test_quote_pricing_tiered_rate_with_demo_fee(api):
    """PRD §3.3: "The `discount_cents` is that rate applied to the summed
    `subtotal_cents`, with the fractional cent floored away." and "from 10 up to
    but not including 25 earns five percent" and "when `night_demo_requested` is
    true the fee is 15000 cents" and "`tax_cents` is computed exactly once on that
    taxable base at a rate of 8.25 percent, rounded half up to a whole cent" and
    "`grand_total_cents` is the taxable base plus the tax."

    18 units selects the 5% tier; demo adds 15000; subtotal 108000, discount 5400,
    base 117600, tax 9702, grand 127302.

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_rate_selection_mode_a
    """
    ctx = _design_locked_project()
    quote = build_draft_quote_with_lines(
        ctx["project_id"],
        lines=[
            {"model_code": "PATH-3W", "quantity": 12, "unit_price_cents": 4500},
            {"model_code": "SPOT-9W", "quantity": 6, "unit_price_cents": 9000},
        ],
        quote_overrides={"night_demo_requested": True, "night_demo_at": "2026-04-20T20:00:00Z"},
    )
    data = validate_success(api.send_quote(quote["id"], DESIGNER))
    assert data["subtotal_cents"] == 108000, f"subtotal {data['subtotal_cents']}"
    assert data["discount_cents"] == 5400, f"discount {data['discount_cents']}"
    assert data["tax_cents"] == 9702, f"tax {data['tax_cents']}"
    assert data["grand_total_cents"] == 127302, f"grand {data['grand_total_cents']}"


def test_quote_pricing_no_demo_no_discount_tier(api):
    """PRD §3.3: "a combined quantity below 10 earns no discount" and "when
    `night_demo_requested` is true the fee is 15000 cents, otherwise it is zero."

    A 9-unit quote with no demo lands in the 0% tier: subtotal 36000, no discount,
    no demo fee, tax round_half_up(36000*0.0825)=2970, grand 38970.

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_rate_selection_mode_a
    """
    ctx = _design_locked_project()
    quote = build_draft_quote_with_lines(
        ctx["project_id"],
        lines=[{"model_code": "PATH-3W", "quantity": 9, "unit_price_cents": 4000}],
    )
    data = validate_success(api.send_quote(quote["id"], DESIGNER))
    assert data["subtotal_cents"] == 36000, f"subtotal {data['subtotal_cents']}"
    assert data["discount_cents"] == 0, f"discount {data['discount_cents']}"
    assert data["tax_cents"] == 2970, f"tax {data['tax_cents']}"
    assert data["grand_total_cents"] == 38970, f"grand {data['grand_total_cents']}"


def test_quote_pricing_rounding_order_discount_on_summed_subtotal(api):
    """PRD §3.3: "`subtotal_cents` is the sum over all of the quote's lines of
    each line's `line_total_cents`." and "The `discount_cents` is that rate applied
    to the summed `subtotal_cents`, with the fractional cent floored away." and
    "`tax_cents` is computed exactly once on that taxable base at a rate of 8.25
    percent, rounded half up to a whole cent — never per line."

    10 units @ 4000: subtotal 40000, 5% discount floored to 2000, base 38000,
    tax 3135, grand 41135 — distinct from any per-line interpretation.

    Design: Difficulty/combinatorial_formula/quote_pricing_rounding_order_mode_b
    """
    ctx = _design_locked_project()
    quote = build_draft_quote_with_lines(
        ctx["project_id"],
        lines=[{"model_code": "PATH-3W", "quantity": 10, "unit_price_cents": 4000}],
    )
    data = validate_success(api.send_quote(quote["id"], DESIGNER))
    assert data["subtotal_cents"] == 40000, f"subtotal {data['subtotal_cents']}"
    assert data["discount_cents"] == 2000, f"discount {data['discount_cents']}"
    assert data["tax_cents"] == 3135, f"tax {data['tax_cents']}"
    assert data["grand_total_cents"] == 41135, f"grand {data['grand_total_cents']}"


def test_quote_pricing_tax_rounds_half_up_on_base(api):
    """PRD §3.3: "`tax_cents` is computed exactly once on that taxable base at a
    rate of 8.25 percent, rounded half up to a whole cent — never per line."

    Re-asserts the pinned round-half-up tax step on the 10-unit @ 4000 base of
    38000 -> tax 3135.

    Design: Difficulty/combinatorial_formula/quote_pricing_rounding_order_mode_b
    """
    ctx = _design_locked_project()
    quote = build_draft_quote_with_lines(
        ctx["project_id"],
        lines=[{"model_code": "PATH-3W", "quantity": 10, "unit_price_cents": 4000}],
    )
    data = validate_success(api.send_quote(quote["id"], DESIGNER))
    # taxable base = 40000 - 2000 = 38000; 38000 * 0.0825 = 3135.0 -> 3135
    assert data["tax_cents"] == 3135, f"tax {data['tax_cents']}"


def test_quote_accept_debits_customer_wallet_and_advances_project(api):
    """PRD §3.3: "Acceptance requires the quote to be `SENT` and the project to be
    `QUOTED`; it moves the quote to `ACCEPTED` (terminal), advances the project's
    `commercial_status` from `QUOTED` to `ACCEPTED` with a project `version`
    increment, and debits the customer's `wallet_credit_cents` by the quote's
    `grand_total_cents`."

    A grand_total of 41135 debits the wallet from 0 to -41135.

    Design: Corner/endpoints/quote_accept_debits_customer_wallet
    """
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    lock_design(ctx["project_id"])
    quote = build_draft_quote_with_lines(
        ctx["project_id"],
        lines=[{"model_code": "PATH-3W", "quantity": 10, "unit_price_cents": 4000}],
    )
    send_quote(quote["id"])

    accepted = validate_success(api.accept_quote(quote["id"], make_customer_headers(ctx["cust_id"])))
    assert accepted["status"] == "ACCEPTED"

    project = validate_success(api.get_project(ctx["project_id"], DESIGNER))
    assert project["commercial_status"] == "ACCEPTED", project["commercial_status"]

    customer = validate_success(api.get_customer(ctx["cust_id"], TEST_USERS["operations_admin_headers"]))
    assert customer["wallet_credit_cents"] == -41135, customer["wallet_credit_cents"]
