"""Menu bill-of-materials, quoting estimate, revise cycle, and optimistic concurrency.

Translates queue-A instances (combinatorial_formula/portion_food_cost_sum_then_round,
non_linear_state_machine/event_order_quote_revise_cycle,
boundary_precision_check/quote_rejected_on_empty_order_lines) and several queue-B
corner instances (calculations, entities, endpoints, cross_cutting, consistency_model).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.factories import create_menu_item_payload


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / portion_food_cost_sum_then_round
# --------------------------------------------------------------------------
def _build_risotto_two_half_cent_lines(api):
    """Two BOM lines each contributing exactly 12.5c. Returns menu_item_id."""
    saffron = fx.create_ingredient(api, name="Saffron", unit="GRAM", unit_cost_cents=1000, on_hand_qty=1000)
    cream = fx.create_ingredient(api, name="Cream", unit="ML", unit_cost_cents=500, on_hand_qty=1000)
    risotto = fx.create_menu_item(api, name="Risotto", category="ENTREE", sell_price_cents_per_portion=1800)
    fx.add_recipe_line(api, risotto["id"], saffron["id"], qty_per_portion=0.0125)   # 12.5c
    fx.add_recipe_line(api, risotto["id"], cream["id"], qty_per_portion=0.025)      # 12.5c
    return risotto["id"]


def test_portion_food_cost_sums_then_rounds_once(api, kitchen_manager_headers):
    """PRD §3.1: "These exact contributions are summed across all lines as exact
    rational values, and only the final sum is rounded half up, once, to whole cents."

    Design: Difficulty/combinatorial_formula/portion_food_cost_sum_then_round
    """
    risotto_id = _build_risotto_two_half_cent_lines(api)
    data = validate_success(api.get_menu_item(risotto_id, kitchen_manager_headers))
    assert data["portion_food_cost_cents"] == 25, (
        f"12.5c + 12.5c summed then rounded once must be 25, got {data['portion_food_cost_cents']}"
    )


def test_portion_food_cost_not_per_line_rounded(api, kitchen_manager_headers):
    """PRD §3.1: "Summing first and rounding once is mandatory; rounding each line
    individually and then adding is explicitly not the intended behavior."

    Design: Difficulty/combinatorial_formula/portion_food_cost_sum_then_round
    """
    risotto_id = _build_risotto_two_half_cent_lines(api)
    data = validate_success(api.get_menu_item(risotto_id, kitchen_manager_headers))
    assert data["portion_food_cost_cents"] != 26, (
        "per-line rounding would give 13+13=26; the sum-then-round result 25 is required"
    )
    assert data["portion_food_cost_cents"] == 25


# --------------------------------------------------------------------------
# Corner: calculations / entities
# --------------------------------------------------------------------------
def test_portion_food_cost_zero_without_recipe_lines(api, kitchen_manager_headers):
    """PRD §3.1: "A menu item with no recipe lines has a `portion_food_cost_cents` of 0."

    Design: Corner/entities/portion_food_cost_computed_input_ignored
    """
    data = validate_success(
        api.create_menu_item(create_menu_item_payload(name="Plain", sell_price_cents_per_portion=500),
                             kitchen_manager_headers),
        201,
    )
    assert data["portion_food_cost_cents"] == 0


def test_recipe_line_is_immutable_no_version_field(api, kitchen_manager_headers):
    """PRD §2.4: "a `RecipeLine` is immutable once created and therefore carries only
    `id` and `created_at`. It has no `updated_at` and no `version`."

    Design: Corner/entities/recipe_line_is_immutable_no_version_field
    """
    ingredient = fx.create_ingredient(api, on_hand_qty=100)
    menu_item = fx.create_menu_item(api)
    from test_helpers.factories import create_recipe_line_payload
    data = validate_success(
        api.create_recipe_line(create_recipe_line_payload(menu_item["id"], ingredient["id"]),
                               kitchen_manager_headers),
        201,
    )
    assert "version" not in data, "RecipeLine response must not carry a version field"
    assert "updated_at" not in data, "RecipeLine response must not carry an updated_at field"


def test_quote_estimate_food_revenue_and_cost_correct(api, sales_manager_headers):
    """PRD §3.3: "The revenue contribution of the line is that portion count times the
    referenced menu item's `sell_price_cents_per_portion`, and the cost contribution is
    that same portion count times the menu item's `portion_food_cost_cents`. Summing the
    revenue contributions over all active lines gives `food_revenue_cents`, and summing
    the cost contributions gives `food_cost_cents`; these subtotals are exact integer
    cents and are not rounded."

    Design: Corner/calculations/quote_estimate_food_revenue_and_cost_correct
    """
    recipe = fx.menu_item_with_recipe(api, unit_cost_cents=10, qty_per_portion=5, sell=1000)  # cost 50
    base = fx.draft_order_with_line(api, menu_item_id=recipe["menu_item_id"], guest_count=40)
    quote = fx.generate_quote(api, base["order_id"])
    assert quote["food_revenue_cents"] == 40000, f"40 portions * 1000, got {quote['food_revenue_cents']}"
    assert quote["food_cost_cents"] == 2000, f"40 portions * 50, got {quote['food_cost_cents']}"


def test_quote_ceils_line_portions_for_fractional_ppg(api, sales_manager_headers):
    """PRD §3.3: "For each `ACTIVE` order line, the line's portion count is the line's
    `portions_per_guest` multiplied by the headcount and then rounded **up** to the next
    whole number (a ceiling)."

    Design: Corner/calculations/quote_ceil_line_portions_fractional_ppg
    """
    base = fx.draft_order_with_line(api, guest_count=10, portions_per_guest=0.33)  # ceil(3.3)=4
    quote = fx.generate_quote(api, base["order_id"])
    assert quote["food_revenue_cents"] == 4000, (
        f"ceil(0.33*10)=4 portions * 1000, got {quote['food_revenue_cents']}"
    )


def test_quote_generation_visible_in_same_response(api, sales_manager_headers):
    """PRD §3.3: "Generating the first quote advances the order `DRAFT → QUOTED` and
    creates a `Quote` in `ACTIVE` status."
    PRD §3.3: "the estimate computed over the active lines"

    Design: Corner/consistency_model/quote_generation_visible_in_same_response
    """
    base = fx.draft_order_with_line(api, guest_count=10, portions_per_guest=1.0)
    quote = fx.generate_quote(api, base["order_id"])
    assert quote["food_revenue_cents"] == 10000, f"10 portions * 1000, got {quote['food_revenue_cents']}"
    order = validate_success(api.get_event_order(base["order_id"], sales_manager_headers))
    assert order["status"] == "QUOTED", "status must be QUOTED on immediate re-read"


# --------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / event_order_quote_revise_cycle
# --------------------------------------------------------------------------
def test_revise_supersedes_quote_and_requote_reactivates(api, sales_manager_headers):
    """PRD §3.3: "revising a `QUOTED` order returns it `QUOTED → DRAFT`, marks its
    `ACTIVE` quote `SUPERSEDED`, and increments `version`."

    Design: Difficulty/non_linear_state_machine/event_order_quote_revise_cycle
    """
    base = fx.quoted_order_with_line(api, guest_count=20)
    q1_id = base["quote_id"]
    validate_success(api.revise_order(base["order_id"], sales_manager_headers))
    q2 = fx.generate_quote(api, base["order_id"])
    q1 = validate_success(api.get_quote(q1_id, sales_manager_headers))
    assert q1["status"] == "SUPERSEDED", f"prior quote must be SUPERSEDED, got {q1['status']}"
    assert q2["status"] == "ACTIVE", f"fresh quote must be ACTIVE, got {q2['status']}"


def test_requote_after_revise_returns_order_to_quoted(api, sales_manager_headers):
    """PRD §3.3: "Generating the first quote advances the order `DRAFT → QUOTED` and
    creates a `Quote` in `ACTIVE` status."

    Design: Difficulty/non_linear_state_machine/event_order_quote_revise_cycle
    """
    base = fx.quoted_order_with_line(api, guest_count=20)
    validate_success(api.revise_order(base["order_id"], sales_manager_headers))
    fx.generate_quote(api, base["order_id"])
    order = validate_success(api.get_event_order(base["order_id"], sales_manager_headers))
    assert order["status"] == "QUOTED", f"order must be QUOTED after re-quote, got {order['status']}"


# --------------------------------------------------------------------------
# Difficulty: boundary_precision_check / quote_rejected_on_empty_order_lines
# --------------------------------------------------------------------------
def test_quote_with_zero_active_lines_rejected(api, sales_manager_headers):
    """PRD §3.3: "A quote may only be generated when the order has at least one `ACTIVE`
    order line; a generation attempt against an order with zero active lines is rejected
    with `ERR_NO_ORDER_LINES`."

    Design: Difficulty/boundary_precision_check/quote_rejected_on_empty_order_lines
    """
    order = fx.create_event_order(api, guest_count=25, service_charge_pct=0.10, gratuity_pct=0.10)
    ver = fx.order_version(api, order["id"])
    resp = api.generate_quote(order["id"], {"expected_event_order_version": ver}, sales_manager_headers)
    validate_error(resp, ApiErrorId.ERR_NO_ORDER_LINES)


def test_quote_with_one_active_line_succeeds(api, sales_manager_headers):
    """PRD §3.3: "Once at least one active line exists, the `SalesManager` generates a
    quote."
    PRD §3.3: "Generating the first quote advances the order `DRAFT → QUOTED` and
    creates a `Quote` in `ACTIVE` status."

    Design: Difficulty/boundary_precision_check/quote_rejected_on_empty_order_lines
    """
    base = fx.draft_order_with_line(api, guest_count=25)
    ver = fx.order_version(api, base["order_id"])
    resp = api.generate_quote(base["order_id"], {"expected_event_order_version": ver}, sales_manager_headers)
    quote = validate_success(resp, 201)
    assert quote["status"] == "ACTIVE"
    order = validate_success(api.get_event_order(base["order_id"], sales_manager_headers))
    assert order["status"] == "QUOTED"


# --------------------------------------------------------------------------
# Corner: cross_cutting / optimistic concurrency
# --------------------------------------------------------------------------
def test_occ_stale_order_version_on_requote_returns_412(api, sales_manager_headers):
    """PRD §2.7: "If that value does not equal the order's current `version`, the request
    is rejected with `ERR_STALE_ORDER_VERSION` and HTTP status 412."
    PRD §2.7: "Because every operation that changes the order's line set or quote history
    — adding an order line, removing an order line, revising the order, or generating a
    prior quote — increments the order's `version`, a client working from a stale view
    will carry a pre-increment number and be turned away rather than silently superseding
    a quote it never saw."

    Design: Corner/cross_cutting/occ_stale_order_version_on_requote_returns_412
    """
    base = fx.draft_order_with_line(api, guest_count=20)
    stale_ver = fx.order_version(api, base["order_id"])
    validate_success(
        api.generate_quote(base["order_id"], {"expected_event_order_version": stale_ver}, sales_manager_headers),
        201,
    )
    resp = api.generate_quote(base["order_id"], {"expected_event_order_version": stale_ver}, sales_manager_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)


def test_occ_correct_version_requote_succeeds_and_bumps_version(api, sales_manager_headers):
    """PRD §2.4: "an integer `version` that starts at 1 and increments by one on each
    mutation."
    PRD §3.2: "Each successful add or remove increments the parent `EventOrder.version`
    by one — the very mutations that the quote-generation concurrency guard keys on."
    PRD §2.7: "Because every operation that changes the order's line set or quote history
    — adding an order line, removing an order line, revising the order, or generating a
    prior quote — increments the order's `version`"

    Design: Corner/cross_cutting/occ_correct_version_requote_succeeds_and_bumps_version
    """
    base = fx.draft_order_with_line(api, guest_count=20)  # create v1, +line v2
    ver = fx.order_version(api, base["order_id"])
    resp = api.generate_quote(base["order_id"], {"expected_event_order_version": ver}, sales_manager_headers)
    validate_success(resp, 201)
    order = validate_success(api.get_event_order(base["order_id"], sales_manager_headers))
    assert order["version"] == 3, f"create(1)->line(2)->quote(3), got {order['version']}"
    assert order["status"] == "QUOTED"


# --------------------------------------------------------------------------
# Corner: endpoints / FK reverse-reachability
# --------------------------------------------------------------------------
def test_list_order_lines_by_event_order_excludes_removed(api, sales_manager_headers):
    """PRD §3.2: "removing it is a soft delete that transitions it `ACTIVE → REMOVED`,
    and removed lines are excluded from every calculation and from default list results."
    PRD §3.2: "When listing order lines, the caller may filter by `event_order_id` and/or
    `menu_item_id`, and may pass `include_removed` set to true to surface soft-removed
    lines that the default view hides."

    Design: Corner/endpoints/list_order_lines_by_event_order_fk_reverse_reachability
    """
    menu_item = fx.create_menu_item(api)
    order = fx.create_event_order(api, guest_count=20, service_charge_pct=0.10, gratuity_pct=0.10)
    keep = fx.add_order_line(api, order["id"], menu_item["id"], portions_per_guest=1.0)
    drop = fx.add_order_line(api, order["id"], menu_item["id"], portions_per_guest=2.0)
    validate_success(api.delete_order_line(drop["id"], sales_manager_headers))
    data, _ = validate_paginated(api.list_order_lines(sales_manager_headers, params={"event_order_id": order["id"]}))
    ids = {line["id"] for line in data}
    assert keep["id"] in ids, "ACTIVE line must appear in default list"
    assert drop["id"] not in ids, "REMOVED line must be excluded from default list"
