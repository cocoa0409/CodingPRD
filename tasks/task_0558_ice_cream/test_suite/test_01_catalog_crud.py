"""Catalog creation, computed fields, defaults, not-found and schema validation.

Each test docstring cites the verbatim PRD sentence it asserts and ends with a
Design: traceability tag mapping it to its originating design-index instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_flavor, assert_order_line, assert_pre_order,
    create_flavor_payload, create_pre_order_payload,
    make_flavor, make_size, make_topping, make_batch, make_station,
    open_drawer, open_order, add_line, pay, make_pre_order,
    get_order, get_pre_order, get_order_line,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
SCOOP = TEST_USERS["scooper_headers"]
BAKER = TEST_USERS["baker_headers"]
LEAD = TEST_USERS["shift_lead_headers"]


def test_create_flavor_success_envelope_system_fields(api):
    """PRD 2.4: "Every persisted resource carries a server-minted `id` formatted
    as a UUID with no type prefix; the `id` is identity only and is never supplied
    by the client."
    PRD 2.4: "`version`: an integer that begins at creation and increments by one
    on every mutation of the resource."
    PRD 3.1: "On creation, before any batch exists, a flavor's computed
    `total_available_ml` is zero and its `stock_status` is therefore `OUT_OF_STOCK`."

    Design: Corner/entities/create_flavor_success_envelope_system_fields
    """
    res = api.create_flavor(create_flavor_payload(name="Vanilla"), MGR)
    flavor = validate_success(res, 201)
    assert_flavor(flavor)
    assert flavor["version"] == 1, f"new resource version must be 1, got {flavor['version']}"
    assert flavor["stock_status"] == "OUT_OF_STOCK"
    assert flavor["total_available_ml"] == 0


def test_order_line_quantity_defaults_to_one(api):
    """PRD 3.3: "an optional `quantity` of identical units defaulting to one. The
    line's computed `scoops` is the size option's `scoop_count` multiplied by
    `quantity`."

    Design: Corner/entities/order_line_quantity_defaults_to_one
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"])
    assert line["quantity"] == 1
    assert line["scoops"] == 2


def test_orderline_allergen_label_is_union_of_flavor_and_toppings(api):
    """PRD 3.3: "The line also computes an `allergen_label`, the union of the
    flavor's `allergens` and the `allergens` of every applied topping."

    Design: Corner/entities/orderline_allergen_label_is_union_of_flavor_and_toppings
    """
    flavor = make_flavor(name="Pistachio", allergens=["MILK", "NUTS", "PISTACHIO"],
                         standard_cost_cents_per_ml=2.20, par_level_ml=300)
    size = make_size(code="DOUBLE", scoop_count=2, base_price_cents=550)
    topping = make_topping(name="Hot Fudge", price_cents=100, allergens=["MILK", "SOY"])
    make_batch(flavor["id"], initial_volume_ml=500, unit_cost_cents_per_ml=2.20)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    line = add_line(order["id"], size["id"], flavor["id"], topping_ids=[topping["id"]])
    label = set(line["allergen_label"])
    assert label == {"MILK", "NUTS", "PISTACHIO", "SOY"}, f"got {label}"
    assert len(line["allergen_label"]) == 4


def test_preorder_deposit_computed_on_confirm(api):
    """PRD 3.6: "`deposit_cents` is set to `quoted_price_cents` multiplied by the
    deposit fraction of 0.20 (twenty percent), rounded half up to whole cents."

    Design: Corner/entities/preorder_deposit_computed_on_confirm
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    pre_order = make_pre_order(flavor["id"], station["id"], quoted_price_cents=4000)
    confirmed = validate_success(api.confirm_pre_order(pre_order["id"], SCOOP), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["deposit_cents"] == 800


def test_order_change_cents_computed_on_cash_pay(api):
    """PRD 3.4: "On a cash payment the order records `tendered_cash_cents` and a
    `change_cents` equal to `tendered_cash_cents` minus `total_cents`."
    PRD 3.4: "At payment the ticket also records `cash_collected_cents` — equal to
    `total_cents` when paid `CASH` and zero when paid `CARD`".

    Design: Corner/entities/order_change_cents_computed_on_cash_pay
    """
    flavor = make_flavor(par_level_ml=500)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    add_line(order["id"], size["id"], flavor["id"])
    paid = validate_success(
        api.pay_order(order["id"], {"payment_method": "CASH", "tendered_cash_cents": 400}, SCOOP), 200)
    assert paid["total_cents"] == 381
    assert paid["change_cents"] == 19
    assert paid["payment_method"] == "CASH"
    assert paid["cash_collected_cents"] == 381


# ─────────────────── Not-found family (existence, priority 3) ───────────────────

def test_flavor_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as `ERR_FLAVOR_NOT_FOUND`, `ERR_SIZE_OPTION_NOT_FOUND`,
    `ERR_TOPPING_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_WASTE_EVENT_NOT_FOUND`,
    `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, `ERR_DRAWER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ORDER_LINE_NOT_FOUND`, `ERR_PREORDER_NOT_FOUND`, `ERR_EVENT_CART_NOT_FOUND`,
    `ERR_DECORATING_STATION_NOT_FOUND`, or `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/flavor_not_found_on_get
    """
    validate_error(api.get_flavor(NON_EXISTENT_UUID, MGR), "ERR_FLAVOR_NOT_FOUND")


def test_order_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as `ERR_FLAVOR_NOT_FOUND`, ... `ERR_ORDER_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/order_not_found_on_get
    """
    validate_error(api.get_order(NON_EXISTENT_UUID, SCOOP), "ERR_ORDER_NOT_FOUND")


def test_batch_not_found_on_release(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_BATCH_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/batch_not_found_on_release
    """
    validate_error(api.release_batch(NON_EXISTENT_UUID, BAKER), "ERR_BATCH_NOT_FOUND")


def test_drawer_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_DRAWER_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/drawer_not_found_on_get
    """
    validate_error(api.get_drawer(NON_EXISTENT_UUID, LEAD), "ERR_DRAWER_NOT_FOUND")


def test_preorder_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_PREORDER_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/preorder_not_found_on_get
    """
    validate_error(api.get_pre_order(NON_EXISTENT_UUID, MGR), "ERR_PREORDER_NOT_FOUND")


def test_catering_booking_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... or `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/catering_booking_not_found_on_get
    """
    validate_error(api.get_catering_booking(NON_EXISTENT_UUID, MGR), "ERR_CATERING_BOOKING_NOT_FOUND")


def test_waste_event_not_found_on_get(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_WASTE_EVENT_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/waste_event_not_found_on_get
    """
    validate_error(api.get_waste_event(NON_EXISTENT_UUID, BAKER), "ERR_WASTE_EVENT_NOT_FOUND")


def test_size_option_not_found_on_line_add(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_SIZE_OPTION_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/size_option_not_found_on_line_add
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    res = api.add_line(order["id"], {"size_option_id": NON_EXISTENT_UUID, "flavor_id": flavor["id"]}, SCOOP)
    validate_error(res, "ERR_SIZE_OPTION_NOT_FOUND")


def test_topping_not_found_on_line_add(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_TOPPING_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/topping_not_found_on_line_add
    """
    flavor = make_flavor(par_level_ml=300)
    size = make_size(code="SINGLE", scoop_count=1, base_price_cents=350)
    make_batch(flavor["id"], initial_volume_ml=500)
    drawer = open_drawer()
    order = open_order(drawer["id"])
    res = api.add_line(order["id"],
                       {"size_option_id": size["id"], "flavor_id": flavor["id"],
                        "topping_ids": [NON_EXISTENT_UUID]}, SCOOP)
    validate_error(res, "ERR_TOPPING_NOT_FOUND")


def test_loyalty_account_not_found_on_order_open(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_LOYALTY_ACCOUNT_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/loyalty_account_not_found_on_order_open
    """
    drawer = open_drawer()
    res = api.create_order({"drawer_id": drawer["id"], "loyalty_account_id": NON_EXISTENT_UUID}, SCOOP)
    validate_error(res, "ERR_LOYALTY_ACCOUNT_NOT_FOUND")


def test_order_line_not_found_on_delete(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_ORDER_LINE_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/order_line_not_found_on_delete
    """
    drawer = open_drawer()
    order = open_order(drawer["id"])
    validate_error(api.remove_line(order["id"], NON_EXISTENT_UUID, SCOOP), "ERR_ORDER_LINE_NOT_FOUND")


def test_event_cart_not_found_on_booking(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_EVENT_CART_NOT_FOUND`, ... or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/event_cart_not_found_on_booking
    """
    flavor = make_flavor(par_level_ml=300)
    make_batch(flavor["id"], initial_volume_ml=500, expiry_at="2026-05-30T00:00:00Z")
    res = api.create_catering_booking(
        {"event_cart_id": NON_EXISTENT_UUID, "event_start_utc": "2026-05-02T10:00:00Z",
         "event_end_utc": "2026-05-02T12:00:00Z",
         "requested_items": [{"flavor_id": flavor["id"], "volume_ml": 100}]}, MGR)
    validate_error(res, "ERR_EVENT_CART_NOT_FOUND")


def test_decorating_station_not_found_on_preorder(api):
    """PRD 2.8: "The first unresolved identifier yields its specific not-found
    error (404), such as ... `ERR_DECORATING_STATION_NOT_FOUND`, or
    `ERR_CATERING_BOOKING_NOT_FOUND`."

    Design: Corner/entities/decorating_station_not_found_on_preorder
    """
    flavor = make_flavor(par_level_ml=300)
    res = api.create_pre_order(
        create_pre_order_payload(flavor["id"], NON_EXISTENT_UUID), SCOOP)
    validate_error(res, "ERR_DECORATING_STATION_NOT_FOUND")


def test_missing_required_field_on_flavor_create(api):
    """PRD 2.8: "Schema validity — required fields present, types and enum values
    correct, quantities and volumes strictly positive where required; a malformed
    body yields `ERR_VALIDATION` (422)".
    PRD 3.1: "A **Flavor** is created with a display `name` (unique among flavors)".

    Design: Corner/entities/missing_required_field_on_flavor_create
    """
    res = api.create_flavor({"standard_cost_cents_per_ml": 1.80, "par_level_ml": 500}, MGR)
    validate_error(res, "ERR_VALIDATION")


def test_invalid_time_window_on_preorder_create(api):
    """PRD 2.5: "For any window whose end is required to be strictly after its
    start, an end at or before the start is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/entities/invalid_time_window_on_preorder_create
    """
    flavor = make_flavor(par_level_ml=300)
    station = make_station()
    res = api.create_pre_order(
        create_pre_order_payload(flavor["id"], station["id"],
                                 decorate_start_utc="2026-05-03T12:00:00Z",
                                 decorate_end_utc="2026-05-03T10:00:00Z"), SCOOP)
    validate_error(res, "ERR_INVALID_TIME_WINDOW")
