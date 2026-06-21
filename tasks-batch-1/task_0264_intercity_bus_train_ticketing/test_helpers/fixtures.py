"""Composite setup helpers for the Intercity Ticketing API.

Each test runs against a freshly restarted, empty server, so every fixture builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
the lenient get_success_data() validator so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.

Identity threading: the Passenger role is entity_backed, so every ownership-gated
call uses make_passenger_headers(passenger["id"]) with the actual passenger id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_passenger_headers,
    schedule_manager_headers,
    fare_analyst_headers,
    support_agent_headers,
    gate_agent_headers,
)
from . import factories as f

CANONICAL_CLOCK = "2026-06-01T00:00:00Z"


# ─── Clock ────────────────────────────────────────────
def set_clock(to_iso8601=CANONICAL_CLOCK):
    """Pin the server clock for deterministic time-dependent setups."""
    return get_success_data(api.set_clock(to_iso8601, support_agent_headers()))


# ─── Tier 1: leaf creators ────────────────────────────
def create_operator(**overrides) -> dict:
    return get_success_data(
        api.create_operator(f.create_operator_payload(**overrides), schedule_manager_headers())
    )


def create_fare_class(operator_id, **overrides) -> dict:
    return get_success_data(
        api.create_fare_class(
            f.create_fare_class_payload(operator_id, **overrides), fare_analyst_headers()
        )
    )


def create_published_route(operator_id, **overrides) -> dict:
    route = get_success_data(
        api.create_route(f.create_route_payload(operator_id, **overrides), schedule_manager_headers())
    )
    get_success_data(api.publish_route(route["id"], schedule_manager_headers()))
    # Re-read so callers see PUBLISHED status + bumped version.
    return get_success_data(api.get_route(route["id"], schedule_manager_headers()))


def create_service_date(route_id, **overrides) -> dict:
    return get_success_data(
        api.create_service_date(
            f.create_service_date_payload(route_id, **overrides), schedule_manager_headers()
        )
    )


def create_passenger(**overrides) -> dict:
    return get_success_data(
        api.create_passenger(f.create_passenger_payload(**overrides), TEST_USERS["passenger_headers"])
    )


def create_pass(passenger_id, operator_id, **overrides) -> dict:
    return get_success_data(
        api.create_pass(
            f.create_pass_payload(passenger_id, operator_id, **overrides), support_agent_headers()
        )
    )


# ─── Tier 2: catalog setup ────────────────────────────
def setup_catalog(operator_overrides=None, fare_overrides=None, route_overrides=None,
                  service_date_overrides=None, set_clock_first=True):
    """Operator + ACTIVE fare class + PUBLISHED route + one SCHEDULED/OPEN ServiceDate.

    Returns dict: {operator, fare_class, route, service_date}.
    """
    if set_clock_first:
        set_clock()
    operator = create_operator(**(operator_overrides or {}))
    fare_class = create_fare_class(operator["id"], **(fare_overrides or {}))
    route = create_published_route(operator["id"], **(route_overrides or {}))
    service_date = create_service_date(route["id"], **(service_date_overrides or {}))
    return {
        "operator": operator,
        "fare_class": fare_class,
        "route": route,
        "service_date": service_date,
    }


# ─── Tier 3: booking lifecycle shortcuts ──────────────
def hold_booking(passenger_id, service_date_id, fare_class_id, leg_order=1,
                 seat_number=None, funding_kind="CASH", pass_id=None, legs=None) -> dict:
    """Create a HELD booking. By default a single leg; pass `legs` to override."""
    if legs is None:
        legs = [f.leg_payload(service_date_id, fare_class_id, leg_order, seat_number)]
    return get_success_data(
        api.create_booking(
            f.create_booking_payload(passenger_id, legs, funding_kind=funding_kind, pass_id=pass_id),
            make_passenger_headers(passenger_id),
        )
    )


def current_sd_version(service_date_id) -> int:
    """Latest ServiceDate.version — the OCC baseline for confirm."""
    sd = get_success_data(api.get_service_date(service_date_id, schedule_manager_headers()))
    return sd["version"]


def confirm_booking(booking_id, passenger_id, service_date_id) -> dict:
    """Confirm a HELD booking against the live ServiceDate.version (OCC baseline)."""
    sd_v = current_sd_version(service_date_id)
    return get_success_data(
        api.confirm_booking(booking_id, f.confirm_payload(sd_v), make_passenger_headers(passenger_id))
    )


def pay_booking(booking_id, passenger_id) -> dict:
    return get_success_data(api.pay_booking(booking_id, make_passenger_headers(passenger_id)))


def hold_and_confirm(passenger_id, service_date_id, fare_class_id, leg_order=1,
                     seat_number=None, funding_kind="CASH", pass_id=None) -> dict:
    """HELD -> CONFIRMED single-leg booking. Returns the confirmed booking."""
    booking = hold_booking(
        passenger_id, service_date_id, fare_class_id, leg_order, seat_number,
        funding_kind=funding_kind, pass_id=pass_id,
    )
    return confirm_booking(booking["id"], passenger_id, service_date_id)


def hold_confirm_pay(passenger_id, service_date_id, fare_class_id, leg_order=1,
                     seat_number=None) -> dict:
    """HELD -> CONFIRMED -> PAID single-leg CASH booking. Returns the PAID booking."""
    booking = hold_booking(passenger_id, service_date_id, fare_class_id, leg_order, seat_number)
    confirm_booking(booking["id"], passenger_id, service_date_id)
    return pay_booking(booking["id"], passenger_id)


# ─── Tier 4: load-factor / accumulation targeting ─────
def prefill_confirmed_seats(service_date_id, fare_class_id, count, reserved=False,
                            email_prefix="seed", seat_prefix="1"):
    """Confirm `count` single-leg bookings (each a distinct passenger) on the
    ServiceDate so its seats_sold == count and load_factor == count/seats_total.

    For RESERVED classes, distinct seat numbers are assigned (1A, 1B, ...).
    Returns the list of confirmed booking dicts.
    """
    confirmed = []
    for i in range(count):
        passenger = create_passenger(full_name=f"Seed {i}", email=f"{email_prefix}{i}@x.com")
        seat = f"{seat_prefix}{chr(ord('A') + i)}" if reserved else None
        booking = hold_and_confirm(
            passenger["id"], service_date_id, fare_class_id, seat_number=seat
        )
        confirmed.append(booking)
    return confirmed


def setup_service_date_at_load_factor(num_confirmed, seats_total, base_fare_cents=4000,
                                      departure_date="2026-06-15", reserved=False,
                                      fare_overrides=None, operator_overrides=None):
    """Catalog with a ServiceDate pre-loaded to seats_sold == num_confirmed
    (load_factor == num_confirmed/seats_total). Then a fresh test passenger is
    created and returned with a fresh re-read of the ServiceDate.

    Returns dict: {operator, fare_class, route, service_date, test_passenger,
                   seed_bookings}.
    """
    fare_overrides = fare_overrides or {}
    if reserved:
        fare_overrides.setdefault("code", "BUSINESS")
        fare_overrides.setdefault("seating_mode", "RESERVED")
    cat = setup_catalog(
        operator_overrides=operator_overrides,
        fare_overrides=fare_overrides,
        service_date_overrides={
            "seats_total": seats_total,
            "base_fare_cents": base_fare_cents,
            "departure_date": departure_date,
        },
    )
    seeds = prefill_confirmed_seats(
        cat["service_date"]["id"], cat["fare_class"]["id"], num_confirmed, reserved=reserved
    )
    test_passenger = create_passenger(full_name="Test Buyer", email="test@x.com")
    cat["service_date"] = get_success_data(
        api.get_service_date(cat["service_date"]["id"], schedule_manager_headers())
    )
    cat["test_passenger"] = test_passenger
    cat["seed_bookings"] = seeds
    return cat


# ─── Tier 5: terminal / cancel / exchange / scanned-ticket states ──
def setup_paid_booking(refundable=True, base_fare_cents=4000, departure_date="2026-06-15",
                       seats_total=10):
    """Full single-leg CASH booking through to PAID. Returns dict with catalog +
    {passenger, booking} where booking is CONFIRMED + PAID.
    """
    cat = setup_catalog(
        fare_overrides={"refundable": refundable},
        service_date_overrides={
            "seats_total": seats_total,
            "base_fare_cents": base_fare_cents,
            "departure_date": departure_date,
        },
    )
    passenger = create_passenger()
    booking = hold_confirm_pay(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    cat["passenger"] = passenger
    cat["booking"] = booking
    return cat


def setup_scanned_ticket_booking(refundable=True):
    """CONFIRMED + PAID single-leg booking whose one ticket has been SCANNED by a
    GateAgent. Returns dict with catalog + {passenger, booking, ticket}.
    """
    cat = setup_paid_booking(refundable=refundable)
    passenger = cat["passenger"]
    booking = cat["booking"]
    tickets, _ = _list(api.list_tickets(gate_agent_headers(), params={"booking_id": booking["id"]}))
    ticket = tickets[0]
    get_success_data(api.scan_ticket(ticket["id"], gate_agent_headers()))
    cat["ticket"] = get_success_data(api.get_ticket(ticket["id"], gate_agent_headers()))
    return cat


def setup_exchange_ready(base_fare_cents=4000, exchange_fee_cents=1000,
                         origin_departure="2026-06-15", target_departure="2026-06-03",
                         seats_total=10):
    """A PAID single-leg CASH booking on an original ServiceDate, plus a separate
    target ServiceDate on the same operator (so an exchange can be performed).

    Returns dict: {operator, fare_class, route, service_date (=original),
                   target_service_date, passenger, booking}.
    """
    set_clock()
    operator = create_operator(exchange_fee_cents=exchange_fee_cents)
    fare_class = create_fare_class(operator["id"])
    route = create_published_route(operator["id"])
    original = create_service_date(
        route["id"], seats_total=seats_total, base_fare_cents=base_fare_cents,
        departure_date=origin_departure,
    )
    target = create_service_date(
        route["id"], seats_total=seats_total, base_fare_cents=base_fare_cents,
        departure_date=target_departure,
    )
    passenger = create_passenger()
    booking = hold_confirm_pay(passenger["id"], original["id"], fare_class["id"])
    return {
        "operator": operator,
        "fare_class": fare_class,
        "route": route,
        "service_date": original,
        "target_service_date": target,
        "passenger": passenger,
        "booking": booking,
    }


def setup_pass_booking_confirmed(rides_total=10, seats_total=10):
    """A PASS-funded single-leg booking, confirmed (one ride consumed). Returns
    dict with catalog + {passenger, travel_pass, booking}.
    """
    cat = setup_catalog(service_date_overrides={"seats_total": seats_total})
    passenger = create_passenger()
    travel_pass = create_pass(passenger["id"], cat["operator"]["id"], rides_total=rides_total)
    booking = hold_and_confirm(
        passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    cat["passenger"] = passenger
    cat["travel_pass"] = travel_pass
    cat["booking"] = booking
    return cat


# ─── List helpers (used to discover server-minted child ids) ──
def _list(response):
    """Return (data_list, meta) from a list response via the lenient validator."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})


def legs_for_booking(booking_id, passenger_id):
    data, _ = _list(api.list_legs(make_passenger_headers(passenger_id), params={"booking_id": booking_id}))
    return data


def tickets_for_booking(booking_id):
    data, _ = _list(api.list_tickets(gate_agent_headers(), params={"booking_id": booking_id}))
    return data


def settlement_notes_for_booking(booking_id, passenger_id):
    data, _ = _list(
        api.list_settlement_notes(make_passenger_headers(passenger_id), params={"booking_id": booking_id})
    )
    return data
