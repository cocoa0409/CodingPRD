"""Entity contracts: declared fields, system defaults, identity and immutability."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PLANNER,
    SAFETY,
    ApiErrorId,
    assert_driver,
    assert_envelope_meta,
    assert_order,
    assert_store,
    assert_telematics_event,
    assert_trailer,
    assert_trip,
    assert_trip_duty_identity,
    assert_trip_stop,
    create_driver_payload,
    create_store_payload,
    create_telematics_event_payload,
    create_trailer_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    new_domicile,
    new_order,
    new_pay_plan,
    new_store,
    new_trip,
    non_delivery_stop_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

STORE_C1 = {
    "store_code": "S-2001",
    "region_code": "MIDWEST",
    "dock_count": 2,
    "cases_per_hour_unload_rate": 600,
    "dock_open_minute": 0,
    "dock_close_minute": 1439,
}

UNMINTED_DRIVER_ID = "99999999-8888-4777-8666-555544443333"
UNMINTED_TRIP_ID = "44444444-3333-4222-8111-000000000000"

ORDER_WINDOW = {
    "requested_window_start": "2026-08-16T08:00:00Z",
    "requested_window_end": "2026-08-16T14:00:00Z",
}


def test_a_registered_store_reports_its_inputs_and_its_system_defaults(api):
    """PRD §3.1: "A newly registered store starts with `status` of `ACTIVE` and both of its
    case ledgers, `open_scheduled_cases` and `delivered_cases_total`, at zero."

    Design: Corner/entities/store_creation_returns_every_declared_field
    """
    set_clock()
    store = validate_success(api.create_store(dict(STORE_C1), PLANNER), 201)
    assert_store(store)
    assert store["store_code"] == "S-2001"
    assert store["region_code"] == "MIDWEST"
    assert store["dock_count"] == 2
    assert store["cases_per_hour_unload_rate"] == 600
    assert store["dock_open_minute"] == 0
    assert store["dock_close_minute"] == 1439
    assert store["status"] == "ACTIVE"
    assert store["open_scheduled_cases"] == 0
    assert store["delivered_cases_total"] == 0
    # Nothing about a store is nullable on creation.
    assert all(value is not None for value in store.values())


def test_the_store_row_is_born_at_version_one_behind_a_bare_uuid(api):
    """PRD §2.4: "Every persisted resource carries a server-minted `id`: a UUID string with
    no type prefix of any kind."

    Design: Corner/entities/store_creation_returns_every_declared_field
    """
    set_clock()
    response = api.create_store(dict(STORE_C1), PLANNER)
    validate_success(response, 201)
    body = response.json()
    assert_envelope_meta(body, "object")

    store = body["data"]
    assert is_valid_uuid(store["id"])
    assert store["id"].count("-") == 4
    assert store["version"] == 1
    assert is_iso8601_timestamp(store["created_at"])
    assert is_iso8601_timestamp(store["updated_at"])


def test_a_freshly_opened_trip_reports_draft_pending_and_no_planned_end(api):
    """PRD §3.4: "The new row records the planner's operator identifier in
    `created_by_user_id`, sets `plan_status` to `DRAFT` and `settlement_status` to `PENDING`,
    puts `stop_count` at zero and `planned_end_at` at null, and zeroes every mileage, minute,
    case and money aggregate."

    Design: Corner/entities/trip_retrieval_returns_the_stored_row
    """
    set_clock()
    domicile = new_domicile(domicile_code="DOM-COR")
    trip = new_trip(domicile["id"], trip_code="TRIP-C1",
                    planned_start_at="2026-08-15T06:00:00Z")

    fetched = validate_success(api.get_trip(trip["id"], MANAGER), 200)
    assert_trip(fetched)
    assert fetched["id"] == trip["id"]
    assert fetched["trip_code"] == "TRIP-C1"
    assert fetched["domicile_id"] == domicile["id"]
    assert fetched["planned_start_at"].startswith("2026-08-15T06:00:00")
    assert fetched["plan_status"] == "DRAFT"
    assert fetched["settlement_status"] == "PENDING"
    assert fetched["stop_count"] == 0
    # A trip with no stops has no end.
    assert fetched["planned_end_at"] is None
    assert fetched["driver_id"] is None
    assert fetched["tractor_id"] is None
    assert fetched["trailer_id"] is None
    for field in (
        "total_miles", "loaded_miles", "empty_miles", "planned_drive_minutes",
        "planned_service_minutes", "planned_break_minutes", "planned_duty_minutes",
        "planned_delivery_cases", "peak_case_load", "delivered_cases",
        "planned_pay_cents", "driver_pay_cents", "backhaul_credit_cents",
    ):
        assert fetched[field] == 0, f"{field} must start at zero"
    # A read never moves a version.
    assert fetched["version"] == trip["version"] == 1


def _three_orders_at_one_store_and_one_at_another():
    """S-2002 holds 100, 200 and 300 cases in that order; S-2003 holds 400."""
    set_clock()
    store_a = new_store(store_code="S-2002", region_code="EAST")
    store_b = new_store(store_code="S-2003", region_code="EAST")
    first = new_order(store_a["id"], cases=100, weight_lbs=2200,
                      temperature_mode="DRY", priority=1, **ORDER_WINDOW)
    second = new_order(store_a["id"], cases=200, weight_lbs=4400,
                       temperature_mode="DRY", priority=2, **ORDER_WINDOW)
    third = new_order(store_a["id"], cases=300, weight_lbs=6600,
                      temperature_mode="REFRIGERATED", priority=3, **ORDER_WINDOW)
    fourth = new_order(store_b["id"], cases=400, weight_lbs=8800,
                       temperature_mode="DRY", priority=3, **ORDER_WINDOW)
    return {
        "store_a": store_a,
        "store_b": store_b,
        "orders": [first, second, third],
        "other_store_order": fourth,
    }


def test_the_order_page_window_reports_the_filtered_total_and_what_remains(api):
    """PRD §2.3: "Collection results are ordered by `created_at` ascending unless the
    endpoint's own description states otherwise — the one exception in this API is the
    listing of a trip's stops, which is ordered by ascending `sequence` because a trip's stop
    set is inherently ordered. List responses populate `limit`, `offset`, `total_count` and
    `has_more` inside `meta`, where `total_count` is the number of rows matching the filter
    before the page window is applied and `has_more` is true whenever rows remain beyond the
    current window."

    Design: Corner/entities/replenishment_order_listing_paginates_and_filters_by_store
    """
    ctx = _three_orders_at_one_store_and_one_at_another()
    expected = [order["id"] for order in ctx["orders"]]

    page_one, meta_one = validate_paginated(
        api.list_orders(PLANNER, {"store_id": ctx["store_a"]["id"], "limit": 2, "offset": 0})
    )
    assert [row["id"] for row in page_one] == expected[:2]
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert all(row["store_id"] == ctx["store_a"]["id"] for row in page_one)

    page_two, meta_two = validate_paginated(
        api.list_orders(PLANNER, {"store_id": ctx["store_a"]["id"], "limit": 2, "offset": 2})
    )
    assert [row["id"] for row in page_two] == expected[2:]
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert_order(page_two[0])


def test_the_store_and_temperature_filters_compose_over_the_default_page(api):
    """PRD §2.3: "`limit` controls page size; it defaults to 10, its minimum accepted value
    is 1 and its maximum accepted value is 100."

    Design: Corner/entities/replenishment_order_listing_paginates_and_filters_by_store
    """
    ctx = _three_orders_at_one_store_and_one_at_another()

    rows, meta = validate_paginated(api.list_orders(PLANNER, {"store_id": ctx["store_a"]["id"]}))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    # The other store's order appears on no page of this filter.
    assert ctx["other_store_order"]["id"] not in [row["id"] for row in rows]

    reefer, reefer_meta = validate_paginated(
        api.list_orders(
            PLANNER,
            {"store_id": ctx["store_a"]["id"], "temperature_mode": "REFRIGERATED"},
        )
    )
    assert reefer_meta["total_count"] == 1
    assert [row["id"] for row in reefer] == [ctx["orders"][2]["id"]]
    assert reefer[0]["status"] == "UNSCHEDULED"


def test_an_unminted_driver_uuid_answers_the_entity_specific_not_found(api):
    """PRD §2.7: "The row named by the final path parameter must exist. Applies to every
    endpoint that has a path parameter."

    Design: Corner/entities/driver_lookup_with_unknown_uuid_returns_driver_not_found
    """
    set_clock()
    response = api.get_driver(UNMINTED_DRIVER_ID, MANAGER)
    payload = validate_error(response, ApiErrorId.ERR_DRIVER_NOT_FOUND, 404)
    assert payload["message"].strip() != ""
    # The error envelope carries exactly the two declared members.
    assert set(payload.keys()) == {"error_id", "message"}
    assert_envelope_meta(response.json(), "error")


def test_a_store_create_missing_a_required_input_persists_nothing(api):
    """PRD §2.7: "Required body fields must be present and non-null; enum fields must carry a
    declared value; integers declared non-negative must be zero or greater; instants must
    parse as RFC 3339 UTC; a window's start must be strictly earlier than its end; and `limit`
    must lie within 1 through 100."

    Design: Corner/entities/store_creation_without_dock_count_is_rejected
    """
    set_clock()
    without_docks = create_store_payload(store_code="S-2004", region_code="WEST")
    without_docks.pop("dock_count")
    validate_error(api.create_store(without_docks, PLANNER), ApiErrorId.ERR_INVALID_REQUEST, 400)

    # Every other Store input carries no declared default either.
    for field in (
        "store_code", "region_code", "cases_per_hour_unload_rate",
        "dock_open_minute", "dock_close_minute",
    ):
        partial = create_store_payload(store_code="S-2004", region_code="WEST")
        partial.pop(field)
        validate_error(api.create_store(partial, PLANNER), ApiErrorId.ERR_INVALID_REQUEST, 400)
    nulled = create_store_payload(store_code="S-2004", region_code="WEST", dock_count=None)
    validate_error(api.create_store(nulled, PLANNER), ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(api.list_stores(PLANNER, {"region_code": "WEST"}))
    assert meta["total_count"] == 0
    assert rows == []


def _draft_trip_with_a_fuel_stop(api):
    """TRIP-C2 carries one FUEL stop appended with no `cases` field at all."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-COR2")
    trip = new_trip(domicile["id"], trip_code="TRIP-C2",
                    planned_start_at="2026-08-17T06:00:00Z")
    payload = non_delivery_stop_payload(
        1, "FUEL", "2026-08-17T07:00:00Z", "2026-08-17T07:25:00Z", 45, 40,
        segment_loaded=True,
    )
    assert "cases" not in payload
    stop = validate_success(api.add_trip_stop(trip["id"], payload, PLANNER), 201)
    return {"trip": trip, "stop": stop}


def test_a_fuel_stop_that_omits_its_cases_stores_zero(api):
    """PRD §3.4: "Finally `cases` records how many cases are dropped at a delivery or
    drop-off, or picked up at a vendor or third-party pickup; it defaults to zero and must be
    zero or greater."

    Design: Corner/entities/fuel_stop_omits_cases_and_defaults_to_zero
    """
    ctx = _draft_trip_with_a_fuel_stop(api)
    stop = ctx["stop"]
    assert_trip_stop(stop)
    assert stop["cases"] == 0
    assert stop["stop_type"] == "FUEL"
    assert stop["status"] == "PLANNED"
    assert stop["store_id"] is None
    assert stop["replenishment_order_id"] is None


def test_the_fuel_stop_books_its_flat_service_minutes_into_the_trip(api):
    """PRD §3.4: "For a `DROP_OFF` it is a flat twenty minutes, and for a `FUEL` stop a flat
    twenty-five minutes."

    Design: Corner/entities/fuel_stop_omits_cases_and_defaults_to_zero
    """
    ctx = _draft_trip_with_a_fuel_stop(api)
    # The default was applied before the service rule ran.
    assert ctx["stop"]["service_minutes"] == 25

    trip = validate_success(api.get_trip(ctx["trip"]["id"], PLANNER), 200)
    assert trip["planned_service_minutes"] == 25
    assert trip["planned_drive_minutes"] == 45
    assert trip["planned_break_minutes"] == 0
    assert trip["planned_duty_minutes"] == 70
    assert_trip_duty_identity(trip)
    assert trip["planned_delivery_cases"] == 0
    assert trip["peak_case_load"] == 0


def test_the_case_ledgers_and_the_store_status_ignore_the_create_body(api):
    """PRD §2.7: "Two conventions here: unknown body keys are ignored rather than rejected,
    and any field the system computes or owns itself is silently ignored when a client
    supplies it."

    Design: Corner/entities/store_creation_with_extra_ledger_fields_input_ignored
    """
    set_clock()
    seeded = create_store_payload(
        store_code="S-2005",
        region_code="SOUTH",
        open_scheduled_cases=5000,
        delivered_cases_total=9000,
        status="SUSPENDED",
    )
    store = validate_success(api.create_store(seeded, PLANNER), 201)
    assert store["open_scheduled_cases"] == 0
    assert store["delivered_cases_total"] == 0
    assert store["status"] == "ACTIVE"
    assert store["version"] == 1


def test_a_new_driver_starts_available_with_clean_counters_and_a_perfect_score(api):
    """PRD §3.3: "The new row starts `ACTIVE` with `hos_status` of `AVAILABLE` — the other
    posture being `ON_DUTY`, which the driver holds between dispatch and close-out — and with
    all three duty counters at zero: `drive_minutes_used_today`, `duty_minutes_used_today` and
    `weekly_on_duty_minutes`. Safety fields start clean as well: `open_penalty_points` at
    zero, `safety_score` at 100, `coaching_hold` false. `ytd_gross_cents` starts at zero."

    Design: Corner/entities/driver_system_fields_are_server_minted
    """
    set_clock()
    domicile = new_domicile(domicile_code="DOM-COR3")
    pay_plan = new_pay_plan()
    body = create_driver_payload(domicile["id"], pay_plan["id"], driver_code="DX-1",
                                 seniority_date="2021-01-04")
    driver = validate_success(api.create_driver(body, MANAGER), 201)

    assert_driver(driver)
    assert is_valid_uuid(driver["id"])
    assert driver["version"] == 1
    assert is_iso8601_timestamp(driver["created_at"])
    assert is_iso8601_timestamp(driver["updated_at"])
    assert driver["status"] == "ACTIVE"
    assert driver["hos_status"] == "AVAILABLE"
    assert driver["drive_minutes_used_today"] == 0
    assert driver["duty_minutes_used_today"] == 0
    assert driver["weekly_on_duty_minutes"] == 0
    assert driver["open_penalty_points"] == 0
    assert driver["safety_score"] == 100
    assert driver["coaching_hold"] is False
    assert driver["ytd_gross_cents"] == 0


def test_the_trailer_type_vocabulary_refuses_a_plausible_third_value(api):
    """PRD §3.2: "A trailer carries a `trailer_code` unique across all trailers and one to
    sixteen characters long, a `domicile_id`, a `trailer_type` of either `DRY_VAN` or `REEFER`,
    a `capacity_cases` of at least 1, and an `inspection_due_at` instant that records the next
    DOT inspection for reporting only and gates nothing."

    Design: Corner/entities/trailer_type_with_undeclared_enum_value_is_rejected
    """
    set_clock()
    domicile = new_domicile(domicile_code="DOM-COR4")

    # REFRIGERATED is the replenishment-order vocabulary, not the trailer vocabulary.
    wrong_enum = create_trailer_payload(domicile["id"], trailer_code="VAN-960",
                                        trailer_type="REFRIGERATED", capacity_cases=1800)
    validate_error(api.create_trailer(wrong_enum, MAINTENANCE),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)

    no_capacity = create_trailer_payload(domicile["id"], trailer_code="VAN-960",
                                         trailer_type="REEFER", capacity_cases=0)
    validate_error(api.create_trailer(no_capacity, MAINTENANCE),
                   ApiErrorId.ERR_INVALID_REQUEST, 400)

    good = create_trailer_payload(domicile["id"], trailer_code="VAN-960",
                                  trailer_type="REEFER", capacity_cases=1800)
    accepted = validate_success(api.create_trailer(good, MAINTENANCE), 201)
    assert_trailer(accepted)
    # VAN-960 was still free, so neither refusal had created a row.
    assert accepted["trailer_code"] == "VAN-960"
    assert accepted["trailer_type"] == "REEFER"
    assert accepted["capacity_cases"] == 1800
    assert accepted["status"] == "AVAILABLE"


def _one_hard_brake_event(api):
    """Driver DX-2 with a single severity-3 HARD_BRAKE exception against them."""
    set_clock()
    domicile = new_domicile(domicile_code="DOM-COR5")
    pay_plan = new_pay_plan()
    driver = get_success_data(
        api.create_driver(
            create_driver_payload(domicile["id"], pay_plan["id"], driver_code="DX-2",
                                  seniority_date="2021-02-04"),
            MANAGER,
        )
    )
    event = validate_success(
        api.create_telematics_event(
            create_telematics_event_payload(driver["id"], "HARD_BRAKE", 3,
                                           "2026-07-30T15:00:00Z"),
            SAFETY,
        ),
        201,
    )
    return {"driver": driver, "event": event}


def test_a_telematics_event_carries_no_version_and_no_updated_at(api):
    """PRD §2.4: "It is an append-only record, and it carries only `id` and `created_at` — it
    has no `updated_at` field and no `version` field at all."

    Design: Corner/entities/telematics_event_is_immutable_with_no_version_field
    """
    ctx = _one_hard_brake_event(api)
    event = ctx["event"]
    assert_telematics_event(event)
    assert "version" not in event
    assert "updated_at" not in event
    assert is_valid_uuid(event["id"])
    assert is_iso8601_timestamp(event["created_at"])
    assert event["coached"] is False
    assert event["coached_at"] is None
    assert event["coached_by_user_id"] is None


def test_the_recorded_exception_prices_its_points_once_and_is_discoverable(api):
    """PRD §3.9: "The bases are 2 for `HARD_BRAKE`, 3 for `SPEEDING`, 2 for
    `FOLLOWING_DISTANCE` and 4 for `SEATBELT`, so a severity-3 seatbelt exception is worth
    twelve points while a severity-1 hard brake is worth two."

    Design: Corner/entities/telematics_event_is_immutable_with_no_version_field
    """
    ctx = _one_hard_brake_event(api)
    assert ctx["event"]["penalty_points"] == 6
    assert ctx["event"]["severity"] == 3
    assert ctx["event"]["event_type"] == "HARD_BRAKE"

    rows, meta = validate_paginated(
        api.list_telematics_events(SAFETY, {"driver_id": ctx["driver"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["event"]["id"]
    assert rows[0]["penalty_points"] == 6


def test_the_immutable_event_still_drives_the_derived_driver_standing(api):
    """PRD §3.9: "`open_penalty_points` is the sum of `penalty_points` across every one of
    that driver's events whose `coached` flag is still false — with no date cutoff and no
    restriction to any trip, so a yard event with a null trip counts exactly as much as an
    on-road one. `safety_score` is one hundred less those open points, floored at zero so it
    never goes negative."

    Design: Corner/entities/telematics_event_is_immutable_with_no_version_field
    """
    ctx = _one_hard_brake_event(api)
    driver = validate_success(api.get_driver(ctx["driver"]["id"], SAFETY), 200)
    assert driver["open_penalty_points"] == ctx["event"]["penalty_points"]
    assert driver["open_penalty_points"] == 6
    assert driver["safety_score"] == 100 - driver["open_penalty_points"]
    assert driver["safety_score"] == 94
    assert driver["coaching_hold"] is False


def test_a_stop_appended_under_an_unminted_trip_reports_the_missing_trip(api):
    """PRD §2.11: "When a stop is appended under a trip, the trip named by `trip_id` is
    resolved first and a missing trip yields `ERR_TRIP_NOT_FOUND` before the body is even
    shape-checked; when a stop is deleted from a trip, `trip_id` resolves first and
    `trip_stop_id` second, and a stop that exists but belongs to a different trip is an
    ownership failure rather than a not-found."

    Design: Corner/entities/trip_stop_creation_under_an_unknown_trip_returns_not_found
    """
    set_clock()
    # A DELIVERY body with neither store_id nor replenishment_order_id: still a 404.
    payload = {
        "sequence": 1,
        "stop_type": "DELIVERY",
        "scheduled_arrival_at": "2026-08-18T08:00:00Z",
        "scheduled_departure_at": "2026-08-18T09:00:00Z",
        "drive_minutes_from_prev": 60,
        "miles_from_prev": 50,
        "segment_loaded": True,
        "cases": 100,
    }
    validate_error(
        api.add_trip_stop(UNMINTED_TRIP_ID, payload, PLANNER),
        ApiErrorId.ERR_TRIP_NOT_FOUND,
        404,
    )
