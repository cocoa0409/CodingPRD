"""Inventory disposition fork & donation credit, product markup rounding, and
the compensating product-cost invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    new_active_project, new_inventory_item, schedule_item, confirm_item,
    new_product_line, setup_scheduled_donation_item,
    make_organizer_headers, TEST_USERS,
)

OM = TEST_USERS["operations_manager_headers"]


# ── Difficulty: donation provisional vs final credit ──────────────────────────

def test_donation_final_credit_recorded_on_confirmation(api):
    """PRD §3.5: "On donation confirmation the system stores final_value_cents and
    computes the final donation credit as final_value_cents multiplied by the same
    10% donation credit rate, rounded half up; this final credit is added to the
    project's donation_credit_cents ledger and is the amount that reduces the
    invoice."

    Design: Difficulty/dual_variant_calc/donation_provisional_vs_final_credit
    """
    client, organizer, project, item = setup_scheduled_donation_item(estimated_value_cents=10000)
    assert item["status"] == "SCHEDULED_DONATION"
    confirmed = validate_success(api.confirm_inventory_item(
        item["id"], {"final_value_cents": 8000}, make_organizer_headers(organizer["id"])), 200)
    assert confirmed["status"] == "DONATED"
    assert confirmed["final_value_cents"] == 8000
    assert confirmed["haul_fee_cents"] == 0

    project_after = validate_success(api.get_project(project["id"], OM), 200)
    # Final credit = round_half_up(8000 * 0.10) = 800.
    assert project_after["donation_credit_cents"] == 800


def test_provisional_donation_value_not_added_to_project_ledger(api):
    """PRD §3.5: "For an item whose disposition is DONATE, scheduling advances it to
    SCHEDULED_DONATION (any other disposition here is again ERR_DISPOSITION_MISMATCH);
    no haul fee applies, and a provisional donation value is computed as the item's
    estimated_value_cents multiplied by the 10% donation credit rate, rounded half up."
    PRD §3.5: "This provisional credit is for planning only and is not added to the
    project's donation_credit_cents ledger or to any invoice."

    Design: Difficulty/dual_variant_calc/donation_provisional_vs_final_credit
    """
    client, organizer, project, item = setup_scheduled_donation_item(estimated_value_cents=10000)
    assert item["status"] == "SCHEDULED_DONATION"
    project_after = validate_success(api.get_project(project["id"], OM), 200)
    # Provisional credit (1000) is planning-only; the ledger stays at 0 until DONATED.
    assert project_after["donation_credit_cents"] == 0


# ── Difficulty: disposition fork HAUL vs DONATE ───────────────────────────────

def test_haul_item_schedule_books_flat_haul_fee(api):
    """PRD §3.5: "For an item whose disposition is HAUL or SELL, scheduling advances
    it to SCHEDULED_HAUL ... Scheduling for hauling books a flat haul fee of 2,500
    cents ($25) into the item's haul_fee_cents and adds that fee to the project's
    projected_haul_cost_cents ledger."

    Design: Difficulty/non_linear_state_machine/inventory_disposition_branch_haul_vs_donate
    """
    client, organizer, project = new_active_project(scope_rooms=["Garage"])
    item = new_inventory_item(project["id"], organizer["id"], "HAUL", description="Broken chair")
    scheduled = schedule_item(item["id"], organizer["id"])
    assert scheduled["status"] == "SCHEDULED_HAUL"
    assert scheduled["haul_fee_cents"] == 2500

    project_after = validate_success(api.get_project(project["id"], OM), 200)
    assert project_after["projected_haul_cost_cents"] == 2500


def test_donate_item_schedule_charges_no_haul_fee(api):
    """PRD §3.5: "For an item whose disposition is DONATE, scheduling advances it to
    SCHEDULED_DONATION (any other disposition here is again ERR_DISPOSITION_MISMATCH);
    no haul fee applies, and a provisional donation value is computed as the item's
    estimated_value_cents multiplied by the 10% donation credit rate, rounded half up."

    Design: Difficulty/non_linear_state_machine/inventory_disposition_branch_haul_vs_donate
    """
    client, organizer, project = new_active_project(scope_rooms=["Garage"])
    item = new_inventory_item(project["id"], organizer["id"], "DONATE",
                              description="Books", estimated_value_cents=3000)
    scheduled = schedule_item(item["id"], organizer["id"])
    assert scheduled["status"] == "SCHEDULED_DONATION"
    assert scheduled["haul_fee_cents"] == 0


# ── Difficulty: product markup pinned rounding order (round per-unit, then multiply) ─

def test_product_client_price_rounds_per_unit_then_multiplies(api):
    """PRD §3.6: "first the per-unit marked price is computed as wholesale_cost_cents
    multiplied by one plus markup_pct and rounded half up to whole cents; then that
    rounded per-unit price is multiplied by quantity."

    Design: Difficulty/combinatorial_formula/product_markup_rounding_order_mode_b
    """
    client, organizer, project = new_active_project(scope_rooms=["Pantry"])
    line = new_product_line(project["id"], organizer["id"],
                            wholesale_cost_cents=1099, quantity=3, markup_pct=0.35)
    # round_half_up(1099 * 1.35) = round(1483.65) = 1484; 1484 * 3 = 4452.
    assert line["client_price_cents"] == 4452


def test_product_client_price_half_up_on_per_unit_only(api):
    """PRD §3.6: "first the per-unit marked price is computed as wholesale_cost_cents
    multiplied by one plus markup_pct and rounded half up to whole cents; then that
    rounded per-unit price is multiplied by quantity."

    Design: Difficulty/combinatorial_formula/product_markup_rounding_order_mode_b
    """
    client, organizer, project = new_active_project(scope_rooms=["Pantry"])
    line = new_product_line(project["id"], organizer["id"],
                            wholesale_cost_cents=101, quantity=4, markup_pct=0.5)
    # round_half_up(101 * 1.5) = round(151.5) = 152; 152 * 4 = 608
    # (multiply-then-round would give 606 — the pinned per-unit order yields 608).
    assert line["client_price_cents"] == 608


# ── Difficulty: compensating product-cost invariant on line cancel ────────────

def test_projected_product_cost_returns_to_zero_after_cancel(api):
    """PRD §3.6: "Cancelling a line is compensating: its client_price_cents is
    subtracted back out of the project's projected_product_cost_cents, keeping that
    ledger equal to the sum of client_price_cents over the project's QUOTED, ORDERED,
    and DELIVERED lines."
    PRD §3.6: "On creation the line's client_price_cents is added to the project's
    projected_product_cost_cents ledger."

    Design: Difficulty/compensating_invariant/product_cost_conserved_on_line_cancel
    """
    client, organizer, project = new_active_project(scope_rooms=["Den"])
    line = new_product_line(project["id"], organizer["id"],
                            wholesale_cost_cents=1099, quantity=3, markup_pct=0.35)
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["projected_product_cost_cents"] == 4452

    cancelled = validate_success(api.patch_product_line(
        line["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(api.get_project(project["id"], OM), 200)
    assert after["projected_product_cost_cents"] == 0


def test_projected_product_cost_equals_remaining_lines_after_cancel(api):
    """PRD §3.6: "Cancelling a line is compensating: its client_price_cents is
    subtracted back out of the project's projected_product_cost_cents, keeping that
    ledger equal to the sum of client_price_cents over the project's QUOTED, ORDERED,
    and DELIVERED lines."

    Design: Difficulty/compensating_invariant/product_cost_conserved_on_line_cancel
    """
    client, organizer, project = new_active_project(scope_rooms=["Den"])
    line1 = new_product_line(project["id"], organizer["id"],
                             wholesale_cost_cents=1099, quantity=3, markup_pct=0.35)  # 4452
    new_product_line(project["id"], organizer["id"],
                     wholesale_cost_cents=1000, quantity=1, markup_pct=0.0)  # 1000
    before = validate_success(api.get_project(project["id"], OM), 200)
    assert before["projected_product_cost_cents"] == 5452

    validate_success(api.patch_product_line(
        line1["id"], {"status": "CANCELLED"}, make_organizer_headers(organizer["id"])), 200)

    after = validate_success(api.get_project(project["id"], OM), 200)
    assert after["projected_product_cost_cents"] == 1000


# ── Corner: scheduling a KEPT item is an invalid transition ───────────────────

def test_schedule_kept_item_returns_invalid_item_transition(api):
    """PRD §3.5: "An item logged as KEEP is terminal immediately: it is created
    directly in KEPT status."
    PRD §3.5: "Any inventory transition the state machine does not allow from the
    item's current state is rejected with ERR_INVALID_ITEM_TRANSITION."

    Design: Corner/state_machines/schedule_kept_item_returns_invalid_item_transition
    """
    client, organizer, project = new_active_project(scope_rooms=["Room"])
    item = new_inventory_item(project["id"], organizer["id"], "KEEP", description="Keepsake")
    assert item["status"] == "KEPT"
    res = api.schedule_inventory_item(item["id"], make_organizer_headers(organizer["id"]))
    validate_error(res, "ERR_INVALID_ITEM_TRANSITION")
