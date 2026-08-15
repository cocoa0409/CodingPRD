"""Booking lifecycle: the modify loop, deck-foot conservation across
confirm/cancel, refund-credit conservation across operator-cancel/rebook,
the sailing-posture gate on confirm, immediate counter consistency, party
spec validation, and ownership enforcement.

Reference rates: standard passenger 1000, vehicle standard base 2000,
overlength 100/ft; fuel surcharge 100 per component when pinned from index
350, 0 when pinned from index 200.
"""
from test_helpers import (
    ApiErrorId,
    assert_booking,
    begin_boarding,
    cancel_sailing,
    close_sailing,
    confirm_booking,
    create_booking,
    create_booking_payload,
    create_customer,
    get_booking,
    get_customer,
    get_sailing,
    make_customer_headers,
    setup_open_sailing,
    setup_sailing_with_confirmed_booking,
    setup_two_open_sailings,
    validate_error,
    validate_success,
)


def test_modify_moves_booking_to_modified_and_requotes(api):
    """PRD §3.5: "A customer may modify a `CONFIRMED` booking while the
    sailing is `OPEN_FOR_BOOKING`, changing `passenger_count`, `has_vehicle`,
    or `vehicle_length_feet`; the booking moves to `MODIFIED`, its fields are
    replaced by the modification payload, and `quoted_fare_cents` is
    recomputed against the pinned schedule."

    Design: Difficulty/non_linear_state_machine/booking_modify_loop
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=1, has_vehicle=True, vehicle_length_feet=18,
        fuel_price_index_cents=350,
    )
    booking = setup["booking"]
    customer = setup["customer"]
    assert booking["status"] == "CONFIRMED"
    assert booking["final_fare_cents"] == 3200  # 1*1000 + 2000 + 100*2

    modified = validate_success(
        api.modify_booking(
            booking["id"],
            {"passenger_count": 2, "has_vehicle": True, "vehicle_length_feet": 18},
            make_customer_headers(customer["id"]),
        )
    )
    assert_booking(modified)
    assert modified["status"] == "MODIFIED", (
        f"modify must move CONFIRMED -> MODIFIED, got {modified['status']}"
    )
    # re-quoted: 2*1000 + 2000 + 100*2 = 4200
    assert modified["quoted_fare_cents"] == 4200, (
        f"modify must re-quote against the pinned schedule: expected 4200, got "
        f"{modified['quoted_fare_cents']}"
    )


def test_modify_confirm_loop_closes_back_to_confirmed(api):
    """PRD §3.5: "The booking then confirms back through the ordinary
    confirmation path, closing `MODIFIED → CONFIRMED`."
    PRD §3.5: "If the pinned schedule is still `EFFECTIVE`, `final_fare_cents`
    settles equal to `quoted_fare_cents`"

    Design: Difficulty/non_linear_state_machine/booking_modify_loop
    """
    setup = setup_sailing_with_confirmed_booking(
        passenger_count=1, has_vehicle=True, vehicle_length_feet=18,
        fuel_price_index_cents=350,
    )
    booking = setup["booking"]
    customer = setup["customer"]
    headers = make_customer_headers(customer["id"])

    validate_success(
        api.modify_booking(
            booking["id"],
            {"passenger_count": 2, "has_vehicle": True, "vehicle_length_feet": 18},
            headers,
        )
    )
    confirmed = validate_success(api.confirm_booking(booking["id"], headers))
    assert confirmed["status"] == "CONFIRMED", "modify loop must close MODIFIED -> CONFIRMED"
    assert confirmed["final_fare_cents"] == 4200, (
        f"final fare must settle equal to the re-quoted 4200, got "
        f"{confirmed['final_fare_cents']}"
    )

    # The loop is repeatable while the sailing stays OPEN_FOR_BOOKING.
    remodified = validate_success(
        api.modify_booking(
            booking["id"],
            {"passenger_count": 1, "has_vehicle": True, "vehicle_length_feet": 18},
            headers,
        )
    )
    assert remodified["status"] == "MODIFIED"
    assert remodified["quoted_fare_cents"] == 3200
    reconfirmed = validate_success(api.confirm_booking(booking["id"], headers))
    assert reconfirmed["status"] == "CONFIRMED"
    assert reconfirmed["final_fare_cents"] == 3200


def test_confirm_then_cancel_conserves_deck_feet(api):
    """PRD §2.7: "the sailing's `reserved_vehicle_feet` counter sums vehicle
    lengths across bookings in `RESERVED`, `CONFIRMED`, `MODIFIED`,
    `CHECKED_IN`, and `BOARDED` status"
    PRD §3.5: "Cancelling a `CONFIRMED` booking is permitted only while the
    sailing is `OPEN_FOR_BOOKING`; it credits the customer's
    `refund_credit_cents` by the booking's `final_fare_cents` and recomputes
    the sailing's `reserved_vehicle_feet` and `booked_passengers`."

    Design: Difficulty/compensating_invariant/deck_feet_conserved_across_confirm_and_cancel
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    assert get_sailing(sailing_id)["reserved_vehicle_feet"] == 0

    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        sailing_id, customer, passenger_count=1, has_vehicle=True, vehicle_length_feet=18
    )
    confirm_booking(booking["id"], customer)
    mid = get_sailing(sailing_id)["reserved_vehicle_feet"]
    assert mid == 18, f"confirmed 18-ft booking must hold 18 feet, got {mid}"

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    end = get_sailing(sailing_id)["reserved_vehicle_feet"]
    assert end == 0, (
        f"forward (+18) and compensating (-18) actions must conserve deck "
        f"feet: expected 0 after cancel, got {end}"
    )
    assert mid - end == 18


def test_reserved_booking_holds_deck_feet_from_quote_time(api):
    """PRD §3.5: "Because reservations hold deck space from quote time, a
    successful create immediately joins the `RESERVED` population counted by
    both counters."
    PRD §3.5: "Cancelling a `RESERVED` booking settles nothing and refunds
    nothing — the reservation simply releases its held space and the sailing's
    aggregates are recomputed."

    Design: Difficulty/compensating_invariant/deck_feet_conserved_across_confirm_and_cancel
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")

    booking = create_booking(
        sailing_id, customer, passenger_count=1, has_vehicle=True, vehicle_length_feet=18
    )
    assert booking["status"] == "RESERVED"
    held = get_sailing(sailing_id)["reserved_vehicle_feet"]
    assert held == 18, (
        f"an unconfirmed reservation must hold its 18 feet from quote time, got {held}"
    )

    cancelled = validate_success(
        api.cancel_booking(booking["id"], make_customer_headers(customer["id"]))
    )
    assert cancelled["status"] == "CANCELLED"
    assert get_sailing(sailing_id)["reserved_vehicle_feet"] == 0
    assert get_customer(customer["id"])["refund_credit_cents"] == 0, (
        "a RESERVED cancellation settles nothing and refunds nothing"
    )


def test_operator_cancel_then_rebook_conserves_refund_credit(
    api, scheduler_admin_headers
):
    """PRD §3.8: "A successful rebook creates a fresh booking on the target
    sailing directly in `CONFIRMED` status with the same `passenger_count` and
    vehicle specifications as the original; the new booking's
    `final_fare_cents` carries over from the cancelled booking exactly — no
    additional charge if the new sailing is dearer, no refund of the
    difference if cheaper. The customer's credit is consumed:
    `refund_credit_cents` decreases by the carried fare. The old booking then
    moves `CANCELLED → REBOOKED`, its `rebooked_to_booking_id` pointing at the
    successor."

    Design: Difficulty/compensating_invariant/refund_credit_conserved_across_operator_cancel_and_rebook
    """
    setup = setup_two_open_sailings(fuel_price_index_cents=350)
    s1, s2 = setup["sailing"], setup["sailing2"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        s1["id"], customer, passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )
    booking = confirm_booking(booking["id"], customer)
    assert booking["final_fare_cents"] == 4200  # 2*1000 + 2000 + 100*2

    cancel_sailing(s1["id"], "WEATHER")
    credit_mid = get_customer(customer["id"])["refund_credit_cents"]
    assert credit_mid == 4200, (
        f"operator cancel must credit the settled 4200, got {credit_mid}"
    )

    headers = make_customer_headers(customer["id"])
    validate_success(api.rebook_booking(booking["id"], {"target_sailing_id": s2["id"]}, headers))

    old = get_booking(booking["id"])
    assert old["status"] == "REBOOKED", f"old booking must move to REBOOKED, got {old['status']}"
    successor_id = old["rebooked_to_booking_id"]
    assert successor_id, "old booking must point at its successor"

    successor = get_booking(successor_id)
    assert_booking(successor)
    assert successor["sailing_id"] == s2["id"]
    assert successor["status"] == "CONFIRMED"
    assert successor["passenger_count"] == 2
    assert successor["has_vehicle"] is True
    assert successor["vehicle_length_feet"] == 18
    assert successor["final_fare_cents"] == 4200, (
        f"successor fare must carry over exactly: expected 4200, got "
        f"{successor['final_fare_cents']}"
    )

    credit_end = get_customer(customer["id"])["refund_credit_cents"]
    assert credit_end == 0, (
        f"credit must be conserved across cancel (+4200) and rebook (-4200): "
        f"expected 0, got {credit_end}"
    )


def test_voluntarily_cancelled_booking_cannot_be_rebooked(api):
    """PRD §3.8: "Rebooking a booking that the customer cancelled voluntarily
    is not permitted — the operator-cancellation precondition fails, and the
    request is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/refund_credit_conserved_across_operator_cancel_and_rebook
    """
    setup = setup_two_open_sailings(fuel_price_index_cents=350)
    s1, s2 = setup["sailing"], setup["sailing2"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        s1["id"], customer, passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )
    confirm_booking(booking["id"], customer)

    headers = make_customer_headers(customer["id"])
    cancelled = validate_success(api.cancel_booking(booking["id"], headers))
    assert cancelled["status"] == "CANCELLED"  # voluntary: sailing still open

    resp = api.rebook_booking(booking["id"], {"target_sailing_id": s2["id"]}, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_rejected_once_sailing_boarding(api):
    """PRD §3.5: "A customer confirming their own booking — from `RESERVED →
    CONFIRMED`, and identically from `MODIFIED → CONFIRMED` to close the
    modify loop — requires the sailing to be in `OPEN_FOR_BOOKING` or
    `BOOKING_CLOSED` and re-checks capacity."
    PRD §3.7: "Requests made against a sailing in the wrong posture fail with
    `ERR_SAILING_NOT_BOOKABLE`; a booking in the wrong status fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_when_sailing_boarding
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(sailing_id, customer, passenger_count=1)

    close_sailing(sailing_id)
    begin_boarding(sailing_id)  # sailing now BOARDING

    resp = api.confirm_booking(booking["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_SAILING_NOT_BOOKABLE)

    after = get_booking(booking["id"])
    assert after["status"] == "RESERVED", (
        f"rejected confirm must leave the booking RESERVED, got {after['status']}"
    )


def test_confirm_allowed_while_booking_closed(api):
    """PRD §3.5: "A customer confirming their own booking — from `RESERVED →
    CONFIRMED`, and identically from `MODIFIED → CONFIRMED` to close the
    modify loop — requires the sailing to be in `OPEN_FOR_BOOKING` or
    `BOOKING_CLOSED` and re-checks capacity."
    PRD §3.5: "If the pinned schedule is still `EFFECTIVE`, `final_fare_cents`
    settles equal to `quoted_fare_cents`"

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_blocked_when_sailing_boarding
    """
    setup = setup_open_sailing(fuel_price_index_cents=350)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(sailing_id, customer, passenger_count=1)
    assert booking["quoted_fare_cents"] == 1100  # 1*1000 + 100*1

    close_sailing(sailing_id)  # BOOKING_CLOSED: confirm still legal

    confirmed = validate_success(
        api.confirm_booking(booking["id"], make_customer_headers(customer["id"]))
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["final_fare_cents"] == 1100, (
        "pinned schedule still EFFECTIVE: final fare settles equal to the quote"
    )


def test_confirm_updates_sailing_counters_immediately(api, scheduler_admin_headers):
    """PRD §1: "First, consistency is immediate: when a sailing is cancelled,
    the booking cancellations, refund credits, standby expirations, and crew
    releases that follow are applied as one visible cascade, not reconciled
    later."
    PRD §3.5: "Confirmation recomputes the sailing's counters and increments
    the booking's `version`."

    Design: Corner/cross_cutting_layers/immediate_consistency_after_booking_confirm
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    booking = create_booking(
        sailing_id, customer, passenger_count=2, has_vehicle=True, vehicle_length_feet=18
    )

    confirm_booking(booking["id"], customer)

    sailing = get_sailing(sailing_id)
    assert sailing["booked_passengers"] == 2, (
        f"booked_passengers must read 2 immediately after confirm, got "
        f"{sailing['booked_passengers']}"
    )
    assert sailing["reserved_vehicle_feet"] == 18, (
        f"reserved_vehicle_feet must read 18 immediately after confirm, got "
        f"{sailing['reserved_vehicle_feet']}"
    )


def test_booking_party_spec_validation(api):
    """PRD §3.5: "Party specifications are validated: a vehicle's length must
    be at least 1 and at most 80 feet when a vehicle is present, and malformed
    combinations (length missing when required, length supplied out of range)
    are rejected with `ERR_INVALID_PARTY_SPEC`."

    Design: Corner/validations/invalid_party_spec_missing_vehicle_length
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    customer = create_customer(full_name="Std Pat", fare_class="STANDARD")
    headers = make_customer_headers(customer["id"])

    missing_length = create_booking_payload(
        customer_id=customer["id"], passenger_count=1, has_vehicle=True
    )
    resp = api.create_booking(sailing_id, missing_length, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_PARTY_SPEC)

    zero_length = create_booking_payload(
        customer_id=customer["id"], passenger_count=1, has_vehicle=True,
        vehicle_length_feet=0,
    )
    resp = api.create_booking(sailing_id, zero_length, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_PARTY_SPEC)


def test_customer_cannot_confirm_others_booking(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer` record; ownership checks on any resource that
    references a customer — a booking's `customer_id`, a standby entry's
    `customer_id` — compare that foreign-key field to `X-User-ID`, and a
    mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/customer_cannot_act_on_others_booking
    """
    setup = setup_open_sailing(fuel_price_index_cents=200)
    sailing_id = setup["sailing"]["id"]
    owner = create_customer(full_name="A Pat", fare_class="STANDARD")
    other = create_customer(full_name="B Pat", fare_class="STANDARD")
    booking = create_booking(sailing_id, owner, passenger_count=1)

    resp = api.confirm_booking(booking["id"], make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    after = get_booking(booking["id"])
    assert after["status"] == "RESERVED", (
        f"rejected confirm must leave the booking RESERVED, got {after['status']}"
    )
