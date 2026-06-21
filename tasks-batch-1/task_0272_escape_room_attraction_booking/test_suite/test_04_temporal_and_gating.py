"""Temporal overlap geometry, cross-entity gating, validation priority, empty pool.

Covers same-room (buffer-inclusive) overlap vs game-master (buffer-excluded) overlap,
the customer-strike and retired-room cross-entity gates, the state-vs-fiscal and
waiver-vs-groupsize priority conflicts, and the empty game-master pool fallback.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_bookable_venue,
    setup_confirmed_booking,
    setup_draft_booking,
    create_room,
    create_time_slot,
    create_customer,
    create_gift_card,
    grab_slot,
    confirm_booking,
    cancel_booking,
    no_show,
    mark_present,
    get_slot,
    get_customer,
    create_booking_payload,
    make_customer_headers,
    make_game_master_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["venue_manager_headers"]

OFFPEAK_SLOT_1 = "2026-07-01T09:00:00Z"
OFFPEAK_SLOT_2 = "2026-07-01T12:00:00Z"


# ─── resource_temporal_overlap: same-room buffer ──────
def test_same_room_buffer_overlap_rejected(api):
    """PRD §3.2: "a slot cannot be grabbed if any other slot of the *same room* that is
    currently `HELD` or `BOOKED` has a `[start_utc, block_end_utc)` interval that
    overlaps the target's `[start_utc, block_end_utc)` interval; a clash here is
    `ERR_SLOT_OVERLAP`."

    Slot A 14:00 (game 60 + buffer 30 -> block window [14:00,15:30)) is BOOKED. Slot B
    starts 15:15 (< 15:30) so its interval overlaps A's buffer-inclusive block window;
    grabbing B is rejected with ERR_SLOT_OVERLAP. Two GMs ensure staff is never the
    blocker.

    Design: Difficulty/resource_temporal_overlap/same_room_buffer_overlap_rejected
    """
    env = setup_bookable_venue(
        num_game_masters=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "game_minutes": 60, "reset_buffer_minutes": 30, "waiver_required": False},
    )
    room = env["room"]
    slot_a = create_time_slot(room["id"], "2026-07-01T14:00:00Z")
    slot_b = create_time_slot(room["id"], "2026-07-01T15:15:00Z")
    customer = create_customer()

    booking_a = grab_slot(slot_a, customer, group_size=2)
    confirm_booking(booking_a, customer)  # slot A -> BOOKED

    payload = create_booking_payload(slot_b["id"], customer["id"], 2, slot_b["version"])
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_SLOT_OVERLAP")


def test_same_room_non_overlapping_after_buffer_succeeds(api):
    """PRD §3.2: "a slot cannot be grabbed if any other slot of the *same room* that is
    currently `HELD` or `BOOKED` has a `[start_utc, block_end_utc)` interval that
    overlaps the target's `[start_utc, block_end_utc)` interval."
    PRD §2.4: "The interval that the slot occupies the *room* is the half-open span from
    `start_utc` up to but not including `block_end_utc`."

    The complement of the buffer overlap: slot B starting exactly at 15:30 (== slot A's
    block_end, the half-open boundary) does NOT overlap A's [14:00,15:30) window, so the
    grab succeeds.

    Design: Difficulty/resource_temporal_overlap/same_room_buffer_overlap_rejected
    """
    env = setup_bookable_venue(
        num_game_masters=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "game_minutes": 60, "reset_buffer_minutes": 30, "waiver_required": False},
    )
    room = env["room"]
    slot_a = create_time_slot(room["id"], "2026-07-01T14:00:00Z")
    slot_b = create_time_slot(room["id"], "2026-07-01T15:30:00Z")
    customer = create_customer()

    booking_a = grab_slot(slot_a, customer, group_size=2)
    confirm_booking(booking_a, customer)

    payload = create_booking_payload(slot_b["id"], customer["id"], 2, slot_b["version"])
    booking_b = validate_success(api.create_booking(payload, make_customer_headers(customer["id"])), 201)
    assert booking_b["lifecycle_status"] == "DRAFT"


# ─── resource_temporal_overlap: game-master window ────
def test_gamemaster_game_window_overlap_excludes_buffer(api):
    """PRD §3.2: "a master is only eligible if it has no `HELD` or `BOOKED` slot of *any*
    room whose game window `[start_utc, game_end_utc)` overlaps the target slot's game
    window `[start_utc, game_end_utc)`."
    PRD §3.3: "the room-overlap check passes (otherwise `ERR_SLOT_OVERLAP`), and an
    eligible game master exists (otherwise `ERR_NO_GAMEMASTER_AVAILABLE`)."

    Staff occupation is the GAME window only (buffer excluded) and crosses rooms. One GM
    busy on Room1 [14:00,15:00); a Room2 grab at 14:30 overlaps that game window, and
    with no other GM the candidate set is empty -> ERR_NO_GAMEMASTER_AVAILABLE.

    Design: Difficulty/resource_temporal_overlap/gamemaster_window_overlap_excludes_buffer
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"name": "Room1", "base_price_cents": 2000, "min_group_size": 1,
                        "max_group_size": 8, "game_minutes": 60, "reset_buffer_minutes": 30,
                        "waiver_required": False},
    )
    room1 = env["room"]
    room2 = create_room(env["venue"]["id"], name="Room2", base_price_cents=2000,
                        min_group_size=1, max_group_size=8, game_minutes=60,
                        reset_buffer_minutes=30, waiver_required=False)
    slot1 = create_time_slot(room1["id"], "2026-07-01T14:00:00Z")
    slot2 = create_time_slot(room2["id"], "2026-07-01T14:30:00Z")
    customer = create_customer()

    booking1 = grab_slot(slot1, customer, group_size=2)
    confirm_booking(booking1, customer)  # GM busy on Room1 game window

    payload = create_booking_payload(slot2["id"], customer["id"], 2, slot2["version"])
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_NO_GAMEMASTER_AVAILABLE")


def test_gamemaster_free_after_game_window_within_buffer(api):
    """PRD §3.2: "a master is only eligible if it has no `HELD` or `BOOKED` slot of *any*
    room whose game window `[start_utc, game_end_utc)` overlaps the target slot's game
    window `[start_utc, game_end_utc)`."
    PRD §3.2: "a room needs its full reset buffer free of other games, but a game master
    only needs the active play windows to not collide."

    The buffer-excluded complement: a Room2 grab at 15:00 (== Room1 game_end, the
    half-open boundary, still inside Room1's buffer) does NOT collide with the GM's
    game window [14:00,15:00), so the single GM is eligible and the grab succeeds.

    Design: Difficulty/resource_temporal_overlap/gamemaster_window_overlap_excludes_buffer
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"name": "Room1", "base_price_cents": 2000, "min_group_size": 1,
                        "max_group_size": 8, "game_minutes": 60, "reset_buffer_minutes": 30,
                        "waiver_required": False},
    )
    room1 = env["room"]
    room2 = create_room(env["venue"]["id"], name="Room2", base_price_cents=2000,
                        min_group_size=1, max_group_size=8, game_minutes=60,
                        reset_buffer_minutes=30, waiver_required=False)
    slot1 = create_time_slot(room1["id"], "2026-07-01T14:00:00Z")
    slot2 = create_time_slot(room2["id"], "2026-07-01T15:00:00Z")
    customer = create_customer()

    booking1 = grab_slot(slot1, customer, group_size=2)
    confirm_booking(booking1, customer)

    payload = create_booking_payload(slot2["id"], customer["id"], 2, slot2["version"])
    booking2 = validate_success(api.create_booking(payload, make_customer_headers(customer["id"])), 201)
    assert booking2["lifecycle_status"] == "DRAFT"


# ─── boundary_precision_check: empty GM pool ──────────
def test_empty_gamemaster_pool_rejects_slot_grab(api):
    """PRD §3.2: "If the candidate set is empty, the operation is rejected with
    `ERR_NO_GAMEMASTER_AVAILABLE`."
    PRD §3.2: "only an `AVAILABLE` master is eligible to be assigned to a slot."

    Empty-set boundary on candidate-pool cardinality: the venue's only game master is
    set OFF_DUTY, leaving zero AVAILABLE candidates, so the grab fails with
    ERR_NO_GAMEMASTER_AVAILABLE.

    Design: Difficulty/boundary_precision_check/empty_gamemaster_pool_fallback_on_slot_grab
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    gm = env["game_masters"][0]
    validate_success(api.set_game_master_status(
        gm["id"], {"status": "OFF_DUTY", "expected_game_master_version": gm["version"]}, MANAGER), 200)

    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    payload = create_booking_payload(slot["id"], customer["id"], 2, slot["version"])
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_NO_GAMEMASTER_AVAILABLE")


def test_available_gamemaster_pool_allows_slot_grab(api):
    """PRD §3.2: "only an `AVAILABLE` master is eligible to be assigned to a slot."
    PRD §3.2: "If the candidate set is empty, the operation is rejected with
    `ERR_NO_GAMEMASTER_AVAILABLE`."

    The non-empty complement: with the single game master AVAILABLE the candidate set is
    non-empty, so the grab succeeds and assigns that master.

    Design: Difficulty/boundary_precision_check/empty_gamemaster_pool_fallback_on_slot_grab
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    gm = env["game_masters"][0]
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    booking = grab_slot(slot, customer, group_size=2)
    assert booking["lifecycle_status"] == "DRAFT"
    assert get_slot(slot["id"])["assigned_game_master_id"] == gm["id"]


# ─── cross_entity_state_dependency: strike count ──────
def test_confirm_blocked_when_customer_at_strike_limit(api):
    """PRD §3.5: "that the owning customer's `no_show_strike_count` is strictly less than
    the venue's `no_show_strike_limit` (otherwise `ERR_NO_SHOW_LIMIT_REACHED`)."
    PRD §3.8: "a customer who accumulates strikes equal to or exceeding the venue's
    `no_show_strike_limit` can no longer drive any future booking from `DRAFT` to
    `CONFIRMED` at that venue."

    Booking->Customer gate: strike_limit=1 and one prior NO_SHOW (count=1) means the
    customer is no longer strictly below the limit, so confirming a fresh booking is
    rejected with ERR_NO_SHOW_LIMIT_REACHED.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_strike_count
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        venue_overrides={"no_show_strike_limit": 1},
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    room, gm = env["room"], env["game_masters"][0]
    slot1 = create_time_slot(room["id"], OFFPEAK_SLOT_1)
    slot2 = create_time_slot(room["id"], OFFPEAK_SLOT_2)
    customer = create_customer()

    booking1 = grab_slot(slot1, customer, group_size=2)
    confirmed1 = confirm_booking(booking1, customer)
    no_show(confirmed1, gm)
    assert get_customer(customer["id"])["no_show_strike_count"] == 1

    booking2 = grab_slot(slot2, customer, group_size=2)
    res = api.confirm_booking(
        booking2["id"], {"expected_booking_version": booking2["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_NO_SHOW_LIMIT_REACHED")


def test_confirm_allowed_when_customer_below_strike_limit(api):
    """PRD §3.5: "that the owning customer's `no_show_strike_count` is strictly less than
    the venue's `no_show_strike_limit` (otherwise `ERR_NO_SHOW_LIMIT_REACHED`)."
    PRD §3.3: "A new customer's `no_show_strike_count` starts at 0."

    The boundary just below the gate: a fresh customer (count 0) at a venue with
    strike_limit 1 is strictly below the limit, so a confirm is permitted.

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_customer_strike_count
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        venue_overrides={"no_show_strike_limit": 1},
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    assert get_customer(customer["id"])["no_show_strike_count"] == 0

    booking = grab_slot(slot, customer, group_size=2)
    confirmed = confirm_booking(booking, customer)
    assert confirmed["lifecycle_status"] == "CONFIRMED"


# ─── cross_entity_state_dependency: retired room ──────
def test_slot_grab_blocked_by_retired_room(api):
    """PRD §3.3: "The grab succeeds only if the slot is currently `OPEN`, the slot's room
    `status` is `ACTIVE` (otherwise `ERR_ROOM_RETIRED`)."
    PRD §3.1: "A manager may later retire a room, advancing its `status` from `ACTIVE` to
    `RETIRED` so that it accepts no new slots or bookings."

    TimeSlot->Room gate: with the room RETIRED (slot still OPEN), grabbing the slot is
    rejected with ERR_ROOM_RETIRED.

    Design: Difficulty/cross_entity_state_dependency/slot_grab_blocked_by_retired_room
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    room = env["room"]
    slot = create_time_slot(room["id"], OFFPEAK_SLOT_1)
    validate_success(api.retire_room(room["id"], {"expected_room_version": room["version"]}, MANAGER), 200)

    customer = create_customer()
    payload = create_booking_payload(slot["id"], customer["id"], 2, slot["version"])
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_ROOM_RETIRED")


def test_slot_grab_allowed_on_active_room(api):
    """PRD §3.3: "The grab succeeds only if the slot is currently `OPEN`, the slot's room
    `status` is `ACTIVE` (otherwise `ERR_ROOM_RETIRED`)."
    PRD §3.1: "A newly created room starts with `status` of `ACTIVE`."

    The ACTIVE-room complement: with the room still ACTIVE the same grab succeeds,
    confirming the gate keys on RETIRED status specifically.

    Design: Difficulty/cross_entity_state_dependency/slot_grab_blocked_by_retired_room
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    assert env["room"]["status"] == "ACTIVE"
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    booking = grab_slot(slot, customer, group_size=2)
    assert booking["lifecycle_status"] == "DRAFT"


# ─── priority_pair_validation_conflict ────────────────
def test_state_check_beats_gift_card_fiscal_on_second_confirm(api):
    """PRD §2.9: "Only then does the system check that the target resource is in a valid
    state for the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when it
    is not."
    PRD §3.5: "A confirm attempted on a booking that is not in `DRAFT`, or whose slot is
    not `HELD`, fails with `ERR_INVALID_STATE`."

    State (evaluated before business rules) wins over the gift-card fiscal check: a
    second confirm on an already-CONFIRMED booking, even carrying a VOID gift card,
    returns ERR_INVALID_STATE rather than ERR_GIFT_CARD_UNUSABLE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_giftcard_fiscal_on_confirm
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    venue, booking, customer = ctx["venue"], ctx["booking"], ctx["customer"]
    gc = create_gift_card(venue["id"], initial_balance_cents=5000)
    validate_success(api.void_gift_card(gc["id"], {"expected_gift_card_version": gc["version"]}, MANAGER), 200)

    res = api.confirm_booking(
        booking["id"], {"gift_card_id": gc["id"], "expected_booking_version": booking["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_state_check_beats_gift_card_fiscal_on_cancelled_booking(api):
    """PRD §2.9: "Only then does the system check that the target resource is in a valid
    state for the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when it
    is not."
    PRD §3.5: "A confirm attempted on a booking that is not in `DRAFT`, or whose slot is
    not `HELD`, fails with `ERR_INVALID_STATE`."

    The same state-vs-fiscal priority pair from a different invalid state: confirming a
    CANCELLED booking while supplying a VOID gift card returns ERR_INVALID_STATE — the
    state check pre-empts the gift-card fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_giftcard_fiscal_on_confirm
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    venue, booking, customer = ctx["venue"], ctx["booking"], ctx["customer"]
    cancelled = cancel_booking(booking, customer)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    gc = create_gift_card(venue["id"], initial_balance_cents=5000)
    validate_success(api.void_gift_card(gc["id"], {"expected_gift_card_version": gc["version"]}, MANAGER), 200)

    res = api.confirm_booking(
        cancelled["id"], {"gift_card_id": gc["id"], "expected_booking_version": cancelled["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


# SKIPPED instance: Difficulty/priority_pair_validation_conflict/
#   waiver_safety_beats_groupsize_constraint_on_checkin
# The instance asserts ERR_WAIVER_NOT_SIGNED wins over ERR_GROUP_SIZE_INVALID when both
# fire at check-in (1-of-2 present, present participant's waiver unsigned). PRD §3.7
# lists the check-in gates in the opposite order — "First, the count of checked-in
# participants must be at least the room's `min_group_size`; too few present is
# `ERR_GROUP_SIZE_INVALID`. Second, if the room's `waiver_required` is true, ...
# `ERR_WAIVER_NOT_SIGNED`." — and §2.9 says the domain-specific rules surface "each ...
# in the workflow narrative that defines it" without committing to waiver-before-group.
# A faithful PRD-only implementer could return either error (and the listed order points
# to ERR_GROUP_SIZE_INVALID), so the asserted outcome is not uniquely derivable. Per the
# Core rule (Silence-pattern: validation-priority / error-precedence) this instance is
# skipped rather than weakened.
