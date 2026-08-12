"""Line pricing under both bases, the per-line tax rounding order, and the
computed money reads that expose them."""
from test_helpers import (
    CLOCK_HOLD_LAPSE_TIME,
    add_line,
    add_menu_item,
    api_client,
    assert_line_pricing,
    authorize_payment,
    confirm_order,
    lines_of,
    open_order,
    read_capacity,
    read_compliance,
    read_line,
    read_order,
    set_clock,
    setup_held_order,
    setup_storefront,
    sweep_holds,
    validate_success,
    window_version,
)


def test_bakers_dozen_total_falls_at_thirteen_and_rises_back_at_twelve(api):
    """PRD §3.3: "Under `PER_DOZEN_BAKERS`, the quantity is divided into whole blocks
    of 13: each full block is charged at `dozen_price_cents`, and whatever units
    remain after the last full block are charged individually at `unit_price_cents`."
    PRD §3.3: "with a unit price of 450 and a dozen price of 4600, twelve units cost
    5400 while thirteen units cost 4600, and twenty-six units cost 9200 while
    twenty-five cost 10,000."
    PRD §3.3: "A buyer who *reduces* a quantity across a block boundary can
    therefore see the line total go **up**."

    Design: Difficulty/dual_variant_calc/bakers_dozen_pricing_variant_raises_total_on_quantity_reduction
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    line = add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)
    total_at_13 = line["line_total_cents"]
    assert total_at_13 == 4600, "one full block of thirteen at the dozen price"

    patched = validate_success(
        api.patch_order_line(
            order["id"],
            line["id"],
            {
                "quantity": 12,
                "expected_offer_window_version": window_version(s.window_id, s.ch),
            },
            s.ch,
        )
    )
    total_at_12 = patched["line_total_cents"]
    assert total_at_12 == 5400, "no full block; twelve remainder units at 450 each"
    assert total_at_12 - total_at_13 == 800, (
        "reducing the quantity by one unit RAISED the line total by 800 cents"
    )
    assert patched["pricing_basis_applied"] == "PER_DOZEN_BAKERS"


def test_per_unit_basis_stays_strictly_increasing_alongside_it(api):
    """PRD §3.3: "Under the `PER_UNIT` basis a line's total is simply its `quantity`
    multiplied by `unit_price_cents`, and the total rises strictly with quantity."
    PRD §3.5: "`pricing_basis_applied` is copied from the menu item's
    `pricing_basis` at pricing time"

    Design: Difficulty/dual_variant_calc/bakers_dozen_pricing_variant_raises_total_on_quantity_reduction
    """
    s = setup_storefront()
    add_menu_item(s, kind="loaf")
    order = open_order(s.customer_id, s.window_id)
    cookie_line = add_line(order["id"], s.cookie_id, 13, s.customer_id, s.window_id)
    loaf_line = add_line(order["id"], s.loaf_id, 13, s.customer_id, s.window_id)

    assert cookie_line["line_total_cents"] == 4600
    assert loaf_line["line_total_cents"] == 11700, "thirteen loaves at 900 each"
    assert cookie_line["pricing_basis_applied"] == "PER_DOZEN_BAKERS"
    assert loaf_line["pricing_basis_applied"] == "PER_UNIT"


def test_tax_is_rounded_per_line_before_the_order_total_is_summed(api):
    """PRD §2.5: "sales tax is rounded per line and only then summed across the
    lines of an order."
    PRD §2.5: "As a worked illustration, two taxable lines of 4600 and 5400 cents
    produce 334 and 392 cents of tax respectively, for an order tax total of 726
    cents; rounding a single 10000-cent aggregate at the same rate would have
    produced 725."
    PRD §3.5: "For a taxable line, `line_tax_cents` is the line total multiplied by
    the tax rate of **725 basis points** — seven and a quarter percent — rounded
    half up to a whole cent."

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_differs_by_one_cent
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    line_a = add_line(
        order["id"], s.cookie_id, 13, s.customer_id, s.window_id,
        disposition="WITH_UTENSILS",
    )
    line_b = add_line(
        order["id"], s.cookie_id, 12, s.customer_id, s.window_id, disposition="HEATED"
    )

    assert_line_pricing(read_line(line_a["id"], s.ch), 4600, 334)
    assert_line_pricing(read_line(line_b["id"], s.ch), 5400, 392)

    confirmed = validate_success(api.confirm_order(order["id"], s.ch, {}))
    assert confirmed["subtotal_cents"] == 10000
    assert confirmed["tax_total_cents"] == 726
    assert confirmed["tax_total_cents"] != 725, (
        "725 is the rejected sum-then-round reading"
    )


def test_an_unheated_whole_line_is_exempt_while_its_siblings_are_taxable(api):
    """PRD §3.5: "A line is `taxable` when its `disposition` is anything other than
    `WHOLE_UNHEATED`: an unheated whole bakery item sold as-is is exempt, and its
    `line_tax_cents` is 0 no matter how large `line_total_cents` is, whereas
    supplying utensils (`WITH_UTENSILS`), slicing it (`BY_THE_SLICE`), or heating it
    (`HEATED`) flips the identical units to taxable."

    Design: Difficulty/combinatorial_formula/per_line_tax_rounding_then_sum_differs_by_one_cent
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    taxable_a = add_line(
        order["id"], s.cookie_id, 13, s.customer_id, s.window_id,
        disposition="WITH_UTENSILS",
    )
    taxable_b = add_line(
        order["id"], s.cookie_id, 12, s.customer_id, s.window_id, disposition="HEATED"
    )
    exempt = add_line(
        order["id"], s.cookie_id, 13, s.customer_id, s.window_id,
        disposition="WHOLE_UNHEATED",
    )

    assert read_line(taxable_a["id"], s.ch)["taxable"] is True
    assert read_line(taxable_b["id"], s.ch)["taxable"] is True
    exempt_line = read_line(exempt["id"], s.ch)
    assert exempt_line["taxable"] is False
    assert exempt_line["line_total_cents"] == 4600
    assert exempt_line["line_tax_cents"] == 0


def test_order_subtotal_excludes_a_released_line(api):
    """PRD §3.5: "the order's `subtotal_cents` is the sum of `line_total_cents` over
    the lines that are neither `RELEASED` nor `RECALL_VOID`."
    PRD §3.5: "The lines released earlier stay `RELEASED` forever and never
    re-enter pricing."

    Design: Corner/calculations/order_subtotal_excludes_released_lines
    """
    s = setup_held_order(quantity=13)
    set_clock(CLOCK_HOLD_LAPSE_TIME)
    sweep_holds(s.window_id)
    second = add_line(s.order_id, s.cookie_id, 5, s.customer_id, s.window_id)

    assert read_line(s.line_id, s.ch)["line_status"] == "RELEASED"
    assert read_line(second["id"], s.ch)["line_status"] == "PENDING"

    confirmed = validate_success(api.confirm_order(s.order_id, s.ch, {}))
    assert confirmed["subtotal_cents"] == 2250, "five remainder units at 450 each"
    assert confirmed["subtotal_cents"] != 6850, (
        "6850 is what including the RELEASED line would give"
    )
    assert confirmed["tax_total_cents"] == 0
    assert read_capacity(s.window_id, s.bh)["confirmed_units"] == 5


def test_the_order_quote_matches_the_stored_money_fields(api):
    """PRD §3.5: "A read-only money breakdown is available on any order and reports,
    in the pinned evaluation order of §3.9, its `subtotal_cents`, `tax_total_cents`,
    `delivery_fee_cents`, `tip_cents`, `credit_applied_cents`, and
    `grand_total_cents`, together with a `taxable_line_count` and an
    `exempt_line_count`."
    PRD §3.9: "Under `FIXED`, the tip is the literal `tip_fixed_cents` with no
    rounding at all."

    Design: Corner/endpoints/order_quote_computed_read_matches_the_stored_money_fields
    """
    s = setup_storefront()
    order = open_order(s.customer_id, s.window_id)
    exempt = add_line(
        order["id"], s.cookie_id, 13, s.customer_id, s.window_id,
        disposition="WHOLE_UNHEATED",
    )
    taxable = add_line(
        order["id"], s.cookie_id, 12, s.customer_id, s.window_id, disposition="HEATED"
    )
    confirm_order(order["id"], s.customer_id)
    authorize_payment(order["id"], s.customer_id, tip_mode="FIXED", tip_fixed_cents=500)

    quote = validate_success(api.get_order_quote(order["id"], s.ch))
    assert quote["subtotal_cents"] == 10000
    assert quote["tax_total_cents"] == 392
    assert quote["delivery_fee_cents"] == 0
    assert quote["tip_cents"] == 500
    assert quote["credit_applied_cents"] == 0
    assert quote["grand_total_cents"] == 10892
    assert quote["taxable_line_count"] == 1
    assert quote["exempt_line_count"] == 1

    assert read_line(exempt["id"], s.ch)["line_tax_cents"] == 0
    assert read_line(taxable["id"], s.ch)["line_tax_cents"] == 392

    stored = read_order(order["id"], s.ch)
    for field in ("subtotal_cents", "tax_total_cents", "delivery_fee_cents",
                  "tip_cents", "credit_applied_cents", "grand_total_cents"):
        assert quote[field] == stored[field], f"quote and order disagree on {field}"


def test_the_confirm_response_already_carries_every_recomputed_figure(api):
    """PRD §3.5: "Once past the ladder, confirmation prices every `PENDING` line and
    its tax, sets `subtotal_cents`, `tax_total_cents`, and `delivery_fee_cents`"
    PRD §2.11: "Read endpoints that expose computed figures recompute them in the
    request."
    PRD §2.11: "reading a window's capacity refreshes `confirmed_units`,
    `held_units`, `reserved_units`, and `capacity_posture`."

    Design: Corner/consistency_model/confirm_response_already_carries_every_recomputed_field
    """
    s = setup_held_order(quantity=13)
    confirmed = validate_success(api.confirm_order(s.order_id, s.ch, {}))
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["subtotal_cents"] == 4600
    assert confirmed["tax_total_cents"] == 0
    assert confirmed["delivery_fee_cents"] == 0
    assert confirmed["version"] >= 2, "the confirm mutated the order at least once"
    assert confirmed["hold_expires_at"] is None

    capacity = read_capacity(s.window_id, s.bh)
    assert capacity["held_units"] == 0
    assert capacity["confirmed_units"] == 13
    assert capacity["units_remaining"] == 227
    assert read_compliance(s.baker_id, s.bh)["annual_gross_sales_cents"] == 4600
    assert len(lines_of(s.order_id, s.ch)) == 1
