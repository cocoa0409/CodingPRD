"""Business-rule violations (empty course, underpaid, comp cap, empty pool),
action endpoints, KDS routing, auth/RBAC denials, optimistic concurrency on
bussing, and immediate tip-pool consistency at close.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_server_headers,
    create_restaurant_payload, set_clock_payload, create_menu_item_payload,
    create_table_payload, create_staff_member_payload, create_seating_payload,
    create_check_payload, create_course_payload, create_order_item_payload,
    create_staff_shift_payload, create_tip_pool_payload, create_payment_payload,
    buss_table_payload,
    setup_seated_restaurant, setup_building_course, setup_fired_single_item,
    setup_dirty_table,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]
KITCHEN = TEST_USERS["kitchen_headers"]


# ===========================================================================
# Section: validations
# ===========================================================================
def test_fire_empty_course_returns_empty_course(api):
    """PRD §3.4: "the course holds at least one PENDING order item — a course with
    no pending items cannot fire and is rejected with ERR_EMPTY_COURSE (HTTP 409)."

    Design: Corner/validations/empty_course_fire_returns_empty_course
    """
    ctx = setup_building_course(clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    validate_error(api.fire_course(ctx["course"]["id"], ctx["server_headers"]),
                   ApiErrorId.ERR_EMPTY_COURSE.value)


def test_close_underpaid_check_returns_underpaid(api):
    """PRD §3.7: "its amount_paid_cents must be greater than or equal to its
    total_due_cents, failing which it is rejected with ERR_UNDERPAID (HTTP 409)."

    Design: Corner/validations/close_underpaid_check_returns_underpaid
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    sh = ctx["server_headers"]
    api.present_check(ctx["check"]["id"], sh)
    api.create_payment(create_payment_payload(
        ctx["restaurant"]["id"], ctx["check"]["id"], amount_cents=500,
        tip_cents=0, method="CASH"), sh)
    validate_error(api.close_check(ctx["check"]["id"], sh),
                   ApiErrorId.ERR_UNDERPAID.value)


def test_comp_exceeding_cap_returns_comp_cap_exceeded(api):
    """PRD §3.5: "A comp whose addition would push comp_total_cents above that cap
    is rejected with ERR_COMP_CAP_EXCEEDED (HTTP 409)."

    Design: Corner/validations/comp_cap_exceeded_returns_comp_cap
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0, comp_cap_bps=5000), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    mix = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="X", station="GRILL", base_price_cents=1200,
        happy_hour_price_cents=1200, initial_available_count=50), MANAGER))
    miz = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Z", station="COLD", base_price_cents=700,
        happy_hour_price_cents=700, initial_available_count=50), MANAGER))
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
    oix = get_success_data(api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mix["id"], quantity=1), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], miz["id"], quantity=1), sh)
    api.fire_course(crs["id"], sh)
    # subtotal 1900; cap = floor(1900*5000/10000)=950; comp X (1200) > 950.
    validate_error(api.comp_order_item(oix["id"], MANAGER),
                   ApiErrorId.ERR_COMP_CAP_EXCEEDED.value)


def test_distribute_empty_pool_returns_pool_empty(api):
    """PRD §3.8: "a pool with no eligible tips or no shifts that day cannot
    distribute and is rejected with ERR_POOL_EMPTY (HTTP 409)."

    Design: Corner/validations/distribute_pool_with_zero_pooled_returns_pool_empty
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    sm = get_success_data(api.create_staff_member(create_staff_member_payload(
        r["id"], name="Srv", role="SERVER", tip_weight_bps=10000), MANAGER))
    api.create_staff_shift(create_staff_shift_payload(
        r["id"], sm["id"], business_date="2026-06-01",
        clock_in_minute=600, clock_out_minute=1080), MANAGER)
    pool = get_success_data(api.create_tip_pool(create_tip_pool_payload(
        r["id"], "2026-06-01", distribution_mode="EVEN_BY_HOURS"), MANAGER))
    validate_error(api.distribute_tip_pool(pool["id"], MANAGER),
                   ApiErrorId.ERR_POOL_EMPTY.value)


# ===========================================================================
# Section: endpoints
# ===========================================================================
def test_serve_endpoint_moves_fired_item_to_served(api):
    """PRD §3.5: "KitchenStaff mark a fired item done, moving it from FIRED to
    SERVED. This is purely a status change — no pricing recomputation, no portion
    restoration — legal only when the item's status is FIRED."

    Design: Corner/endpoints/serve_item_action_endpoint_transitions_fired_to_served
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    served = validate_success(api.serve_order_item(ctx["order_item"]["id"], KITCHEN))
    assert served["status"] == "SERVED"


def test_kds_lists_order_items_by_menu_item_filter(api):
    """PRD §3.4: "list order items filtered by restaurant_id, course_id,
    menu_item_id, and status — the latter is how the kitchen display pulls its
    station-routed stream."

    Design: Corner/endpoints/kds_routing_list_order_items_by_station_via_menu_item
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", station="GRILL", name="R", tax_rate_bps=0)
    data, _ = validate_paginated(api.list_order_items(
        KITCHEN, params={"menu_item_id": ctx["menu_item"]["id"], "status": "FIRED"}))
    ids = [(o["id"], o["status"]) for o in data]
    assert ids == [(ctx["order_item"]["id"], "FIRED")], \
        f"menu_item+status filter must return the one FIRED item, got {ids}"


# ===========================================================================
# Section: errors
# ===========================================================================
def test_protected_get_without_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing or blank on a protected endpoint, the
    request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Item", station="GRILL", base_price_cents=1000,
        happy_hour_price_cents=1000, initial_available_count=5), MANAGER))
    no_auth = {"Content-Type": "application/json"}
    validate_error(api.get_menu_item(mi["id"], no_auth),
                   ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Section: rbac
# ===========================================================================
def test_server_cannot_comp_item_forbidden(api):
    """PRD §2.1: "A Manager owns back-of-house authority: menu, schedule, table,
    and staff configuration; comps; item, check, and payment voids; and tip-pool
    distribution."

    Design: Corner/rbac/server_cannot_comp_item_forbidden
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0, comp_cap_bps=10000)
    # Server (the check owner) attempts a Manager-exclusive comp → 403.
    validate_error(api.comp_order_item(ctx["order_item"]["id"], ctx["server_headers"]),
                   ApiErrorId.ERR_FORBIDDEN.value)


def test_host_cannot_open_check_forbidden(api):
    """PRD §2.1: "A Server owns the order workflow for checks: courses, items,
    modifiers, firing, presenting, reopening, closing, splitting, and tendering
    payments."

    Design: Corner/rbac/host_cannot_open_check_forbidden
    """
    ctx = setup_seated_restaurant(clock_iso="2026-06-03T12:00:00Z", name="R", tax_rate_bps=0)
    validate_error(api.create_check(create_check_payload(
        ctx["restaurant"]["id"], ctx["seating"]["id"], ctx["staff"]["id"], party_size=2),
        HOST), ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Section: cross_cutting_complexity_layers
# ===========================================================================
def test_buss_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §3.3: "First, it returns the table from DIRTY to AVAILABLE and
    increments the table's version by one ... If no eligible waiting party exists,
    the table simply remains AVAILABLE."

    Design: Corner/cross_cutting_complexity_layers/buss_with_correct_table_version_succeeds_and_increments
    """
    dt = setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                           name="R", tax_rate_bps=0)
    tv = dt["table_version"]
    bussed = validate_success(api.buss_table(
        dt["table"]["id"], buss_table_payload(tv), HOST))
    assert bussed["occupancy_status"] == "AVAILABLE", \
        "no waitlist → table stays AVAILABLE after buss"
    assert bussed["version"] == tv + 1, \
        f"buss must increment version to {tv + 1}, got {bussed['version']}"


def test_buss_with_stale_version_returns_stale(api):
    """PRD §2.9: "If expected_table_version does not equal the table's current
    version — meaning another writer has advanced the table since the client read
    it, for instance by already bussing and re-seating it — the request is rejected
    with ERR_STALE_TABLE_VERSION (HTTP 412), and no promotion occurs."

    Design: Corner/cross_cutting_complexity_layers/buss_with_stale_table_version_returns_stale
    """
    dt = setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                           name="R", tax_rate_bps=0)
    r, tbl, tv = dt["restaurant"], dt["table"], dt["table_version"]
    # First buss with the correct version (bumps to tv+1).
    api.buss_table(tbl["id"], buss_table_payload(tv), HOST)
    # Re-dirty the table so a second buss is state-legal.
    seat2 = get_success_data(api.create_seating(create_seating_payload(
        r["id"], tbl["id"], party_size=2), HOST))
    api.clear_seating(seat2["id"], HOST)
    # Second buss still carrying the now-stale pre-buss version → 412.
    validate_error(api.buss_table(tbl["id"], buss_table_payload(tv), HOST),
                   ApiErrorId.ERR_STALE_TABLE_VERSION.value)


# ===========================================================================
# Section: consistency_model
# ===========================================================================
def test_close_contributes_tip_to_pool_immediately(api):
    """PRD §3.7: "Closing moves the check from PRESENTED to CLOSED and contributes
    the check's tip_cents to the tip pool for the close-day business date: the
    relevant pool is located (or created if none exists yet) and its pooled_cents
    is increased by the check's tip_cents."

    Design: Corner/consistency_model/close_check_contributes_tip_to_pool_in_same_request
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    api.set_clock(set_clock_payload(r["id"], "2026-06-02T10:00:00Z"), MANAGER)
    pool = get_success_data(api.create_tip_pool(create_tip_pool_payload(
        r["id"], "2026-06-02", distribution_mode="EVEN_BY_HOURS"), MANAGER))
    mi = get_success_data(api.create_menu_item(create_menu_item_payload(
        r["id"], name="Item", station="GRILL", base_price_cents=1000,
        happy_hour_price_cents=1000, initial_available_count=5), MANAGER))
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
    api.create_order_item(create_order_item_payload(
        r["id"], crs["id"], mi["id"], quantity=1), sh)
    api.fire_course(crs["id"], sh)
    api.present_check(chk["id"], sh)
    api.create_payment(create_payment_payload(
        r["id"], chk["id"], amount_cents=1000, tip_cents=300, method="CARD"), sh)
    api.close_check(chk["id"], sh)
    pool_after = get_success_data(api.get_tip_pool(pool["id"], MANAGER))
    assert pool_after["pooled_cents"] == 300, \
        f"tip must contribute atomically at close, got {pool_after['pooled_cents']}"
