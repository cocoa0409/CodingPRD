"""CRUD, defaults, computed fields, capacity/inventory/fiscal validations,
pagination, and catalog-error coverage.

Covers Corner queue: entities, validations, endpoints, errors instances.
"""

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    create_rate_card_payload,
    create_lane_payload,
    create_customer_payload,
    create_reservation_payload,
    create_rental_item_payload,
    create_rental_line_payload,
    create_food_item_payload,
    create_food_line_payload,
    create_league_payload,
    create_league_night_payload,
    NON_EXISTENT_UUID,
    CM, FD, LA,
)


# =============================================================================
# Corner / entities
# =============================================================================
def test_create_reservation_returns_201_with_system_fields(api):
    """PRD §3.3: "A booking begins as a **reservation** in `DRAFT`."
    PRD §2.4: "a `version`, an integer that starts at 1 and increments by one on
    every mutation to the resource."

    Design: Corner/entities/create_reservation_returns_201_with_system_fields
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="E1", per_game_cents=500, per_hour_cents=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-01T18:00:00.000Z", end_at="2026-09-01T19:00:00.000Z",
        bowler_count=2, game_count=2), FD), 201)
    assert res["status"] == "DRAFT"
    assert res["version"] == 1


def test_get_reservation_not_found_returns_404(api):
    """PRD §2.6: "every resource referenced in the path or body must exist ... the
    first identifier that names no existing resource produces `ERR_NOT_FOUND`".

    Design: Corner/entities/get_reservation_not_found_returns_404
    """
    resp = api.get_reservation(NON_EXISTENT_UUID, FD)
    validate_error(resp, "ERR_NOT_FOUND", expected_status=404)


def test_create_reservation_missing_required_field_returns_400(api):
    """PRD §3.3: "A malformed body — a missing required field, an out-of-range
    enum, a `start_at` at or after `end_at`, or a non-positive count — is rejected
    with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_reservation_missing_required_field_returns_400
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="E2", per_game_cents=500, per_hour_cents=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    # omit required pricing_mode
    payload = {
        "customer_id": cust["id"], "rate_card_id": rc["id"],
        "resource_kind": "LANE", "lane_id": lane["id"],
        "start_at": "2026-09-02T18:00:00.000Z", "end_at": "2026-09-02T19:00:00.000Z",
        "bowler_count": 2,
    }
    resp = api.create_reservation(payload, FD)
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_reservation_start_after_end_returns_400(api):
    """PRD §3.3: "a `start_at` at or after `end_at` ... is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_reservation_start_after_end_returns_400
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="E3", per_game_cents=500, per_hour_cents=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    resp = api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-03T19:00:00.000Z", end_at="2026-09-03T18:00:00.000Z",
        bowler_count=2, game_count=1), FD)
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_lane_applies_defaults(api):
    """PRD §3.1: "A **lane** is a physical bowling lane, created with a unique
    `number` of at least 1 and an optional `max_bowlers` seating-and-scoring cap
    that defaults to 6 and must be at least 1. ... A lane's `status` is
    system-managed and begins `IN_SERVICE`".

    Design: Corner/entities/create_lane_defaults_max_bowlers_and_status
    """
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    assert lane["max_bowlers"] == 6
    assert lane["status"] == "IN_SERVICE"


def test_duplicate_lane_number_rejected(api):
    """PRD §3.1: "Attempting to create a lane whose `number` is already in use is
    rejected with `ERR_DUPLICATE_LANE_NUMBER`."

    Design: Corner/entities/duplicate_lane_number_rejected
    """
    lane = validate_success(api.create_lane(create_lane_payload(number=4205), CM), 201)
    assert lane["number"] == 4205
    resp = api.create_lane(create_lane_payload(number=4205), CM)
    validate_error(resp, "ERR_DUPLICATE_LANE_NUMBER", expected_status=409)


def test_rental_item_computed_available_count_on_create(api):
    """PRD §3.1: "At creation a rental item's `out_on_rent_count` is 0 and its
    `available_count` equals its `total_count`."

    Design: Corner/entities/rental_item_computed_available_count_on_create
    """
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="BUMPER", label="std", unit_price_cents=0, total_count=8), CM), 201)
    assert ri["available_count"] == 8
    assert ri["out_on_rent_count"] == 0


def test_food_order_line_total_with_tax(api):
    """PRD §3.4: "the tax is that gross multiplied by 825 basis points, divided by
    ten thousand, and rounded half-up to whole cents ... the line's
    `line_total_cents` is gross plus that rounded tax."

    Design: Corner/entities/food_order_line_immutable_no_version_field
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="E4", per_game_cents=0, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    fi = validate_success(api.create_food_item(create_food_item_payload(
        name="Fries", unit_cents=300, taxable=True), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-04T18:00:00.000Z", end_at="2026-09-04T19:00:00.000Z",
        bowler_count=2, game_count=0), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    fl = validate_success(api.create_food_line(
        create_food_line_payload(res["id"], fi["id"], 2), FD), 201)
    fetched = validate_success(api.get_food_line(fl["id"], FD), 200)
    # gross 600 + tax round_half_up(600*0.0825=49.5)=50 -> 650
    assert fetched["line_total_cents"] == 650


# =============================================================================
# Corner / validations
# =============================================================================
def test_capacity_exceeded_lane_max_bowlers(api):
    """PRD §3.3: "A party that overruns the resource cap ... is rejected with
    `ERR_CAPACITY_EXCEEDED`".
    PRD §3.3: "the party fits the resource, meaning `bowler_count` does not exceed
    the lane's `max_bowlers` for a lane booking".

    Design: Corner/validations/capacity_exceeded_lane_max_bowlers
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="V1", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(max_bowlers=4), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-18T18:00:00.000Z", end_at="2026-09-18T19:00:00.000Z",
        bowler_count=6, game_count=1), FD), 201)
    resp = api.hold_reservation(res["id"], FD)
    validate_error(resp, "ERR_CAPACITY_EXCEEDED", expected_status=409)


def test_rental_unavailable_quantity_exceeds_stock(api):
    """PRD §3.4: "the requested `quantity` may not exceed the item's
    `available_count`, and a shortfall is rejected with `ERR_RENTAL_UNAVAILABLE`."

    Design: Corner/validations/rental_unavailable_quantity_exceeds_stock
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="V2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="BALL", label="10lb", unit_price_cents=400, total_count=2), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-19T18:00:00.000Z", end_at="2026-09-19T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    resp = api.create_rental_line(create_rental_line_payload(res["id"], ri["id"], 3), FD)
    validate_error(resp, "ERR_RENTAL_UNAVAILABLE", expected_status=409)


def test_suspended_customer_cannot_hold(api):
    """PRD §3.2: "A suspended customer cannot place a reservation on hold or take
    out a rental; either attempt is rejected with `ERR_CUSTOMER_SUSPENDED`."

    Design: Corner/validations/suspended_customer_cannot_hold
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="V3", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-20T18:00:00.000Z", end_at="2026-09-20T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.suspend_customer(cust["id"], CM), 200)
    resp = api.hold_reservation(res["id"], FD)
    validate_error(resp, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


# =============================================================================
# Corner / endpoints
# =============================================================================
def test_list_reservations_pagination_envelope(api):
    """PRD §2.3: "The `meta` object of a list response carries the four pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_reservations_pagination_envelope
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="EP1", per_game_cents=500, per_hour_cents=0), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    for s, e in [("2026-09-21T18:00:00.000Z", "2026-09-21T19:00:00.000Z"),
                 ("2026-09-21T20:00:00.000Z", "2026-09-21T21:00:00.000Z")]:
        validate_success(api.create_reservation(create_reservation_payload(
            cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
            pricing_mode="PER_GAME", start_at=s, end_at=e,
            bowler_count=2, game_count=1), FD), 201)

    data, meta = validate_paginated(api.list_reservations(
        FD, params={"customer_id": cust["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_filtered_list_rental_lines_by_reservation(api):
    """PRD §4: "/rental-lines accepts reservation_id, rental_item_id, and status".
    PRD §2.3: "every list endpoint returns its resources sorted by `created_at` in
    ascending order."

    Design: Corner/endpoints/filtered_list_rental_lines_by_reservation
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="EP2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    ri = validate_success(api.create_rental_item(create_rental_item_payload(
        kind="SHOES", label="M9", unit_price_cents=300, total_count=4), CM), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-22T18:00:00.000Z", end_at="2026-09-22T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    validate_success(api.hold_reservation(res["id"], FD), 200)
    rl = validate_success(api.create_rental_line(
        create_rental_line_payload(res["id"], ri["id"], 1), FD), 201)

    data, meta = validate_paginated(api.list_rental_lines(
        FD, params={"reservation_id": res["id"]}))
    assert len(data) == 1
    assert data[0]["id"] == rl["id"]


# =============================================================================
# Corner / errors
# =============================================================================
def test_duplicate_night_index_rejected(api):
    """PRD §3.8: "a `night_index` (a 1-based ordinal that must be unique within its
    league — a duplicate is rejected with `ERR_DUPLICATE_NIGHT_INDEX`)".

    Design: Corner/errors/error_duplicate_night_index
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="ER1", per_game_cents=0, per_hour_cents=0), CM), 201)
    validate_success(api.create_lane(create_lane_payload(), CM), 201)
    league = validate_success(api.create_league(create_league_payload(
        rc["id"], season_night_count=2, lanes_per_night=1, weekly_fee_cents=5000), LA), 201)
    validate_success(api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-09-28T18:00:00.000Z", end_at="2026-09-28T20:00:00.000Z"), LA), 201)
    resp = api.create_league_night(create_league_night_payload(
        league["id"], night_index=1,
        start_at="2026-10-05T18:00:00.000Z", end_at="2026-10-05T20:00:00.000Z"), LA)
    validate_error(resp, "ERR_DUPLICATE_NIGHT_INDEX", expected_status=409)


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "accepted values range from a minimum of 1 to a maximum of 100. ...
    A `limit` or `offset` outside its allowed range is rejected with
    `ERR_PAGINATION_INVALID`."

    Design: Corner/errors/error_pagination_invalid
    """
    resp = api.list_reservations(FD, params={"limit": 500})
    validate_error(resp, "ERR_PAGINATION_INVALID", expected_status=400)


def test_waitlist_on_free_window_rejected(api):
    """PRD §3.7: "A waitlist join is only meaningful on a genuinely contended
    window; requesting it on a window that has no active overlap is rejected with
    `ERR_NOT_WAITLISTED`, since such a booking should simply be held directly."

    Design: Corner/errors/error_not_waitlisted_direct_window_free
    """
    rc = validate_success(api.create_rate_card(create_rate_card_payload(
        name="ER2", per_game_cents=500, per_hour_cents=0, deposit_pct_bps=2000), CM), 201)
    lane = validate_success(api.create_lane(create_lane_payload(), CM), 201)
    cust = validate_success(api.create_customer(create_customer_payload(), FD), 201)
    res = validate_success(api.create_reservation(create_reservation_payload(
        cust["id"], rc["id"], resource_kind="LANE", lane_id=lane["id"],
        pricing_mode="PER_GAME",
        start_at="2026-09-29T18:00:00.000Z", end_at="2026-09-29T19:00:00.000Z",
        bowler_count=2, game_count=1), FD), 201)
    resp = api.waitlist_reservation(res["id"], FD)
    validate_error(resp, "ERR_NOT_WAITLISTED", expected_status=409)
