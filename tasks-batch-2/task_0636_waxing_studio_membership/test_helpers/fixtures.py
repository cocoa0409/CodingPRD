"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before every test. Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion failure.

Identity threading: after creating a Member or Technician (entity_backed roles),
ownership-gated calls use make_member_headers(member_id) /
make_technician_headers(technician_id), never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_technician_headers,
    make_front_desk_headers,
    make_studio_admin_headers,
)
from .factories import (
    create_location_payload,
    create_service_type_payload,
    create_product_payload,
    create_room_payload,
    create_technician_payload,
    create_member_payload,
    create_membership_payload,
    create_reservation_payload,
    create_retail_sale_payload,
    unique_email,
)
from .constants import DEFAULT_CLOCK_UTC

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str):
    """Set the logical clock (StudioAdmin). Runs scheduled sweeps as a side effect."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweeps():
    return get_success_data(api_client.run_sweeps(ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: Base configuration (location + service + room + technician + member)
# ---------------------------------------------------------------------------
def create_location(**overrides) -> dict:
    return get_success_data(api_client.create_location(create_location_payload(**overrides), ADMIN))


def create_service_type(**overrides) -> dict:
    return get_success_data(api_client.create_service_type(create_service_type_payload(**overrides), ADMIN))


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def create_room(location_id, **overrides) -> dict:
    return get_success_data(api_client.create_room(create_room_payload(location_id, **overrides), ADMIN))


def create_technician(location_id, certified_service_ids=None, **overrides) -> dict:
    return get_success_data(api_client.create_technician(
        create_technician_payload(location_id, certified_service_ids, **overrides), ADMIN))


def create_member(home_location_id, **overrides) -> dict:
    return get_success_data(api_client.create_member(
        create_member_payload(home_location_id, **overrides), FRONT))


def setup_studio(clock=None, location_overrides=None, service_overrides=None):
    """Create a fully wired studio: clock + location + service + room + certified
    technician + member. Returns a dict of the created entities and their key
    versions.

    Keys: loc, svc, room, tech, member, room_version.
    """
    if clock is not None:
        set_clock(clock)
    loc = create_location(**(location_overrides or {}))
    svc = create_service_type(**(service_overrides or {}))
    room = create_room(loc["id"])
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]])
    member = create_member(loc["id"])
    return {
        "loc": loc,
        "svc": svc,
        "room": room,
        "tech": tech,
        "member": member,
        "room_version": room["version"],
    }


# ---------------------------------------------------------------------------
# Tier 1: Membership state progression
# ---------------------------------------------------------------------------
def create_membership(member_id, **overrides) -> dict:
    return get_success_data(api_client.create_membership(
        create_membership_payload(member_id, **overrides), FRONT))


def create_and_activate_membership(member_id, **overrides) -> dict:
    """Create a PENDING membership and activate it (PENDING -> ACTIVE, grants
    first-cycle credits). Returns the ACTIVE membership object."""
    mbr = create_membership(member_id, **overrides)
    return get_success_data(api_client.activate_membership(mbr["id"], FRONT))


def create_frozen_membership(member_id, freeze_days=30, **overrides) -> dict:
    """ACTIVE membership then FROZEN for freeze_days. Returns the FROZEN membership."""
    mbr = create_and_activate_membership(member_id, **overrides)
    return get_success_data(api_client.freeze_membership(
        mbr["id"], {"freeze_days": freeze_days}, make_member_headers(member_id)))


# ---------------------------------------------------------------------------
# Tier 3: Reservation lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_reservation(member, location_id, room_id, technician_id, service_type_id,
                     start_utc, payment_method, expected_room_version,
                     membership_id=None, expected_membership_version=None,
                     booked_by="member", **overrides) -> dict:
    """Create one reservation. By default the booking member books for themselves
    (ownership-correct). Pass booked_by='frontdesk' for a desk booking."""
    payload = create_reservation_payload(
        member_id=member["id"],
        location_id=location_id,
        room_id=room_id,
        technician_id=technician_id,
        service_type_id=service_type_id,
        start_utc=start_utc,
        payment_method=payment_method,
        expected_room_version=expected_room_version,
        **overrides,
    )
    if membership_id is not None:
        payload["membership_id"] = membership_id
    if expected_membership_version is not None:
        payload["expected_membership_version"] = expected_membership_version
    headers = FRONT if booked_by == "frontdesk" else make_member_headers(member["id"])
    return get_success_data(api_client.create_reservation(payload, headers))


def check_in(reservation_id):
    return get_success_data(api_client.check_in_reservation(reservation_id, FRONT))


def complete(reservation_id):
    return get_success_data(api_client.complete_reservation(reservation_id, FRONT))


def book_and_complete_walk_in(studio, start_utc, checkin_clock):
    """Book a WALK_IN reservation, advance the clock, check in, and complete it.
    Returns the completed reservation. studio is the dict from setup_studio()."""
    res = book_reservation(
        member=studio["member"],
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc=start_utc,
        payment_method="WALK_IN",
        expected_room_version=studio["room"]["version"],
    )
    set_clock(checkin_clock)
    check_in(res["id"])
    return complete(res["id"])


# ---------------------------------------------------------------------------
# Tier 4: Strike accumulation / threshold targeting
# ---------------------------------------------------------------------------
def accumulate_no_show_strikes(studio, count, base_start="2026-06-16T10:00:00Z",
                               sweep_clock="2026-06-16T12:00:00Z"):
    """Book `count` DEPOSIT reservations on consecutive hourly slots, advance the
    clock past their no-show window, and mark each NO_SHOW so the member ends
    with `count` ACTIVE strikes. Returns the list of reservation ids.

    Slots are hourly (non-overlapping for a 15/30-min service with a 5m buffer);
    `base_start` is the first slot start (10:00Z).
    """
    member = studio["member"]
    room = studio["room"]
    room_version = room["version"]
    res_ids = []
    # base_start hour as integer; book at base_hour, base_hour+1, ...
    base_hour = int(base_start[11:13])
    date = base_start[:10]
    for i in range(count):
        start = f"{date}T{base_hour + i:02d}:00:00Z"
        res = book_reservation(
            member=member,
            location_id=studio["loc"]["id"],
            room_id=room["id"],
            technician_id=studio["tech"]["id"],
            service_type_id=studio["svc"]["id"],
            start_utc=start,
            payment_method="DEPOSIT",
            expected_room_version=room_version,
            booked_by="frontdesk",
        )
        res_ids.append(res["id"])
        # Each booking holds the room and advances its version.
        room_version = res["version"] if "version" in res else room_version
        fresh_room = get_success_data(api_client.get_room(room["id"], ADMIN))
        room_version = fresh_room["version"]
    set_clock(sweep_clock)
    for rid in res_ids:
        get_success_data(api_client.mark_no_show_reservation(rid, FRONT))
    return res_ids


def get_member(member_id) -> dict:
    return get_success_data(api_client.get_member(member_id, FRONT))


def get_membership(membership_id, member_id=None) -> dict:
    headers = make_member_headers(member_id) if member_id else FRONT
    return get_success_data(api_client.get_membership(membership_id, headers))


def get_reservation(reservation_id) -> dict:
    return get_success_data(api_client.get_reservation(reservation_id, FRONT))


def get_room_version(room_id) -> int:
    return get_success_data(api_client.get_room(room_id, ADMIN))["version"]


def get_membership_version(membership_id) -> int:
    return get_success_data(api_client.get_membership(membership_id, FRONT))["version"]


# ---------------------------------------------------------------------------
# Tier 5: Retail attach
# ---------------------------------------------------------------------------
def attach_retail_sale(member, reservation_id, product_id, quantity) -> dict:
    """Attach a PENDING retail sale to a reservation (member books for self)."""
    return get_success_data(api_client.create_retail_sale(
        create_retail_sale_payload(member["id"], reservation_id, product_id, quantity),
        make_member_headers(member["id"]),
    ))
