"""Inventory receipt/depletion, production forecast, prepare, and cancel/restore."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_site, create_food_items, receive_lot, receive_inventory,
    create_approved_lunch_menu, create_planned_production, create_prepared_production,
    setup_prepared_lunch_site, create_funded_student, record_reimbursable_lunch,
    TEST_USERS,
)

CAFETERIA = TEST_USERS["cafeteria_manager_headers"]


# ==========================================================================
# Transitive cascade: prepare -> lot on-hand 0 -> lot DEPLETED
# ==========================================================================
class TestPrepareDepletionCascade:
    def _prepare_100_against_100_unit_entree_lot(self, api):
        site = create_site(api)
        food_ids = create_food_items(api)
        lot_ent = receive_lot(api, site["id"], food_ids["ent"], quantity_received=100)
        for key in ("grn", "fru", "milk"):
            receive_lot(api, site["id"], food_ids[key], quantity_received=1000)
        mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
        create_prepared_production(api, site["id"], mc_id, planned_qty=100, prepared_qty=100)
        return lot_ent["id"]

    def test_entree_lot_on_hand_hits_zero_after_prepare(self, api):
        """PRD §3.4: "Each lot's `quantity_on_hand` is decremented until the required units are satisfied, and any lot reaching 0 flips to `DEPLETED`."
        PRD §3.4: "For each menu component, the required units equal `prepared_qty` multiplied by that component's `serving_amount`."

        Design: Difficulty/transitive_cascade/prepare_depletion_cascade_to_lot_depleted
        """
        lot_id = self._prepare_100_against_100_unit_entree_lot(api)
        lot = validate_success(api.get_inventory_lot(lot_id, CAFETERIA), 200)
        assert lot["quantity_on_hand"] == 0, f"expected 0 on-hand, got {lot['quantity_on_hand']}"

    def test_entree_lot_flips_to_depleted_after_prepare(self, api):
        """PRD §3.4: "Each lot's `quantity_on_hand` is decremented until the required units are satisfied, and any lot reaching 0 flips to `DEPLETED`."

        Design: Difficulty/transitive_cascade/prepare_depletion_cascade_to_lot_depleted
        """
        lot_id = self._prepare_100_against_100_unit_entree_lot(api)
        lot = validate_success(api.get_inventory_lot(lot_id, CAFETERIA), 200)
        assert lot["status"] == "DEPLETED", f"expected DEPLETED, got {lot['status']}"


# ==========================================================================
# Compensating invariant: prepare then cancel conserves inventory units
# ==========================================================================
class TestInventoryConservation:
    def _prepare_then_cancel(self, api):
        site = create_site(api)
        food_ids = create_food_items(api)
        lot_ent = receive_lot(api, site["id"], food_ids["ent"], quantity_received=100)
        for key in ("grn", "fru", "milk"):
            receive_lot(api, site["id"], food_ids[key], quantity_received=1000)
        mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
        pr = create_prepared_production(api, site["id"], mc_id, planned_qty=100, prepared_qty=100)
        cancel_resp = api.cancel_production_record(pr["id"], CAFETERIA)
        return lot_ent["id"], pr["id"], cancel_resp

    def test_cancel_from_prepared_restores_exact_units_and_availability(self, api):
        """PRD §3.4: "when it does cancel, the system runs the compensating restoration, returning the exact per-lot amounts that were drawn back to the exact lots they came from, so each affected lot's `quantity_on_hand` increases and any lot that was `DEPLETED` flips back to `AVAILABLE`."

        Design: Difficulty/compensating_invariant/inventory_units_conserved_across_prepare_and_cancel
        """
        lot_id, _pr_id, _cancel = self._prepare_then_cancel(api)
        lot = validate_success(api.get_inventory_lot(lot_id, CAFETERIA), 200)
        assert lot["quantity_on_hand"] == 100, f"expected restored on-hand 100, got {lot['quantity_on_hand']}"
        assert lot["status"] == "AVAILABLE", f"restored lot must be AVAILABLE, got {lot['status']}"

    def test_cancel_from_prepared_moves_record_to_cancelled(self, api):
        """PRD §3.4: "Cancelling a record moves it to the terminal `CANCELLED` status."

        Design: Difficulty/compensating_invariant/inventory_units_conserved_across_prepare_and_cancel
        """
        _lot_id, _pr_id, cancel_resp = self._prepare_then_cancel(api)
        data = validate_success(cancel_resp, 200)
        assert data["status"] == "CANCELLED", f"expected CANCELLED, got {data['status']}"


# ==========================================================================
# Dual-variant calc: forecast_par (projection) vs served_qty (actual)
# ==========================================================================
class TestForecastVersusServed:
    def test_forecast_par_is_planned_times_participation_factor(self, api):
        """PRD §3.4: "At creation the system computes the **forecast par**: `forecast_par_qty` is the forward-looking projection equal to `planned_qty` multiplied by the participation factor of 0.9, rounded half-up to a whole number of portions."

        Design: Difficulty/dual_variant_calc/forecast_par_vs_served_on_production_record
        """
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"negative_balance_allowed": True}, planned_qty=100)
        pr = validate_success(api.get_production_record(scenario["pr_id"], CAFETERIA), 200)
        assert pr["forecast_par_qty"] == 90, f"round(100*0.9)=90, got {pr['forecast_par_qty']}"

    def test_served_qty_counts_meals_and_diverges_from_forecast(self, api):
        """PRD §3.4: "Distinct from it, `served_qty` is the chronological actual — a running count of the non-voided meal transactions linked to this record — and `leftover_qty` is `prepared_qty` minus `served_qty`, never allowed below zero and reported as 0 while the record is still `PLANNED`."

        Design: Difficulty/dual_variant_calc/forecast_par_vs_served_on_production_record
        """
        scenario = setup_prepared_lunch_site(
            api, site_overrides={"negative_balance_allowed": True}, planned_qty=100)
        student = create_funded_student(api, scenario["site_id"], eligibility_category="PAID")
        record_reimbursable_lunch(api, scenario, student["id"])

        pr = validate_success(api.get_production_record(scenario["pr_id"], CAFETERIA), 200)
        assert pr["served_qty"] == 1, f"one recorded meal -> served_qty 1, got {pr['served_qty']}"
        assert pr["forecast_par_qty"] == 90
        assert pr["forecast_par_qty"] != pr["served_qty"], "projection and actual must diverge"


# ==========================================================================
# Corner: inventory & production breadth claims
# ==========================================================================
def test_depletion_draws_commodity_before_purchased(api):
    """PRD §3.4: "Those units are drawn from the site's inventory lots matching the component's `food_item_id`, in this exact order: all `COMMODITY_USDA_FOODS` lots before any `PURCHASED` lot; then by ascending `received_date`; then by ascending `created_at` (never by `id`)."

    Design: Corner/calculations/inventory_depletion_draws_commodity_before_purchased
    """
    site = create_site(api)
    food_ids = create_food_items(api)
    lot_comm = receive_lot(api, site["id"], food_ids["ent"], lot_type="COMMODITY_USDA_FOODS",
                           quantity_received=30, received_date="2026-03-05")
    lot_purch = receive_lot(api, site["id"], food_ids["ent"], lot_type="PURCHASED",
                            quantity_received=30, received_date="2026-03-06")
    for key in ("grn", "fru", "milk"):
        receive_lot(api, site["id"], food_ids[key], quantity_received=1000)
    mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
    create_prepared_production(api, site["id"], mc_id, planned_qty=40, prepared_qty=40)

    comm = validate_success(api.get_inventory_lot(lot_comm["id"], CAFETERIA), 200)
    purch = validate_success(api.get_inventory_lot(lot_purch["id"], CAFETERIA), 200)
    assert comm["quantity_on_hand"] == 0, "commodity lot drawn first to 0"
    assert comm["status"] == "DEPLETED"
    assert purch["quantity_on_hand"] == 20, "purchased lot supplies the remaining 10 (30-10=20)"


def test_prepare_insufficient_inventory_rejected(api):
    """PRD §3.4: "If the total on-hand across all eligible lots for a component is less than the required units, the preparation is refused with `ERR_INSUFFICIENT_INVENTORY` (409) and no lot is partially depleted."

    Design: Corner/validations/prepare_insufficient_inventory_rejected
    """
    site = create_site(api)
    food_ids = create_food_items(api)
    receive_lot(api, site["id"], food_ids["ent"], quantity_received=10)
    for key in ("grn", "fru", "milk"):
        receive_lot(api, site["id"], food_ids[key], quantity_received=1000)
    mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
    pr = create_planned_production(api, site["id"], mc_id, planned_qty=100)

    resp = api.prepare_production_record(pr["id"], CAFETERIA, {"prepared_qty": 100})
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_duplicate_production_same_day_rejected(api):
    """PRD §3.4: "at most one production record may exist per site, service date, and meal type, a second being refused with `ERR_PRODUCTION_ALREADY_EXISTS` (409)."

    Design: Corner/validations/duplicate_production_same_day_rejected
    """
    site = create_site(api)
    food_ids = create_food_items(api)
    mc_id = create_approved_lunch_menu(api, site["id"], food_ids)
    create_planned_production(api, site["id"], mc_id, service_date="2026-04-15",
                              meal_type="LUNCH", planned_qty=100)

    resp = api.create_production_record(
        {"site_id": site["id"], "menu_cycle_id": mc_id, "service_date": "2026-04-15",
         "meal_type": "LUNCH", "planned_qty": 80}, CAFETERIA)
    validate_error(resp, ApiErrorId.ERR_PRODUCTION_ALREADY_EXISTS.value)
