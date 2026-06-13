"""Composite setup helpers for the Cruise Booking & Cabin Management API.

Each helper builds multi-step preconditions from scratch using only
PRD-declared endpoints, because the harness restarts the server (empty DB)
before every test. Helpers use get_success_data() (lenient) internally so
setup failures surface as clear "Setup failed" errors.

Identity threading: GuestUser is entity-backed by the booking it owns. Every
ownership-gated call uses make_guest_user_headers(owner_user_id) with the exact
owner_user_id passed at booking creation.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_guest_user_headers
from .factories import (
    create_sailing_payload,
    create_cabin_category_payload,
    create_cabin_payload,
    create_group_block_payload,
    create_booking_payload,
    create_guest_payload,
    create_payment_payload,
)

RM = TEST_USERS["revenue_manager_headers"]
PA = TEST_USERS["port_agent_headers"]
RA = TEST_USERS["reservations_agent_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the simulated UTC clock (RevenueManager only)."""
    return get_success_data(api_client.set_clock(to_iso8601, RM))


# --------------------------------------------------------------------------
# Tier 1/2: Inventory foundation
# --------------------------------------------------------------------------
def create_sailing(**overrides):
    """Create a DRAFT sailing. Returns the sailing dict."""
    return get_success_data(api_client.create_sailing(create_sailing_payload(**overrides), RM))


def create_category(sailing_id, **overrides):
    """Create a cabin category on a sailing. Returns the category dict."""
    return get_success_data(
        api_client.create_cabin_category(
            create_cabin_category_payload(sailing_id, **overrides), RM
        )
    )


def create_cabins(category_id, count, start_number=8001, deck=8):
    """Create `count` cabins in a category with sequential numbers. Returns list."""
    cabins = []
    for i in range(count):
        cabins.append(
            get_success_data(
                api_client.create_cabin(
                    create_cabin_payload(category_id, str(start_number + i), deck=deck), RM
                )
            )
        )
    return cabins


def setup_sailing_with_inventory(num_cabins=2, category_overrides=None, **sailing_overrides):
    """DRAFT sailing + one category + num_cabins cabins.

    Returns (sailing, category, [cabins]). Sailing is NOT yet opened.
    """
    category_overrides = category_overrides or {}
    sailing = create_sailing(**sailing_overrides)
    category = create_category(sailing["id"], **category_overrides)
    cabins = create_cabins(category["id"], num_cabins)
    return sailing, category, cabins


def open_sailing(sailing_id):
    """Open a sailing (DRAFT/CLOSED -> OPEN). Returns the updated sailing dict."""
    return get_success_data(api_client.open_sailing(sailing_id, RM))


def setup_open_sailing(num_cabins=2, category_overrides=None, **sailing_overrides):
    """Open sailing + category + cabins.

    Returns (sailing_after_open, category, [cabins]). The returned sailing
    reflects the post-open version.
    """
    sailing, category, cabins = setup_sailing_with_inventory(
        num_cabins=num_cabins, category_overrides=category_overrides, **sailing_overrides
    )
    opened = open_sailing(sailing["id"])
    return opened, category, cabins


# --------------------------------------------------------------------------
# Group blocks
# --------------------------------------------------------------------------
def create_group_block(sailing_id, category_id, **overrides):
    """Create a NEGOTIATING group block. Returns the block dict."""
    return get_success_data(
        api_client.create_group_block(
            create_group_block_payload(sailing_id, category_id, **overrides), RM
        )
    )


def hold_group_block(block_id):
    """Hold a block (NEGOTIATING -> HELD). Returns the updated block dict."""
    return get_success_data(api_client.hold_group_block(block_id, RM))


def setup_held_group_block(num_cabins=4, block_size=2, group_discount_pct=0.15,
                           open_first=True, **sailing_overrides):
    """Open sailing + category + cabins + a HELD group block.

    Returns (sailing, category, cabins, block). The block holds `block_size`
    cabins (created_at ASC). When open_first is False the sailing is left DRAFT
    (block hold requires OPEN/CLOSED so callers usually keep True).
    """
    if open_first:
        sailing, category, cabins = setup_open_sailing(
            num_cabins=num_cabins, **sailing_overrides
        )
    else:
        sailing, category, cabins = setup_sailing_with_inventory(
            num_cabins=num_cabins, **sailing_overrides
        )
    block = create_group_block(
        sailing["id"], category["id"],
        block_size=block_size, group_discount_pct=group_discount_pct,
    )
    held = hold_group_block(block["id"])
    return sailing, category, cabins, held


# --------------------------------------------------------------------------
# Bookings — QUOTE / DEPOSIT_HELD / CONFIRMED
# --------------------------------------------------------------------------
def create_booking(sailing_id, category_id, owner_user_id, sailing_version,
                   group_block_id=None):
    """Create a QUOTE booking owned by owner_user_id. Returns the booking dict."""
    extra = {}
    if group_block_id is not None:
        extra["group_block_id"] = group_block_id
    headers = make_guest_user_headers(owner_user_id)
    return get_success_data(
        api_client.create_booking(
            create_booking_payload(
                sailing_id, category_id, owner_user_id, sailing_version, **extra
            ),
            headers,
        )
    )


def add_guests(booking_id, owner_user_id, guests):
    """Add guests (list of (full_name, age)) to a QUOTE booking. Returns list."""
    headers = make_guest_user_headers(owner_user_id)
    created = []
    for full_name, age in guests:
        created.append(
            get_success_data(
                api_client.create_guest(
                    create_guest_payload(booking_id, full_name=full_name, age=age), headers
                )
            )
        )
    return created


def make_and_capture_payment(booking_id, owner_user_id, kind, amount_cents):
    """Create + capture a payment on a booking. Returns the captured payment dict."""
    headers = make_guest_user_headers(owner_user_id)
    payment = get_success_data(
        api_client.create_payment(
            create_payment_payload(booking_id, kind, amount_cents), headers
        )
    )
    return get_success_data(api_client.capture_payment(payment["id"], headers))


def create_quote_booking(owner_user_id, num_guests=2, sailing=None, category=None,
                         num_cabins=2, group_block_id=None, guests=None,
                         **sailing_overrides):
    """Open sailing + category + cabins (if not supplied) + a QUOTE booking with guests.

    Returns (sailing, category, booking). Guests default to num_guests adults.
    """
    if sailing is None or category is None:
        sailing, category, _ = setup_open_sailing(
            num_cabins=num_cabins, **sailing_overrides
        )
    booking = create_booking(
        sailing["id"], category["id"], owner_user_id, sailing["version"],
        group_block_id=group_block_id,
    )
    if guests is None:
        guests = [(f"Guest {i + 1}", 40 - i) for i in range(num_guests)]
    add_guests(booking["id"], owner_user_id, guests)
    return sailing, category, booking


def get_booking(booking_id, headers=None):
    """Fetch the current booking dict."""
    return get_success_data(api_client.get_booking(booking_id, headers or RM))


def create_deposit_held_booking(owner_user_id, num_guests=2, deposit_cents=None,
                                sailing=None, category=None, num_cabins=2,
                                group_block_id=None, guests=None, **sailing_overrides):
    """Build a booking through QUOTE -> DEPOSIT_HELD.

    The deposit captured equals the booking's deposit_due_cents unless an
    explicit deposit_cents is supplied. Returns (sailing, category, booking)
    where booking reflects the DEPOSIT_HELD state.
    """
    sailing, category, booking = create_quote_booking(
        owner_user_id, num_guests=num_guests, sailing=sailing, category=category,
        num_cabins=num_cabins, group_block_id=group_block_id, guests=guests,
        **sailing_overrides
    )
    current = get_booking(booking["id"])
    deposit = deposit_cents if deposit_cents is not None else current["deposit_due_cents"]
    make_and_capture_payment(booking["id"], owner_user_id, "DEPOSIT", deposit)
    held = get_success_data(
        api_client.hold_deposit(booking["id"], make_guest_user_headers(owner_user_id))
    )
    return sailing, category, held


def create_confirmed_booking(owner_user_id, num_guests=2, sailing=None, category=None,
                             num_cabins=2, group_block_id=None, guests=None,
                             **sailing_overrides):
    """Build a booking through QUOTE -> DEPOSIT_HELD -> CONFIRMED (paid in full).

    The deposit and final payments together cover booking_total_cents. Returns
    (sailing, category, booking) where booking reflects CONFIRMED state.
    """
    sailing, category, held = create_deposit_held_booking(
        owner_user_id, num_guests=num_guests, sailing=sailing, category=category,
        num_cabins=num_cabins, group_block_id=group_block_id, guests=guests,
        **sailing_overrides
    )
    current = get_booking(held["id"])
    final_due = current["booking_total_cents"] - current["amount_paid_cents"]
    if final_due > 0:
        make_and_capture_payment(held["id"], owner_user_id, "FINAL", final_due)
    confirmed = get_success_data(
        api_client.confirm_booking(held["id"], make_guest_user_headers(owner_user_id))
    )
    return sailing, category, confirmed


def create_embarked_booking(owner_user_id, num_guests=2, sailing=None, category=None,
                            num_cabins=2, depart_clock="2026-09-01T18:00:00Z",
                            guests=None, **sailing_overrides):
    """Build a booking through to EMBARKED via the depart cascade.

    Advances the clock to depart_clock, departs the sailing as PortAgent, which
    cascades the CONFIRMED booking to EMBARKED and opens its folio. Returns
    (sailing, category, booking).
    """
    sailing, category, confirmed = create_confirmed_booking(
        owner_user_id, num_guests=num_guests, sailing=sailing, category=category,
        num_cabins=num_cabins, guests=guests, **sailing_overrides
    )
    set_clock(depart_clock)
    get_success_data(api_client.depart_sailing(sailing["id"], PA))
    return sailing, category, get_booking(confirmed["id"])


def get_folio_for_booking(booking_id, headers=None):
    """Return the booking's folio dict (or None), via GET /folios?booking_id=."""
    resp = api_client.list_folios(headers or PA, params={"booking_id": booking_id})
    data = get_success_data(resp)
    if isinstance(data, list):
        return data[0] if data else None
    return data
