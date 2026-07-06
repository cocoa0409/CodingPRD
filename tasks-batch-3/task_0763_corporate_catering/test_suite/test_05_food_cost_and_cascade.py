"""Food-cost finalization (theoretical vs actual FIFO), the session-close rollup cascade,
PO-receipt inventory valuation, the empty-set zero boundary, the session changeover buffer,
waste valuation, and satisfaction averaging (PRD §2.9, §2.10, §3.2, §3.3, §3.4, §3.5, §3.8).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    setup_session, setup_received_po, create_site, create_cycle, add_item, create_venue,
    create_employee, create_pos, stock_site, get_lot, get_site,
    create_service_session_payload, create_catering_order_payload,
    create_satisfaction_survey_payload,
    make_coordinator_headers, make_diner_headers,
)

ADMIN = TEST_USERS["site_admin_headers"]
MANAGER = TEST_USERS["cafeteria_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]

COMBO = {"name": "Combo", "category": "ENTREE", "price_cents": 1000, "standard_recipe_cost_cents": 400}


# ─── Difficulty: dual_variant_calc — session theoretical vs actual food cost ──
def _dual_variant_close(api):
    ctx = setup_session(stage="IN_SERVICE", items=[COMBO], site_overrides={"food_cost_target_pct": 0.32})
    combo = ctx["items"][0]
    create_pos(ctx["employee"]["id"], ctx["session"]["id"], [{"menu_item_id": combo["id"], "qty": 1}])
    stock_site(ctx["site"]["id"], "COMBO_KIT", 5, 500)
    closed = validate_success(api.close_session(
        ctx["session"]["id"], {"consumed_ingredients": [{"ingredient": "COMBO_KIT", "qty": 1}]}, MANAGER), 200)
    return closed


def test_session_theoretical_food_cost_is_recipe_based(api):
    """PRD §3.3: "the session's running figures are updated ... `theoretical_food_cost_cents`
    increases by the sum over the lines of the menu item's `standard_recipe_cost_cents` times
    `qty`."

    Design: Difficulty/dual_variant_calc/session_theoretical_vs_actual_food_cost
    """
    closed = _dual_variant_close(api)
    assert closed["theoretical_food_cost_cents"] == 400


def test_session_actual_food_cost_is_fifo_and_diverges_from_theoretical(api):
    """PRD §3.4: "The manager-supplied consumption is valued by FIFO against the site's
    `AVAILABLE` lots of each ingredient (earliest `received_at` first, ties broken by earliest
    `created_at`), producing `actual_food_cost_cents`."

    Design: Difficulty/dual_variant_calc/session_theoretical_vs_actual_food_cost
    """
    closed = _dual_variant_close(api)
    assert closed["actual_food_cost_cents"] == 500
    assert closed["actual_food_cost_cents"] != closed["theoretical_food_cost_cents"]


# ─── Difficulty: transitive_cascade — close rolls up and flags catering ─────
def _cascade_scenario(api):
    site = create_site(food_cost_target_pct=0.32, daily_subsidy_cap_cents=100000)
    cycle = create_cycle(site["id"])
    combo = add_item(cycle["id"], **COMBO)
    validate_success(api.publish_menu_cycle(cycle["id"], MANAGER), 200)
    venue = create_venue(site["id"])
    coord = make_coordinator_headers("coord-1")
    order = validate_success(api.create_catering_order(create_catering_order_payload(
        site["id"], venue["id"], [{"menu_item_id": combo["id"], "qty": 1}]), coord), 201)
    order = validate_success(api.submit_catering_order(order["id"], coord), 200)

    lot = stock_site(site["id"], "COMBO_KIT", 1, 500)

    emp = create_employee(site["id"])
    session = validate_success(api.create_service_session(
        create_service_session_payload(site["id"], cycle["id"]), MANAGER), 201)
    validate_success(api.lock_forecast(session["id"], MANAGER), 200)
    validate_success(api.open_session(session["id"], MANAGER), 200)
    create_pos(emp["id"], session["id"], [{"menu_item_id": combo["id"], "qty": 1}])

    validate_success(api.close_session(
        session["id"], {"consumed_ingredients": [{"ingredient": "COMBO_KIT", "qty": 1}]}, MANAGER), 200)
    return {"site": site, "lot": lot, "order": order}


def test_close_depletes_lot_and_flips_cost_status_over_target(api):
    """PRD §3.4: "each consumed lot has its `qty_on_hand` decremented by the amount taken,
    and any lot reaching 0 becomes `DEPLETED`."
    PRD §3.4: "if the recomputed `food_cost_pct` now exceeds the site's
    `food_cost_target_pct`, the site's `cost_status` flips to `OVER_TARGET`."

    Design: Difficulty/transitive_cascade/session_close_site_rollup_catering_flag
    """
    ctx = _cascade_scenario(api)
    lot = get_lot(ctx["lot"]["id"])
    assert lot["status"] == "DEPLETED"
    site = get_site(ctx["site"]["id"])
    assert site["cost_status"] == "OVER_TARGET"


def test_close_over_target_flags_submitted_catering_order(api):
    """PRD §3.4: "every catering order at that site currently in `SUBMITTED` status is
    stamped with `requires_finance_review` set to true — flagging in-flight orders for extra
    scrutiny because the site has just breached its target."

    Design: Difficulty/transitive_cascade/session_close_site_rollup_catering_flag
    """
    ctx = _cascade_scenario(api)
    order = validate_success(api.get_catering_order(ctx["order"]["id"], FINANCE), 200)
    assert order["requires_finance_review"] is True


# ─── Difficulty: transitive_cascade — PO receipt creates lot & raises value ──
def test_po_receive_creates_lot_with_full_quantity(api):
    """PRD §3.5: "for each order line the system creates an inventory lot at the destination
    site with `qty_received` and `qty_on_hand` equal to the line quantity."

    Design: Difficulty/transitive_cascade/po_receive_creates_lot_raises_inventory_value
    """
    base = setup_received_po(line=("FLOUR", 10, 200))
    lots, _meta = validate_paginated(api.list_inventory_lots(
        MANAGER, params={"purchase_order_id": base["po"]["id"]}))
    assert lots[0]["qty_on_hand"] == 10


def test_po_receive_raises_site_inventory_value(api):
    """PRD §2.9: "The `inventory_value_cents` is the sum, over the site's `AVAILABLE`
    inventory lots, of each lot's remaining on-hand quantity multiplied by its unit cost."

    Design: Difficulty/transitive_cascade/po_receive_creates_lot_raises_inventory_value
    """
    base = setup_received_po(line=("FLOUR", 10, 200))
    site = get_site(base["site"]["id"])
    assert site["inventory_value_cents"] == 2000


# ─── Difficulty: boundary_precision_check — zero-sales / empty-set close ─────
def test_close_zero_sales_actual_cost_is_zero(api):
    """PRD §3.4: "The manager-supplied consumption is valued by FIFO against the site's
    `AVAILABLE` lots of each ingredient ... producing `actual_food_cost_cents`."

    Design: Difficulty/boundary_precision_check/session_close_zero_sales_empty_set
    """
    ctx = setup_session(stage="IN_SERVICE", make_employee=False,
                        session_overrides={"forecast_headcount": 0})
    closed = validate_success(api.close_session(
        ctx["session"]["id"], {"consumed_ingredients": []}, MANAGER), 200)
    assert closed["actual_food_cost_cents"] == 0


def test_close_zero_revenue_leaves_food_cost_pct_null_on_target(api):
    """PRD §2.9: "When `period_revenue_cents` is 0 the division is undefined and
    `food_cost_pct` is reported as null. The site's `cost_status` is `OVER_TARGET` when
    `food_cost_pct` is not null and strictly greater than the site's `food_cost_target_pct`;
    otherwise it is `ON_TARGET` (including whenever `food_cost_pct` is null)."

    Design: Difficulty/boundary_precision_check/session_close_zero_sales_empty_set
    """
    ctx = setup_session(stage="IN_SERVICE", make_employee=False,
                        session_overrides={"forecast_headcount": 0})
    validate_success(api.close_session(
        ctx["session"]["id"], {"consumed_ingredients": []}, MANAGER), 200)
    site = get_site(ctx["site"]["id"])
    assert site["food_cost_pct"] is None
    assert site["cost_status"] == "ON_TARGET"


# ─── Difficulty: resource_temporal_overlap — session changeover buffer ──────
def test_session_within_changeover_buffer_rejected(api):
    """PRD §3.2: "any two sessions on the same date at a site must be separated by at least
    the site's `session_changeover_buffer_minutes`; a session planned too close to an
    existing one on that date is rejected with `ERR_SESSION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_changeover_buffer_gap
    """
    site = create_site(session_changeover_buffer_minutes=30)
    cycle = create_cycle(site["id"])
    validate_success(api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="BREAKFAST",
        window_start="2026-03-02T10:00:00Z", window_end="2026-03-02T11:00:00Z"), MANAGER), 201)
    res = api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="LUNCH",
        window_start="2026-03-02T11:15:00Z", window_end="2026-03-02T12:15:00Z"), MANAGER)
    validate_error(res, ApiErrorId.ERR_SESSION_BUFFER_CONFLICT.value, expected_status=409)


def test_session_at_exact_changeover_buffer_allowed(api):
    """PRD §3.2: "any two sessions on the same date at a site must be separated by at least
    the site's `session_changeover_buffer_minutes`; a session planned too close to an
    existing one on that date is rejected with `ERR_SESSION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/session_changeover_buffer_gap
    """
    site = create_site(session_changeover_buffer_minutes=30)
    cycle = create_cycle(site["id"])
    validate_success(api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="BREAKFAST",
        window_start="2026-03-02T10:00:00Z", window_end="2026-03-02T11:00:00Z"), MANAGER), 201)
    created = validate_success(api.create_service_session(create_service_session_payload(
        site["id"], cycle["id"], service_date="2026-03-02", meal_period="LUNCH",
        window_start="2026-03-02T11:30:00Z", window_end="2026-03-02T12:30:00Z"), MANAGER), 201)
    assert created["status"] == "PLANNED"


# ─── Corner: calculations — waste & satisfaction ────────────────────────────
def test_waste_event_charges_cost_and_depletes_lot(api):
    """PRD §3.5: "The event's `cost_cents` is the wasted quantity multiplied by that lot's
    `unit_cost_cents`. Logging waste decrements the lot's `qty_on_hand` by the wasted
    quantity, marks the lot `DEPLETED` if it reaches 0."

    Design: Corner/calculations/waste_event_depletes_lot_and_charges_cost
    """
    site = create_site()
    lot = stock_site(site["id"], "LETTUCE", 10, 200)
    waste = validate_success(api.create_waste_event(
        {"client_site_id": site["id"], "inventory_lot_id": lot["id"], "qty": 3, "reason": "SPOILAGE"},
        MANAGER), 201)
    assert waste["cost_cents"] == 600
    assert get_lot(lot["id"])["qty_on_hand"] == 7


def test_satisfaction_avg_rounds_two_places(api):
    """PRD §3.8: "Submitting a survey recomputes the site's `satisfaction_avg` as the mean of
    all ratings on that site's surveys, to two decimal places with round half up (null when
    the site has none)."

    Design: Corner/calculations/satisfaction_avg_rounds_two_places
    """
    ctx = setup_session()
    site = ctx["site"]
    session_id = ctx["session"]["id"]
    validate_success(api.create_satisfaction_survey(
        create_satisfaction_survey_payload(site["id"], 5, service_session_id=session_id),
        make_diner_headers("diner-1")), 201)
    validate_success(api.create_satisfaction_survey(
        create_satisfaction_survey_payload(site["id"], 4, service_session_id=session_id),
        make_diner_headers("diner-2")), 201)
    site_after = get_site(site["id"])
    assert site_after["satisfaction_avg"] == 4.5
