"""Validation corners: group size, age, operating hours, pagination, gift-card
usability, list envelopes, and immediate consistency.

Corner coverage over the validations, endpoints, and consistency_model sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_bookable_venue,
    setup_confirmed_booking,
    create_venue,
    create_room,
    create_time_slot,
    create_customer,
    create_gift_card,
    grab_slot,
    confirm_booking,
    add_participant,
    mark_present,
    create_booking_payload,
    make_customer_headers,
    make_game_master_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["venue_manager_headers"]
OFFPEAK_SLOT_1 = "2026-07-01T09:00:00Z"
OFFPEAK_SLOT_2 = "2026-07-01T12:00:00Z"


def test_group_size_above_max_rejected_on_create(api):
    """PRD §3.3: "The intended `group_size` must lie between the room's `min_group_size`
    and `max_group_size` inclusive; a value outside that band is `ERR_GROUP_SIZE_INVALID`."

    A room with max_group_size=4 and a booking-create group_size=5 yields
    ERR_GROUP_SIZE_INVALID (409).

    Design: Corner/validations/group_size_above_max_rejected_on_create
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    payload = create_booking_payload(slot["id"], customer["id"], 5, slot["version"])
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_GROUP_SIZE_INVALID")


def test_under_age_participant_rejected_at_check_in(api):
    """PRD §3.7: "every checked-in participant must have `age` at least the room's
    `min_age`; an under-age guest is `ERR_AGE_REQUIREMENT_NOT_MET`."

    Room min_age=18; a present participant of age 10 makes check-in fail with
    ERR_AGE_REQUIREMENT_NOT_MET (409).

    Design: Corner/validations/under_age_participant_checkin_rejected
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=1,
        num_game_masters=1,
        num_participants=0,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False, "min_age": 18},
    )
    # Note: participant added after confirm (still allowed in CONFIRMED) so the under-age
    # guest never triggers the sign-waiver age gate (waiver not required here).
    booking, gm, customer = ctx["booking"], ctx["game_masters"][0], ctx["customer"]
    participant = add_participant(booking, customer, display_name="Kid", age=10)
    mark_present(participant, gm)

    res = api.check_in_booking(
        booking["id"], {"expected_booking_version": booking["version"]},
        make_game_master_headers(gm["id"]))
    validate_error(res, "ERR_AGE_REQUIREMENT_NOT_MET")


def test_slot_outside_operating_hours_rejected(api):
    """PRD §3.2: "A slot may only be created if its game window fits inside the venue's
    operating window: with the slot's minute-of-day evaluated on UTC, the game window
    must fall between `open_minute_of_day` and `close_minute_of_day`, and a slot that
    falls outside that window is rejected with `ERR_OUTSIDE_OPERATING_HOURS`."

    Venue closes at 1080 (18:00 UTC); a slot starting 17:30 with game=60 ends 18:30,
    past close -> ERR_OUTSIDE_OPERATING_HOURS (409).

    Design: Corner/validations/slot_outside_operating_hours_rejected
    """
    venue = create_venue(open_minute_of_day=540, close_minute_of_day=1080)
    room = create_room(venue["id"], name="R", min_group_size=1, max_group_size=4,
                       base_price_cents=2000, game_minutes=60, reset_buffer_minutes=0)
    res = api.create_time_slot({"room_id": room["id"], "start_utc": "2026-07-01T17:30:00Z"}, MANAGER)
    validate_error(res, "ERR_OUTSIDE_OPERATING_HOURS")


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "A `limit` outside the range of 1 to 100, or a negative `offset`, is
    rejected with `ERR_VALIDATION_PAGINATION`."

    Listing rooms with limit=500 (> max 100) yields ERR_VALIDATION_PAGINATION (422).

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    create_venue()  # ensure DB is non-trivially initialized; listing itself is the probe
    res = api.list_rooms(MANAGER, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_PAGINATION")


def test_depleted_gift_card_unusable_on_confirm(api):
    """PRD §3.5: "when a gift card is supplied — that the gift card's `status` is
    `ACTIVE`, that its `venue_id` matches the booking's `venue_id`, and that its
    `balance_cents` is greater than 0 (any of these failing yields
    `ERR_GIFT_CARD_UNUSABLE`)."

    A first confirm spends the card down to a 0 balance (DEPLETED); applying that same
    depleted card at a second confirm yields ERR_GIFT_CARD_UNUSABLE (409).

    Design: Corner/validations/gift_card_zero_balance_unusable_on_confirm
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    room = env["room"]
    slot1 = create_time_slot(room["id"], OFFPEAK_SLOT_1)
    slot2 = create_time_slot(room["id"], OFFPEAK_SLOT_2)
    customer = create_customer()
    # A 4000 card fully spent by a group-2 booking (quote 4000) -> DEPLETED.
    gc = create_gift_card(env["venue"]["id"], initial_balance_cents=4000)

    booking1 = grab_slot(slot1, customer, group_size=2)
    confirm_booking(booking1, customer, gift_card_id=gc["id"])

    booking2 = grab_slot(slot2, customer, group_size=2)
    res = api.confirm_booking(
        booking2["id"], {"gift_card_id": gc["id"], "expected_booking_version": booking2["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_GIFT_CARD_UNUSABLE")


def test_list_rooms_returns_array_envelope_with_pagination_meta(api):
    """PRD §2.3: "List responses always carry the pagination bookkeeping fields `limit`,
    `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope,
    where `total_count` reflects the full size of the filtered set and `has_more`
    indicates whether further pages remain."

    After two rooms are created under a venue, the filtered list returns an array
    envelope with total_count==2 and has_more==false (page fits the limit).

    Design: Corner/endpoints/list_rooms_paginated_envelope
    """
    venue = create_venue()
    create_room(venue["id"], name="R1", min_group_size=1, max_group_size=4,
                base_price_cents=1000, game_minutes=60)
    create_room(venue["id"], name="R2", min_group_size=1, max_group_size=4,
                base_price_cents=1000, game_minutes=60)
    data, meta = validate_paginated(api.list_rooms(MANAGER, params={"venue_id": venue["id"],
                                                                    "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_slot_status_immediately_held_after_grab(api):
    """PRD §3.3: "This single action advances the slot from `OPEN` to `HELD` and creates a
    new booking in `lifecycle_status` of `DRAFT`."
    PRD §3.3: "The slot's `booking_id` is set to the new booking, its
    `assigned_game_master_id` is set to the selected master."

    Immediately after the grab, a GET on the slot already reflects status==HELD with the
    booking_id and assigned master set (immediate consistency).

    Design: Corner/consistency_model/immediate_visibility_of_slot_status_after_grab
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    gm = env["game_masters"][0]
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer = create_customer()
    booking = grab_slot(slot, customer, group_size=2)

    fetched = validate_success(api.get_time_slot(slot["id"], make_customer_headers(customer["id"])), 200)
    assert fetched["status"] == "HELD"
    assert fetched["booking_id"] == booking["id"]
    assert fetched["assigned_game_master_id"] == gm["id"]
