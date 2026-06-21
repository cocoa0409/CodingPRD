"""Composite setup helpers for the Karaoke Private Room Booking API.

Most interesting claims need the system walked several steps into a reservation
lifecycle (venue -> room-type -> room -> customer -> reservation -> confirm ->
check-in -> ...). These helpers encapsulate those chains so test files focus on
assertions. All helpers use get_success_data() so a setup failure surfaces as a
clear "Setup step failed" error rather than a confusing assertion deeper in.

Identity threading: every reservation create / confirm / cancel / extend / queue
/ fb-order call uses make_customer_headers(customer["id"]) so the entity_backed
Customer ownership check passes. FrontDesk / VenueManager use opaque headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_room_type_payload,
    create_room_payload,
    create_group_package_payload,
    create_customer_payload,
    create_song_payload,
    create_reservation_payload,
    create_extension_payload,
    create_queue_entry_payload,
    create_fb_order_payload,
)
from .test_users import (
    make_venue_manager_headers,
    make_front_desk_headers,
    make_customer_headers,
)

VM = make_venue_manager_headers()
FD = make_front_desk_headers()

_EMAIL_SEQ = [0]


def _unique_email(prefix: str = "cust") -> str:
    _EMAIL_SEQ[0] += 1
    return f"{prefix}{_EMAIL_SEQ[0]}@example.com"


# ─────────────────────────────────────────────────────────────────
# Tier 1 / Tier 2: base configuration + single entities
# ─────────────────────────────────────────────────────────────────
def create_venue(**overrides) -> dict:
    """Create a venue (VenueManager). Returns the venue resource."""
    return get_success_data(
        api_client.create_venue(create_venue_payload(**overrides), VM)
    )


def create_room_type(venue_id, **overrides) -> dict:
    """Create a room-type under a venue (VenueManager)."""
    return get_success_data(
        api_client.create_room_type(create_room_type_payload(venue_id, **overrides), VM)
    )


def create_room(venue_id, room_type_id, **overrides) -> dict:
    """Create a physical room (VenueManager)."""
    return get_success_data(
        api_client.create_room(create_room_payload(venue_id, room_type_id, **overrides), VM)
    )


def create_group_package(venue_id, included_room_type_id, **overrides) -> dict:
    """Create a group package (VenueManager)."""
    return get_success_data(
        api_client.create_group_package(
            create_group_package_payload(venue_id, included_room_type_id, **overrides), VM
        )
    )


def create_customer(**overrides) -> dict:
    """Register a customer. Email defaults to a unique value per call."""
    if "email" not in overrides:
        overrides["email"] = _unique_email()
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), make_customer_headers("self"))
    )


def create_song(venue_id, **overrides) -> dict:
    """Add a song to the venue catalog (FrontDesk)."""
    return get_success_data(
        api_client.create_song(create_song_payload(venue_id, **overrides), FD)
    )


def set_clock(venue_id, now_utc):
    """Set the venue logical clock (FrontDesk)."""
    return get_success_data(api_client.set_clock(venue_id, {"now_utc": now_utc}, FD))


def run_ops(venue_id):
    """Run the ops sweep (FrontDesk)."""
    return get_success_data(api_client.run_ops(venue_id, FD))


def get_room_version(room_id) -> int:
    """Read the current Room.version for the OCC field on reservation create."""
    return get_success_data(api_client.get_room(room_id, FD))["version"]


def get_reservation_version(reservation_id, customer) -> int:
    """Read the current Reservation.version for the OCC field on extension create."""
    return get_success_data(
        api_client.get_reservation(reservation_id, make_customer_headers(customer["id"]))
    )["version"]


# ─────────────────────────────────────────────────────────────────
# Base scenario: venue + room-type + room + customer, clock set.
# ─────────────────────────────────────────────────────────────────
def setup_base(venue_overrides=None, room_type_overrides=None,
               room_label="Room 1", clock_utc=None):
    """Active venue + one room-type + one room + one customer, with the clock
    optionally set. Returns dict(venue, room_type, room, customer)."""
    venue = create_venue(**(venue_overrides or {}))
    room_type = create_room_type(venue["id"], **(room_type_overrides or {}))
    room = create_room(venue["id"], room_type["id"], label=room_label)
    customer = create_customer()
    if clock_utc is not None:
        set_clock(venue["id"], clock_utc)
    return {"venue": venue, "room_type": room_type, "room": room, "customer": customer}


# ─────────────────────────────────────────────────────────────────
# Tier 3: reservation lifecycle shortcuts
# ─────────────────────────────────────────────────────────────────
def create_held_reservation(venue, room, customer, slot_start_utc, slot_end_utc,
                            party_size=4, group_package_id=None, room_version=None):
    """Create a HELD reservation on a room. Reads room version unless supplied.
    Returns the reservation resource."""
    if room_version is None:
        room_version = get_room_version(room["id"])
    extra = {"party_size": party_size}
    if group_package_id is not None:
        extra["group_package_id"] = group_package_id
    payload = create_reservation_payload(
        venue["id"], room["id"], customer["id"], room_version,
        slot_start_utc, slot_end_utc, **extra,
    )
    return get_success_data(
        api_client.create_reservation(payload, make_customer_headers(customer["id"]))
    )


def confirm_reservation(reservation, customer):
    """Confirm a HELD reservation (Customer). Returns updated reservation."""
    return get_success_data(
        api_client.confirm_reservation(reservation["id"], make_customer_headers(customer["id"]))
    )


def check_in_reservation(reservation):
    """Check in a CONFIRMED reservation (FrontDesk). Returns updated reservation."""
    return get_success_data(
        api_client.check_in_reservation(reservation["id"], FD)
    )


def close_reservation(reservation, actual_end_utc):
    """Close a CHECKED_IN reservation (FrontDesk). Returns settled reservation."""
    return get_success_data(
        api_client.close_reservation(reservation["id"], {"actual_end_utc": actual_end_utc}, FD)
    )


def create_confirmed_reservation(venue, room, customer, slot_start_utc, slot_end_utc,
                                 confirm_clock_utc, party_size=4, group_package_id=None,
                                 room_version=None):
    """Create + confirm a reservation. confirm_clock_utc is set before confirm so
    the timing window passes. Returns the CONFIRMED reservation resource."""
    res = create_held_reservation(
        venue, room, customer, slot_start_utc, slot_end_utc,
        party_size=party_size, group_package_id=group_package_id, room_version=room_version,
    )
    if confirm_clock_utc is not None:
        set_clock(venue["id"], confirm_clock_utc)
    return confirm_reservation(res, customer)


def create_checked_in_reservation(venue, room, customer, slot_start_utc, slot_end_utc,
                                  checkin_clock_utc, confirm_clock_utc=None,
                                  party_size=4, group_package_id=None, room_version=None):
    """Create + confirm + check-in a reservation. Sets the clock to checkin_clock_utc
    before check-in. Returns the CHECKED_IN reservation resource."""
    res = create_confirmed_reservation(
        venue, room, customer, slot_start_utc, slot_end_utc,
        confirm_clock_utc=confirm_clock_utc, party_size=party_size,
        group_package_id=group_package_id, room_version=room_version,
    )
    set_clock(venue["id"], checkin_clock_utc)
    return check_in_reservation(res)


# ─────────────────────────────────────────────────────────────────
# Children: queue entries, fb orders, extensions
# ─────────────────────────────────────────────────────────────────
def queue_song(reservation, customer, song_id, priority=None):
    """Queue a song in a reservation (Customer). Returns the queue entry."""
    extra = {} if priority is None else {"priority": priority}
    return get_success_data(
        api_client.queue_song(
            reservation["id"], create_queue_entry_payload(song_id, **extra),
            make_customer_headers(customer["id"]),
        )
    )


def add_fb_order(reservation, customer, unit_price_cents, quantity, description="Item"):
    """Place an F&B order on a reservation (Customer). Returns the order."""
    payload = create_fb_order_payload(
        description=description, unit_price_cents=unit_price_cents, quantity=quantity,
    )
    return get_success_data(
        api_client.create_fb_order(reservation["id"], payload, make_customer_headers(customer["id"]))
    )


def void_fb_order(fb_order_id):
    """Void an F&B order (FrontDesk)."""
    return get_success_data(api_client.void_fb_order(fb_order_id, FD))


def apply_extension(reservation, customer, new_slot_end_utc, expected_reservation_version):
    """Apply an extension to a reservation (Customer). Returns the extension."""
    payload = create_extension_payload(new_slot_end_utc, expected_reservation_version)
    return get_success_data(
        api_client.create_extension(reservation["id"], payload, make_customer_headers(customer["id"]))
    )


# ─────────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────────
def get_reservation(reservation_id, headers=None):
    """Fetch a reservation by id (default FrontDesk reader)."""
    return get_success_data(api_client.get_reservation(reservation_id, headers or FD))


def get_room(room_id, headers=None):
    return get_success_data(api_client.get_room(room_id, headers or FD))


def get_queue_entry(queue_entry_id, headers=None):
    return get_success_data(api_client.get_queue_entry(queue_entry_id, headers or FD))


def get_customer(customer_id, headers=None):
    return get_success_data(api_client.get_customer(customer_id, headers or FD))


def list_payments(reservation_id, headers=None):
    """Return the payment ledger list for a reservation (PRD: GET /payments?reservation_id=)."""
    resp = api_client.list_payments(headers or FD, params={"reservation_id": reservation_id})
    body = resp.json()
    assert 200 <= resp.status_code < 300, f"list payments failed: {resp.status_code} {resp.text}"
    return body["data"]
