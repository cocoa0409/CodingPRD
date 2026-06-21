"""Composite setup helpers for multi-step test prerequisites.

Every fixture uses get_success_data() (lenient validator) so a setup failure
produces a clear 'Setup failed' error rather than a confusing assertion.

The test harness restarts the API server before each pytest test, so every
fixture starts against an empty database and builds its preconditions from
scratch using only PRD-declared endpoints.

Identity threading: every fixture that creates an entity_backed Captain or
Customer then issues an ownership-gated call (sail, weather-hold, catch-report
for the captain; create / pay / cancel booking, add-on for the customer) uses
make_captain_headers / make_customer_headers with the just-created entity id.
The shared TEST_USERS['captain_headers'] / ['customer_headers'] constants are
NEVER used for ownership-gated calls inside this file.

Charter version threading: booking creation and slot-reservation creation each
advance the charter's version (PRD §2.6/§2.8). Helpers therefore re-read the
charter's live version with current_charter_version() immediately before each
version-gated write.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_marina_payload,
    create_dock_slot_payload,
    create_boat_payload,
    create_captain_payload,
    create_mate_payload,
    create_permit_payload,
    create_customer_payload,
    create_charter_payload,
    create_crew_assignment_payload,
    create_slot_reservation_payload,
    create_booking_payload,
    create_add_on_line_payload,
    create_catch_report_payload,
)
from .test_users import TEST_USERS, make_captain_headers, make_customer_headers


DOCK_MASTER = TEST_USERS["dock_master_headers"]
FLEET_MANAGER = TEST_USERS["fleet_manager_headers"]


# ---- Tier 0: atomic helpers --------------------------------------------------

def pin_clock(iso_time: str) -> None:
    """Pin the server clock (PRD §3.9). Needed so depart-time gating, lead-time
    refunds, and slot-window occupancy are deterministic."""
    get_success_data(api_client.set_clock(iso_time, FLEET_MANAGER))


def create_marina(**overrides) -> dict:
    return get_success_data(api_client.create_marina(create_marina_payload(**overrides), DOCK_MASTER))


def create_dock_slot(marina_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dock_slot(create_dock_slot_payload(marina_id, **overrides), DOCK_MASTER)
    )


def create_boat(marina_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_boat(create_boat_payload(marina_id, **overrides), FLEET_MANAGER)
    )


def create_captain(marina_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_captain(create_captain_payload(marina_id, **overrides), FLEET_MANAGER)
    )


def create_mate(marina_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_mate(create_mate_payload(marina_id, **overrides), FLEET_MANAGER)
    )


def create_permit(**overrides) -> dict:
    return get_success_data(api_client.create_permit(create_permit_payload(**overrides), FLEET_MANAGER))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), DOCK_MASTER))


def create_charter(marina_id: str, boat_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_charter(create_charter_payload(marina_id, boat_id, **overrides), FLEET_MANAGER)
    )


def current_charter_version(charter_id: str) -> int:
    """Read the charter's live version (used to thread OCC writes)."""
    return get_success_data(api_client.get_charter(charter_id, FLEET_MANAGER))["version"]


def get_charter(charter_id: str) -> dict:
    return get_success_data(api_client.get_charter(charter_id, FLEET_MANAGER))


def assign_captain(charter_id: str, captain_id: str) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(charter_id, "CAPTAIN", captain_id=captain_id), FLEET_MANAGER
    ))


def assign_mate(charter_id: str, mate_id: str) -> dict:
    return get_success_data(api_client.create_crew_assignment(
        create_crew_assignment_payload(charter_id, "MATE", mate_id=mate_id), FLEET_MANAGER
    ))


def reserve_slot(dock_slot_id: str, charter_id: str) -> dict:
    version = current_charter_version(charter_id)
    return get_success_data(api_client.create_slot_reservation(
        create_slot_reservation_payload(dock_slot_id, charter_id, version), DOCK_MASTER
    ))


def create_booking(charter_id: str, customer_id: str, **overrides) -> dict:
    """Create a booking, threading the charter's live version into the OCC field."""
    version = current_charter_version(charter_id)
    return get_success_data(api_client.create_booking(
        create_booking_payload(charter_id, customer_id, version, **overrides),
        make_customer_headers(customer_id),
    ))


def pay_deposit(booking_id: str, customer_id: str, amount_cents: int) -> dict:
    return get_success_data(api_client.pay_deposit(
        booking_id, {"amount_cents": amount_cents}, make_customer_headers(customer_id)
    ))


def add_on_line(booking_id: str, customer_id: str, addon_kind: str, quantity: int) -> dict:
    return get_success_data(api_client.create_add_on_line(
        create_add_on_line_payload(booking_id, addon_kind, quantity),
        make_customer_headers(customer_id),
    ))


def file_catch_report(charter_id: str, captain_id: str, species: str,
                      fish_count: int, released_count: int = 0) -> dict:
    return get_success_data(api_client.create_catch_report(
        create_catch_report_payload(charter_id, species, fish_count, released_count=released_count),
        make_captain_headers(captain_id),
    ))


# ---- Tier 1: base scenarios --------------------------------------------------

def setup_marina_boat_customer(boat_overrides=None, marina_overrides=None):
    """Active marina + one boat + one customer. Returns (marina, boat, customer)."""
    marina = create_marina(**(marina_overrides or {}))
    boat = create_boat(marina["id"], **(boat_overrides or {}))
    customer = create_customer()
    return marina, boat, customer


def setup_draft_charter(charter_overrides=None, boat_overrides=None, marina_overrides=None):
    """Marina + boat + customer + a DRAFT charter. Returns
    (marina, boat, customer, charter)."""
    marina, boat, customer = setup_marina_boat_customer(boat_overrides, marina_overrides)
    charter = create_charter(marina["id"], boat["id"], **(charter_overrides or {}))
    return marina, boat, customer, charter


# ---- Tier 2/3: lifecycle shortcuts (INSHORE, single captain) ----------------

def setup_scheduled_charter(charter_overrides=None, party_size=2, deposit_cents=5000,
                            booking_overrides=None, customer_loyalty=None):
    """Build an INSHORE charter all the way to SCHEDULED with one paid (CONFIRMED)
    booking.

    Returns a dict with keys: marina, slot, boat, captain, customer, charter
    (fresh GET after schedule), booking, crew, reservation.

    Internally: marina + slot + boat + captain + customer + charter (DRAFT) ->
    assign captain -> reserve slot -> create booking -> pay deposit -> schedule.
    """
    marina = create_marina()
    slot = create_dock_slot(marina["id"])
    boat = create_boat(marina["id"])
    captain = create_captain(marina["id"])
    cust_overrides = {}
    if customer_loyalty is not None:
        cust_overrides["loyalty_tier"] = customer_loyalty
    customer = create_customer(**cust_overrides)
    charter = create_charter(marina["id"], boat["id"], **(charter_overrides or {}))

    crew = assign_captain(charter["id"], captain["id"])
    reservation = reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=party_size,
                             **(booking_overrides or {}))
    pay_deposit(booking["id"], customer["id"], deposit_cents)
    get_success_data(api_client.schedule_charter(charter["id"], FLEET_MANAGER))

    return {
        "marina": marina,
        "slot": slot,
        "boat": boat,
        "captain": captain,
        "customer": customer,
        "charter": get_charter(charter["id"]),
        "booking": get_success_data(api_client.get_booking(booking["id"], FLEET_MANAGER)),
        "crew": crew,
        "reservation": reservation,
    }


def setup_weather_hold_charter(**kwargs):
    """Build an INSHORE charter to WEATHER_HOLD (scheduled, then captain calls a
    weather hold). Returns the same dict as setup_scheduled_charter with a fresh
    charter GET."""
    ctx = setup_scheduled_charter(**kwargs)
    get_success_data(api_client.weather_hold_charter(
        ctx["charter"]["id"], make_captain_headers(ctx["captain"]["id"])
    ))
    ctx["charter"] = get_charter(ctx["charter"]["id"])
    return ctx


def setup_sailed_charter(charter_overrides=None, party_size=2, deposit_cents=5000,
                         booking_overrides=None):
    """Build an INSHORE charter through to SAILED (clock past depart). Returns the
    same dict as setup_scheduled_charter with a fresh charter GET after sail."""
    ctx = setup_scheduled_charter(charter_overrides=charter_overrides, party_size=party_size,
                                  deposit_cents=deposit_cents, booking_overrides=booking_overrides)
    get_success_data(api_client.sail_charter(
        ctx["charter"]["id"], make_captain_headers(ctx["captain"]["id"])
    ))
    ctx["charter"] = get_charter(ctx["charter"]["id"])
    return ctx


# ---- Tier 4: offshore lifecycle (captain + mate + permit) -------------------

def setup_scheduled_offshore_charter(daily_bag_limit=20, charter_overrides=None,
                                     party_size=2, deposit_cents=15000):
    """Build an OFFSHORE charter to SCHEDULED with a captain, a certified mate, a
    federal permit, an offshore-rated boat, a reserved slot, and one paid booking.

    Returns a dict: marina, slot, boat, captain, mate, permit, customer, charter,
    booking.
    """
    marina = create_marina()
    slot = create_dock_slot(marina["id"], max_boat_length_ft=50)
    boat = create_boat(marina["id"], length_ft=42, passenger_capacity=8, offshore_rated=True)
    permit = create_permit(daily_bag_limit=daily_bag_limit)
    captain = create_captain(marina["id"], uscg_license_grade="MASTER_100")
    mate = create_mate(marina["id"], certified_offshore=True)
    customer = create_customer()
    overrides = {
        "trip_type": "OFFSHORE",
        "permit_id": permit["id"],
        "base_seat_price_cents": 30000,
        "seats_total": 8,
        "depart_at": "2027-06-10T06:00:00Z",
        "return_at": "2027-06-10T18:00:00Z",
    }
    overrides.update(charter_overrides or {})
    charter = create_charter(marina["id"], boat["id"], **overrides)

    assign_captain(charter["id"], captain["id"])
    assign_mate(charter["id"], mate["id"])
    reserve_slot(slot["id"], charter["id"])
    booking = create_booking(charter["id"], customer["id"], party_size=party_size)
    pay_deposit(booking["id"], customer["id"], deposit_cents)
    get_success_data(api_client.schedule_charter(charter["id"], FLEET_MANAGER))

    return {
        "marina": marina,
        "slot": slot,
        "boat": boat,
        "captain": captain,
        "mate": mate,
        "permit": permit,
        "customer": customer,
        "charter": get_charter(charter["id"]),
        "booking": get_success_data(api_client.get_booking(booking["id"], FLEET_MANAGER)),
    }


def setup_sailed_offshore_charter(daily_bag_limit=20, charter_overrides=None):
    """Build an OFFSHORE charter through to SAILED (clock past depart)."""
    ctx = setup_scheduled_offshore_charter(daily_bag_limit=daily_bag_limit,
                                           charter_overrides=charter_overrides)
    get_success_data(api_client.sail_charter(
        ctx["charter"]["id"], make_captain_headers(ctx["captain"]["id"])
    ))
    ctx["charter"] = get_charter(ctx["charter"]["id"])
    return ctx
