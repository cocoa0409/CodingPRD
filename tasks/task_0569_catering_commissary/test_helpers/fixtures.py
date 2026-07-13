"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server database is empty
at the start of each test) using only PRD-declared endpoints. Setup calls use the
lenient get_success_data() validator so setup failures surface clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .constants import dt
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]
KITCHEN = TEST_USERS["kitchen_manager_headers"]
SALES = TEST_USERS["sales_manager_headers"]
CAPTAIN = TEST_USERS["event_captain_headers"]


# --------------------------------------------------------------------------
# Primitive creators
# --------------------------------------------------------------------------
def create_ingredient(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_ingredient(f.create_ingredient_payload(**overrides), ADMIN))


def create_menu_item(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_menu_item(f.create_menu_item_payload(**overrides), KITCHEN))


def add_recipe_line(api, menu_item_id, ingredient_id, **overrides) -> dict:
    return get_success_data(
        api.create_recipe_line(
            f.create_recipe_line_payload(menu_item_id, ingredient_id, **overrides), KITCHEN
        )
    )


def create_station(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_station(f.create_station_payload(**overrides), ADMIN))


def create_equipment_item(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_equipment_item(f.create_equipment_item_payload(**overrides), ADMIN))


def create_staff_member(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_staff_member(f.create_staff_member_payload(**overrides), ADMIN))


def create_event_order(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_event_order(f.create_event_order_payload(**overrides), SALES))


def add_order_line(api, order_id, menu_item_id, **overrides) -> dict:
    return get_success_data(
        api.create_order_line(f.create_order_line_payload(order_id, menu_item_id, **overrides), SALES)
    )


def order_version(api, order_id) -> int:
    return get_success_data(api.get_event_order(order_id, SALES))["version"]


def generate_quote(api, order_id) -> dict:
    """Generate a quote using the order's current version (happy path)."""
    ver = order_version(api, order_id)
    return get_success_data(api.generate_quote(order_id, {"expected_event_order_version": ver}, SALES))


# --------------------------------------------------------------------------
# Menu / BOM composites
# --------------------------------------------------------------------------
def menu_item_with_recipe(api=api_client, *, unit_cost_cents=10, on_hand_qty=100000,
                          sell=1000, qty_per_portion=5) -> dict:
    """Ingredient + menu item + one recipe line.

    portion_food_cost_cents == round(qty_per_portion * unit_cost_cents).
    Returns {ingredient, menu_item, ingredient_id, menu_item_id}.
    """
    ingredient = create_ingredient(api, unit_cost_cents=unit_cost_cents, on_hand_qty=on_hand_qty)
    menu_item = create_menu_item(api, sell_price_cents_per_portion=sell)
    add_recipe_line(api, menu_item["id"], ingredient["id"], qty_per_portion=qty_per_portion)
    return {
        "ingredient": ingredient,
        "menu_item": menu_item,
        "ingredient_id": ingredient["id"],
        "menu_item_id": menu_item["id"],
    }


# --------------------------------------------------------------------------
# EventOrder lifecycle composites
# --------------------------------------------------------------------------
def draft_order_with_line(api=api_client, *, menu_item_id=None, guest_count=20,
                          portions_per_guest=1.0, service_charge_pct=0.10,
                          gratuity_pct=0.10, event_start=None, event_end=None) -> dict:
    """DRAFT order with one ACTIVE order line. Creates a menu item if none given.

    Returns {order_id, order, menu_item_id, line_id}.
    """
    if menu_item_id is None:
        menu_item_id = create_menu_item(api)["id"]
    kwargs = dict(guest_count=guest_count, service_charge_pct=service_charge_pct,
                  gratuity_pct=gratuity_pct)
    if event_start is not None:
        kwargs["event_start"] = event_start
    if event_end is not None:
        kwargs["event_end"] = event_end
    order = create_event_order(api, **kwargs)
    line = add_order_line(api, order["id"], menu_item_id, portions_per_guest=portions_per_guest)
    return {"order_id": order["id"], "order": order, "menu_item_id": menu_item_id, "line_id": line["id"]}


def quoted_order_with_line(api=api_client, **overrides) -> dict:
    """DRAFT order + line, then a first quote -> order is QUOTED.

    Returns {order_id, menu_item_id, line_id, quote_id, quote}.
    """
    base = draft_order_with_line(api, **overrides)
    quote = generate_quote(api, base["order_id"])
    base["quote_id"] = quote["id"]
    base["quote"] = quote
    return base


def confirmed_order_with_line(api=api_client, **overrides) -> dict:
    """Order driven to CONFIRMED with one ACTIVE line.

    Returns {order_id, menu_item_id, line_id, quote_id, quote}.
    """
    base = quoted_order_with_line(api, **overrides)
    get_success_data(api.confirm_order(base["order_id"], SALES))
    return base


def confirmed_order_for_production(api=api_client, *, on_hand_qty=100000, qty_per_portion=5,
                                   sell=1000, unit_cost_cents=10, station_capacity=2,
                                   guest_count=40, portions_per_guest=1.0) -> dict:
    """CONFIRMED order plus the kitchen assets needed to schedule production runs:
    ingredient (with recipe), menu item, station.

    Returns {order_id, menu_item_id, ingredient_id, station_id, line_id}.
    """
    recipe = menu_item_with_recipe(
        api, unit_cost_cents=unit_cost_cents, on_hand_qty=on_hand_qty,
        sell=sell, qty_per_portion=qty_per_portion,
    )
    station = create_station(api, concurrent_capacity=station_capacity)
    order = confirmed_order_with_line(
        api, menu_item_id=recipe["menu_item_id"], guest_count=guest_count,
        portions_per_guest=portions_per_guest,
    )
    return {
        "order_id": order["order_id"],
        "menu_item_id": recipe["menu_item_id"],
        "ingredient_id": recipe["ingredient_id"],
        "station_id": station["id"],
        "line_id": order["line_id"],
    }


def scheduled_run(api=api_client, *, run_portions=50, scheduled_start=None,
                  scheduled_end=None, **prod_overrides) -> dict:
    """CONFIRMED production-capable order + one SCHEDULED run.

    Returns confirmed_order_for_production dict plus {run_id, run}.
    """
    ctx = confirmed_order_for_production(api, **prod_overrides)
    payload_over = {"portions": run_portions}
    if scheduled_start is not None:
        payload_over["scheduled_start"] = scheduled_start
    if scheduled_end is not None:
        payload_over["scheduled_end"] = scheduled_end
    run = get_success_data(
        api.create_production_run(
            f.create_production_run_payload(
                ctx["order_id"], ctx["station_id"], ctx["menu_item_id"], **payload_over
            ),
            KITCHEN,
        )
    )
    ctx["run_id"] = run["id"]
    ctx["run"] = run
    return ctx


def run_in_progress(api=api_client, **overrides) -> dict:
    """Order IN_PRODUCTION with one run IN_PROGRESS (started but not completed)."""
    ctx = scheduled_run(api, **overrides)
    get_success_data(api.start_production(ctx["order_id"], KITCHEN))
    get_success_data(api.start_run(ctx["run_id"], KITCHEN))
    return ctx


def order_at_packed(api=api_client, **overrides) -> dict:
    """Order driven to PACKED via a single run started+completed, no staff yet."""
    ctx = run_in_progress(api, **overrides)
    get_success_data(api.complete_run(ctx["run_id"], KITCHEN))
    get_success_data(api.pack_order(ctx["order_id"], KITCHEN))
    return ctx


# --------------------------------------------------------------------------
# Equipment composites
# --------------------------------------------------------------------------
def confirmed_order_with_equipment(api=api_client, *, total_units=10, rental_price_cents=500,
                                   guest_count=30, service_charge_pct=0.10,
                                   gratuity_pct=0.10) -> dict:
    """CONFIRMED order + one equipment pool.

    Returns {order_id, equipment_id, menu_item_id}.
    """
    equipment = create_equipment_item(api, total_units=total_units, rental_price_cents=rental_price_cents)
    order = confirmed_order_with_line(
        api, guest_count=guest_count, service_charge_pct=service_charge_pct,
        gratuity_pct=gratuity_pct, event_end=dt(20),
    )
    return {"order_id": order["order_id"], "equipment_id": equipment["id"],
            "menu_item_id": order["menu_item_id"]}


def reserve_equipment(api, order_id, equipment_id, qty, out_time, return_time) -> dict:
    return get_success_data(
        api.create_rental_reservation(
            f.create_rental_reservation_payload(
                order_id, equipment_id, qty=qty, out_time=out_time, return_time=return_time
            ),
            CAPTAIN,
        )
    )


# --------------------------------------------------------------------------
# Staff composites
# --------------------------------------------------------------------------
def confirmed_order_with_staff(api=api_client, *, staff_role="SERVER", hourly_rate_cents=2000,
                               guest_count=30, event_end=None) -> dict:
    """CONFIRMED order + one staff member (no assignment yet).

    Returns {order_id, staff_member_id, menu_item_id}.
    """
    staff = create_staff_member(api, staff_role=staff_role, hourly_rate_cents=hourly_rate_cents)
    order = confirmed_order_with_line(
        api, guest_count=guest_count, event_end=event_end or dt(20),
    )
    return {"order_id": order["order_id"], "staff_member_id": staff["id"],
            "menu_item_id": order["menu_item_id"]}


def offered_assignment(api=api_client, *, staff_role="SERVER", hourly_rate_cents=2000,
                       shift_start=None, shift_end=None, guest_count=30) -> dict:
    """CONFIRMED order + staff + one OFFERED StaffAssignment.

    Returns {order_id, staff_member_id, assignment_id, assignment}.
    """
    ctx = confirmed_order_with_staff(
        api, staff_role=staff_role, hourly_rate_cents=hourly_rate_cents, guest_count=guest_count,
    )
    over = {"staff_role": staff_role}
    if shift_start is not None:
        over["shift_start"] = shift_start
    if shift_end is not None:
        over["shift_end"] = shift_end
    assignment = get_success_data(
        api.create_staff_assignment(
            f.create_staff_assignment_payload(ctx["order_id"], ctx["staff_member_id"], **over),
            CAPTAIN,
        )
    )
    ctx["assignment_id"] = assignment["id"]
    ctx["assignment"] = assignment
    return ctx


def checked_in_assignment(api=api_client, *, hourly_rate_cents=2000, shift_start=None,
                          shift_end=None, actual_start=None, guest_count=30) -> dict:
    """CONFIRMED order + staff + assignment confirmed and CHECKED_IN.

    Returns {order_id, staff_member_id, assignment_id, assignment, scheduled_labor_cents}.
    Test triggers check-out with a chosen actual_end.
    """
    ctx = offered_assignment(
        api, hourly_rate_cents=hourly_rate_cents, shift_start=shift_start,
        shift_end=shift_end, guest_count=guest_count,
    )
    ctx["scheduled_labor_cents"] = ctx["assignment"]["scheduled_labor_cents"]
    get_success_data(api.confirm_assignment(ctx["assignment_id"], CAPTAIN))
    get_success_data(
        api.checkin_assignment(ctx["assignment_id"], {"actual_start": actual_start or dt(10)}, CAPTAIN)
    )
    return ctx


# --------------------------------------------------------------------------
# Full lifecycle to COMPLETED (settlement / dual-variant tests)
# --------------------------------------------------------------------------
def drive_order_to_completed(api=api_client, *, guest_count, service_charge_pct, gratuity_pct,
                             portions_per_guest=1.0, sell=1000, unit_cost_cents=10,
                             qty_per_portion=5, on_hand_qty=100000, run_portions=None,
                             staff_rate=2000, staff_shift=None, staff_actual=None,
                             rental=None, event_start=None, event_end=None) -> dict:
    """Drive an order all the way to COMPLETED, ready for the actualize trigger.

    - staff_actual: (start, end) tuple -> the assignment is checked in and out,
      accumulating actual labor into the order. None -> assignment only confirmed.
    - rental: dict {qty, price, total_units, out, return} -> creates equipment and
      an ACTIVE reservation. None -> no rental.

    Returns {order_id, menu_item_id, ingredient_id, station_id, staff_member_id,
             assignment_id, quote_id, quote_food_revenue, run_id, equipment_id,
             reservation_id}.
    """
    if run_portions is None:
        run_portions = guest_count
    if staff_shift is None:
        staff_shift = (dt(10), dt(16))
    if event_start is None:
        event_start = dt(9)
    if event_end is None:
        event_end = dt(20)

    recipe = menu_item_with_recipe(
        api, unit_cost_cents=unit_cost_cents, on_hand_qty=on_hand_qty,
        sell=sell, qty_per_portion=qty_per_portion,
    )
    station = create_station(api, concurrent_capacity=2)
    staff = create_staff_member(api, staff_role="SERVER", hourly_rate_cents=staff_rate)

    equipment_id = None
    if rental is not None:
        equipment_id = create_equipment_item(
            api, total_units=rental["total_units"], rental_price_cents=rental["price"]
        )["id"]

    order = create_event_order(
        api, guest_count=guest_count, service_charge_pct=service_charge_pct,
        gratuity_pct=gratuity_pct, event_start=event_start, event_end=event_end,
    )
    order_id = order["id"]
    add_order_line(api, order_id, recipe["menu_item_id"], portions_per_guest=portions_per_guest)
    quote = generate_quote(api, order_id)
    get_success_data(api.confirm_order(order_id, SALES))

    run = get_success_data(
        api.create_production_run(
            f.create_production_run_payload(
                order_id, station["id"], recipe["menu_item_id"],
                portions=run_portions, scheduled_start=dt(6), scheduled_end=dt(8),
            ),
            KITCHEN,
        )
    )

    reservation_id = None
    if rental is not None:
        reservation_id = get_success_data(
            api.create_rental_reservation(
                f.create_rental_reservation_payload(
                    order_id, equipment_id, qty=rental["qty"],
                    out_time=rental["out"], return_time=rental["return"],
                ),
                CAPTAIN,
            )
        )["id"]

    assignment = get_success_data(
        api.create_staff_assignment(
            f.create_staff_assignment_payload(
                order_id, staff["id"], staff_role="SERVER",
                shift_start=staff_shift[0], shift_end=staff_shift[1],
            ),
            CAPTAIN,
        )
    )
    assignment_id = assignment["id"]
    get_success_data(api.confirm_assignment(assignment_id, CAPTAIN))
    if staff_actual is not None:
        get_success_data(api.checkin_assignment(assignment_id, {"actual_start": staff_actual[0]}, CAPTAIN))
        get_success_data(api.checkout_assignment(assignment_id, {"actual_end": staff_actual[1]}, CAPTAIN))

    # Production run through DONE, then pack.
    get_success_data(api.start_production(order_id, KITCHEN))
    get_success_data(api.start_run(run["id"], KITCHEN))
    get_success_data(api.complete_run(run["id"], KITCHEN))
    get_success_data(api.pack_order(order_id, KITCHEN))

    # Dispatch (confirmed staff present) and complete.
    get_success_data(api.dispatch_order(order_id, CAPTAIN))
    get_success_data(api.complete_order(order_id, CAPTAIN))

    return {
        "order_id": order_id,
        "menu_item_id": recipe["menu_item_id"],
        "ingredient_id": recipe["ingredient_id"],
        "station_id": station["id"],
        "staff_member_id": staff["id"],
        "assignment_id": assignment_id,
        "quote_id": quote["id"],
        "quote_food_revenue": quote["food_revenue_cents"],
        "run_id": run["id"],
        "equipment_id": equipment_id,
        "reservation_id": reservation_id,
    }
