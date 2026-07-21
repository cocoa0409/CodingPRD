"""Composite setup helpers.

These encapsulate multi-step API sequences so tests focus on assertions.
All helpers use the lenient ``get_success_data`` validator so a broken setup
surfaces as a clear "Setup failed" error rather than a confusing assertion.

Identity threading: entity_backed roles (Customer, Guide) are always addressed
with make_*_headers(entity_id) on ownership-gated calls.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers, make_guide_headers
from . import factories as f

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["clerk_headers"]
DIRECTOR = TEST_USERS["director_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(iso: str):
    """Set the server logical clock (ShopManager-only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, MANAGER))


# --------------------------------------------------------------------------
# Simple entity creation
# --------------------------------------------------------------------------
def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(f.customer_payload(**overrides), CLERK))


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(f.product_payload(**overrides), MANAGER))


def create_guide(**overrides) -> dict:
    return get_success_data(api_client.create_guide(f.guide_payload(**overrides), MANAGER))


def create_venue(**overrides) -> dict:
    return get_success_data(api_client.create_venue(f.venue_payload(**overrides), MANAGER))


def create_bait_tank(**overrides) -> dict:
    return get_success_data(api_client.create_bait_tank(f.bait_tank_payload(**overrides), MANAGER))


def create_license(customer_id, **overrides) -> dict:
    payload = f.license_payload(customer_id=customer_id, **overrides)
    return get_success_data(api_client.create_license(payload, CLERK))


def create_service_order(customer_id, **overrides) -> dict:
    payload = f.service_order_payload(customer_id=customer_id, **overrides)
    return get_success_data(api_client.create_service_order(payload, CLERK))


def create_special_order(customer_id, product_id, **overrides) -> dict:
    payload = f.special_order_payload(customer_id=customer_id, product_id=product_id, **overrides)
    return get_success_data(api_client.create_special_order(payload, CLERK))


# --------------------------------------------------------------------------
# Bait tanks: deliver a stocked tank
# --------------------------------------------------------------------------
def create_tank_with_batch(initial_count=100, capacity_units=100,
                           mortality_rate_bps_per_day=0, delivered_at=None,
                           species="MINNOW", **tank_overrides) -> dict:
    """Create a tank and deliver a single batch. Returns the tank after delivery."""
    tank = create_bait_tank(
        capacity_units=capacity_units,
        mortality_rate_bps_per_day=mortality_rate_bps_per_day,
        species=species,
        **tank_overrides,
    )
    payload = {"initial_count": initial_count, "expected_bait_tank_version": tank["version"]}
    if delivered_at is not None:
        payload["delivered_at"] = delivered_at
    return get_success_data(api_client.deliver_batch(tank["id"], payload, MANAGER))


# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
def open_sale(customer_id) -> dict:
    return get_success_data(api_client.create_sale(f.sale_payload(customer_id=customer_id), CLERK))


def add_line(sale_id, product_id, qty=1) -> dict:
    payload = f.sale_line_payload(product_id=product_id, qty=qty)
    return get_success_data(api_client.add_sale_line(sale_id, payload, CLERK))


def open_sale_with_lines(customer_id, product_id, line_qtys) -> dict:
    """Open a sale for customer_id and add one line per qty in line_qtys.
    Returns the sale after the last line add (OPEN)."""
    sale = open_sale(customer_id)
    result = sale
    for qty in line_qtys:
        result = add_line(sale["id"], product_id, qty)
    return result


def complete_sale(sale_id) -> dict:
    return get_success_data(api_client.transition_sale(sale_id, {"action": "COMPLETE"}, CLERK))


# --------------------------------------------------------------------------
# Charter bookings
# --------------------------------------------------------------------------
def create_booking(customer_id, guide_id, venue_id, **overrides) -> dict:
    """Request a booking as the owning customer (REQUESTED)."""
    payload = f.charter_booking_payload(
        customer_id=customer_id, guide_id=guide_id, venue_id=venue_id, **overrides
    )
    return get_success_data(
        api_client.create_charter_booking(payload, make_customer_headers(customer_id))
    )


def quote_booking(booking_id) -> dict:
    return get_success_data(
        api_client.transition_charter_booking(booking_id, {"action": "QUOTE"}, CLERK)
    )


def confirm_booking(booking_id, customer_id) -> dict:
    return get_success_data(
        api_client.transition_charter_booking(
            booking_id, {"action": "CONFIRM"}, make_customer_headers(customer_id)
        )
    )


def setup_confirmed_booking(customer_kwargs=None, guide_kwargs=None,
                            venue_kwargs=None, booking_kwargs=None):
    """Full charter setup through CONFIRMED.

    Returns (customer, guide, venue, booking) where booking is CONFIRMED.
    Callers set the clock beforehand so the quote records the intended season.
    """
    customer = create_customer(**(customer_kwargs or {}))
    guide = create_guide(**(guide_kwargs or {}))
    venue = create_venue(**(venue_kwargs or {}))
    booking = create_booking(customer["id"], guide["id"], venue["id"], **(booking_kwargs or {}))
    quote_booking(booking["id"])
    booking = confirm_booking(booking["id"], customer["id"])
    return customer, guide, venue, booking


def complete_booking(booking_id, guide_id) -> dict:
    """Complete a CONFIRMED booking as the owning guide (fires loyalty cascade)."""
    return get_success_data(
        api_client.transition_charter_booking(
            booking_id, {"action": "COMPLETE"}, make_guide_headers(guide_id)
        )
    )


# --------------------------------------------------------------------------
# Tournaments
# --------------------------------------------------------------------------
def create_tournament(venue_id, **overrides) -> dict:
    payload = f.tournament_payload(venue_id=venue_id, **overrides)
    return get_success_data(api_client.create_tournament(payload, DIRECTOR))


def open_tournament(tournament_id) -> dict:
    return get_success_data(
        api_client.transition_tournament(tournament_id, {"action": "OPEN"}, DIRECTOR)
    )


def start_tournament(tournament_id) -> dict:
    return get_success_data(
        api_client.transition_tournament(tournament_id, {"action": "START"}, DIRECTOR)
    )


def register_entry(tournament_id, customer_id) -> dict:
    payload = f.tournament_entry_payload(customer_id=customer_id)
    return get_success_data(
        api_client.create_tournament_entry(tournament_id, payload, make_customer_headers(customer_id))
    )


def add_weigh_in(entry_id, species="LARGEMOUTH_BASS", weight_grams=3000) -> dict:
    payload = f.weigh_in_payload(species=species, weight_grams=weight_grams)
    return get_success_data(api_client.create_weigh_in(entry_id, payload, DIRECTOR))


def setup_open_tournament(venue_kwargs=None, tournament_kwargs=None):
    """Venue + tournament in REGISTRATION_OPEN. Returns (venue, tournament)."""
    venue = create_venue(**(venue_kwargs or {}))
    tournament = create_tournament(venue["id"], **(tournament_kwargs or {}))
    tournament = open_tournament(tournament["id"])
    return venue, tournament


def setup_registered_entry(customer_kwargs=None, venue_kwargs=None, tournament_kwargs=None):
    """Open tournament with one registered entry.
    Returns (customer, venue, tournament, entry)."""
    customer = create_customer(**(customer_kwargs or {}))
    venue, tournament = setup_open_tournament(venue_kwargs, tournament_kwargs)
    entry = register_entry(tournament["id"], customer["id"])
    return customer, venue, tournament, entry


def setup_in_progress_entry(customer_kwargs=None, venue_kwargs=None, tournament_kwargs=None):
    """Started tournament with one registered entry (ready for weigh-ins).
    Returns (customer, venue, tournament, entry)."""
    customer, venue, tournament, entry = setup_registered_entry(
        customer_kwargs, venue_kwargs, tournament_kwargs
    )
    tournament = start_tournament(tournament["id"])
    return customer, venue, tournament, entry


# --------------------------------------------------------------------------
# Service orders
# --------------------------------------------------------------------------
def transition_service_order(order_id, action) -> dict:
    return get_success_data(
        api_client.transition_service_order(order_id, {"action": action}, CLERK)
    )


def setup_service_order_in_progress(customer_kwargs=None, order_kwargs=None):
    """ServiceOrder advanced RECEIVED -> IN_PROGRESS. Returns (customer, order)."""
    customer = create_customer(**(customer_kwargs or {}))
    order = create_service_order(customer["id"], **(order_kwargs or {}))
    order = transition_service_order(order["id"], "START")
    return customer, order


# --------------------------------------------------------------------------
# Special orders
# --------------------------------------------------------------------------
def transition_special_order(order_id, action) -> dict:
    return get_success_data(
        api_client.transition_special_order(order_id, {"action": action}, CLERK)
    )


def get_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, CLERK))
