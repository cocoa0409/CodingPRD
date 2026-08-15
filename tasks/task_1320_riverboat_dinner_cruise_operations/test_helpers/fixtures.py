"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Ownership-gated Customer calls always thread the real
customer id through make_customer_headers (PRD §2.1 identity semantics).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT
from .factories import (
    create_booking_payload,
    create_charter_inquiry_payload,
    create_cruise_payload,
    create_customer_payload,
    create_dock_payload,
    create_dock_slot_payload,
    create_menu_tier_payload,
    create_parking_pass_payload,
    create_passenger_payload,
    create_staff_assignment_payload,
    create_staff_member_payload,
    create_vessel_payload,
    create_weather_event_payload,
)
from .test_users import TEST_USERS, make_customer_headers

OM = TEST_USERS["ops_manager_headers"]
CAPTAIN = TEST_USERS["captain_headers"]
AGENT = TEST_USERS["charter_agent_headers"]
GALLEY = TEST_USERS["galley_manager_headers"]
ATTENDANT = TEST_USERS["dock_attendant_headers"]

DEFAULT_DEPART = "2026-08-10T19:00:00Z"   # PEAK, non-holiday
DEFAULT_RETURN = "2026-08-10T22:00:00Z"
DEFAULT_WINDOW = ("2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z")


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — standing inventory (dock / vessel / tier / cruise / customer)
# ---------------------------------------------------------------------------

def create_dock(parking_capacity=10, name="Pier 9"):
    resp = api_client.create_dock(
        create_dock_payload(name=name, parking_capacity=parking_capacity), OM)
    return _ok("create_dock", resp)


def create_vessel(dock_id, capacity=100, name="Belle"):
    resp = api_client.create_vessel(
        create_vessel_payload(name=name, coast_guard_capacity=capacity,
                              home_dock_id=dock_id),
        OM)
    return _ok("create_vessel", resp)


def create_tier(code="STANDARD", base_price_cents=8900,
                galley_load_per_cover=2.5, bar_package_price_cents=4200):
    resp = api_client.create_menu_tier(
        create_menu_tier_payload(
            code=code, base_price_cents=base_price_cents,
            galley_load_per_cover=galley_load_per_cover,
            bar_package_price_cents=bar_package_price_cents),
        OM)
    return _ok("create_menu_tier", resp)


def create_cruise(vessel_id, tier_id, depart_at=DEFAULT_DEPART,
                  return_at=DEFAULT_RETURN):
    resp = api_client.create_cruise(
        create_cruise_payload(vessel_id=vessel_id, menu_tier_id=tier_id,
                              depart_at=depart_at, return_at=return_at),
        OM)
    return _ok("create_cruise", resp)


def create_customer(email, full_name="Guest"):
    resp = api_client.create_customer(
        create_customer_payload(email=email, full_name=full_name), OM)
    return _ok("create_customer", resp)


def setup_inventory(vessel_capacity=100, parking_capacity=10,
                    depart_at=DEFAULT_DEPART, return_at=DEFAULT_RETURN,
                    tier_overrides=None):
    """Dock + vessel + menu tier + cruise. Returns dict of the four records."""
    dock = create_dock(parking_capacity=parking_capacity)
    vessel = create_vessel(dock["id"], capacity=vessel_capacity)
    tier = create_tier(**(tier_overrides or {}))
    cruise = create_cruise(vessel["id"], tier["id"],
                           depart_at=depart_at, return_at=return_at)
    return {"dock": dock, "vessel": vessel, "tier": tier, "cruise": cruise}


# ---------------------------------------------------------------------------
# Tier 2 — bookings and passengers
# ---------------------------------------------------------------------------

def create_booking(cruise_id, customer_id, party_size, expected_cruise_version,
                   bar_package_count=None):
    payload = create_booking_payload(
        customer_id=customer_id, party_size=party_size,
        expected_cruise_version=expected_cruise_version)
    if bar_package_count is not None:
        payload["bar_package_count"] = bar_package_count
    resp = api_client.create_booking(
        cruise_id, payload, make_customer_headers(customer_id))
    return _ok("create_booking", resp)


def pay_booking(booking_id, customer_id):
    resp = api_client.pay_booking(booking_id, make_customer_headers(customer_id))
    return _ok("pay_booking", resp)


def cancel_booking(booking_id, customer_id):
    resp = api_client.cancel_booking(booking_id, make_customer_headers(customer_id))
    return _ok("cancel_booking", resp)


def add_passenger(booking_id, customer_id, full_name="Passenger",
                  date_of_birth="1990-01-01"):
    resp = api_client.add_booking_passenger(
        booking_id,
        create_passenger_payload(full_name=full_name, date_of_birth=date_of_birth),
        make_customer_headers(customer_id))
    return _ok("add_passenger", resp)


def get_cruise(cruise_id):
    return _ok("get_cruise", api_client.get_cruise(cruise_id, OM))


def get_booking(booking_id):
    return _ok("get_booking", api_client.get_booking(booking_id, OM))


def create_paid_booking(cruise_id, customer_id, party_size,
                        expected_cruise_version, bar_package_count=None):
    """Create + pay a booking. Returns the paid booking record."""
    booking = create_booking(cruise_id, customer_id, party_size,
                             expected_cruise_version,
                             bar_package_count=bar_package_count)
    return pay_booking(booking["id"], customer_id)


# ---------------------------------------------------------------------------
# Tier 3 — staffing, galley, manifest, boarding, weather, clock, parking
# ---------------------------------------------------------------------------

def create_bartender(cert_expires_at="2027-01-01T00:00:00Z", full_name="Tom"):
    resp = api_client.create_staff_member(
        create_staff_member_payload(
            full_name=full_name, role_code="BARTENDER",
            alcohol_cert_expires_at=cert_expires_at),
        OM)
    return _ok("create_bartender", resp)


def create_staff(full_name="Sam", role_code="SERVER", cert_expires_at=None):
    payload = create_staff_member_payload(full_name=full_name, role_code=role_code)
    if cert_expires_at is not None:
        payload["alcohol_cert_expires_at"] = cert_expires_at
    resp = api_client.create_staff_member(payload, OM)
    return _ok("create_staff_member", resp)


def assign_staff(cruise_id, staff_member_id, assigned_role="BARTENDER"):
    resp = api_client.create_staff_assignment(
        cruise_id,
        create_staff_assignment_payload(staff_member_id=staff_member_id,
                                        assigned_role=assigned_role),
        OM)
    return _ok("create_staff_assignment", resp)


def confirm_assignment(cruise_id, assignment_id):
    resp = api_client.confirm_staff_assignment(cruise_id, assignment_id, OM)
    return _ok("confirm_staff_assignment", resp)


def assign_confirmed_bartender(cruise_id, cert_expires_at="2027-01-01T00:00:00Z"):
    """Bartender with a valid cert assigned and confirmed (enables bar service)."""
    staff = create_bartender(cert_expires_at=cert_expires_at)
    assignment = assign_staff(cruise_id, staff["id"], assigned_role="BARTENDER")
    return confirm_assignment(cruise_id, assignment["id"])


def create_provision_order(cruise_id):
    resp = api_client.create_provision_order(cruise_id, {}, GALLEY)
    return _ok("create_provision_order", resp)


def place_provision_order(cruise_id, order_id):
    resp = api_client.place_provision_order(cruise_id, order_id, GALLEY)
    return _ok("place_provision_order", resp)


def create_placed_provision_order(cruise_id):
    order = create_provision_order(cruise_id)
    return place_provision_order(cruise_id, order["id"])


def get_manifest(cruise_id):
    data = _ok("get_manifest", api_client.get_cruise_manifest(cruise_id, CAPTAIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"Expected exactly one manifest for cruise, got: {data!r}"
    )
    return data[0]


def freeze_manifest(cruise_id):
    return _ok("freeze_manifest", api_client.freeze_manifest(cruise_id, CAPTAIN))


def open_boarding(cruise_id):
    return _ok("open_boarding", api_client.open_boarding(cruise_id, OM))


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, OM)
    return _ok("set_clock", resp)


def declare_weather_event(severity="CANCELLATION_REQUIRED",
                          window_start=DEFAULT_WINDOW[0],
                          window_end=DEFAULT_WINDOW[1]):
    resp = api_client.create_weather_event(
        create_weather_event_payload(severity=severity, window_start=window_start,
                                     window_end=window_end),
        OM)
    return _ok("create_weather_event", resp)


def weather_cancel(cruise_id):
    return _ok("weather_cancel", api_client.weather_cancel_cruise(cruise_id, OM))


def settle_credits(event_id):
    return _ok("settle_credits",
               api_client.settle_weather_event_credits(event_id, OM))


def create_parking_pass(dock_id, booking_id, cruise_id):
    resp = api_client.create_parking_pass(
        dock_id,
        create_parking_pass_payload(booking_id=booking_id, cruise_id=cruise_id),
        ATTENDANT)
    return _ok("create_parking_pass", resp)


def create_dock_slot(dock_id, vessel_id, slot_start, slot_end):
    resp = api_client.create_dock_slot(
        dock_id,
        create_dock_slot_payload(vessel_id=vessel_id, slot_start=slot_start,
                                 slot_end=slot_end),
        OM)
    return _ok("create_dock_slot", resp)


# ---------------------------------------------------------------------------
# Tier 4 — charter pipeline
# ---------------------------------------------------------------------------

def create_inquiry(cruise_id, customer_id):
    resp = api_client.create_charter_inquiry(
        create_charter_inquiry_payload(cruise_id=cruise_id,
                                       customer_id=customer_id),
        AGENT)
    return _ok("create_charter_inquiry", resp)


def quote_inquiry(inquiry_id, expected_inquiry_version):
    resp = api_client.quote_charter_inquiry(
        inquiry_id, {"expected_inquiry_version": expected_inquiry_version}, AGENT)
    return _ok("quote_inquiry", resp)


def counter_inquiry(inquiry_id, customer_id):
    resp = api_client.counter_charter_inquiry(
        inquiry_id, make_customer_headers(customer_id))
    return _ok("counter_inquiry", resp)


def accept_inquiry(inquiry_id, customer_id):
    resp = api_client.accept_charter_inquiry(
        inquiry_id, make_customer_headers(customer_id))
    return _ok("accept_inquiry", resp)


def get_inquiry(inquiry_id):
    return _ok("get_inquiry", api_client.get_charter_inquiry(inquiry_id, AGENT))


def setup_accepted_inquiry(cruise_id, charter_customer_id):
    """Inquiry DRAFT -> QUOTED -> ACCEPTED. Returns the ACCEPTED inquiry."""
    inquiry = create_inquiry(cruise_id, charter_customer_id)
    quoted = quote_inquiry(inquiry["id"], inquiry["version"])
    return accept_inquiry(quoted["id"], charter_customer_id)


# ---------------------------------------------------------------------------
# Tier 5 — full voyage and weather-cancellation composites
# ---------------------------------------------------------------------------

def setup_voyage_ready(num_passengers=1, vessel_capacity=100):
    """Cruise with one PAID/CONFIRMED booking whose passengers are all added,
    manifest frozen, boarding opened. Returns a context dict."""
    inv = setup_inventory(vessel_capacity=vessel_capacity)
    cruise = inv["cruise"]
    customer = create_customer("voyager@example.com", "Voyager")
    booking = create_paid_booking(cruise["id"], customer["id"], num_passengers,
                                  cruise["version"])
    passengers = [
        add_passenger(booking["id"], customer["id"],
                      full_name=f"P{i+1}", date_of_birth="1990-01-01")
        for i in range(num_passengers)
    ]
    manifest = freeze_manifest(cruise["id"])
    open_boarding(cruise["id"])
    return {**inv, "customer": customer, "booking": booking,
            "passengers": passengers, "manifest": manifest}


def setup_weather_cancelled_cruise(clock_at="2026-08-09T13:00:00Z",
                                   party_size=2, place_order=False,
                                   vessel_capacity=100):
    """Cruise with one PAID booking, optionally a PLACED provision order,
    weather-cancelled under a covering CANCELLATION_REQUIRED event declared
    at `clock_at`. Returns a context dict."""
    inv = setup_inventory(vessel_capacity=vessel_capacity)
    cruise = inv["cruise"]
    customer = create_customer("weather@example.com", "Weather Guest")
    booking = create_paid_booking(cruise["id"], customer["id"], party_size,
                                  cruise["version"])
    order = create_placed_provision_order(cruise["id"]) if place_order else None
    set_clock(clock_at)
    event = declare_weather_event()
    weather_cancel(cruise["id"])
    return {**inv, "customer": customer, "booking": booking, "order": order,
            "event": event}
