"""Composite setup helpers.

Every test runs against a freshly-restarted, empty server, so these helpers build
all preconditions from scratch using only PRD-declared endpoints. They use the
lenient get_success_data() validator so setup failures surface as clear errors.

Roles: ShopManager (`_sm`) and Associate (`_assoc`) are opaque operators; Instructor
and Member are entity-backed and threaded via make_*_headers with the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_instructor_headers, make_member_headers
from .factories import (
    create_product_payload, create_member_payload, create_instructor_payload,
    create_service_bay_payload, create_rental_unit_payload, create_board_build_payload,
    create_service_order_payload, create_rental_payload, create_lesson_payload,
    create_trade_in_payload, create_special_order_payload, create_event_payload,
)

_sm = TEST_USERS["shop_manager_headers"]
_assoc = TEST_USERS["associate_headers"]


# ------------------------------------------------------------------ simple builders
def create_product(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_product(create_product_payload(**overrides), _sm))


def create_active_product(api=api_client, unit_price_cents=6000, stock_on_hand=5,
                          buildable_component=True, category="DECK", **overrides) -> dict:
    return create_product(
        api, unit_price_cents=unit_price_cents, stock_on_hand=stock_on_hand,
        buildable_component=buildable_component, category=category, **overrides,
    )


def create_member(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_member(create_member_payload(**overrides), _sm))


def create_instructor(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_instructor(create_instructor_payload(**overrides), _sm))


def create_service_bay(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_service_bay(create_service_bay_payload(**overrides), _sm))


def create_rental_unit(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_rental_unit(create_rental_unit_payload(**overrides), _sm))


def set_clock(api=api_client, to_iso8601="2026-07-01T00:00:00Z") -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, _sm))


# -------------------------------------------------------------------- board builds
def create_draft_build(api=api_client, member_id=None, component_lines=None,
                       member_tier="STANDARD") -> dict:
    """Create a member (unless member_id given) + a DRAFT build with the given lines."""
    if member_id is None:
        member_id = create_member(api, tier=member_tier)["id"]
    payload = create_board_build_payload(member_id, component_lines)
    return get_success_data(api.create_board_build(payload, _assoc))


def create_build_in_state(api=api_client, target_state="DRAFT", lines_spec=None,
                          member=None, member_tier="STANDARD"):
    """Build a BoardBuild walked to target_state.

    lines_spec: list of dicts {price, qty, stock, category}. Defaults to one deck
    priced 6000, stock 5, qty 1. Products are ACTIVE + buildable.

    Returns (build, member, products) where products is the list of component products.
    """
    if lines_spec is None:
        lines_spec = [{"price": 6000, "qty": 1, "stock": 5, "category": "DECK"}]
    if member is None:
        member = create_member(api, tier=member_tier)

    products = []
    component_lines = []
    for spec in lines_spec:
        prod = create_active_product(
            api, unit_price_cents=spec["price"], stock_on_hand=spec.get("stock", 5),
            category=spec.get("category", "DECK"),
        )
        products.append(prod)
        component_lines.append({"product_id": prod["id"], "qty": spec["qty"]})

    build = get_success_data(api.create_board_build(
        create_board_build_payload(member["id"], component_lines), _assoc))

    order = ["DRAFT", "COMPONENTS_RESERVED", "ASSEMBLED", "SETUP_COMPLETE", "COMPLETED"]
    steps = {
        "COMPONENTS_RESERVED": api.reserve_board_build,
        "ASSEMBLED": api.assemble_board_build,
        "SETUP_COMPLETE": api.setup_board_build,
        "COMPLETED": api.complete_board_build,
    }
    target_idx = order.index(target_state)
    for state in order[1:target_idx + 1]:
        build = get_success_data(steps[state](build["id"], _assoc))

    return build, member, products


# ----------------------------------------------------------------- loyalty points
def create_member_with_points(api=api_client, points=300, tier="STANDARD") -> dict:
    """Return a member holding exactly `points` loyalty points, earned by completing
    a STANDARD lesson whose fee is points*100 (multiplier 1, no cap for points<=500)."""
    member = create_member(api, tier=tier)
    instructor = create_instructor(api, discipline="SKATE")
    fee = points * 100
    lesson = get_success_data(api.create_lesson(create_lesson_payload(
        member["id"], instructor["id"], "SKATE",
        "2026-07-02T08:00:00Z", "2026-07-02T09:00:00Z", fee), _assoc))
    api.confirm_lesson(lesson["id"], _sm)
    api.complete_lesson(lesson["id"], _sm)
    return get_success_data(api.get_member(member["id"], _sm))


# --------------------------------------------------------------------- trade-ins
def create_appraised_tradein(api=api_client, appraised_value_cents=10000, member=None):
    """Return (tradein, member) with the trade-in in APPRAISED state."""
    if member is None:
        member = create_member(api)
    ti = get_success_data(api.create_trade_in(create_trade_in_payload(member["id"]), _assoc))
    ti = get_success_data(api.appraise_trade_in(
        ti["id"], {"appraised_value_cents": appraised_value_cents}, _sm))
    return ti, member


def create_listed_tradein(api=api_client, appraised_value_cents=10000,
                          list_price_cents=20000, member=None):
    """Return (tradein, member) with the trade-in APPRAISED then LISTED."""
    ti, member = create_appraised_tradein(api, appraised_value_cents, member)
    ti = get_success_data(api.list_for_consignment(
        ti["id"], {"list_price_cents": list_price_cents}, _assoc))
    return ti, member


# ---------------------------------------------------------------------- rentals
def create_reserved_rental(api=api_client, start_date="2026-07-10", end_date="2026-07-12",
                           daily_rate_cents=2500, member=None, unit=None, **overrides):
    """Return (rental, member, unit) with the rental in RESERVED state."""
    if member is None:
        member = create_member(api)
    if unit is None:
        unit = create_rental_unit(api, daily_rate_cents=daily_rate_cents)
    rental = get_success_data(api.create_rental(create_rental_payload(
        member["id"], unit["id"], start_date, end_date, **overrides), _assoc))
    return rental, member, unit


def create_checked_out_rental(api=api_client, start_date="2026-07-10", end_date="2026-07-12",
                              daily_rate_cents=2500, member=None, unit=None):
    """Return (rental, member, unit) with the rental CHECKED_OUT."""
    rental, member, unit = create_reserved_rental(
        api, start_date, end_date, daily_rate_cents, member, unit)
    rental = get_success_data(api.checkout_rental(rental["id"], _assoc))
    return rental, member, unit


# --------------------------------------------------------------------- lessons
def create_booked_lesson(api=api_client, discipline="SKATE", fee_cents=5000,
                         start_at="2026-07-09T10:00:00Z", end_at="2026-07-09T11:00:00Z",
                         member=None, instructor=None):
    """Return (lesson, member, instructor) with the lesson in BOOKED state."""
    if member is None:
        member = create_member(api)
    if instructor is None:
        instructor = create_instructor(api, discipline=discipline)
    lesson = get_success_data(api.create_lesson(create_lesson_payload(
        member["id"], instructor["id"], discipline, start_at, end_at, fee_cents), _assoc))
    return lesson, member, instructor


# ---------------------------------------------------------------- service orders
def create_scheduled_service_order(api=api_client, service_type="GRIP", parts_spec=None,
                                   slot_start="2026-07-05T10:00:00Z",
                                   slot_end="2026-07-05T10:45:00Z",
                                   member=None, bay=None, build_id=None):
    """Return (order, member, bay, part_products).

    parts_spec: list of dicts {price, qty, stock, category} for parts products.
    """
    if member is None:
        member = create_member(api)
    if bay is None:
        bay = create_service_bay(api)

    part_products = []
    parts_lines = []
    if parts_spec:
        for spec in parts_spec:
            prod = create_product(
                api, unit_price_cents=spec["price"], stock_on_hand=spec.get("stock", 5),
                category=spec.get("category", "WAX"), buildable_component=False,
            )
            part_products.append(prod)
            parts_lines.append({"product_id": prod["id"], "qty": spec["qty"]})

    overrides = {}
    if parts_lines:
        overrides["parts_lines"] = parts_lines
    if build_id is not None:
        overrides["build_id"] = build_id

    order = get_success_data(api.create_service_order(create_service_order_payload(
        member["id"], bay["id"], service_type, slot_start, slot_end, **overrides), _assoc))
    return order, member, bay, part_products


# -------------------------------------------------------------- special orders
def create_quoted_special_order(api=api_client, quoted_price_cents=12000, member=None):
    """Return (order, member) with the order quoted once (version advanced 1 -> 2)."""
    if member is None:
        member = create_member(api)
    order = get_success_data(api.create_special_order(
        create_special_order_payload(member["id"], product_name="Custom trucks"), _assoc))
    v0 = order["version"]
    order = get_success_data(api.quote_special_order(
        order["id"],
        {"quoted_price_cents": quoted_price_cents, "expected_special_order_version": v0},
        _assoc))
    return order, member, v0


# ------------------------------------------------------------ events / registration
def create_open_event(api=api_client, capacity=5, entry_points_cost=0, **overrides) -> dict:
    return get_success_data(api.create_event(
        create_event_payload(capacity=capacity, entry_points_cost=entry_points_cost,
                             **overrides), _sm))


def create_event_with_registration(api=api_client, capacity=5, entry_points_cost=0,
                                   member=None):
    """Return (event, registration, member) with the member REGISTERED for an OPEN event."""
    if member is None:
        member = create_member(api)
    event = create_open_event(api, capacity=capacity, entry_points_cost=entry_points_cost)
    reg = get_success_data(api.register_event(event["id"], {"member_id": member["id"]}, _assoc))
    return event, reg, member
