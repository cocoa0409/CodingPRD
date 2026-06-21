"""RBAC, optimistic concurrency, and a full-group settle cascade.

Corner coverage over the rbac, cross_cutting_complexity_layers sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_bookable_venue,
    setup_confirmed_booking,
    create_venue,
    create_room,
    create_time_slot,
    create_customer,
    create_gift_card,
    grab_slot,
    confirm_booking,
    cancel_booking,
    add_participant,
    mark_present,
    check_in,
    complete,
    get_slot,
    create_room_payload,
    create_booking_payload,
    make_customer_headers,
    make_game_master_headers,
    build_user_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["venue_manager_headers"]
OFFPEAK_SLOT_1 = "2026-07-01T09:00:00Z"
OFFPEAK_SLOT_2 = "2026-07-01T12:00:00Z"


# ─── rbac ─────────────────────────────────────────────
def test_customer_cannot_create_room(api):
    """PRD §2.1: "When a request is well-formed and authenticated but the declared role
    is not permitted to perform the operation under the access-control matrix in Section
    4, the request is rejected with `ERR_FORBIDDEN`."
    PRD §3.1: "Within a venue, a `VenueManager` configures the rooms."

    Room creation is VenueManager-only; a Customer calling POST /rooms gets
    ERR_FORBIDDEN (403).

    Design: Corner/rbac/customer_cannot_create_room
    """
    venue = create_venue()
    customer = create_customer()
    payload = create_room_payload(venue["id"], name="R", min_group_size=1, max_group_size=4,
                                  base_price_cents=1000, game_minutes=60)
    res = api.create_room(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory HTTP
    headers."
    PRD §2.1: "If either header is missing, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    A write call with no X-User-ID / X-User-Role headers yields ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.create_venue(
        {"name": "V", "timezone": "UTC", "open_minute_of_day": 0, "close_minute_of_day": 1440},
        {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_customer_cannot_confirm_other_customers_booking(api):
    """PRD §2.1: "a `Customer` acting on a booking must be the booking's owner —
    `X-User-ID` must equal the booking's `customer_id`, and a mismatch is an
    `ERR_FORBIDDEN`."

    Customer B confirming Customer A's DRAFT booking (X-User-ID != booking.customer_id)
    yields ERR_FORBIDDEN (403).

    Design: Corner/rbac/customer_cannot_act_on_other_customers_booking
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    customer_a = create_customer()
    customer_b = create_customer()
    booking = grab_slot(slot, customer_a, group_size=2)

    res = api.confirm_booking(
        booking["id"], {"expected_booking_version": booking["version"]},
        make_customer_headers(customer_b["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ─── cross_cutting: OCC ───────────────────────────────
def test_slot_grab_with_stale_version_rejected(api):
    """PRD §2.5: "If another writer has advanced that slot's `version` since the client
    read it — for example, by legitimately grabbing the same open slot under the booking
    flow — the create is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412)."
    PRD §3.3: "if `expected_time_slot_version` does not match the slot's current
    `version`, it fails with `ERR_STALE_SLOT_VERSION`."

    A slot grabbed then released (cancel) has its version advanced past the originally
    observed value; re-grabbing with the stale original version yields
    ERR_STALE_SLOT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_slot_grab_stale_version_conflict
    """
    env = setup_bookable_venue(
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot = create_time_slot(env["room"]["id"], OFFPEAK_SLOT_1)
    stale_version = slot["version"]
    customer = create_customer()

    booking1 = grab_slot(slot, customer, group_size=2)  # advances slot version
    cancel_booking(booking1, customer)                  # advances slot version again, OPEN

    payload = create_booking_payload(slot["id"], customer["id"], 2, stale_version)
    res = api.create_booking(payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_STALE_SLOT_VERSION")


def test_reschedule_with_stale_slot_version_rejected(api):
    """PRD §2.5: "The reschedule operation applies the same pattern to the slot swap: it
    requires an `expected_time_slot_version` matching the current (old) slot's `version`,
    and if that slot's `version` has advanced since the client observed it, the reschedule
    is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412)."
    PRD §3.6: "The old slot's `version` must match `expected_time_slot_version`, or the
    reschedule is rejected with `ERR_STALE_SLOT_VERSION`."

    Rescheduling while carrying a current-slot version one behind the live value yields
    ERR_STALE_SLOT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_reschedule_stale_slot_version_conflict
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer = ctx["booking"], ctx["customer"]
    slot1 = get_slot(ctx["slot"]["id"])
    slot2 = create_time_slot(ctx["room"]["id"], OFFPEAK_SLOT_2)

    stale_slot_version = slot1["version"] - 1
    payload = {
        "new_time_slot_id": slot2["id"],
        "expected_time_slot_version": stale_slot_version,
        "expected_booking_version": booking["version"],
    }
    res = api.reschedule_booking(booking["id"], payload, make_customer_headers(customer["id"]))
    validate_error(res, "ERR_STALE_SLOT_VERSION")


def test_gift_card_topup_with_stale_version_rejected(api):
    """PRD §2.5: "The other versioned mutations operate on non-slot resources and carry a
    generic stale-version error, `ERR_STALE_VERSION` (HTTP 412), when the submitted
    version is out of date."
    PRD §2.5: "topping up and voiding a gift card each require
    `expected_gift_card_version`."

    A gift-card top-up carrying a version one behind the live value (after a prior top-up
    bumped it) yields ERR_STALE_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_non_slot_stale_version_on_giftcard_topup
    """
    venue = create_venue()
    gc = create_gift_card(venue["id"], initial_balance_cents=5000)
    topped = validate_success(api.top_up_gift_card(
        gc["id"], {"amount_cents": 1000, "expected_gift_card_version": gc["version"]}, MANAGER), 200)

    stale_version = topped["version"] - 1
    res = api.top_up_gift_card(
        gc["id"], {"amount_cents": 1000, "expected_gift_card_version": stale_version}, MANAGER)
    validate_error(res, "ERR_STALE_VERSION")


# ─── cross_cutting: cascade complete full group ───────
def test_complete_full_group_settles_and_captures(api):
    """PRD §3.7: "When every booked participant checked in, the settled count equals
    `group_size` and `final_charge_cents` equals `quoted_charge_cents`."
    PRD §3.7: "Completion captures the card portion of the settled charge —
    `final_charge_cents` minus `gift_card_applied_cents` — moving `payment_status` from
    `AUTHORIZED` to `CAPTURED`, and increments the booking's `version`."

    A full-group complete (both of 2 present, off-peak group-2 quote 4000) settles
    final_charge_cents == 4000, captures payment, and reaches COMPLETED.

    Design: Corner/cross_cutting_complexity_layers/cascade_complete_settles_and_captures_full_group
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT_1,
        group_size=2,
        num_game_masters=1,
        num_participants=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, gm, participants = ctx["booking"], ctx["game_masters"][0], ctx["participants"]
    assert booking["quoted_charge_cents"] == 4000

    for p in participants:
        mark_present(p, gm)
    checked = check_in(booking, gm)
    completed = complete(checked, gm)

    assert completed["quoted_charge_cents"] == 4000
    assert completed["final_charge_cents"] == 4000
    assert completed["payment_status"] == "CAPTURED"
    assert completed["lifecycle_status"] == "COMPLETED"
