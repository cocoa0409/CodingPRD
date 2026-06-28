"""Pricing engine: the charge rollup (estimate vs actual variants, per-component
rounding), billable_count selection, menu/service line extensions, room rental
started-hour rounding, and the payment waterfall.

Every test builds its own state from scratch via test_helpers fixtures and pins
the literal expected cents values from the design index.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_event, add_menu_line, add_service_line, add_schedule_item,
    record_payment, get_event, get_event_version,
    setup_confirmed_event, setup_definite_event,
    setup_tentative_event_with_hold_booking, make_definite,
    TEST_USERS,
)
from test_helpers.api_client import api_client

_SALES = TEST_USERS["sales_manager_headers"]
_CAPTAIN = TEST_USERS["banquet_captain_headers"]
_CLERK = TEST_USERS["accounting_clerk_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================

def test_charge_rollup_estimate_vs_actual_diverge_on_event(api):
    """PRD §3.7: "The **estimate** variant writes the event's `estimated_total_cents`
    and applies while the event is `DEFINITE` or `CONFIRMED`, feeding per-person lines
    with the estimate headcount (the planning attendance, or the oversetted guarantee
    once locked)."
    PRD §3.7: "The **actual** variant writes the event's `actualized_total_cents` and
    applies once the event is `COMPLETED`, feeding per-person lines with the actual
    headcount (the larger of guarantee and actual); for the same line, service, and
    rental rows it can produce a different grand total whenever the real count differs
    from the oversetted guarantee."

    Design: Difficulty/dual_variant_calc/charge_rollup_estimate_vs_actual_on_event
    """
    confirmed, room, booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Acme Gala", "event_date": "2026-09-10",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.20,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.10},
        room_overrides={"name": "Grand Ballroom", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 50000},
        menu_lines=[{"name": "Plated Filet", "pricing_mode": "PER_PERSON", "unit_price_cents": 10000}],
        guarantee_count=120, deposit_amount_cents=500000,
    )
    # ESTIMATE variant frozen at CONFIRMED: oversetted guarantee 126.
    assert confirmed["estimated_total_cents"] == 1883200, (
        f"estimate total should be 1883200, got {confirmed['estimated_total_cents']}"
    )

    completed = validate_success(
        api.actualize_event(confirmed["id"], {"actual_attendance": 140}, _CAPTAIN)
    )
    assert completed["billable_count"] == 140, f"got {completed['billable_count']}"
    assert completed["actualized_total_cents"] == 2068000, (
        f"actual total should be 2068000, got {completed['actualized_total_cents']}"
    )
    assert completed["actualized_total_cents"] != completed["estimated_total_cents"], (
        "actual and estimate grand totals must differ for the same rows"
    )


def test_rooms_committed_reserved_vs_pickedup_on_block(api):
    """PRD §3.6: "a `RESERVED` link contributes its `rooms_reserved` (the optimistic
    hold), a `PICKED_UP` link contributes its `rooms_picked_up` (the realized count,
    which is at most the rooms reserved), and a `RELEASED` link contributes nothing."
    PRD §3.6: "On success the link's `rooms_picked_up` is set, and because the link now
    counts its realized figure instead of its reservation, the block's `rooms_committed`
    and `rooms_available` are recomputed — which may free rooms back to the available pool."

    Design: Difficulty/dual_variant_calc/rooms_committed_reserved_vs_pickedup_on_block
    """
    block = get_success_data(api.create_hotel_room_block(
        {"block_name": "Wedding Block", "total_rooms": 10, "nightly_rate_cents": 19900}, _ADMIN))
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Beta Wedding", "event_date": "2026-07-02",
                         "setup_style": "ROUNDS", "expected_attendance": 50},
        room_overrides={"name": "Salon A", "max_capacity": 200,
                        "turnover_buffer_minutes": 60, "hourly_rental_cents": 0},
        start_utc="2026-07-02T18:00:00Z", end_utc="2026-07-02T22:00:00Z",
        guarantee_count=40, deposit_amount_cents=100000,
    )
    link = get_success_data(api.create_room_block_link(
        confirmed["id"],
        {"hotel_room_block_id": block["id"], "rooms_reserved": 8,
         "check_in_date": "2026-07-01", "check_out_date": "2026-07-03"}, _CLERK))
    # While RESERVED, committed counts rooms_reserved (8 -> available 2).
    block_reserved = get_success_data(api.get_hotel_room_block(block["id"], _CLERK))
    assert block_reserved["rooms_committed"] == 8, f"got {block_reserved['rooms_committed']}"

    validate_success(api.record_pickup(
        confirmed["id"], link["id"], {"rooms_picked_up": 3}, _CLERK))
    block_pickup = get_success_data(api.get_hotel_room_block(block["id"], _CLERK))
    assert block_pickup["rooms_committed"] == 3, (
        f"after pickup committed should switch to rooms_picked_up 3, got {block_pickup['rooms_committed']}"
    )
    assert block_pickup["rooms_available"] == 7, f"got {block_pickup['rooms_available']}"
    # Confirm link status flipped via the event's link listing.
    links = get_success_data(api.list_event_room_block_links(confirmed["id"], _CLERK))
    this_link = next(l for l in links if l["id"] == link["id"])
    assert this_link["link_status"] == "PICKED_UP", f"got {this_link['link_status']}"


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================

def test_billable_count_nonmonotone_switch_confirmed_to_completed(api):
    """PRD §3.5: "Once a guarantee has been locked (the event is `CONFIRMED` but not yet
    completed), `billable_count` becomes the guaranteed headcount inflated by the overset:
    the `guarantee_count` multiplied by one plus the `overset_pct`, rounded **up** to a
    whole number of covers — the venue prepares for that many."
    PRD §3.5: "Once the event is `COMPLETED`, the overset inflation is dropped entirely
    and `billable_count` becomes the larger of the `guarantee_count` and the counted
    `actual_attendance`; the venue bills the greater of the firm guarantee and the real
    count, never the oversetted prep figure."

    Design: Difficulty/combinatorial_formula/billable_count_nested_conditional_mode_a
    """
    confirmed, _room, _booking, _ = setup_confirmed_event(
        event_overrides={"account_name": "Gamma Conf", "event_date": "2026-10-01",
                         "setup_style": "THEATER", "expected_attendance": 100,
                         "overset_pct": 0.05, "service_charge_pct": 0.0,
                         "gratuity_pct": 0.0, "sales_tax_pct": 0.0},
        room_overrides={"name": "Salon B", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2026-10-01T17:00:00Z", end_utc="2026-10-01T21:00:00Z",
        menu_lines=[{"name": "Buffet", "pricing_mode": "PER_PERSON", "unit_price_cents": 5000}],
        guarantee_count=120, deposit_amount_cents=100000,
    )
    # CONFIRMED estimate: ceil(120 * 1.05) = 126.
    assert confirmed["billable_count"] == 126, (
        f"CONFIRMED billable should be ceil(120*1.05)=126, got {confirmed['billable_count']}"
    )
    completed = validate_success(
        api.actualize_event(confirmed["id"], {"actual_attendance": 110}, _CAPTAIN))
    # COMPLETED actual: max(120, 110) = 120 (non-monotone drop from 126).
    assert completed["billable_count"] == 120, (
        f"COMPLETED billable should be max(120,110)=120, got {completed['billable_count']}"
    )


def test_charge_rollup_per_component_rounding_order(api):
    """PRD §2.6: "This rounding is applied **independently to each of the three
    components, in the fixed order** service charge first, then gratuity, then sales tax —
    each is rounded to a whole cent *before* it is added into any running total. The system
    never sums the three at full precision and rounds once at the end."
    PRD §3.7: "The taxable base is the food-and-beverage subtotal plus the service subtotal
    plus the rental subtotal plus the service charge."

    Design: Difficulty/combinatorial_formula/charge_rollup_per_component_rounding_order_mode_b
    """
    event_definite, _room, _booking = setup_definite_event(
        event_overrides={"account_name": "Delta Dinner", "event_date": "2026-11-05",
                         "setup_style": "CLASSROOM", "expected_attendance": 30,
                         "service_charge_pct": 0.225, "gratuity_pct": 0.075,
                         "sales_tax_pct": 0.08},
        room_overrides={"name": "Salon C", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 0},
        start_utc="2026-11-05T18:00:00Z", end_utc="2026-11-05T21:00:00Z",
        menu_lines=[{"name": "Open Bar", "pricing_mode": "CONSUMPTION",
                     "unit_price_cents": 461, "consumption_qty": 10}],
    )
    # service_charge = rhu(4610*0.225)=1037, gratuity = rhu(4610*0.075)=346,
    # sales_tax = rhu((4610+1037)*0.08)=452 -> grand 6445.
    assert event_definite["estimated_total_cents"] == 6445, (
        f"per-component rounding should yield 6445 (sum-then-round gives 6443), "
        f"got {event_definite['estimated_total_cents']}"
    )


# ===========================================================================
# Difficulty: boundary_precision_check (room rental started-hour)
# ===========================================================================

def test_room_rental_exact_hour_boundary_does_not_round_up(api):
    """PRD §3.3: "the system takes the window's duration in minutes (the gap from
    `start_utc` to `end_utc`), divides by the 60 minutes in an hour and rounds **up** to a
    whole number of billed hours, and multiplies that hour count by the room's
    `hourly_rental_cents`. Because the rounding is upward, a two-hour-and-one-minute window
    bills three hours, while a window whose duration is an exact multiple of 60 minutes
    bills no extra hour."

    Design: Difficulty/boundary_precision_check/room_rental_ceil_started_hour_boundary
    """
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Lambda Mtg", "event_date": "2027-06-01",
                         "setup_style": "THEATER", "expected_attendance": 50},
        room_overrides={"name": "Salon I", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 50000},
        start_utc="2027-06-01T18:00:00Z", end_utc="2027-06-01T22:00:00Z",
    )
    definite = validate_success(api.make_definite(held["id"], booking["id"], _SALES))
    # 240 minutes -> ceil(240/60)=4 hours -> 200000 (exact-hour, no extra hour).
    assert definite["rental_charge_cents"] == 200000, (
        f"exactly 240 min should bill 4 hours = 200000, got {definite['rental_charge_cents']}"
    )
    assert definite["hold_status"] == "DEFINITE"


# ===========================================================================
# Corner: calculations
# ===========================================================================

def test_consumption_menu_line_uses_qty_not_billable(api):
    """PRD §3.7: "A line's `extended_cents` total is its `unit_price_cents` multiplied by
    the event's `billable_count` for a `PER_PERSON` line, or its `unit_price_cents`
    multiplied by its `consumption_qty` for a `CONSUMPTION` line."

    Design: Corner/calculations/consumption_menu_line_extended_uses_qty_not_billable
    """
    event = create_event(account_name="Cons Co", event_date="2028-08-01",
                         setup_style="RECEPTION", expected_attendance=200)
    ml = validate_success(api.create_menu_line(
        event["id"],
        {"name": "Wine bottles", "pricing_mode": "CONSUMPTION",
         "unit_price_cents": 350, "consumption_qty": 12}, _SALES), expected_status=201)
    assert ml["extended_cents"] == 4200, (
        f"350*12 = 4200, independent of billable_count, got {ml['extended_cents']}"
    )


def test_service_line_extended_is_qty_times_unit_price(api):
    """PRD §3.7: "A service line's `extended_cents` is simply its `quantity` multiplied by
    its `unit_price_cents`."

    Design: Corner/calculations/service_line_extended_is_qty_times_unit_price
    """
    event = create_event(account_name="Svc Co", event_date="2028-09-01",
                         setup_style="THEATER", expected_attendance=50)
    sl = validate_success(api.create_service_line(
        event["id"],
        {"category": "LABOR", "description": "Banquet servers", "quantity": 8,
         "unit_price_cents": 7500, "gratuity_eligible": True}, _SALES), expected_status=201)
    assert sl["extended_cents"] == 60000, f"8*7500 = 60000, got {sl['extended_cents']}"


def test_room_rental_rounds_up_on_241_minutes(api):
    """PRD §3.3: "Because the rounding is upward, a two-hour-and-one-minute window bills
    three hours, while a window whose duration is an exact multiple of 60 minutes bills no
    extra hour."

    Design: Corner/calculations/room_rental_started_hour_rounds_up_on_241_minutes
    """
    held, _room, booking = setup_tentative_event_with_hold_booking(
        event_overrides={"account_name": "Hour Co", "event_date": "2028-10-01",
                         "setup_style": "THEATER", "expected_attendance": 40},
        room_overrides={"name": "Salon R", "max_capacity": 300,
                        "turnover_buffer_minutes": 0, "hourly_rental_cents": 50000},
        start_utc="2028-10-01T18:00:00Z", end_utc="2028-10-01T22:01:00Z",
    )
    definite = validate_success(api.make_definite(held["id"], booking["id"], _SALES))
    # 241 minutes -> ceil(241/60)=5 hours -> 250000.
    assert definite["rental_charge_cents"] == 250000, (
        f"241 min should bill 5 hours = 250000, got {definite['rental_charge_cents']}"
    )


def test_payment_waterfall_overpayment_spills_to_negative_balance(api):
    """PRD §3.8: "Walking the items from `sequence_no` 1 upward, each item is allocated the
    smaller of the remaining unallocated pool and that item's `amount_due_cents`; the
    item's `allocated_cents` is set to that amount, its `settled` flag is set true when the
    amount allocated reaches its `amount_due_cents`, and the pool is reduced by the amount
    taken. Any pool left over after the last item is unallocated overpayment, which
    surfaces as a negative balance."
    PRD §3.8: "The `balance_due_cents` is the active grand total minus `paid_to_date_cents`"

    Design: Corner/calculations/payment_waterfall_overpayment_spills_to_negative_balance
    """
    event = create_event(account_name="Over Co", event_date="2028-11-01",
                         setup_style="THEATER", expected_attendance=20,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    item1 = add_schedule_item(event["id"], 500000, label="Deposit", due_date="2028-09-01")
    item2 = add_schedule_item(event["id"], 300000, label="Second", due_date="2028-10-01")
    version = get_event_version(event["id"])
    validate_success(api.create_payment(
        event["id"], {"amount_cents": 900000, "method": "WIRE",
                      "expected_event_version": version}, _CLERK), expected_status=201)

    items = get_success_data(api.list_payment_schedule_items(event["id"], _CLERK))
    by_id = {i["id"]: i for i in items}
    assert by_id[item1["id"]]["allocated_cents"] == 500000, f"got {by_id[item1['id']]['allocated_cents']}"
    assert by_id[item2["id"]]["allocated_cents"] == 300000, f"got {by_id[item2['id']]['allocated_cents']}"
    assert by_id[item1["id"]]["settled"] is True
    assert by_id[item2["id"]]["settled"] is True

    ev = get_event(event["id"])
    assert ev["balance_due_cents"] == -900000, (
        f"overpayment should make balance_due -900000, got {ev['balance_due_cents']}"
    )


def test_delete_menu_line_recomputes_estimated_total(api):
    """PRD §3.7: "Menu lines and service lines may be removed while the event is not
    terminal; removing either recomputes the event's `estimated_total_cents`."

    Design: Corner/endpoints/delete_menu_line_recomputes_estimated_total
    """
    event = create_event(account_name="Del Co", event_date="2029-06-01",
                         setup_style="THEATER", expected_attendance=40,
                         service_charge_pct=0.0, gratuity_pct=0.0, sales_tax_pct=0.0)
    ml = add_menu_line(event["id"], name="Coffee", pricing_mode="CONSUMPTION",
                       unit_price_cents=350, consumption_qty=12)
    del_resp = api.delete_menu_line(event["id"], ml["id"], _SALES)
    assert del_resp.status_code == 204, (
        f"DELETE menu line should return 204 No Content, got {del_resp.status_code}: {del_resp.text}"
    )
    ev = get_event(event["id"])
    assert ev["estimated_total_cents"] == 0, (
        f"removing the only line should drop estimated_total to 0, got {ev['estimated_total_cents']}"
    )
