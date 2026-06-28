"""Reservation charge calculation and the parallel booking/settlement axes.

Translates difficulty-design instances on the Reservation domain: the
provisional-vs-final deposit charge divergence and the independent evolution of
the booking and settlement state axes.
"""
from test_helpers import (
    validate_success,
    setup_studio,
    set_clock,
    book_reservation,
    check_in,
    complete,
    create_and_activate_membership,
    TEST_USERS,
)

FRONT = TEST_USERS["front_desk_headers"]


def test_deposit_charge_provisional_quote_differs_from_final(api):
    """PRD 3.6: "for a `DEPOSIT` visit the final charge is the service's
    `list_price_cents` minus the already-held `deposit_held_cents`, floored at 0
    so it never goes negative, reflecting the deposit being applied against the
    service price; and for a `WALK_IN` visit the final charge is simply the
    service's `list_price_cents`."
    PRD 3.6: "a `DEPOSIT` hold quoted the location's `deposit_required_cents`
    (the deposit amount, not the net service price)".

    A DEPOSIT booking on a 4500-cent service at a location with deposit 1000:
    the booking holds deposit_held_cents=1000, and completion bills
    4500-1000=3500.

    Design: Difficulty/dual_variant_calc/reservation_charge_deposit_provisional_vs_final_diverge
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Downtown", "deposit_required_cents": 1000},
        service_overrides={"name": "Brazilian", "duration_minutes": 30,
                           "list_price_cents": 4500, "intro_eligible": True},
    )
    res = book_reservation(
        member=studio["member"],
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc="2026-06-20T10:00:00Z",
        payment_method="DEPOSIT",
        expected_room_version=studio["room"]["version"],
    )
    # Provisional: the held deposit, not the net service price.
    assert res["deposit_held_cents"] == 1000, \
        f"Expected deposit_held_cents 1000, got {res['deposit_held_cents']}"

    # PRD 3.6: check-in is permitted only once the clock has reached at least
    # 30 minutes before start_utc (start is 10:00Z).
    set_clock("2026-06-20T09:45:00Z")
    check_in(res["id"])
    resp = api.complete_reservation(res["id"], FRONT)
    data = validate_success(resp, 200)
    # Final charge: list_price - deposit applied = 4500 - 1000.
    assert data["deposit_held_cents"] == 1000
    assert data["charged_amount_cents"] == 3500, \
        f"Expected final charge 3500, got {data['charged_amount_cents']}"
    assert data["settlement_status"] == "PAID"
    assert data["booking_status"] == "COMPLETED"


def test_walk_in_final_charge_is_list_price(api):
    """PRD 3.6: "for a `WALK_IN` visit the final charge is simply the service's
    `list_price_cents`."

    A WALK_IN visit on a 4500-cent service finalizes charged_amount_cents=4500
    (the WALK_IN branch quotes and bills the list price, unlike DEPOSIT which
    nets the deposit out).

    Design: Difficulty/dual_variant_calc/reservation_charge_deposit_provisional_vs_final_diverge
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        service_overrides={"name": "Brazilian", "duration_minutes": 30,
                           "list_price_cents": 4500},
    )
    res = book_reservation(
        member=studio["member"],
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc="2026-06-20T10:00:00Z",
        payment_method="WALK_IN",
        expected_room_version=studio["room"]["version"],
    )
    # PRD 3.6: check-in is permitted only once the clock has reached at least
    # 30 minutes before start_utc (start is 10:00Z).
    set_clock("2026-06-20T09:45:00Z")
    check_in(res["id"])
    data = validate_success(api.complete_reservation(res["id"], FRONT), 200)
    assert data["charged_amount_cents"] == 4500, \
        f"Expected final charge 4500, got {data['charged_amount_cents']}"
    assert data["settlement_status"] == "PAID"


def test_credit_booking_axes_independent_at_checkin(api):
    """PRD 3.6: "The two axes move on their own schedules: a booking can be
    `BOOKED` while its money sits in `CREDIT_HELD`, and completing the visit
    advances both."
    PRD 3.6: "Check-in is performed by a `FrontDesk` operator and moves a
    reservation from `BOOKED` to `CHECKED_IN`."

    At check-in the booking axis advances to CHECKED_IN while the settlement
    axis stays CREDIT_HELD; only completion drives settlement to PAID.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_settlement_axes
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        service_overrides={"name": "Bikini", "duration_minutes": 30,
                           "list_price_cents": 3000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(
        member=member,
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc="2026-06-16T10:00:00Z",
        payment_method="CREDIT",
        expected_room_version=studio["room"]["version"],
        membership_id=mbr["id"],
        expected_membership_version=mbr["version"],
    )
    assert res["settlement_status"] == "CREDIT_HELD"
    set_clock("2026-06-16T09:45:00Z")
    data = validate_success(api.check_in_reservation(res["id"], FRONT), 200)
    assert data["booking_status"] == "CHECKED_IN"
    assert data["settlement_status"] == "CREDIT_HELD", \
        "settlement axis must stay CREDIT_HELD at check-in (independent axes)"
    assert data["credits_held"] == 1


def test_credit_booking_settlement_advances_to_paid_only_at_completion(api):
    """PRD 3.6: "completing the visit advances both."
    PRD 3.6: "Completion ... moves a `CHECKED_IN` reservation to `COMPLETED`
    while the settlement axis advances to `PAID`."

    The settlement axis stays CREDIT_HELD through check-in and only reaches PAID
    when the visit completes — confirming the two axes evolve on independent
    schedules.

    Design: Difficulty/non_linear_state_machine/reservation_parallel_booking_and_settlement_axes
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        service_overrides={"name": "Bikini", "duration_minutes": 30,
                           "list_price_cents": 3000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(
        member=member,
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc="2026-06-16T10:00:00Z",
        payment_method="CREDIT",
        expected_room_version=studio["room"]["version"],
        membership_id=mbr["id"],
        expected_membership_version=mbr["version"],
    )
    set_clock("2026-06-16T09:45:00Z")
    checked = validate_success(api.check_in_reservation(res["id"], FRONT), 200)
    assert checked["settlement_status"] == "CREDIT_HELD"
    completed = validate_success(api.complete_reservation(res["id"], FRONT), 200)
    assert completed["booking_status"] == "COMPLETED"
    assert completed["settlement_status"] == "PAID"

