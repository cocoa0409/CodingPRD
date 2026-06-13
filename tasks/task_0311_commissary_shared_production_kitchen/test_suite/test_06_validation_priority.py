"""Validation-priority conflicts and the order-receipt restock cascade.

Translates difficulty queue instances:
  priority_pair_validation_conflict / booking_state_vs_fiscal_member_not_active_wins
  priority_pair_validation_conflict / storage_safety_vs_fiscal_unit_quarantined_wins
  transitive_cascade / order_receive_restocks_then_enables_batch_start
and corner queue instances for stock-block guard and order-receipt
reconciliation (on_hand_qty + unit_cost_cents).
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_member, create_ingredient,
    create_published_recipe, create_planned_batch, create_storage_unit,
)

FM = TEST_USERS["facility_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ── Difficulty: priority_pair_validation_conflict / booking_state_vs_fiscal_member_not_active_wins ──

def test_suspended_member_zero_wallet_booking_reports_member_not_active(api):
    """PRD 2.11: "then the acting member being ACTIVE for member-scoped creates
    (ERR_MEMBER_NOT_ACTIVE). After these, the domain-specific business rules
    described throughout 3 apply ... and finally wallet sufficiency." The member
    state check (ERR_MEMBER_NOT_ACTIVE) is evaluated before the wallet check, so a
    SUSPENDED member with a zero wallet booking returns ERR_MEMBER_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/booking_state_vs_fiscal_member_not_active_wins
    """
    member = register_member(business_name="M9")
    mo = make_member_operator_headers(member["id"])
    station = validate_success(api.create_station({"name": "Prep9", "station_class": "PREP_TABLE"}, FM), 201)
    suspended = validate_success(api.suspend_member(member["id"], {"expected_member_version": member["version"]}, FM), 200)
    res = api.create_booking(member["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-04T12:00:00.000Z",
        "end_utc": "2026-07-04T13:00:00.000Z",
        "expected_member_version": suspended["version"],
    }, mo)
    validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


def test_suspended_member_cannot_book_even_with_funds(api):
    """PRD 3.1: "while suspended or closed, the member may not create bookings,
    batches, storage assignments, ingredient orders, or packouts, and any such
    attempt is rejected with ERR_MEMBER_NOT_ACTIVE." A suspended member is frozen
    out of booking regardless of wallet.

    Design: Difficulty/priority_pair_validation_conflict/booking_state_vs_fiscal_member_not_active_wins
    """
    member = register_member(business_name="M9b")
    mo = make_member_operator_headers(member["id"])
    # Fund the wallet so the only failing condition is the suspended state.
    topped = validate_success(api.top_up_wallet(member["id"], {"amount_cents": 100000}, mo), 201)
    station = validate_success(api.create_station({"name": "Prep9b", "station_class": "PREP_TABLE"}, FM), 201)
    suspended = validate_success(api.suspend_member(member["id"], {"expected_member_version": topped["version"]}, FM), 200)
    res = api.create_booking(member["id"], {
        "station_id": station["id"],
        "start_utc": "2026-07-04T12:00:00.000Z",
        "end_utc": "2026-07-04T13:00:00.000Z",
        "expected_member_version": suspended["version"],
    }, mo)
    validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


# ── Difficulty: priority_pair_validation_conflict / storage_safety_vs_fiscal_unit_quarantined_wins ──

def test_quarantined_and_overcapacity_request_reports_unit_quarantined(api):
    """PRD 2.11: "the domain-specific business rules described throughout 3 apply
    — quarantine blocks, allergen conflicts, interval validity, peak-tier gating,
    booking overlap, station availability, recipe-publication state, stock
    sufficiency, batch-completion-for-packout, recipe-in-use, open-obligation
    blocks, storage-capacity sufficiency, and finally wallet sufficiency." The
    quarantine block precedes the storage-capacity check, so a request against a
    quarantined unit that also exceeds capacity returns ERR_UNIT_QUARANTINED.

    Design: Difficulty/priority_pair_validation_conflict/storage_safety_vs_fiscal_unit_quarantined_wins
    """
    member = register_member(business_name="M10")
    mo = make_member_operator_headers(member["id"])
    cold = create_storage_unit(name="Cold2", temp_class="COLD", total_slots=2,
                               temp_min_c=0.0, temp_max_c=4.0)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-05T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-05T12:01:00.000Z"}, CO)
    quarantined = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert quarantined["compliance_status"] == "QUARANTINED"
    # Request 5 slots (also exceeds the 2-slot capacity) against the quarantined unit.
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "COLD", "requested_slots": 5, "expected_member_version": member["version"],
    }, mo)
    validate_error(res, "ERR_UNIT_QUARANTINED")


def test_quarantined_unit_blocks_assignment_even_with_capacity(api):
    """PRD 3.9: "Independently, if any same-class unit that the waterfall plan
    would touch is itself QUARANTINED, the create is refused with
    ERR_UNIT_QUARANTINED." When the requested slots would fit the unit's capacity
    (2 of 2) but the unit is quarantined, the quarantine block still fires rather
    than the capacity error never being reached.

    Design: Difficulty/priority_pair_validation_conflict/storage_safety_vs_fiscal_unit_quarantined_wins
    """
    member = register_member(business_name="M10b")
    mo = make_member_operator_headers(member["id"])
    cold = create_storage_unit(name="Cold2b", temp_class="COLD", total_slots=2,
                               temp_min_c=0.0, temp_max_c=4.0)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-05T10:00:00.000Z"}, CO)
    api.create_temp_log(cold["id"], {"reading_c": 9.0, "reading_utc": "2026-07-05T12:01:00.000Z"}, CO)
    quarantined = validate_success(api.get_storage_unit(cold["id"], FM), 200)
    assert quarantined["compliance_status"] == "QUARANTINED"
    res = api.create_storage_assignment(member["id"], {
        "temp_class": "COLD", "requested_slots": 2, "expected_member_version": member["version"],
    }, mo)
    validate_error(res, "ERR_UNIT_QUARANTINED")


# ── Difficulty: transitive_cascade / order_receive_restocks_then_enables_batch_start ──

def test_order_receipt_restocks_and_enables_batch_start(api):
    """PRD 3.7: "receipt increments the ingredient's on_hand_qty by the order_qty".
    PRD 3.6: "Starting a batch ... is permitted only when the batch is currently
    PLANNED (otherwise ERR_INVALID_STATE) and only when there is enough stock on
    hand". An order receipt raises on_hand_qty to 5, which then lets the
    stock-blocked batch start IN_PRODUCTION.

    Design: Difficulty/transitive_cascade/order_receive_restocks_then_enables_batch_start
    """
    member = register_member(business_name="M8")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Butter", unit_cost_cents=500)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 5.0)], name="R8")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=10)
    # Place + receive an order for exactly the scaled demand (5 base units).
    order = validate_success(api.create_ingredient_order(member["id"], {
        "ingredient_id": ing["id"], "order_qty": 5, "unit_cost_cents": 500,
    }, mo), 201)
    validate_success(api.receive_ingredient_order(member["id"], order["id"], mo), 200)

    ingredient_after = validate_success(api.get_ingredient(ing["id"], FM), 200)
    assert ingredient_after["on_hand_qty"] == 5, f"got {ingredient_after['on_hand_qty']}"

    started = validate_success(api.start_batch(member["id"], batch["id"], mo), 200)
    assert started["status"] == "IN_PRODUCTION"


def test_batch_start_before_restock_blocked_by_stock(api):
    """PRD 3.6: "If any ingredient falls short of its scaled demand, the start is
    rejected with ERR_INSUFFICIENT_STOCK." Before any order is received, the
    batch cannot start because on_hand_qty is 0 against a scaled demand of 5.

    Design: Difficulty/transitive_cascade/order_receive_restocks_then_enables_batch_start
    """
    member = register_member(business_name="M8b")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Butter2", unit_cost_cents=500)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 5.0)], name="R8b")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=10)
    res = api.start_batch(member["id"], batch["id"], mo)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")


# ── Corner: state_machines / batch_start_below_stock_returns_insufficient_stock ──

def test_batch_start_below_stock_keeps_batch_planned(api):
    """PRD 3.6: "If any ingredient falls short of its scaled demand, the start is
    rejected with ERR_INSUFFICIENT_STOCK." The batch remains PLANNED after the
    rejected start.

    Design: Corner/state_machines/batch_start_below_stock_returns_insufficient_stock
    """
    member = register_member(business_name="St")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="StIng", unit_cost_cents=100)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 5.0)], name="StR")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=10)
    res = api.start_batch(member["id"], batch["id"], mo)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
    still = validate_success(api.get_member_batch(member["id"], batch["id"], mo), 200)
    assert still["status"] == "PLANNED"


# ── Corner: state_machines / order_receive_bubbles_stock_and_cost ──

def test_order_receipt_updates_stock_and_cost(api):
    """PRD 3.7: "receipt increments the ingredient's on_hand_qty by the order_qty
    and sets the ingredient's unit_cost_cents to the order's unit_cost_cents".
    After receiving qty 40 at cost 150, both fields reflect the new values.

    Design: Corner/state_machines/order_receive_bubbles_stock_and_cost
    """
    member = register_member(business_name="Rc")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="RcIng", unit_cost_cents=100)
    order = validate_success(api.create_ingredient_order(member["id"], {
        "ingredient_id": ing["id"], "order_qty": 40, "unit_cost_cents": 150,
    }, mo), 201)
    validate_success(api.receive_ingredient_order(member["id"], order["id"], mo), 200)
    ingredient_after = validate_success(api.get_ingredient(ing["id"], FM), 200)
    assert ingredient_after["on_hand_qty"] == 40
    assert ingredient_after["unit_cost_cents"] == 150


# ── Corner: cross_cutting / ingredient_cost_reconciled_after_order_receipt ──

def test_ingredient_cost_reconciled_after_receipt(api):
    """PRD 3.7: "receipt increments the ingredient's on_hand_qty by the order_qty
    and sets the ingredient's unit_cost_cents to the order's unit_cost_cents,
    which is exactly how a later batch can complete against a different cost than
    its estimate assumed." After receiving qty 25 at cost 175, both reconcile.

    Design: Corner/cross_cutting_complexity_layers/ingredient_cost_reconciled_after_order_receipt
    """
    member = register_member(business_name="Dr")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="DrIng", unit_cost_cents=100)
    order = validate_success(api.create_ingredient_order(member["id"], {
        "ingredient_id": ing["id"], "order_qty": 25, "unit_cost_cents": 175,
    }, mo), 201)
    validate_success(api.receive_ingredient_order(member["id"], order["id"], mo), 200)
    ingredient_after = validate_success(api.get_ingredient(ing["id"], FM), 200)
    assert ingredient_after["on_hand_qty"] == 25
    assert ingredient_after["unit_cost_cents"] == 175
