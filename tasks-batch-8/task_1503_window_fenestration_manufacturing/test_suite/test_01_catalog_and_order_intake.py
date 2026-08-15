"""Catalog foundations, dealer onboarding, and order intake (PRD §3.1–§3.2)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line,
    assert_dealer,
    assert_order_line,
    assert_window_order,
    create_a050_series_payload,
    create_catalog_series_payload,
    create_dealer,
    create_draft_order,
    create_glass_gp1,
    create_order_line_payload,
    create_series_v200,
    get_success_data,
    setup_mn_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
PE = TEST_USERS["plant_engineer_headers"]


def test_dealer_created_with_credit_active_default(api):
    """PRD §3.1: "Every dealer begins life with `credit_status` set to `ACTIVE`."
    PRD §2.5: "At server start the clock reads exactly `2026-08-01T00:00:00Z`, and
    the server never falls back to real time for any computation."

    Design: Corner/entities/dealer_created_with_credit_active_default
    """
    res = api.create_dealer({"name": "NorthStar", "ship_to_state_code": "MN"}, PM)
    dealer = validate_success(res, 201)
    assert_dealer(dealer)
    assert dealer["credit_status"] == "ACTIVE"
    assert isinstance(dealer["version"], int)
    assert dealer["created_at"].startswith("2026-08-01T00:00:00"), (
        f"created_at must be stamped from the logical clock, got {dealer['created_at']!r}"
    )


def test_order_defaults_ship_to_from_dealer_and_initial_states(api):
    """PRD §3.2: "A `DealerRep` opens an order for their own dealership — or a
    `PlantManager` on any dealer's behalf — by supplying the `dealer_id`, the
    `order_date`, and optionally a `ship_to_state_code`; when the destination is
    omitted it defaults to the dealer's own `ship_to_state_code`."
    PRD §3.2: "A new order starts with `production_status` `DRAFT` and
    `compliance_status` `PENDING`; its `wave_id` and `delivered_at` are null, its
    money fields `subtotal_cents`, `discount_cents`, and `total_price_cents` are
    zero, and `promised_date` stays null until the first line exists."

    Design: Corner/entities/order_defaults_ship_to_from_dealer_and_initial_states
    """
    dealer = create_dealer(name="NorthStar", state="MN")
    res = api.create_order(
        {"dealer_id": dealer["id"], "order_date": "2026-08-02T00:00:00Z"}, PM
    )
    order = validate_success(res, 201)
    assert_window_order(order)
    assert order["ship_to_state_code"] == "MN"
    assert order["production_status"] == "DRAFT"
    assert order["compliance_status"] == "PENDING"
    assert order["subtotal_cents"] == 0
    assert order["discount_cents"] == 0
    assert order["total_price_cents"] == 0
    assert order["promised_date"] is None
    assert order["wave_id"] is None
    assert order["delivered_at"] is None


def test_line_create_rejects_invalid_shape_enum(api):
    """PRD §2.10: "required fields are present, types are valid, enum values are
    members of their enumeration, `width_in` and `height_in` are greater than
    zero, `quantity` is at least 1, a `CIRCLE` line has `width_in` equal to
    `height_in`, and a `failure_date` is not later than the current logical time;
    failures return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/line_create_rejects_invalid_shape_enum
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])
    payload = create_order_line_payload(
        cat["series"]["id"], cat["glass"]["id"], shape="HEXAGON"
    )
    res = api.add_order_line(order["id"], payload, PM)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    lines, meta = validate_paginated(api.list_order_lines(order["id"], PM))
    assert meta["total_count"] == 0, "rejected line must not be persisted"


def test_circle_shape_requires_equal_dimensions(api):
    """PRD §3.2: "a `CIRCLE` line requires `width_in` equal to `height_in`".
    PRD §3.2: "Its per-unit `glazing_sqft` is the width times the height divided
    by 144, scaled by the shape's area factor — 1.0 for `RECTANGLE`, 0.85 for
    `ARCH`, 0.785 for `CIRCLE`, and 0.9 for `TRAPEZOID` — rounded half-up to two
    decimal places."

    Design: Corner/entities/circle_shape_requires_equal_dimensions
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])

    bad = api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"],
            shape="CIRCLE", width_in=30, height_in=36,
        ),
        PM,
    )
    validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    ok = api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"],
            shape="CIRCLE", width_in=30, height_in=30,
        ),
        PM,
    )
    line = validate_success(ok, 201)
    assert_order_line(line)
    # glazing = round_half_up(30*30/144*0.785, 2) = 4.91; billable = max(4.91, 3.0)
    assert line["glazing_sqft"] == pytest.approx(4.91, abs=0.001)
    # per-unit: 60*1500*1.40 + 4.91*900 = 126000 + 4419 = 130419
    assert line["line_total_cents"] == 130419


def test_size_cap_exceeded_returns_422(api):
    """PRD §3.2: "The series must still be `ACTIVE` (a discontinued series yields
    `ERR_SERIES_DISCONTINUED`), and the configured size must fit the series: a
    line whose united inches exceed the series' `max_united_inches` is rejected
    with `ERR_SIZE_EXCEEDS_SERIES_LIMIT` (HTTP 422) — a line exactly at the cap
    fits."

    Design: Corner/validations/size_cap_exceeded_returns_422
    """
    cat = setup_mn_catalog()
    order = create_draft_order(cat["dealer"]["id"])

    too_big = api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"], width_in=60, height_in=61
        ),
        PM,
    )
    validate_error(too_big, ApiErrorId.ERR_SIZE_EXCEEDS_SERIES_LIMIT, expected_status=422)

    at_cap = api.add_order_line(
        order["id"],
        create_order_line_payload(
            cat["series"]["id"], cat["glass"]["id"], width_in=60, height_in=60
        ),
        PM,
    )
    line = validate_success(at_cap, 201)
    assert line["united_inches"] == 120


def test_series_discontinue_side_effect_blocks_new_lines(api):
    """PRD §3.1: "A series starts `ACTIVE`; discontinuing it moves it to
    `DISCONTINUED`, after which creating or reconfiguring a line with that series
    is rejected with `ERR_SERIES_DISCONTINUED`. Lines already written against the
    series are unaffected."

    Design: Corner/state_machines/series_discontinue_side_effect_blocks_new_lines
    """
    series = create_series_v200()
    glass = create_glass_gp1()
    dealer = create_dealer()
    order1 = create_draft_order(dealer["id"])
    add_line(order1["id"], series["id"], glass["id"])

    validate_success(api.discontinue_catalog_series(series["id"], PE), 200)

    order2 = create_draft_order(dealer["id"], order_date="2026-08-03T00:00:00Z")
    blocked = api.add_order_line(
        order2["id"], create_order_line_payload(series["id"], glass["id"]), PM
    )
    validate_error(blocked, ApiErrorId.ERR_SERIES_DISCONTINUED, expected_status=409)

    confirmed = validate_success(api.confirm_order(order1["id"], PM), 200)
    assert confirmed["production_status"] == "CONFIRMED", (
        "pre-existing line on a discontinued series must remain confirmable"
    )


def test_orders_list_pagination_and_dealer_filter(api):
    """PRD §3.2: "The orders list can be filtered by `dealer_id`, `wave_id`, or
    `production_status`."
    PRD §2.3: "Paginated and non-paginated list-based responses include the
    following fields in the `meta` object of the response envelope: `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/orders_list_pagination_and_dealer_filter
    """
    dealer_a = create_dealer(name="A", state="MN")
    dealer_b = create_dealer(name="B", state="WI")
    for day in ("2026-08-02T00:00:00Z", "2026-08-03T00:00:00Z", "2026-08-04T00:00:00Z"):
        create_draft_order(dealer_a["id"], order_date=day)
    create_draft_order(dealer_b["id"])

    page1, meta1 = validate_paginated(
        api.list_orders(PM, params={"dealer_id": dealer_a["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_orders(PM, params={"dealer_id": dealer_a["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False
    assert all(row["dealer_id"] == dealer_a["id"] for row in page1 + page2)


def test_order_lines_filtered_by_series(api):
    """PRD §3.2: "Lines can be browsed per order, or across the plant filtered by
    `order_id`, `series_id`, `glass_package_id`, or `rack_id`."

    Design: Corner/endpoints/order_lines_filtered_by_series
    """
    v200 = create_series_v200()
    a050 = get_success_data(api.create_catalog_series(create_a050_series_payload(), PE))
    glass = create_glass_gp1()
    dealer = create_dealer()
    order1 = create_draft_order(dealer["id"])
    line_v = add_line(order1["id"], v200["id"], glass["id"])
    order2 = create_draft_order(dealer["id"])
    line_a = add_line(order2["id"], a050["id"], glass["id"], width_in=30, height_in=30)

    data, meta = validate_paginated(
        api.list_all_order_lines(PM, params={"series_id": v200["id"]})
    )
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == line_v["id"]
    assert data[0]["id"] != line_a["id"]


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.6: "the server validates the existence of each identifier in path
    order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier that does not correspond to an existing resource"

    Design: Corner/entities/get_nonexistent_order_returns_not_found
    """
    res = api.get_order(NON_EXISTENT_UUID, PM)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
