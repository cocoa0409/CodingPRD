"""Composite setup helpers for the Restaurant POS API.

Each test runs against a freshly-restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Fixtures use
get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: the Server role is entity-backed (X-User-ID is the acting
StaffMember.id). Every ownership-gated Server call here uses
make_server_headers(staff_member_id) with the real StaffMember id — never the
shared TEST_USERS["server_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_server_headers
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]
KITCHEN = TEST_USERS["kitchen_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity primitives
# ---------------------------------------------------------------------------
def create_restaurant(clock_iso=None, **overrides):
    """Create a restaurant and optionally advance its clock.

    Returns the restaurant dict (re-fetched after the clock set, so current_utc
    reflects the advance)."""
    r = get_success_data(api_client.create_restaurant(
        f.create_restaurant_payload(**overrides), MANAGER))
    if clock_iso is not None:
        r = get_success_data(api_client.set_clock(
            f.set_clock_payload(r["id"], clock_iso), MANAGER))
    return r


def create_menu_item(restaurant_id, **overrides):
    return get_success_data(api_client.create_menu_item(
        f.create_menu_item_payload(restaurant_id, **overrides), MANAGER))


def create_table(restaurant_id, **overrides):
    return get_success_data(api_client.create_table(
        f.create_table_payload(restaurant_id, **overrides), MANAGER))


def create_staff_member(restaurant_id, **overrides):
    return get_success_data(api_client.create_staff_member(
        f.create_staff_member_payload(restaurant_id, **overrides), MANAGER))


def create_happy_hour_window(restaurant_id, **overrides):
    return get_success_data(api_client.create_happy_hour_window(
        f.create_happy_hour_window_payload(restaurant_id, **overrides), MANAGER))


def create_waitlist_entry(restaurant_id, **overrides):
    return get_success_data(api_client.create_waitlist_entry(
        f.create_waitlist_payload(restaurant_id, **overrides), HOST))


def create_seating(restaurant_id, table_id, **overrides):
    return get_success_data(api_client.create_seating(
        f.create_seating_payload(restaurant_id, table_id, **overrides), HOST))


def create_staff_shift(restaurant_id, staff_id, **overrides):
    return get_success_data(api_client.create_staff_shift(
        f.create_staff_shift_payload(restaurant_id, staff_id, **overrides), MANAGER))


def create_tip_pool(restaurant_id, business_date, **overrides):
    return get_success_data(api_client.create_tip_pool(
        f.create_tip_pool_payload(restaurant_id, business_date, **overrides), MANAGER))


# ---------------------------------------------------------------------------
# Tier 2: floor + check setup helpers
# ---------------------------------------------------------------------------
def setup_seated_restaurant(clock_iso="2026-06-02T10:00:00Z", table_capacity=4,
                            party_size=2, **rest_overrides):
    """Restaurant (clock set) + one table + one SERVER StaffMember + one walk-in
    seating. Returns dict with keys: restaurant, table, staff, seating, server_headers."""
    r = create_restaurant(clock_iso=clock_iso, **rest_overrides)
    table = create_table(r["id"], capacity=table_capacity)
    staff = create_staff_member(r["id"])
    seating = create_seating(r["id"], table["id"], party_size=party_size)
    return {
        "restaurant": r,
        "table": table,
        "staff": staff,
        "seating": seating,
        "server_headers": make_server_headers(staff["id"]),
    }


def setup_open_check(clock_iso="2026-06-02T10:00:00Z", table_capacity=4,
                     party_size=2, **rest_overrides):
    """Floor setup + an OPEN check owned by the Server StaffMember.

    Returns dict adding `check` to the setup_seated_restaurant bundle."""
    ctx = setup_seated_restaurant(clock_iso=clock_iso, table_capacity=table_capacity,
                                  party_size=party_size, **rest_overrides)
    check = get_success_data(api_client.create_check(
        f.create_check_payload(ctx["restaurant"]["id"], ctx["seating"]["id"],
                               ctx["staff"]["id"], party_size=party_size),
        ctx["server_headers"]))
    ctx["check"] = check
    return ctx


def setup_building_course(clock_iso="2026-06-02T10:00:00Z", table_capacity=4,
                          party_size=2, **rest_overrides):
    """OPEN check + one BUILDING course (number 1). Returns bundle adding `course`."""
    ctx = setup_open_check(clock_iso=clock_iso, table_capacity=table_capacity,
                           party_size=party_size, **rest_overrides)
    course = get_success_data(api_client.create_course(
        f.create_course_payload(ctx["restaurant"]["id"], ctx["check"]["id"],
                                course_number=1),
        ctx["server_headers"]))
    ctx["course"] = course
    return ctx


def add_order_item(ctx, course_id, menu_item_id, quantity=1):
    """Add one PENDING order item to a building course. Returns the item dict."""
    return get_success_data(api_client.create_order_item(
        f.create_order_item_payload(ctx["restaurant"]["id"], course_id, menu_item_id,
                                    quantity=quantity),
        ctx["server_headers"]))


def add_modifier(ctx, order_item_id, name="extra cheese", surcharge_cents=0):
    return get_success_data(api_client.create_item_modifier(
        f.create_item_modifier_payload(ctx["restaurant"]["id"], order_item_id,
                                       name=name, surcharge_cents=surcharge_cents),
        ctx["server_headers"]))


def fire_course(ctx, course_id):
    return get_success_data(api_client.fire_course(course_id, ctx["server_headers"]))


# ---------------------------------------------------------------------------
# Tier 3: a single fired item on its own check (the most common "money" preamble)
# ---------------------------------------------------------------------------
def setup_fired_single_item(base_price_cents=1000, happy_hour_price_cents=None,
                            quantity=1, initial_available_count=50,
                            clock_iso="2026-06-02T10:00:00Z", party_size=2,
                            table_capacity=4, station="GRILL", **rest_overrides):
    """Restaurant + menu item + floor + OPEN check + one fired course holding one
    order item.

    Returns dict with: restaurant, table, staff, seating, server_headers, check,
    course, menu_item, order_item. The course is FIRED."""
    if happy_hour_price_cents is None:
        happy_hour_price_cents = base_price_cents
    ctx = setup_building_course(clock_iso=clock_iso, table_capacity=table_capacity,
                                party_size=party_size, **rest_overrides)
    mi = create_menu_item(ctx["restaurant"]["id"], station=station,
                          base_price_cents=base_price_cents,
                          happy_hour_price_cents=happy_hour_price_cents,
                          initial_available_count=initial_available_count)
    oi = add_order_item(ctx, ctx["course"]["id"], mi["id"], quantity=quantity)
    fire_course(ctx, ctx["course"]["id"])
    ctx["menu_item"] = mi
    ctx["order_item"] = oi
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: floor cascade state (dirty table / waitlist)
# ---------------------------------------------------------------------------
def setup_dirty_table(clock_iso="2026-06-03T12:00:00Z", table_capacity=4,
                      seating_party_size=2, **rest_overrides):
    """Restaurant + table seated by a walk-in then cleared → table is DIRTY.

    Returns dict: restaurant, table, seating, table_version (live version read
    after clear, ready to pass as expected_table_version on buss)."""
    r = create_restaurant(clock_iso=clock_iso, **rest_overrides)
    table = create_table(r["id"], capacity=table_capacity)
    seating = create_seating(r["id"], table["id"], party_size=seating_party_size)
    get_success_data(api_client.clear_seating(seating["id"], HOST))
    tv = get_success_data(api_client.get_table(table["id"], HOST))["version"]
    return {"restaurant": r, "table": table, "seating": seating, "table_version": tv}


# ---------------------------------------------------------------------------
# Tier 5: tip-pool lifecycle (closed check → pool → distribute)
# ---------------------------------------------------------------------------
def setup_closed_check_with_tip(tip_cents, business_date, clock_iso,
                                distribution_mode="EVEN_BY_HOURS",
                                shifts=None, **rest_overrides):
    """Restaurant + staff/shifts + one fired/presented/paid/closed check whose tip
    flows into a tip pool for `business_date`.

    `shifts` is a list of dicts each with role/tip_weight_bps/clock_in_minute/
    clock_out_minute. The first shift's staff member owns the check. If `shifts`
    is None a single SERVER shift 600..1080 is created.

    Returns dict: restaurant, staff (list), shifts (list), pool, check,
    server_headers."""
    if shifts is None:
        shifts = [{"role": "SERVER", "tip_weight_bps": 10000,
                   "clock_in_minute": 600, "clock_out_minute": 1080}]
    r = create_restaurant(clock_iso=clock_iso, **rest_overrides)
    staff_list = []
    shift_list = []
    for i, s in enumerate(shifts):
        sm = create_staff_member(r["id"], name=f"Staff{i}", role=s["role"],
                                 tip_weight_bps=s["tip_weight_bps"])
        staff_list.append(sm)
        sh = create_staff_shift(r["id"], sm["id"], business_date=business_date,
                                clock_in_minute=s["clock_in_minute"],
                                clock_out_minute=s["clock_out_minute"])
        shift_list.append(sh)
    server = staff_list[0]
    server_headers = make_server_headers(server["id"])

    mi = create_menu_item(r["id"], name="Soda", station="BAR",
                          base_price_cents=500, happy_hour_price_cents=500,
                          initial_available_count=50)
    table = create_table(r["id"], capacity=4)
    seating = create_seating(r["id"], table["id"], party_size=2)
    check = get_success_data(api_client.create_check(
        f.create_check_payload(r["id"], seating["id"], server["id"], party_size=2),
        server_headers))
    course = get_success_data(api_client.create_course(
        f.create_course_payload(r["id"], check["id"], course_number=1), server_headers))
    get_success_data(api_client.create_order_item(
        f.create_order_item_payload(r["id"], course["id"], mi["id"], quantity=1),
        server_headers))
    get_success_data(api_client.fire_course(course["id"], server_headers))
    pool = create_tip_pool(r["id"], business_date, distribution_mode=distribution_mode)
    get_success_data(api_client.present_check(check["id"], server_headers))
    get_success_data(api_client.create_payment(
        f.create_payment_payload(r["id"], check["id"], amount_cents=500,
                                 tip_cents=tip_cents, method="CARD"),
        server_headers))
    get_success_data(api_client.close_check(check["id"], server_headers))
    return {
        "restaurant": r,
        "staff": staff_list,
        "shifts": shift_list,
        "pool": pool,
        "check": check,
        "server_headers": server_headers,
    }
