"""Optimistic concurrency (stale-version on checkout and gift-card redeem),
version increment semantics, the state-before-fiscal validation precedence, and
remaining validation guards (pagination bounds, retired-item booking, loyalty)."""
from test_helpers import (
    validate_success, validate_error, assert_version_incremented,
    TEST_USERS,
    create_appointment_payload, checkout_payload, redeem_gift_card_payload,
    make_station, make_menu_item, make_technician, make_client, make_gift_card,
    book_appointment, confirm, drive_to_in_service, inject_client_state, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Corner: optimistic concurrency control (OCC) stale-version
# ---------------------------------------------------------------------------
def test_occ_checkout_stale_version_rejected(api):
    """PRD §2.9: "A checkout request must carry `expected_appointment_version`. The
    server compares it to the target appointment's current `version`. If an add-on
    attach, a deposit payment, or a re-confirmation has advanced the appointment's
    `version` since the client last read it, the snapshotted subtotal the client is
    about to charge against is stale, and the checkout is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_checkout_stale_version_rejected
    """
    set_clock("2026-07-22T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="WALK_IN")
    stale_version = started["version"] - 1

    res = api.checkout_appointment(
        started["id"], checkout_payload(stale_version), FRONT_DESK
    )
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_appointment(started["id"], FRONT_DESK))
    assert after["booking_status"] == "IN_SERVICE"


def test_occ_giftcard_redeem_stale_version_rejected(api):
    """PRD §2.9: "The request must carry `expected_gift_card_version`. The server
    compares it to the target gift card's current `version`; if a prior redemption
    or a checkout draw has lowered the balance and advanced the card's `version`
    since the client last read it, the redemption is rejected with
    `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_giftcard_redeem_stale_version_rejected
    """
    gc = make_gift_card(initial_balance_cents=5000)
    first = validate_success(api.redeem_gift_card(
        gc["id"], redeem_gift_card_payload(1000, gc["version"]), FRONT_DESK
    ))
    stale_version = first["version"] - 1

    res = api.redeem_gift_card(
        gc["id"], redeem_gift_card_payload(500, stale_version), FRONT_DESK
    )
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert after["balance_cents"] == 4000   # unchanged by the rejected redeem


def test_version_increments_on_each_mutation(api):
    """PRD §2.4: "The `version` is an integer that starts at its initial value and
    increments by one on every mutation of the resource; it underpins optimistic
    concurrency control (Section 2.9)."
    PRD §3.7: "increments the appointment's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    set_clock("2026-07-23T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="WALK_IN")
    confirmed = validate_success(api.confirm_appointment(appt["id"], FRONT_DESK))
    assert_version_incremented(confirmed["version"], appt["version"])


# ---------------------------------------------------------------------------
# Difficulty: state precedes fiscal at checkout
# ---------------------------------------------------------------------------
def test_state_check_precedes_loyalty_check_on_checkout(api):
    """PRD §2.11: "an attempted state transition that is not defined from the
    resource's current state yields `ERR_INVALID_STATE`. Only after these
    foundational checks pass does the system evaluate the domain-specific business
    rules (item-retirement, sterilization, licensing, scheduling overlaps, grace
    timing, deposit, loyalty, gift-card, and OCC checks)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_checkout
    """
    set_clock("2026-03-28T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()   # 0 loyalty points
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-28T13:00:00Z")
    confirmed = validate_success(api.confirm_appointment(appt["id"], FRONT_DESK))
    # Checkout from CONFIRMED (not IN_SERVICE) while also over-redeeming loyalty.
    res = api.checkout_appointment(
        appt["id"], checkout_payload(confirmed["version"], loyalty_points_redeemed=50),
        FRONT_DESK,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_invalid_state_checkout_leaves_appointment_confirmed(api):
    """PRD §2.11: "an attempted state transition that is not defined from the
    resource's current state yields `ERR_INVALID_STATE`. Only after these
    foundational checks pass does the system evaluate the domain-specific business
    rules (item-retirement, sterilization, licensing, scheduling overlaps, grace
    timing, deposit, loyalty, gift-card, and OCC checks)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_checkout
    """
    set_clock("2026-03-28T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-03-28T13:00:00Z")
    confirmed = validate_success(api.confirm_appointment(appt["id"], FRONT_DESK))
    api.checkout_appointment(
        appt["id"], checkout_payload(confirmed["version"], loyalty_points_redeemed=50),
        FRONT_DESK,
    )
    after = validate_success(api.get_appointment(appt["id"], FRONT_DESK))
    assert after["booking_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Corner: remaining validation guards
# ---------------------------------------------------------------------------
def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100." And: "A `limit`
    outside the 1-to-100 range or a negative `offset` is rejected with
    `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/pagination_limit_over_max_rejected
    """
    res = api.list_appointments(FRONT_DESK, params={"limit": 101})
    validate_error(res, "ERR_INVALID_PAGINATION")


def test_book_retired_menu_item_rejected(api):
    """PRD §3.5: "The booked `service_item_id` must reference a menu item whose
    `is_active` is true; booking a retired service is rejected with
    `ERR_ITEM_RETIRED`."

    Design: Corner/validations/book_retired_menu_item_rejected
    """
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    validate_success(api.retire_menu_item(menu["id"], MANAGER))
    tech = make_technician(station["id"])
    client = make_client()
    payload = create_appointment_payload(client["id"], tech["id"], station["id"],
                                         menu["id"], origin="WALK_IN")
    res = api.create_appointment(payload, FRONT_DESK)
    validate_error(res, "ERR_ITEM_RETIRED")


def test_error_insufficient_loyalty_triggerable(api):
    """PRD §3.10: "the `loyalty_points_redeemed` must not exceed the client's
    `loyalty_points_balance`, or the checkout is rejected with
    `ERR_INSUFFICIENT_LOYALTY`".

    Design: Corner/errors/error_insufficient_loyalty_triggerable
    """
    set_clock("2026-07-19T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=3000, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], loyalty_points_balance=10)
    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="WALK_IN")
    res = api.checkout_appointment(
        started["id"], checkout_payload(started["version"], loyalty_points_redeemed=50),
        FRONT_DESK,
    )
    validate_error(res, "ERR_INSUFFICIENT_LOYALTY")
