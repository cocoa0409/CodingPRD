"""Meal tickets: component-wise rounding, the posture ladder and the verified-order gate."""
from test_helpers import (
    DINING_MANAGER,
    ApiErrorId,
    approve_diet_order,
    create_diet_order,
    create_reservation,
    issue_ticket,
    log_temperature,
    read_diet_order,
    read_resident,
    read_seat_availability,
    read_venue,
    setup_dining_program,
    validate_error,
    validate_success,
    venue_version,
)


def _fairhaven_sponsoring_resident():
    """A bistro and an ACTIVE resident who can sponsor guest and takeout meals."""
    return setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Fairhaven",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Fairhaven Bistro",
        venue_kind="BISTRO",
        seat_capacity=12,
        resident_name="Cal Vega",
        baseline_weight_kg=70.0,
        with_approved_order=False,
    )


def test_sponsored_takeout_dinner_rounds_each_component_before_summing(api):
    """The worked case: 1450 base, a discount of 181, packaging of 175 and tax of 105 give 1549,
    not the 1548 that carrying unrounded components through would produce.

    PRD: "Take a sponsored `TAKEOUT` `DINNER`: the base is 1450, twelve-and-a-half percent of that
    is 181.25 which rounds half up to 181, and adding 175 packaging gives a subtotal of 1444; 7.25
    percent of 1444 is 104.69 which rounds half up to 105; the `billed_amount_cents` is 1549."

    Design: Difficulty/combinatorial_formula/ticket_amount_round_per_component_then_sum
    """
    program = _fairhaven_sponsoring_resident()

    response = api.create_meal_ticket(
        {
            "venue_id": program["venue"]["id"],
            "ticket_type": "TAKEOUT",
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "resident_id": program["resident"]["id"],
        },
        DINING_MANAGER,
    )
    ticket = validate_success(response, 201)

    assert ticket["billed_amount_cents"] == 1549
    assert ticket["billed_amount_cents"] != 1548
    assert ticket["status"] == "ISSUED"


def test_sponsored_guest_lunch_takes_the_discount_and_tax_but_no_packaging(api):
    """A sponsored `GUEST` `LUNCH` prices to 1173, and the two sponsored tickets together move the
    resident's sponsorship balance to 2722.

    PRD: "A packaging fee of 175 cents applies to `TAKEOUT` tickets and to nothing else."

    Design: Difficulty/combinatorial_formula/ticket_amount_round_per_component_then_sum
    """
    program = _fairhaven_sponsoring_resident()
    takeout = issue_ticket(
        program["venue"]["id"],
        "TAKEOUT",
        "2026-08-10",
        "DINNER",
        resident_id=program["resident"]["id"],
    )

    guest = issue_ticket(
        program["venue"]["id"],
        "GUEST",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )

    assert guest["billed_amount_cents"] == 1173
    assert guest["status"] == "ISSUED"
    assert takeout["status"] == "ISSUED"
    assert (
        read_resident(program["resident"]["id"])["guest_meal_charge_balance_cents"]
        == 2722
    )


def _harborview_satellite():
    """A satellite kitchen serving memory care, with one verified resident."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Harborview",
        care_levels=["MEMORY_CARE"],
        venue_name="Harborview Memory Care Satellite",
        venue_kind="SATELLITE",
        seat_capacity=6,
        resident_name="Priya Deshmukh",
        care_level="MEMORY_CARE",
        baseline_weight_kg=58.0,
    )
    assert program["venue"]["temp_compliance_posture"] == "COMPLIANT"
    return program


def test_two_out_of_range_readings_put_the_venue_on_watch_and_close_guest_business(api):
    """Each out-of-range hot-holding reading stamps the running counter into
    `violation_sequence_index`; at two the posture is `WATCH`, which refuses a `GUEST` ticket while
    still allowing the `RESIDENT` transfer at 650.

    PRD: "Crossing into `WATCH` closes the venue to guest and takeout business — those issuance
    attempts now report `ERR_VENUE_POSTURE_RESTRICTED` — while `RESIDENT` tickets continue to be
    issued and served."

    Design: Difficulty/cross_entity_state_dependency/ticket_depends_on_venue_temperature_posture
    """
    program = _harborview_satellite()

    first = log_temperature(program["venue"]["id"], "HOT_HOLDING", 120.0)
    second = log_temperature(program["venue"]["id"], "HOT_HOLDING", 120.0)
    assert first["in_range"] is False
    assert first["violation_sequence_index"] == 1
    assert second["violation_sequence_index"] == 2

    venue = read_venue(program["venue"]["id"])
    assert venue["temp_compliance_posture"] == "WATCH"
    assert venue["consecutive_temp_violation_count"] == 2

    guest_response = api.create_meal_ticket(
        {
            "venue_id": program["venue"]["id"],
            "ticket_type": "GUEST",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": program["resident"]["id"],
        },
        DINING_MANAGER,
    )
    validate_error(guest_response, ApiErrorId.ERR_VENUE_POSTURE_RESTRICTED, 409)

    resident_ticket = issue_ticket(
        program["venue"]["id"],
        "RESIDENT",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )
    assert resident_ticket["billed_amount_cents"] == 650


def test_the_third_reading_suspends_the_venue_and_stops_resident_tickets_too(api):
    """At a count of three the posture is `SUSPENDED` and even a `RESIDENT` ticket is refused with
    the suspension error rather than the watch-only restriction; no guest charge was ever booked.

    PRD: "From the counter the venue's `temp_compliance_posture` is derived: `SUSPENDED` when the
    count is 3 or more, `WATCH` when the count is 2, and `COMPLIANT` when the count is 1 or 0."

    Design: Difficulty/cross_entity_state_dependency/ticket_depends_on_venue_temperature_posture
    """
    program = _harborview_satellite()
    log_temperature(program["venue"]["id"], "HOT_HOLDING", 120.0)
    log_temperature(program["venue"]["id"], "HOT_HOLDING", 120.0)
    issue_ticket(
        program["venue"]["id"],
        "RESIDENT",
        "2026-08-10",
        "LUNCH",
        resident_id=program["resident"]["id"],
    )

    third = log_temperature(program["venue"]["id"], "HOT_HOLDING", 120.0)
    assert third["violation_sequence_index"] == 3

    venue = read_venue(program["venue"]["id"])
    assert venue["temp_compliance_posture"] == "SUSPENDED"
    assert venue["consecutive_temp_violation_count"] == 3

    response = api.create_meal_ticket(
        {
            "venue_id": program["venue"]["id"],
            "ticket_type": "RESIDENT",
            "service_date": "2026-08-10",
            "meal_period": "DINNER",
            "resident_id": program["resident"]["id"],
        },
        DINING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_VENUE_SERVICE_SUSPENDED, 409)

    assert (
        read_resident(program["resident"]["id"])["guest_meal_charge_balance_cents"] == 0
    )


def _pinecrest_unreviewed_order():
    """A resident whose only diet order is still waiting on the dietitian."""
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Pinecrest",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Pinecrest Main Dining",
        seat_capacity=8,
        resident_name="Omar Sandoval",
        baseline_weight_kg=73.0,
        with_approved_order=False,
    )
    program["order"] = create_diet_order(
        program["resident"]["id"], texture_level="BITE_SIZED", liquid_consistency="THIN"
    )
    program["venue_version"] = venue_version(program["venue"]["id"])
    return program


def test_booking_is_refused_while_the_diet_order_awaits_the_dietitian(api):
    """The reservation payload never names the diet order, yet the booking is refused because that
    order is still `PENDING_REVIEW` / `AWAITING_DIETITIAN`.

    PRD: "The resident must have a diet order that is at once `ACTIVE` on the clinical axis and
    `APPROVED` on the review axis, or the booking is refused with `ERR_DIET_ORDER_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_depends_on_diet_order_review_state
    """
    program = _pinecrest_unreviewed_order()
    assert program["order"]["clinical_status"] == "PENDING_REVIEW"
    assert program["order"]["review_status"] == "AWAITING_DIETITIAN"

    response = api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-11",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-11T12:00:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DIET_ORDER_NOT_VERIFIED, 409)


def test_the_identical_booking_is_accepted_once_the_order_is_approved(api):
    """Approval alone flips the outcome: the same payload now books, and the meal period reports
    one committed seat against seven open.

    PRD: "An `APPROVE` decision from `AWAITING_DIETITIAN` moves `review_status` to `APPROVED` and,
    on the other axis, moves `clinical_status` from `PENDING_REVIEW` to `ACTIVE` with
    `activated_at` stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/reservation_depends_on_diet_order_review_state
    """
    program = _pinecrest_unreviewed_order()
    api.create_reservation(
        {
            "resident_id": program["resident"]["id"],
            "venue_id": program["venue"]["id"],
            "service_date": "2026-08-11",
            "meal_period": "LUNCH",
            "seat_start_utc": "2026-08-11T12:00:00Z",
            "party_size": 1,
            "expected_venue_version": program["venue_version"],
        },
        DINING_MANAGER,
    )

    approve_diet_order(program["order"]["id"])
    order = read_diet_order(program["order"]["id"])
    assert order["clinical_status"] == "ACTIVE"
    assert order["review_status"] == "APPROVED"

    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=1,
    )
    assert reservation["status"] == "RESERVED"

    availability = read_seat_availability(program["venue"]["id"], "2026-08-11", "LUNCH")
    assert availability["committed_seats"] == 1
    assert availability["open_seats"] == 7
