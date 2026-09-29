"""Field-level fidelity of the catalogue and equipment rows.

These tests read the persisted representations straight back: what a create
returns, which optional inputs fall back to which declared default, which
client-supplied fields the server must ignore, and which rows are append-only
evidence with no version to bump. Pagination metadata and the entity-specific
404s belong to the same surface and are checked here too.
"""

import test_helpers as H
from test_helpers import factories as F
from test_helpers import fixtures as X

DEFAULT_CLOCK_PREFIX = "2026-08-01T00:00:00"


def test_registering_a_store_returns_the_whole_seeded_projection(api):
    """The create body carries every declared Store field, not just an id.

    "Endpoints that create a new resource respond with HTTP 201 and return the
    created resource." The seeded posture is fixed: "A freshly registered store
    opens in the `BREAKFAST` daypart with a `daypart_epoch` of 0, a
    `hot_case_slots_used` count of 0, a `waste_cost_cents_mtd` of 0 and a
    `rework_waste_cents_mtd` of 0." Both supplied capacities are echoed back
    alongside the audit envelope, where "`version`, an integer that starts at 1
    on creation and increments by exactly one on every mutation".

    Design: Corner/entities/create_store_returns_201_with_every_declared_field_seeded
    """
    response = api.create_store(F.store_payload(), H.CHAIN_ADMIN_HEADERS)

    store = H.get_success_data(response, 201)
    assert response.json()["response_type"] == "object"
    H.assert_store(
        store,
        {
            "store_code": "WAWA-0101",
            "name": "Wawa Route 1",
            "hot_case_slot_capacity": 4,
            "pickup_slot_capacity": 2,
            "is_fuel_site": True,
            "current_daypart": "BREAKFAST",
            "daypart_epoch": 0,
            "hot_case_slots_used": 0,
            "waste_cost_cents_mtd": 0,
            "rework_waste_cents_mtd": 0,
            "version": 1,
        },
    )
    assert H.is_valid_uuid(store["id"])
    assert H.is_iso8601_timestamp(store["created_at"])


def test_reading_a_holding_unit_reproduces_its_band_and_slot_count(api):
    """The stored safety band round-trips exactly, with a clean posture.

    A unit is described by "a safe holding band expressed as `min_temp_f` and
    `max_temp_f` in degrees Fahrenheit, and a `slot_count` of at least 1 giving
    the number of independently schedulable pan slots in the cabinet", and it
    starts untouched: "A new unit opens in the `OPERATIONAL` posture with a
    `consecutive_out_of_range_count` of 0 and a `last_temp_log_at` of null,
    since no probe reading has yet been taken against it."

    Design: Corner/entities/get_holding_unit_returns_the_stored_band_and_slot_count
    """
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=3)

    response = api.get_holding_unit(unit["id"], H.FOOD_SAFETY_LEAD_HEADERS)

    read_back = H.get_success_data(response, 200)
    H.assert_holding_unit(
        read_back,
        {
            "store_id": store["id"],
            "unit_code": "BC-1",
            "unit_type": "BAKERY_CASE",
            "min_temp_f": 135,
            "max_temp_f": 185,
            "slot_count": 3,
            "status": "OPERATIONAL",
            "consecutive_out_of_range_count": 0,
            "last_temp_log_at": None,
        },
    )


def test_holding_unit_pages_report_the_filtered_total_not_the_page_size(api):
    """Three units under a limit of 2 give 2 + 1 rows and one total of 3.

    "Every list response carries `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the size of
    the full filtered result set and `has_more` indicates whether records remain
    beyond the current page." The page order is fixed, since "Unless a specific
    endpoint states otherwise, list endpoints return their records sorted by
    `created_at` in ascending order", and "The `offset` parameter is the number
    of records to skip and defaults to 0."

    Design: Corner/entities/list_store_holding_units_pages_with_total_count_and_has_more
    """
    store = X.create_store(api)
    X.create_bakery_case(api, store["id"], unit_code="BC-1", slot_count=3)
    X.create_bakery_case(
        api, store["id"], unit_code="HC-1", unit_type="HOT_CASE",
        min_temp_f=140, max_temp_f=190, slot_count=2,
    )
    X.create_bakery_case(
        api, store["id"], unit_code="CC-1", unit_type="COLD_CASE",
        min_temp_f=33, max_temp_f=41, slot_count=4,
    )

    first_response = api.list_store_holding_units(
        store["id"], H.STORE_MANAGER_HEADERS, {"limit": 2, "offset": 0}
    )
    second_response = api.list_store_holding_units(
        store["id"], H.STORE_MANAGER_HEADERS, {"limit": 2, "offset": 2}
    )

    first_rows, first_meta = H.validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert first_rows[0]["unit_code"] == "BC-1"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_rows, second_meta = H.validate_paginated(second_response)
    assert second_response.json()["response_type"] == "array"
    assert len(second_rows) == 1
    assert second_rows[0]["unit_code"] == "CC-1"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2


def test_an_unknown_batch_id_reports_the_batch_specific_not_found(api):
    """The 404 names the entity the path segment failed to resolve.

    Path ids are resolved before anything else touches the domain: "The first
    identifier in the path that resolves to nothing produces its own 404" -
    and the catalogue of those 404s includes `ERR_PRODUCTION_BATCH_NOT_FOUND`
    for exactly this segment. The database holds no batch at all, so the read
    cannot fall back to an empty success body.

    Design: Corner/entities/get_production_batch_with_unknown_id_returns_batch_not_found
    """
    response = api.get_production_batch(H.NON_EXISTENT_UUID, H.KITCHEN_ASSOCIATE_HEADERS)

    H.validate_error(response, H.ApiErrorId.ERR_PRODUCTION_BATCH_NOT_FOUND.value, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"]


def test_a_menu_item_without_valid_dayparts_is_a_malformed_request(api):
    """The daypart list has no empty-array fallback, so omitting it is a defect.

    "The item also declares `valid_dayparts`, a non-empty subset of the four
    daypart names, restricting when it may be ordered." Body shape is checked at
    step 3 of the pipeline - "Request-body shape on write endpoints —
    `ERR_INVALID_REQUEST` (HTTP 400). This covers a missing required field" -
    and nothing may be persisted: the sku is still free afterwards, and a
    catalogue create carries "a chain-unique `sku` (a collision reports
    `ERR_DUPLICATE_CODE`)".

    Design: Corner/entities/create_menu_item_missing_required_valid_dayparts_is_rejected
    """
    response = api.create_menu_item(
        F.menu_item_payload(prep_seconds=None, valid_dayparts=None), H.CHAIN_ADMIN_HEADERS
    )

    H.validate_error(response, H.ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    retry = api.create_menu_item(
        F.menu_item_payload(valid_dayparts=["LUNCH"]), H.CHAIN_ADMIN_HEADERS
    )
    accepted = H.get_success_data(retry, 201)
    assert accepted["sku"] == "HOAGIE-ITAL"


def test_omitted_optional_inputs_land_on_their_declared_defaults(api):
    """Three defaults are probed at once, including the two that invert.

    A store create carries "optionally an `is_fuel_site` flag that defaults to
    true", while on the item "The `prep_seconds` field is the hands-on make time
    for one unit at its station and defaults to 0", "The `bake_minutes` field is
    the oven time for one production batch of the item and defaults to 0", "The
    `included_premium_count` field is the number of premium modifiers included
    with each unit before a surcharge applies and defaults to 0." and "Finally,
    `is_catering_eligible` defaults to false". On the option, "The `is_premium`
    flag defaults to false" and "The `max_qty` field defaults to 1, must be at
    least 1, and caps how many units of that option a single order line may
    take."

    Design: Corner/entities/optional_inputs_fall_back_to_the_declared_entity_defaults
    """
    store = H.get_success_data(
        api.create_store(F.store_payload(is_fuel_site=None), H.CHAIN_ADMIN_HEADERS), 201
    )
    item = H.get_success_data(
        api.create_menu_item(
            F.menu_item_payload(prep_seconds=None, valid_dayparts=["LUNCH"]),
            H.CHAIN_ADMIN_HEADERS,
        ),
        201,
    )
    option = H.get_success_data(
        api.create_modifier_option(
            item["id"],
            F.modifier_option_payload(price_delta_cents=60, is_premium=None, max_qty=None),
            H.CHAIN_ADMIN_HEADERS,
        ),
        201,
    )

    assert store["is_fuel_site"] is True
    assert item["prep_seconds"] == 0
    assert item["bake_minutes"] == 0
    assert item["hold_minutes"] == 0
    assert item["included_premium_count"] == 0
    assert item["is_catering_eligible"] is False
    assert option["is_premium"] is False
    assert option["max_qty"] == 1
    assert option["menu_item_id"] == item["id"]


def test_fuel_spend_rounds_the_half_cent_midpoint_upwards(api):
    """12.5 gallons at 329 cents is 4112.5, which must persist as 4113.

    "The system computes `fuel_spend_cents` as the gallons multiplied by the
    posted price per gallon, rounded half up to whole cents." The chain-wide
    convention is the same one - "round half up on the absolute value, to whole
    cents or whole integers" - so banker's rounding to 4112 and a float leak of
    4112.5 are both wrong. The row is evidence, not a resource: "Fuel
    transactions, like modifier options, are immutable evidence and carry no
    `updated_at` and no `version`; each one references its owner through
    `loyalty_account_id`."

    Design: Corner/entities/fuel_transaction_spend_cents_is_computed_from_gallons_and_posted_price
    """
    account = X.create_loyalty_account(api, member_code="WAWA-M-001")

    response = api.create_fuel_transaction(
        account["id"],
        F.fuel_transaction_payload(
            gallons=12.5, price_per_gallon_cents=329, occurred_at="2026-07-20T09:00:00Z"
        ),
        H.STORE_TERMINAL_HEADERS,
    )

    fuel = H.get_success_data(response, 201)
    assert fuel["fuel_spend_cents"] == 4113
    assert fuel["loyalty_account_id"] == account["id"]
    assert float(fuel["gallons"]) == 12.5
    assert fuel["occurred_at"].startswith("2026-07-20T09:00:00")
    H.assert_append_only_record(fuel, "FuelTransaction")

    rows, meta = H.validate_paginated(
        api.list_fuel_transactions(account["id"], H.STORE_TERMINAL_HEADERS)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == fuel["id"]


def test_client_supplied_system_fields_are_ignored_on_store_registration(api):
    """A payload that dictates daypart, epoch and slot usage changes nothing.

    The daypart is not client input: "A store's `current_daypart` is
    **operational state, not a derived read of the clock**. It begins at
    `BREAKFAST` when the store is registered and changes only through an
    explicit daypart-transition request issued by a `StoreManager`." The epoch
    is server-owned too - "Each accepted transition also increments the store's
    `daypart_epoch`, a monotonic counter that starts at 0" - as is the slot
    counter, seeded at "a `hot_case_slots_used` count of 0". The identity is
    minted server-side: "Every persisted resource carries a server-minted `id`,
    formatted as a UUID with no type prefix".

    Design: Corner/entities/store_system_fields_are_server_seeded_and_client_input_ignored
    """
    payload = F.store_payload(
        is_fuel_site=None, current_daypart="LUNCH", daypart_epoch=7, hot_case_slots_used=3
    )

    store = H.get_success_data(api.create_store(payload, H.CHAIN_ADMIN_HEADERS), 201)

    assert store["current_daypart"] == "BREAKFAST"
    assert store["daypart_epoch"] == 0
    assert store["hot_case_slots_used"] == 0
    assert store["version"] == 1
    assert H.is_valid_uuid(store["id"])
    assert X.read_store(api, store["id"])["current_daypart"] == "BREAKFAST"


def test_a_unit_type_outside_the_enum_is_refused_before_any_row_is_written(api):
    """FREEZER is not a cabinet this chain knows about.

    A holding unit declares "a `unit_type` of `HOT_CASE`, `COLD_CASE` or
    `BAKERY_CASE`", a closed set, and the body-shape step rejects anything else:
    "Request-body shape on write endpoints — `ERR_INVALID_REQUEST` (HTTP 400).
    This covers a missing required field, a wrong JSON type, an unrecognized
    enum member". The refusal must not store the value verbatim, so the store's
    unit list stays empty.

    Design: Corner/entities/create_holding_unit_with_unknown_unit_type_returns_invalid_request
    """
    store = X.create_store(api)

    response = api.create_holding_unit(
        store["id"],
        F.holding_unit_payload(
            unit_code="FZ-1", unit_type="FREEZER", min_temp_f=-10, max_temp_f=10, slot_count=2
        ),
        H.STORE_MANAGER_HEADERS,
    )

    H.validate_error(response, H.ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    rows, meta = H.validate_paginated(
        api.list_store_holding_units(store["id"], H.STORE_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_a_probe_reading_is_append_only_evidence_with_no_version(api):
    """The reading carries an author and a clock stamp, and nothing to bump.

    "An accepted reading is stored with its own `holding_unit_id`, a computed
    `in_range` flag, a `logged_by_user_id` set to the acting `X-User-ID` and a
    `recorded_at` set to the current logical-clock instant." 160 F sits inside
    the band, since "The `in_range` flag is true exactly when the `reading_f` is
    greater than or equal to the unit's `min_temp_f` and less than or equal to
    its `max_temp_f`", so the posture is untouched. The row is not a mutable
    resource: "Readings are immutable evidence: they carry no `updated_at` and no
    `version`", and no clock call has been made, so "Before any clock-setting
    call has been made, the clock reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/entities/temperature_log_is_immutable_with_no_update_endpoint_and_no_version
    """
    store = X.create_store(api)
    unit = X.create_bakery_case(api, store["id"], slot_count=3)

    response = api.create_temperature_log(
        unit["id"], F.temperature_log_payload(160), H.KITCHEN_ASSOCIATE_HEADERS
    )

    reading = H.get_success_data(response, 201)
    assert reading["in_range"] is True
    assert reading["logged_by_user_id"] == H.ASSOCIATE_1_USER_ID
    assert reading["holding_unit_id"] == unit["id"]
    assert reading["recorded_at"].startswith(DEFAULT_CLOCK_PREFIX)
    H.assert_append_only_record(reading, "TemperatureLog")

    after = X.read_holding_unit(api, unit["id"])
    assert after["status"] == "OPERATIONAL"
    assert after["consecutive_out_of_range_count"] == 0
    assert after["last_temp_log_at"] == reading["recorded_at"]


def test_a_modifier_option_cannot_be_hung_off_an_unknown_menu_item(api):
    """The parent segment must resolve before a catalogue leaf is written.

    "Each option belongs to its parent through `menu_item_id`", and the path
    parent is resolved at step 4, where "The first identifier in the path that
    resolves to nothing produces its own 404" and the entity-specific code for
    this segment is `ERR_MENU_ITEM_NOT_FOUND`. An orphan row keyed to a dangling
    foreign key is therefore impossible.

    Design: Corner/entities/create_modifier_option_under_unknown_menu_item_returns_menu_item_not_found
    """
    response = api.create_modifier_option(
        H.NON_EXISTENT_UUID,
        F.modifier_option_payload(price_delta_cents=60, is_premium=True, max_qty=2),
        H.CHAIN_ADMIN_HEADERS,
    )

    H.validate_error(response, H.ApiErrorId.ERR_MENU_ITEM_NOT_FOUND.value, 404)


def test_an_order_line_is_reachable_from_both_of_its_parents(api):
    """The junction row answers to its order and to its menu item alike.

    "At line creation the line's `station` is copied from the menu item's
    `station`, its `line_discount_cents` and `line_net_cents` remain 0 until the
    order is committed, its `reserved_qty` is 0 and its `fulfillment_batch_id` is
    null." Pricing is per-unit: "the line's `unit_price_cents` is the menu item's
    `base_price_cents` plus, for every modifier entry on the line, that option's
    `price_delta_cents` multiplied by the entry's `qty`", and the single premium
    unit is covered by the allowance because "the line's
    `premium_surcharge_cents` is 75 cents multiplied by the amount, never less
    than zero, by which the premium modifier unit count exceeds the menu item's
    `included_premium_count`". Both filters are declared: "lines may be listed
    with filters on `order_id`, `menu_item_id` and `fulfillment_batch_id`."

    Design: Corner/entities/order_line_junction_ties_an_order_to_a_menu_item_and_its_modifiers
    """
    store = X.create_store(api)
    hoagie = X.create_hoagie(api)
    provolone = X.create_modifier_option(
        api, hoagie["id"], price_delta_cents=60, is_premium=True, max_qty=2
    )
    order = X.create_draft_order(api, store["id"])

    response = api.create_order_line(
        order["id"],
        F.order_line_payload(hoagie["id"], 1, [F.modifier_selection(provolone["id"], 1)]),
        H.STORE_TERMINAL_HEADERS,
    )

    line = H.get_success_data(response, 201)
    assert line["station"] == "SANDWICH"
    assert line["unit_price_cents"] == 959
    assert line["premium_surcharge_cents"] == 0
    assert line["line_gross_cents"] == 959
    assert line["order_id"] == order["id"]
    assert line["menu_item_id"] == hoagie["id"]
    assert line["fulfillment_batch_id"] is None
    assert line["reserved_qty"] == 0
    assert [
        (entry["modifier_option_id"], entry["qty"]) for entry in line["modifiers"]
    ] == [(provolone["id"], 1)]

    by_order, order_meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"order_id": order["id"]})
    )
    assert order_meta["total_count"] == 1
    assert by_order[0]["id"] == line["id"]

    by_item, item_meta = H.validate_paginated(
        api.list_order_lines(H.STORE_MANAGER_HEADERS, {"menu_item_id": hoagie["id"]})
    )
    assert item_meta["total_count"] == 1
    assert by_item[0]["id"] == line["id"]

    assert X.read_order(api, order["id"])["subtotal_gross_cents"] == 959
