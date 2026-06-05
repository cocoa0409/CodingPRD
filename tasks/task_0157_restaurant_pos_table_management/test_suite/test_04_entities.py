"""Entity creation, retrieval, listing, not-found, required-field/enum validation,
immutable line-detail records, referential capacity, and FK reverse-reachability.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_server_headers,
    create_restaurant_payload, set_clock_payload, create_menu_item_payload,
    create_table_payload, create_staff_member_payload, create_seating_payload,
    create_check_payload, create_course_payload, create_order_item_payload,
    create_item_modifier_payload, create_staff_shift_payload,
    create_tip_pool_payload, create_payment_payload,
    setup_building_course, setup_closed_check_with_tip,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]
SERVER_SHARED = TEST_USERS["server_headers"]
KITCHEN = TEST_USERS["kitchen_headers"]


def test_create_restaurant_applies_config_defaults(api):
    """PRD §3.1: "The creator may also override four pricing-policy defaults:
    large_party_threshold, the party size at or above which auto-gratuity applies,
    which defaults to 8 and must be at least 2; auto_gratuity_bps, the gratuity
    rate for large parties, defaulting to 2000 and capped at 5000; comp_cap_bps,
    the ceiling on total comps for one check as a fraction of its pre-comp
    subtotal, defaulting to 10000 (one hundred percent) and never above 10000".

    Design: Corner/entities/create_restaurant_returns_201_with_config_defaults
    """
    data = validate_success(api.create_restaurant(
        create_restaurant_payload(name="Bistro", tax_rate_bps=875), MANAGER),
        expected_status=201)
    assert data["large_party_threshold"] == 8
    assert data["auto_gratuity_bps"] == 2000
    assert data["comp_cap_bps"] == 10000
    assert data["version"] == 1


def test_get_menu_item_returns_computed_count(api):
    """PRD §3.1: "The menu item also defines its starting eighty-six count through
    initial_available_count (zero or more), which seeds the live available_count.
    The computed flag is_86 is true exactly when available_count reaches zero."

    Design: Corner/entities/get_menu_item_returns_stored_fields_and_computed_count
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Fries", station="FRY", base_price_cents=400,
        happy_hour_price_cents=300, initial_available_count=4), MANAGER))
    data = validate_success(api.get_menu_item(mi["id"], SERVER_SHARED))
    assert data["available_count"] == 4
    assert data["is_86"] is False


def test_list_menu_items_paginated_envelope(api):
    """PRD §2.3: "The meta block of a list response carries the pagination fields
    limit, offset, total_count, and has_more, where total_count reflects the full
    size of the filtered set before pagination and has_more indicates whether
    additional records remain beyond the current page."

    Design: Corner/entities/list_menu_items_paginated_envelope
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    api.create_menu_item(create_menu_item_payload(
        r["id"], name="A", station="GRILL", base_price_cents=100,
        happy_hour_price_cents=100, initial_available_count=1), MANAGER)
    api.create_menu_item(create_menu_item_payload(
        r["id"], name="B", station="GRILL", base_price_cents=200,
        happy_hour_price_cents=200, initial_available_count=1), MANAGER)
    data, meta = validate_paginated(
        api.list_menu_items(MANAGER, params={"restaurant_id": r["id"], "limit": 1}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_check_nonexistent_returns_not_found(api):
    """PRD §2.6: "the first identifier that resolves to no existing resource causes
    the request to be rejected with ERR_NOT_FOUND (HTTP 404) before any later
    reference is checked."

    Design: Corner/entities/get_check_nonexistent_id_returns_not_found
    """
    get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    validate_error(api.get_check("00000000-0000-4000-8000-000000000000", MANAGER),
                   ApiErrorId.ERR_NOT_FOUND.value)


def test_create_menu_item_missing_required_field_invalid(api):
    """PRD §2.6: "every required field must be present and well-typed and every
    enum-valued field must carry a legal value, failing which the request is
    rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_menu_item_missing_required_field_returns_invalid_request
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    # Omit base_price_cents (required, no default).
    payload = {"restaurant_id": r["id"], "name": "X", "station": "GRILL",
               "happy_hour_price_cents": 100, "initial_available_count": 1}
    validate_error(api.create_menu_item(payload, MANAGER),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_menu_item_bad_enum_station_invalid(api):
    """PRD §3.1: "a kitchen-routing station that is one of GRILL, FRY, SAUTE, COLD,
    BAR, or EXPO".
    PRD §2.6: "every enum-valued field must carry a legal value, failing which the
    request is rejected with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_menu_item_bad_enum_station_returns_invalid_request
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    validate_error(api.create_menu_item(create_menu_item_payload(
        r["id"], name="X", station="OVEN", base_price_cents=100,
        happy_hour_price_cents=100, initial_available_count=1), MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_order_item_created_with_pending_status(api):
    """PRD §3.4: "The Server adds order items to a building course, each citing
    restaurant_id, the course_id, the menu_item_id ordered, and a quantity of at
    least one; a new item's status is PENDING."

    Design: Corner/entities/order_item_system_fields_generated_input_ignored
    """
    ctx = setup_building_course(clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        ctx["restaurant"]["id"], station="GRILL", base_price_cents=1000,
        happy_hour_price_cents=1000, initial_available_count=5), MANAGER))
    data = validate_success(api.create_order_item(create_order_item_payload(
        ctx["restaurant"]["id"], ctx["course"]["id"], mi["id"], quantity=1),
        ctx["server_headers"]), expected_status=201)
    assert data["status"] == "PENDING"


def test_item_modifier_carries_no_version_field(api):
    """PRD §2.4: "Two entities are immutable line-detail records and therefore
    carry only id and created_at, with no updated_at and no version: the item
    modifier and the tip allocation."

    Design: Corner/entities/item_modifier_immutable_no_version_field
    """
    ctx = setup_building_course(clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        ctx["restaurant"]["id"], station="GRILL", base_price_cents=1000,
        happy_hour_price_cents=1000, initial_available_count=5), MANAGER))
    oi = get_success_data(api.create_order_item(create_order_item_payload(
        ctx["restaurant"]["id"], ctx["course"]["id"], mi["id"], quantity=1),
        ctx["server_headers"]))
    data = validate_success(api.create_item_modifier(create_item_modifier_payload(
        ctx["restaurant"]["id"], oi["id"], name="no salt", surcharge_cents=0),
        ctx["server_headers"]), expected_status=201)
    assert "version" not in data, "item modifier must carry no version field"


def test_seating_party_size_over_capacity_referential(api):
    """PRD §3.3: "The seated party_size must not exceed the table's capacity, and
    the seating's table must belong to the same restaurant as the seating — a
    violation of the capacity rule is rejected with ERR_CAPACITY_EXCEEDED
    (HTTP 409)."

    Design: Corner/entities/seating_party_size_exceeds_table_capacity_referential
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-03T12:00:00Z"), MANAGER)
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    validate_error(
        api.create_seating(create_seating_payload(r["id"], tbl["id"], party_size=6), HOST),
        ApiErrorId.ERR_CAPACITY_EXCEEDED.value)


def test_courses_discoverable_by_check_id_filter(api):
    """PRD §2.6: "A child resource is therefore reached not by path nesting but by
    a filtered list — for example, the courses of a check are retrieved by listing
    courses filtered on check_id".

    Design: Corner/entities/fk_reverse_reachability_courses_by_check
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    tbl = get_success_data(api.create_table(create_table_payload(
        r["id"], table_number="T1", capacity=4), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Sam", role="SERVER", tip_weight_bps=10000), MANAGER))
    sh = make_server_headers(sm["id"])
    seat = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST))
    chk = get_success_data(api.create_check(create_check_payload(
        r["id"], seat["id"], sm["id"], party_size=2), sh))
    crs = get_success_data(api.create_course(create_course_payload(
        r["id"], chk["id"], course_number=1), sh))
    data, _ = validate_paginated(api.list_courses(sh, params={"check_id": chk["id"]}))
    ids = [c["id"] for c in data]
    assert ids == [crs["id"]], f"check filter must return exactly the one course, got {ids}"


def test_tip_allocations_discoverable_by_pool_id_filter(api):
    """PRD §3.8: "A Manager may list tip pools by restaurant_id and business_date,
    and tip allocations by restaurant_id, tip_pool_id, and staff_shift_id."

    Design: Corner/entities/fk_reverse_reachability_tip_allocations_by_pool
    """
    # Single SERVER shift → one allocation receiving the full 6000.
    ctx = setup_closed_check_with_tip(
        tip_cents=6000, business_date="2026-06-01",
        clock_iso="2026-06-01T20:00:00Z", distribution_mode="EVEN_BY_HOURS",
        name="R", tax_rate_bps=0)
    api.distribute_tip_pool(ctx["pool"]["id"], MANAGER)
    data, _ = validate_paginated(
        api.list_tip_allocations(MANAGER, params={"tip_pool_id": ctx["pool"]["id"]}))
    assert len(data) == 1, f"single shift must yield one allocation, got {len(data)}"
    assert data[0]["amount_cents"] == 6000
