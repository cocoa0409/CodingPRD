"""Endpoint behaviour: resubmission, linked references, computed reads and participation gates."""
from test_helpers import (
    BILLING_SPECIALIST,
    CLINICAL_STAFF,
    DIETITIAN,
    DINING_MANAGER,
    ApiErrorId,
    add_verified_resident,
    create_community,
    create_diet_order,
    create_reservation,
    create_resident,
    read_tray_card,
    request_changes_on_diet_order,
    set_clock,
    set_dining_status,
    setup_dining_program,
    setup_published_menu_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
)


def test_resubmission_returns_the_order_to_the_dietitian_without_bumping_the_round(api):
    """Only the `REQUEST_CHANGES` decision moves `review_round`; the resubmit that answers it keeps
    the round at 1, replaces exactly the supplied clinical fields and leaves the original author
    stamped.

    PRD: "It moves `review_status` back to `AWAITING_DIETITIAN` while retaining `review_round`,
    re-applies the texture liberalization gate against the resident's `ACTIVE` order using the
    resubmitted values, and recomputes the community's `pending_dietitian_review_count`, which in
    this case nets out unchanged."

    Design: Corner/endpoints/diet_order_resubmit_returns_to_awaiting_without_bumping_round
    """
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Rita Sandoval", baseline_weight_kg=66.0
    )
    order = create_diet_order(
        resident["id"], texture_level="BITE_SIZED", liquid_consistency="THIN"
    )
    assert order["review_round"] == 0

    changes_requested = request_changes_on_diet_order(
        order["id"], reviewer_note="texture too liberal for observed swallowing"
    )
    assert changes_requested["review_status"] == "CHANGES_REQUESTED"
    assert changes_requested["review_round"] == 1
    assert changes_requested["clinical_status"] == "PENDING_REVIEW"

    resubmitted = validate_success(
        api.resubmit_diet_order(
            order["id"],
            {"texture_level": "MINCED_MOIST", "liquid_consistency": "MILDLY_THICK"},
            CLINICAL_STAFF,
        )
    )

    assert resubmitted["review_status"] == "AWAITING_DIETITIAN"
    assert resubmitted["review_round"] == 1
    assert resubmitted["texture_level"] == "MINCED_MOIST"
    assert resubmitted["liquid_consistency"] == "MILDLY_THICK"
    assert resubmitted["therapeutic_codes"] == []
    assert resubmitted["ordered_by_user_id"] == order["ordered_by_user_id"]

    approved = validate_success(
        api.dietitian_review_diet_order(order["id"], {"decision": "APPROVE"}, DIETITIAN)
    )
    assert approved["review_status"] == "APPROVED"
    assert approved["clinical_status"] == "ACTIVE"
    assert approved["review_round"] == 1
    assert approved["activated_at"].startswith("2026-08-01T00:00:00")


def test_a_ticket_cannot_borrow_another_residents_reservation(api):
    """Both ids resolve, so the refusal is the linked-subject mismatch rather than a 404; the same
    call naming the reservation's own resident stores the association.

    PRD: "When `reservation_id` is supplied, that reservation's own resident and venue must equal the
    payload's `resident_id` and `venue_id`."

    Design: Corner/endpoints/ticket_reservation_link_of_another_resident_rejected
    """
    program = setup_dining_program(
        clock="2026-08-10T12:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Resident A",
        baseline_weight_kg=70.0,
    )
    resident_b = add_verified_resident(
        program["community"], "Resident B", baseline_weight_kg=71.0
    )
    reservation = create_reservation(
        program["resident"]["id"],
        program["venue"]["id"],
        "2026-08-10",
        "LUNCH",
        "2026-08-10T12:30:00Z",
        party_size=1,
    )

    mismatched = api.create_meal_ticket(
        {
            "venue_id": program["venue"]["id"],
            "ticket_type": "RESIDENT",
            "service_date": "2026-08-10",
            "meal_period": "LUNCH",
            "resident_id": resident_b["id"],
            "reservation_id": reservation["id"],
        },
        DINING_MANAGER,
    )
    validate_error(mismatched, ApiErrorId.ERR_LINKED_RESOURCE_MISMATCH, 422)

    ticket = validate_success(
        api.create_meal_ticket(
            {
                "venue_id": program["venue"]["id"],
                "ticket_type": "RESIDENT",
                "service_date": "2026-08-10",
                "meal_period": "LUNCH",
                "resident_id": program["resident"]["id"],
                "reservation_id": reservation["id"],
            },
            DINING_MANAGER,
        ),
        201,
    )

    assert ticket["reservation_id"] == reservation["id"]
    assert ticket["resident_id"] == program["resident"]["id"]
    assert ticket["billed_amount_cents"] == 650
    assert ticket["status"] == "ISSUED"

    _, meta = validate_paginated(
        api.list_meal_tickets(
            BILLING_SPECIALIST, params={"reservation_id": reservation["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_the_tray_card_day_index_is_a_modulo_over_the_whole_cycle(api):
    """On a two-week rotation starting 2026-08-10 the 2026-08-20 service date is cycle day 11, not a
    day-of-week; with no rules the line falls back to the base item, and a meal period with no items
    returns an empty line list rather than an error.

    PRD: "From that cycle the cycle day is derived: take the number of whole days from the cycle's
    `effective_start_date` to the requested `service_date`, reduce it modulo the cycle's `week_count`
    multiplied by seven, and add 1."

    Design: Corner/endpoints/tray_card_computed_read_returns_day_index_and_lines
    """
    set_clock("2026-08-19T08:00:00Z")
    community = create_community("Brookdale Aldergate", ["ASSISTED_LIVING"])
    resident = create_resident(
        community["id"], full_name="Sylvia Tran", baseline_weight_kg=63.0
    )
    program = setup_published_menu_cycle(
        community["id"],
        cycle_number=1,
        week_count=2,
        effective_start_date="2026-08-10",
        effective_end_date="2026-08-23",
        items=[
            {
                "item_code": "REG-BRISKET",
                "name": "Braised Brisket",
                "day_index": 11,
                "meal_period": "DINNER",
                "base_texture": "REGULAR",
            }
        ],
    )

    dinner = read_tray_card(resident["id"], "2026-08-20", "DINNER")

    assert dinner["day_index"] == 11
    assert dinner["menu_cycle_id"] == program["cycle"]["id"]
    assert len(dinner["lines"]) == 1
    assert dinner["lines"][0]["served_item_code"] == "REG-BRISKET"
    assert dinner["lines"][0]["reason"] == "NONE"
    assert dinner["lines"][0]["substitution_rule_id"] is None
    assert dinner["tray_status"] == "CLEAR"
    assert dinner["blocked_item_codes"] == []

    lunch = read_tray_card(resident["id"], "2026-08-20", "LUNCH")

    assert lunch["day_index"] == 11
    assert lunch["lines"] == []
    assert lunch["tray_status"] == "CLEAR"
    assert lunch["blocked_item_codes"] == []


def test_an_on_leave_resident_cannot_be_booked_until_they_are_active_again(api):
    """Participation alone decides: the identical payload is refused while the resident is
    `ON_LEAVE` and accepted the moment they are `ACTIVE`, the refused attempt having bumped no venue
    version.

    PRD: "`ON_LEAVE` and `DISCHARGED` residents cannot be reserved, cannot have a `RESIDENT` ticket
    issued, cannot cast a committee ballot and cannot sponsor a guest or takeout meal — all of which
    report `ERR_RESIDENT_NOT_ACTIVE`."

    Design: Corner/endpoints/on_leave_resident_cannot_be_reserved
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Main Dining",
        seat_capacity=6,
        resident_name="Tobias Grenfell",
        baseline_weight_kg=79.0,
    )
    on_leave = set_dining_status(program["resident"]["id"], "ON_LEAVE")
    assert on_leave["dining_status"] == "ON_LEAVE"
    pinned_version = venue_version(program["venue"]["id"])

    payload = {
        "resident_id": program["resident"]["id"],
        "venue_id": program["venue"]["id"],
        "service_date": "2026-08-11",
        "meal_period": "LUNCH",
        "seat_start_utc": "2026-08-11T12:00:00Z",
        "party_size": 1,
        "expected_venue_version": pinned_version,
    }
    refused = api.create_reservation(payload, DINING_MANAGER)
    validate_error(refused, ApiErrorId.ERR_RESIDENT_NOT_ACTIVE, 409)

    back = set_dining_status(program["resident"]["id"], "ACTIVE")
    assert back["dining_status"] == "ACTIVE"

    reservation = validate_success(api.create_reservation(payload, DINING_MANAGER), 201)
    assert reservation["status"] == "RESERVED"


def test_the_period_rollup_may_exceed_capacity_across_two_disjoint_turns(api):
    """Two seatings that do not intersect each pass the interval gate at a capacity of 2, yet the
    whole-period roll-up reports 4 committed seats with `open_seats` floored at 0.

    PRD: "This roll-up spans the whole meal period rather than an interval, so when two disjoint
    seating turns are booked inside one meal period it can legitimately report more committed seats
    than the venue's capacity."

    Design: Corner/endpoints/seat_availability_rollup_can_exceed_capacity_across_two_turns
    """
    program = setup_dining_program(
        clock="2026-08-10T09:00:00Z",
        community_name="Brookdale Aldergate",
        care_levels=["ASSISTED_LIVING"],
        venue_name="Aldergate Bistro",
        venue_kind="BISTRO",
        seat_capacity=2,
        resident_name="Resident A",
        baseline_weight_kg=70.0,
    )
    venue_id = program["venue"]["id"]
    assert program["venue"]["seating_turn_minutes"] == 60
    assert program["venue"]["turnover_buffer_minutes"] == 20
    resident_b = add_verified_resident(
        program["community"], "Resident B", baseline_weight_kg=71.0
    )

    first = create_reservation(
        program["resident"]["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T12:00:00Z",
        party_size=2,
    )
    assert first["seat_end_utc"].startswith("2026-08-11T13:00:00")

    second = create_reservation(
        resident_b["id"],
        venue_id,
        "2026-08-11",
        "LUNCH",
        "2026-08-11T13:30:00Z",
        party_size=2,
    )
    assert second["status"] == "RESERVED"

    availability = validate_success(
        api.get_seat_availability(venue_id, "2026-08-11", "LUNCH", DINING_MANAGER)
    )

    assert availability["seat_capacity"] == 2
    assert availability["committed_seats"] == 4
    assert availability["open_seats"] == 0
    assert availability["blocking_reservation_ids"] == [first["id"], second["id"]]
