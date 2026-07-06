"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures.

The test harness restarts the API server (empty database) before every test, so
every helper builds its preconditions from scratch using only PRD-declared
endpoints. Role headers follow PRD §2.1: the three operator roles are opaque
(shared constants); the entity_backed Client role is threaded per-customer with
make_client_headers(customer_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_venue_payload, create_equipment_payload,
    create_crew_member_payload, create_order_payload, create_reservation_payload,
    create_crew_assignment_payload, create_sub_rental_payload, create_coi_payload,
    create_damage_report_payload,
)
from .test_users import TEST_USERS, make_client_headers

AM = TEST_USERS["account_manager_headers"]
WM = TEST_USERS["warehouse_manager_headers"]
CC = TEST_USERS["crew_chief_headers"]


# ─── Logical clock (PRD §2.6) ─────────────────────────────────────────
def set_clock(iso: str) -> dict:
    """Move the server logical clock to `iso` (e.g. '2026-05-01T00:00:00Z')."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, AM))


# ─── Tier 0: single-entity creation helpers ───────────────────────────
def new_customer(credit_limit_cents=100_000_000, name="Acme Productions",
                 contact_email="ops@acme.test") -> dict:
    return get_success_data(api_client.create_customer(
        create_customer_payload(name=name, contact_email=contact_email,
                                credit_limit_cents=credit_limit_cents), AM))


def new_venue(required_coverage_cents=0, name="Grand Hall", address="1 Main St",
              dock_type=None) -> dict:
    return get_success_data(api_client.create_venue(
        create_venue_payload(name=name, address=address,
                             required_coverage_cents=required_coverage_cents,
                             dock_type=dock_type), AM))


def new_equipment(name="LED Panel P3", category="LED", total_units=20,
                  daily_rate_cents=12000, replacement_value_cents=500000,
                  requires_operator=None) -> dict:
    return get_success_data(api_client.create_equipment(
        create_equipment_payload(name=name, category=category, total_units=total_units,
                                 daily_rate_cents=daily_rate_cents,
                                 replacement_value_cents=replacement_value_cents,
                                 requires_operator=requires_operator), WM))


def new_crew_member(name="Tech One", crew_role="TECH", hourly_rate_cents=4000) -> dict:
    return get_success_data(api_client.create_crew_member(
        create_crew_member_payload(name=name, crew_role=crew_role,
                                   hourly_rate_cents=hourly_rate_cents), CC))


def new_order(customer_id, venue_id, event_name="Gala",
              event_start_date="2026-06-10", event_end_date="2026-06-12") -> dict:
    return get_success_data(api_client.create_order(
        create_order_payload(customer_id, venue_id, event_name=event_name,
                             event_start_date=event_start_date,
                             event_end_date=event_end_date), AM))


def add_reservation(order_id, equipment_id, qty=1, reserve_start_date="2026-06-10",
                    reserve_end_date="2026-06-12", is_standby=None) -> dict:
    return get_success_data(api_client.create_reservation(
        order_id,
        create_reservation_payload(equipment_id, qty=qty,
                                   reserve_start_date=reserve_start_date,
                                   reserve_end_date=reserve_end_date,
                                   is_standby=is_standby), WM))


def add_crew_assignment(order_id, crew_member_id, assignment_role="TECH",
                        shift_start="2026-06-10T08:00:00Z",
                        shift_end="2026-06-10T16:00:00Z", scheduled_hours=8,
                        is_standby=None) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        order_id,
        create_crew_assignment_payload(crew_member_id, assignment_role=assignment_role,
                                       shift_start=shift_start, shift_end=shift_end,
                                       scheduled_hours=scheduled_hours,
                                       is_standby=is_standby), CC))


def add_sub_rental(order_id, equipment_id, reservation_id=None, direction=None,
                   vendor_name="PeerAV", qty=1, cost_cents=20000) -> dict:
    return get_success_data(api_client.create_sub_rental(
        order_id,
        create_sub_rental_payload(equipment_id, vendor_name=vendor_name, qty=qty,
                                  cost_cents=cost_cents, reservation_id=reservation_id,
                                  direction=direction), WM))


def submit_coi(order_id, customer_id, insurer="Lloyd", coverage_amount_cents=100000,
               expiry_date="2026-12-31") -> dict:
    return get_success_data(api_client.create_coi(
        order_id,
        create_coi_payload(insurer=insurer, coverage_amount_cents=coverage_amount_cents,
                           expiry_date=expiry_date),
        make_client_headers(customer_id)))


def approve_coi(coi_id) -> dict:
    return get_success_data(api_client.approve_coi(coi_id, AM))


# ─── Tier 1: order-state progression ──────────────────────────────────
def quote(order_id) -> dict:
    return get_success_data(api_client.quote_order(order_id, AM))


def read_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, AM))


def order_version(order_id) -> int:
    return read_order(order_id)["version"]


def confirm_fresh(order_id) -> dict:
    """Re-read the order's current version and confirm with it (passes the OCC guard)."""
    version = order_version(order_id)
    return get_success_data(
        api_client.confirm_order(order_id, {"expected_order_version": version}, AM))


# ─── Tier 2: composite scenarios ──────────────────────────────────────
def setup_confirmed_order_single_led(clock="2026-05-01T00:00:00Z", qty=1,
                                     daily_rate_cents=12000, replacement_value_cents=500000,
                                     total_units=20, credit_limit_cents=100_000_000,
                                     required_coverage_cents=0, coverage_amount_cents=100000,
                                     coi_expiry_date="2026-12-31",
                                     event_start_date="2026-06-10",
                                     event_end_date="2026-06-12") -> dict:
    """Build a CONFIRMED order with a single HELD LED reservation.

    Chain: clock -> customer -> venue -> equipment -> order -> reservation ->
    quote -> submit COI -> approve COI -> confirm (deposit HOLD written).
    Returns a context dict of the created entities and their ids.
    """
    if clock:
        set_clock(clock)
    cust = new_customer(credit_limit_cents=credit_limit_cents)
    ven = new_venue(required_coverage_cents=required_coverage_cents)
    led = new_equipment(total_units=total_units, daily_rate_cents=daily_rate_cents,
                        replacement_value_cents=replacement_value_cents)
    order = new_order(cust["id"], ven["id"], event_start_date=event_start_date,
                     event_end_date=event_end_date)
    res = add_reservation(order["id"], led["id"], qty=qty,
                          reserve_start_date=event_start_date,
                          reserve_end_date=event_end_date)
    quote(order["id"])
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=coverage_amount_cents,
                     expiry_date=coi_expiry_date)
    approve_coi(coi["id"])
    order = confirm_fresh(order["id"])
    return {
        "customer": cust, "venue": ven, "equipment": led, "order": order,
        "reservation": res, "coi": coi,
        "cust_id": cust["id"], "ven_id": ven["id"], "led_id": led["id"],
        "ord_id": order["id"], "res_id": res["id"], "coi_id": coi["id"],
    }


def setup_in_event_order_single_led(**kwargs) -> dict:
    """Extend setup_confirmed_order_single_led through to IN_EVENT:
    load-out -> check-out the reservation -> start-event."""
    ctx = setup_confirmed_order_single_led(**kwargs)
    get_success_data(api_client.load_out_order(ctx["ord_id"], WM))
    get_success_data(api_client.check_out_reservation(ctx["res_id"], WM))
    get_success_data(api_client.start_event_order(ctx["ord_id"], AM))
    ctx["order"] = read_order(ctx["ord_id"])
    return ctx


def setup_confirmed_order_led_and_array(clock="2026-05-01T00:00:00Z", led_qty=2,
                                        led_replacement_value_cents=500000, arr_qty=1,
                                        arr_replacement_value_cents=800000,
                                        credit_limit_cents=100_000_000,
                                        required_coverage_cents=0,
                                        event_start_date="2026-06-10",
                                        event_end_date="2026-06-12") -> dict:
    """Build a CONFIRMED order carrying two reservations: LED (qty led_qty) and a sound
    array (qty arr_qty). With the default replacement values the deposit HOLD is
    round(0.20 * (500000*2 + 800000*1)) = 360000. Returns a context dict."""
    if clock:
        set_clock(clock)
    cust = new_customer(credit_limit_cents=credit_limit_cents)
    ven = new_venue(required_coverage_cents=required_coverage_cents)
    led = new_equipment(name="LED Panel", category="LED", total_units=20,
                        daily_rate_cents=12000,
                        replacement_value_cents=led_replacement_value_cents)
    arr = new_equipment(name="K2 Line Array", category="SOUND", total_units=8,
                        daily_rate_cents=15000,
                        replacement_value_cents=arr_replacement_value_cents)
    order = new_order(cust["id"], ven["id"], event_start_date=event_start_date,
                     event_end_date=event_end_date)
    res_led = add_reservation(order["id"], led["id"], qty=led_qty,
                              reserve_start_date=event_start_date,
                              reserve_end_date=event_end_date)
    res_arr = add_reservation(order["id"], arr["id"], qty=arr_qty,
                              reserve_start_date=event_start_date,
                              reserve_end_date=event_end_date)
    quote(order["id"])
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])
    order = confirm_fresh(order["id"])
    return {
        "customer": cust, "venue": ven, "led": led, "array": arr, "order": order,
        "res_led": res_led, "res_arr": res_arr, "coi": coi,
        "cust_id": cust["id"], "ven_id": ven["id"], "led_id": led["id"],
        "arr_id": arr["id"], "ord_id": order["id"],
        "res_led_id": res_led["id"], "res_arr_id": res_arr["id"], "coi_id": coi["id"],
    }


def setup_quoted_order_single_led(clock="2026-05-01T00:00:00Z", qty=1,
                                  daily_rate_cents=12000, replacement_value_cents=500000,
                                  total_units=20, credit_limit_cents=100_000_000,
                                  required_coverage_cents=0,
                                  event_start_date="2026-06-10",
                                  event_end_date="2026-06-12") -> dict:
    """Build a QUOTED order with one HELD LED reservation (no COI, no confirm)."""
    if clock:
        set_clock(clock)
    cust = new_customer(credit_limit_cents=credit_limit_cents)
    ven = new_venue(required_coverage_cents=required_coverage_cents)
    led = new_equipment(total_units=total_units, daily_rate_cents=daily_rate_cents,
                        replacement_value_cents=replacement_value_cents)
    order = new_order(cust["id"], ven["id"], event_start_date=event_start_date,
                     event_end_date=event_end_date)
    res = add_reservation(order["id"], led["id"], qty=qty,
                          reserve_start_date=event_start_date,
                          reserve_end_date=event_end_date)
    order = quote(order["id"])
    return {
        "customer": cust, "venue": ven, "equipment": led, "order": order, "reservation": res,
        "cust_id": cust["id"], "ven_id": ven["id"], "led_id": led["id"],
        "ord_id": order["id"], "res_id": res["id"],
    }
