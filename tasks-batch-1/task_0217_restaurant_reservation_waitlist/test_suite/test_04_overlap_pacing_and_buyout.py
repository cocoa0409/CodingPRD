"""Temporal overlap, pacing capacity, service-period windows, and area buyout.

Covers Difficulty rules resource_temporal_overlap (table half-open overlap;
area closed-interval buyout exclusivity) and boundary_precision_check (pacing
inclusive cap), plus the corner validation instances on booking.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, make_customer_headers,
    TEST_USERS,
    setup_floor, setup_private_area,
    make_restaurant, make_dining_area, make_table, make_service_period,
    make_customer, set_clock, book_reservation, current_table_version,
    make_private_event, propose_private_event, confirm_private_event,
    create_reservation_payload,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


# ─── resource_temporal_overlap / table half-open overlap ──────────────────
def test_release_at_is_start_plus_turn_plus_buffer(api):
    """PRD §3.3: "the `release_at` is `turn_window_end` plus the restaurant's
    `cleanup_buffer_minutes` — the instant after which the table frees for the
    next booking."

    Design: Difficulty/resource_temporal_overlap/table_double_book_halfopen_with_cleanup_buffer
    """
    floor = setup_floor(
        restaurant_overrides={"default_turn_time_minutes": 90,
                              "cleanup_buffer_minutes": 15},
        table_overrides={"max_party_size": 8},
        period_overrides={"slot_interval_minutes": 15, "pacing_max_covers_per_slot": 30})
    res1 = book_reservation(floor["restaurant"]["id"], floor["customer"]["id"],
                            floor["table"]["id"], party_size=2,
                            reservation_start="2026-06-15T18:00:00Z")
    # 18:00 + 90 (turn) + 15 (buffer) → 19:45.
    assert res1["release_at"] == "2026-06-15T19:45:00.000Z", \
        f"release_at == 19:45, got {res1['release_at']}"


def test_overlapping_booking_inside_release_window_rejected(api):
    """PRD §3.3: "A booking's occupied window runs from its `reservation_start`
    inclusive up to its `release_at` exclusive ... The new window must not
    intersect the window of any active reservation on the same `table_id`; an
    intersection is rejected with `ERR_TABLE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/table_double_book_halfopen_with_cleanup_buffer
    """
    floor = setup_floor(
        restaurant_overrides={"default_turn_time_minutes": 90,
                              "cleanup_buffer_minutes": 15},
        table_overrides={"max_party_size": 8},
        period_overrides={"slot_interval_minutes": 15, "pacing_max_covers_per_slot": 30})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    book_reservation(rid, cust, tbl, party_size=2,
                     reservation_start="2026-06-15T18:00:00Z")
    tv = current_table_version(tbl)
    # 19:00 is inside [18:00, 19:45) → rejected.
    resp = api.create_reservation(
        create_reservation_payload(rid, cust, tbl, tv, party_size=2,
                                   reservation_start="2026-06-15T19:00:00Z"),
        make_customer_headers(cust))
    validate_error(resp, "ERR_TABLE_DOUBLE_BOOKED")


def test_booking_at_release_at_boundary_accepted(api):
    """PRD §3.3: "A booking's occupied window runs from its `reservation_start`
    inclusive up to its `release_at` exclusive — the cleanup buffer is already
    baked into `release_at`."

    Design: Difficulty/resource_temporal_overlap/table_double_book_halfopen_with_cleanup_buffer
    """
    floor = setup_floor(
        restaurant_overrides={"default_turn_time_minutes": 90,
                              "cleanup_buffer_minutes": 15},
        table_overrides={"max_party_size": 8},
        period_overrides={"slot_interval_minutes": 15, "pacing_max_covers_per_slot": 30})
    rid, cust, tbl = floor["restaurant"]["id"], floor["customer"]["id"], floor["table"]["id"]
    book_reservation(rid, cust, tbl, party_size=2,
                     reservation_start="2026-06-15T18:00:00Z")
    tv = current_table_version(tbl)
    # 19:45 == release_at (exclusive upper bound) → does not intersect → accepted.
    res2 = validate_success(api.create_reservation(
        create_reservation_payload(rid, cust, tbl, tv, party_size=2,
                                   reservation_start="2026-06-15T19:45:00Z"),
        make_customer_headers(cust)), 201)
    assert res2["status"] == "REQUESTED"


# ─── resource_temporal_overlap / area buyout closed-interval exclusivity ───
def _setup_confirmed_buyout_with_table(api):
    """A PRIVATE area + table; a CONFIRMED buyout over [18:00, 22:00]. Returns
    dict with restaurant, area, table, customer, pre-buyout table_version."""
    restaurant = make_restaurant(default_turn_time_minutes=90, cleanup_buffer_minutes=15)
    area = make_dining_area(restaurant["id"], name="PRIVATE_ROOM", kind="PRIVATE")
    area_version = area["version"]
    table = make_table(area["id"], label="P1", max_party_size=12)
    make_service_period(restaurant["id"], pacing_max_covers_per_slot=30)
    customer = make_customer()
    set_clock("2026-06-15T12:00:00Z")
    table_version = current_table_version(table["id"])
    event = make_private_event(restaurant["id"], area["id"], customer["id"],
                               party_size=12, food_minimum_cents=200000,
                               event_start="2026-06-15T18:00:00Z",
                               event_end="2026-06-15T22:00:00Z")
    propose_private_event(event["id"])
    confirm_private_event(event["id"], area_version)
    return {"restaurant": restaurant, "area": area, "table": table,
            "customer": customer, "table_version": table_version}


def test_reservation_on_bought_out_area_rejected(api):
    """PRD §3.4: "A reservation create or reschedule whose window would intersect
    a `CONFIRMED` buyout's closed window on the table's dining area is rejected
    with `ERR_AREA_BOUGHT_OUT`".

    Design: Difficulty/resource_temporal_overlap/area_buyout_closed_interval_whole_area_exclusivity
    """
    ctx = _setup_confirmed_buyout_with_table(api)
    resp = api.create_reservation(
        create_reservation_payload(
            ctx["restaurant"]["id"], ctx["customer"]["id"], ctx["table"]["id"],
            ctx["table_version"], party_size=4,
            reservation_start="2026-06-15T19:00:00Z"),
        HOST)
    validate_error(resp, "ERR_AREA_BOUGHT_OUT")


def test_buyout_sets_area_bought_out(api):
    """PRD §3.4: "On confirm the area is set `BOUGHT_OUT` and its `version` is
    incremented".

    Design: Difficulty/resource_temporal_overlap/area_buyout_closed_interval_whole_area_exclusivity
    """
    ctx = _setup_confirmed_buyout_with_table(api)
    area = validate_success(api.get_dining_area(ctx["area"]["id"], HOST), 200)
    assert area["status"] == "BOUGHT_OUT"


# ─── boundary_precision_check / pacing inclusive cap on create ─────────────
def _setup_pacing_loaded_to_eight(api):
    """Three tables; pacing cap 10; one REQUESTED party-8 reservation already on
    the 18:00 slot (load 8). Returns ids dict."""
    restaurant = make_restaurant(default_turn_time_minutes=90, cleanup_buffer_minutes=15)
    area = make_dining_area(restaurant["id"])
    t1 = make_table(area["id"], label="T1", max_party_size=8)
    t2 = make_table(area["id"], label="T2", max_party_size=8)
    t3 = make_table(area["id"], label="T3", max_party_size=8)
    make_service_period(restaurant["id"], pacing_max_covers_per_slot=10)
    customer = make_customer()
    set_clock("2026-06-15T12:00:00Z")
    book_reservation(restaurant["id"], customer["id"], t1["id"], party_size=8,
                     reservation_start="2026-06-15T18:00:00Z")
    return {"rid": restaurant["id"], "cust": customer["id"],
            "t2": t2["id"], "t3": t3["id"]}


def test_pacing_accepts_projected_load_equal_to_cap(api):
    """PRD §3.3: "The booking is accepted only when the projected load is less
    than or equal to the period's `pacing_max_covers_per_slot`; a projected load
    equal to the cap is allowed, and one greater than the cap is rejected with
    `ERR_PACING_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/pacing_cap_inclusive_boundary_on_create
    """
    ids = _setup_pacing_loaded_to_eight(api)
    tv = current_table_version(ids["t2"])
    # load 8 + 2 = 10 == cap → accepted.
    res = validate_success(api.create_reservation(
        create_reservation_payload(ids["rid"], ids["cust"], ids["t2"], tv,
                                   party_size=2,
                                   reservation_start="2026-06-15T18:00:00Z"),
        make_customer_headers(ids["cust"])), 201)
    assert res["status"] == "REQUESTED"


def test_pacing_rejects_projected_load_above_cap(api):
    """PRD §3.3: "a projected load equal to the cap is allowed, and one greater
    than the cap is rejected with `ERR_PACING_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/pacing_cap_inclusive_boundary_on_create
    """
    ids = _setup_pacing_loaded_to_eight(api)
    # Fill the slot to exactly 10 first (8 + 2), then a party of 1 → 11 > cap.
    tv2 = current_table_version(ids["t2"])
    validate_success(api.create_reservation(
        create_reservation_payload(ids["rid"], ids["cust"], ids["t2"], tv2,
                                   party_size=2,
                                   reservation_start="2026-06-15T18:00:00Z"),
        make_customer_headers(ids["cust"])), 201)
    tv3 = current_table_version(ids["t3"])
    resp = api.create_reservation(
        create_reservation_payload(ids["rid"], ids["cust"], ids["t3"], tv3,
                                   party_size=1,
                                   reservation_start="2026-06-15T18:00:00Z"),
        make_customer_headers(ids["cust"]))
    validate_error(resp, "ERR_PACING_EXCEEDED")


# ─── corner validation instances on booking ───────────────────────────────
def test_book_outside_service_period_rejected(api):
    """PRD §2.5: "A booking whose local start falls outside every service-period
    window, or which does not land exactly on a period's slot grid, is rejected
    with `ERR_OUTSIDE_SERVICE_PERIOD` (HTTP 422)."

    Design: Corner/validations/book_outside_service_period_rejected
    """
    floor = setup_floor(table_overrides={"max_party_size": 8}, clock="2026-06-15T08:00:00Z")
    tv = current_table_version(floor["table"]["id"])
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], floor["customer"]["id"],
                                   floor["table"]["id"], tv, party_size=2,
                                   reservation_start="2026-06-15T15:00:00Z"),
        make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_OUTSIDE_SERVICE_PERIOD")


def test_book_misaligned_slot_grid_rejected(api):
    """PRD §2.5: "a booking's local start must align to the grid formed by
    stepping that interval forward from `start_local_time` ... or which does not
    land exactly on a period's slot grid, is rejected with
    `ERR_OUTSIDE_SERVICE_PERIOD`".

    Design: Corner/validations/book_misaligned_slot_grid_rejected
    """
    floor = setup_floor(table_overrides={"max_party_size": 8},
                        period_overrides={"slot_interval_minutes": 30})
    tv = current_table_version(floor["table"]["id"])
    # 18:10 is not on the 30-min grid from 17:00.
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], floor["customer"]["id"],
                                   floor["table"]["id"], tv, party_size=2,
                                   reservation_start="2026-06-15T18:10:00Z"),
        make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_OUTSIDE_SERVICE_PERIOD")


def test_book_at_closed_restaurant_rejected(api):
    """PRD §3.1: "A restaurant is born `OPEN`; a manager may later close it,
    which makes it reject all new reservations and waitlist joins". PRD §3.3:
    "The restaurant must be `OPEN`, else `ERR_RESTAURANT_CLOSED`."

    Design: Corner/validations/book_at_closed_restaurant_rejected
    """
    floor = setup_floor(table_overrides={"max_party_size": 8})
    get_success_data(api.close_restaurant(floor["restaurant"]["id"], MANAGER))
    tv = current_table_version(floor["table"]["id"])
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], floor["customer"]["id"],
                                   floor["table"]["id"], tv, party_size=2,
                                   reservation_start="2026-06-15T18:00:00Z"),
        make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_RESTAURANT_CLOSED")


def test_party_size_mismatch_alone_rejected(api):
    """PRD §3.3: "The `party_size` must fall within the chosen table's band — at
    least its `min_party_size` and at most its `max_party_size` — else
    `ERR_PARTY_SIZE_MISMATCH`."

    Design: Corner/validations/party_size_mismatch_alone_rejected
    """
    floor = setup_floor(table_overrides={"max_party_size": 8},
                        period_overrides={"pacing_max_covers_per_slot": 30})
    tv = current_table_version(floor["table"]["id"])
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"], floor["customer"]["id"],
                                   floor["table"]["id"], tv, party_size=10,
                                   reservation_start="2026-06-15T18:00:00Z"),
        make_customer_headers(floor["customer"]["id"]))
    validate_error(resp, "ERR_PARTY_SIZE_MISMATCH")


def test_unknown_customer_fk_returns_not_found(api):
    """PRD §2.8: "every foreign key carried in a body (such as `restaurant_id`,
    `customer_id`, `table_id`, `dining_area_id`, or `reservation_id`) must
    resolve to an existing entity, validated in left-to-right order, and the
    first unresolved reference yields `ERR_NOT_FOUND`."

    Design: Corner/validations/existence_unknown_customer_returns_not_found
    """
    floor = setup_floor()
    tv = current_table_version(floor["table"]["id"])
    resp = api.create_reservation(
        create_reservation_payload(floor["restaurant"]["id"],
                                   "00000000-0000-4000-8000-0000000000cc",
                                   floor["table"]["id"], tv, party_size=2,
                                   reservation_start="2026-06-15T18:00:00Z"),
        HOST)
    validate_error(resp, "ERR_NOT_FOUND")
