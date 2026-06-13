"""Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the runner restarts the server before
each test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion mismatches.

Identity threading: any ownership-gated call uses make_customer_headers(cust["id"])
or make_game_master_headers(gm["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_venue_payload,
    create_room_payload,
    create_pricing_rule_payload,
    create_game_master_payload,
    create_time_slot_payload,
    create_customer_payload,
    create_booking_payload,
    create_participant_payload,
    create_gift_card_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_game_master_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["venue_manager_headers"]


# ─── Atomic creators ──────────────────────────────────
def create_venue(**overrides) -> dict:
    """PlatformAdmin creates a venue. Defaults to open-all-day (0..1440)."""
    return get_success_data(api_client.create_venue(create_venue_payload(**overrides), ADMIN))


def create_room(venue_id: str, **overrides) -> dict:
    """VenueManager creates a room under a venue."""
    return get_success_data(
        api_client.create_room(create_room_payload(venue_id, **overrides), MANAGER)
    )


def create_pricing_rule(venue_id: str, room_id: str, **overrides) -> dict:
    """VenueManager creates a pricing rule for a room."""
    return get_success_data(
        api_client.create_pricing_rule(
            create_pricing_rule_payload(venue_id, room_id, **overrides), MANAGER
        )
    )


def create_game_master(venue_id: str, **overrides) -> dict:
    """VenueManager registers a game master under a venue (starts AVAILABLE)."""
    return get_success_data(
        api_client.create_game_master(create_game_master_payload(venue_id, **overrides), MANAGER)
    )


def create_time_slot(room_id: str, start_utc: str, **overrides) -> dict:
    """VenueManager publishes an OPEN time slot for a room."""
    return get_success_data(
        api_client.create_time_slot(create_time_slot_payload(room_id, start_utc, **overrides), MANAGER)
    )


def create_customer(**overrides) -> dict:
    """Register a customer (starts no_show_strike_count=0)."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_gift_card(venue_id: str, initial_balance_cents: int = 5000, **overrides) -> dict:
    """VenueManager issues a gift card under a venue (starts ACTIVE)."""
    return get_success_data(
        api_client.create_gift_card(
            create_gift_card_payload(venue_id, initial_balance_cents, **overrides), MANAGER
        )
    )


def grab_slot(slot: dict, customer: dict, group_size: int = 2, **overrides) -> dict:
    """Customer grabs an OPEN slot -> creates a DRAFT booking (slot -> HELD).

    `slot` must be the freshly-read slot dict (uses its current version).
    """
    payload = create_booking_payload(
        time_slot_id=slot["id"],
        customer_id=customer["id"],
        group_size=group_size,
        expected_time_slot_version=slot["version"],
        **overrides,
    )
    return get_success_data(
        api_client.create_booking(payload, make_customer_headers(customer["id"]))
    )


def add_participant(booking: dict, customer: dict, display_name="P", age=30) -> dict:
    """Customer adds a participant to a DRAFT/CONFIRMED booking."""
    return get_success_data(
        api_client.add_participant(
            booking["id"], create_participant_payload(display_name, age),
            make_customer_headers(customer["id"]),
        )
    )


def confirm_booking(booking: dict, customer: dict, gift_card_id=None) -> dict:
    """Customer confirms a DRAFT booking. Optional gift_card_id redeemed at confirm."""
    payload = {"expected_booking_version": booking["version"]}
    if gift_card_id is not None:
        payload["gift_card_id"] = gift_card_id
    return get_success_data(
        api_client.confirm_booking(booking["id"], payload, make_customer_headers(customer["id"]))
    )


def cancel_booking(booking: dict, customer: dict) -> dict:
    """Customer cancels a DRAFT/CONFIRMED booking."""
    return get_success_data(
        api_client.cancel_booking(
            booking["id"], {"expected_booking_version": booking["version"]},
            make_customer_headers(customer["id"]),
        )
    )


def mark_present(participant: dict, game_master: dict) -> dict:
    """GameMaster marks a participant present (checked_in=true)."""
    return get_success_data(
        api_client.mark_present(
            participant["id"], {"expected_participant_version": participant["version"]},
            make_game_master_headers(game_master["id"]),
        )
    )


def sign_waiver(participant: dict, customer: dict) -> dict:
    """Customer signs a participant's waiver."""
    return get_success_data(
        api_client.sign_waiver(
            participant["id"], {"expected_participant_version": participant["version"]},
            make_customer_headers(customer["id"]),
        )
    )


def check_in(booking: dict, game_master: dict) -> dict:
    """GameMaster checks in the present group (CONFIRMED -> CHECKED_IN)."""
    return get_success_data(
        api_client.check_in_booking(
            booking["id"], {"expected_booking_version": booking["version"]},
            make_game_master_headers(game_master["id"]),
        )
    )


def complete(booking: dict, game_master: dict) -> dict:
    """GameMaster completes a CHECKED_IN booking (settles + captures)."""
    return get_success_data(
        api_client.complete_booking(
            booking["id"], {"expected_booking_version": booking["version"]},
            make_game_master_headers(game_master["id"]),
        )
    )


def no_show(booking: dict, game_master: dict) -> dict:
    """GameMaster marks a CONFIRMED booking NO_SHOW."""
    return get_success_data(
        api_client.no_show_booking(
            booking["id"], {"expected_booking_version": booking["version"]},
            make_game_master_headers(game_master["id"]),
        )
    )


def get_slot(slot_id: str) -> dict:
    return get_success_data(api_client.get_time_slot(slot_id, MANAGER))


def get_booking(booking_id: str, customer: dict) -> dict:
    return get_success_data(api_client.get_booking(booking_id, make_customer_headers(customer["id"])))


def get_game_master(gm_id: str) -> dict:
    return get_success_data(api_client.get_game_master(gm_id, MANAGER))


def get_gift_card(gc_id: str) -> dict:
    return get_success_data(api_client.get_gift_card(gc_id, MANAGER))


def get_customer(customer_id: str) -> dict:
    return get_success_data(api_client.get_customer(customer_id, MANAGER))


# ─── Tier 2: Bookable-venue scaffolding ───────────────
# The canonical venue used across the difficulty suite: open all day, one room
# (base 2000, game 60, buffer 30, group 1..8), one or more game masters.
def setup_bookable_venue(
    *,
    venue_overrides=None,
    room_overrides=None,
    num_game_masters=1,
    pricing_overrides=None,
):
    """Build a venue + one room + N game masters (+ optional pricing rule).

    Returns dict: {venue, room, game_masters, pricing_rule}.
    Off-peak by default (no pricing rule unless pricing_overrides given).
    """
    venue = create_venue(**(venue_overrides or {}))
    room = create_room(venue["id"], **(room_overrides or {}))
    pricing_rule = None
    if pricing_overrides is not None:
        pricing_rule = create_pricing_rule(venue["id"], room["id"], **pricing_overrides)
    game_masters = [create_game_master(venue["id"], full_name=f"GM {i}") for i in range(num_game_masters)]
    return {
        "venue": venue,
        "room": room,
        "game_masters": game_masters,
        "pricing_rule": pricing_rule,
    }


# ─── Tier 3: Booking lifecycle shortcuts ──────────────
def setup_draft_booking(
    *,
    start_utc="2026-07-01T09:00:00Z",
    group_size=2,
    is_private=False,
    venue_overrides=None,
    room_overrides=None,
    pricing_overrides=None,
    num_game_masters=1,
):
    """Build a bookable venue + one slot + a customer + a DRAFT booking (slot HELD).

    Returns dict: {venue, room, game_masters, slot, customer, booking, pricing_rule}.
    """
    env = setup_bookable_venue(
        venue_overrides=venue_overrides,
        room_overrides=room_overrides,
        num_game_masters=num_game_masters,
        pricing_overrides=pricing_overrides,
    )
    slot = create_time_slot(env["room"]["id"], start_utc)
    customer = create_customer()
    booking = grab_slot(slot, customer, group_size=group_size, is_private=is_private)
    return {**env, "slot": slot, "customer": customer, "booking": booking}


def setup_confirmed_booking(
    *,
    start_utc="2026-07-01T09:00:00Z",
    group_size=2,
    is_private=False,
    gift_card_id=None,
    venue_overrides=None,
    room_overrides=None,
    pricing_overrides=None,
    num_game_masters=1,
    num_participants=0,
):
    """Build through to a CONFIRMED booking.

    Optionally adds `num_participants` PENDING participants (age 30) before confirm.
    Returns dict: {venue, room, game_masters, slot, customer, booking, participants, pricing_rule}.
    The returned `booking` reflects the post-confirm state (CONFIRMED, version bumped).
    """
    ctx = setup_draft_booking(
        start_utc=start_utc,
        group_size=group_size,
        is_private=is_private,
        venue_overrides=venue_overrides,
        room_overrides=room_overrides,
        pricing_overrides=pricing_overrides,
        num_game_masters=num_game_masters,
    )
    participants = [
        add_participant(ctx["booking"], ctx["customer"], display_name=f"P{i+1}", age=30)
        for i in range(num_participants)
    ]
    confirmed = confirm_booking(ctx["booking"], ctx["customer"], gift_card_id=gift_card_id)
    return {**ctx, "booking": confirmed, "participants": participants}
