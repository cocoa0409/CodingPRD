"""Reads and links: what an endpoint recomputes, charges and resolves."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND,
)
from test_helpers.assertions import assert_conduct_mirrors, assert_vehicle_counters
from test_helpers.fixtures import (
    auto_referral,
    create_applicant,
    create_slot,
    create_vehicle,
    ingest_trip_events,
    scheduled_assessment,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    EVALUATOR_HEADERS,
    TRAINER_HEADERS,
    make_applicant_headers,
)


def test_the_rider_read_recomputes_every_conduct_mirror_from_a_mixed_stream(api):
    """Five event types, two scoring ones, and one excusal re-derives them all.

    "The event is stored with `recorded_at` stamped from the logical clock,
    `excused` false, `excuse_reason` null, and `points_assessed` set to 2 for an
    unexcused `NO_SHOW`, 1 for an unexcused `LATE_CANCEL`, and 0 for every other
    event type."

    "Events scored at 0 points — `COMPLETED`, `CANCEL_IN_ADVANCE` and
    `AGENCY_FAULT_NO_SHOW` — contribute nothing to either total."

    "Both ingestion and excusal recompute the whole conduct block, as does every
    read of the rider."

    "The subtlety worth internalizing is that an excused event **stays in the
    denominator and leaves the numerator** of the miss ratio — the trip still
    happened and still consumed a slot, it just no longer counts against the
    rider."

    Design: Corner/endpoints/the_applicant_read_recomputes_every_conduct_mirror_from_a_mixed_event_stream
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Rosa Delacroix",
        date_of_birth="1978-08-08",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    events = ingest_trip_events(
        api,
        rider["id"],
        [
            ("2026-07-05", "NO_SHOW"),
            ("2026-07-06", "LATE_CANCEL"),
            ("2026-07-07", "COMPLETED"),
            ("2026-07-08", "CANCEL_IN_ADVANCE"),
            ("2026-07-09", "AGENCY_FAULT_NO_SHOW"),
        ],
    )
    assert [event["points_assessed"] for event in events] == [2, 1, 0, 0, 0]
    assert all(event["excused"] is False for event in events)

    rider = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(
        rider,
        event_basis=3,
        report_basis=3,
        miss_count=2,
        scheduled_count=5,
        ratio_pct=40.0,
    )
    assert rider["service_status"] == "ACTIVE"

    _proceedings, proceeding_meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert proceeding_meta["total_count"] == 0

    excused = validate_success(
        api.excuse_trip_event(
            events[0]["id"],
            factories.excuse_payload(excuse_reason="provider transport failure"),
            CONDUCT_OFFICER_HEADERS,
        )
    )
    assert excused["excused"] is True
    assert excused["points_assessed"] == 0

    rider = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(
        rider,
        event_basis=1,
        report_basis=1,
        miss_count=1,
        scheduled_count=5,
        ratio_pct=20.0,
    )

    excused_rows, excused_meta = validate_paginated(
        api.list_trip_events(
            rider["id"], CONDUCT_OFFICER_HEADERS, params={"excused": "true"}
        )
    )
    assert excused_meta["total_count"] == 1
    assert excused_rows[0]["id"] == events[0]["id"]


def test_confirming_fixed_route_competency_flips_the_same_trip_check_to_denied(api):
    """One completion turns the identical unfamiliar-route request into a denial.

    "A `COGNITIVE_UNFAMILIAR_ROUTE` condition is satisfied only when the
    request's `route_familiarity` is `UNFAMILIAR` **and** the determination's own
    `fixed_route_competency_confirmed` is false; once competency has been
    confirmed, that condition can never be satisfied again."

    "A score of at least 80 confirms fixed-route competency, and that
    confirmation cascades: the rider's `fixed_route_competency_confirmed` flips
    to true, and because the rider flag has flipped, the
    `fixed_route_competency_confirmed` mirror on the rider's determination that
    is still in `ISSUED` flips to true as well, which permanently suppresses
    `COGNITIVE_UNFAMILIAR_ROUTE` conditions in every subsequent trip-by-trip
    evaluation of that grant."

    "The response reports `applied_condition_ids` as the identifiers of the
    satisfied conditions in the order they were evaluated, `eligible` as true
    when that list holds at least one entry, `denial_reason` as null when
    eligible and `NO_CONDITION_MET` when the list is empty,
    `evaluated_condition_count` as the number of the determination's conditions
    that were examined, and `category` as the determination's own category."

    Design: Corner/endpoints/confirming_fixed_route_competency_flips_the_same_trip_check_to_denied
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Sipho Nkemelu",
        date_of_birth="1990-10-30",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    context = auto_referral(
        api,
        applicant=rider,
        conditions=[
            factories.boolean_trip_condition_payload(
                "COGNITIVE_UNFAMILIAR_ROUTE",
                note="trips on routes the rider has not learned",
            )
        ],
        functional_answers=factories.functional_answers(
            can_board_bus_steps=True,
            can_navigate_unfamiliar_route=False,
            max_walk_distance_meters=500,
            uses_mobility_aid_outdoors=False,
            has_cognitive_impairment=True,
        ),
        claimed_conditions=["autism spectrum disorder"],
        score_overrides={
            "board_alight_score": 4,
            "wayfinding_score": 2,
            "distance_meters_walked": 500,
            "heat_sensitivity_flag": False,
        },
    )
    determination = context["determination"]
    referral = context["referral"]

    assert context["assessment"]["recommended_category"] == "CONDITIONAL"
    assert determination["category"] == "CONDITIONAL"
    assert determination["trip_condition_count"] == 1
    assert determination["fixed_route_competency_confirmed"] is False
    assert referral["referral_reason"] == "CONDITIONAL_ELIGIBILITY_AUTO"
    assert referral["status"] == "REFERRED"

    conditions, condition_meta = validate_paginated(
        api.list_trip_conditions(determination["id"], TRAINER_HEADERS)
    )
    assert condition_meta["total_count"] == 1
    condition_id = conditions[0]["id"]

    set_clock(api, "2026-08-06T12:00:00Z")
    rider_headers = make_applicant_headers(rider["id"])
    trip_request = factories.trip_eligibility_check_payload(
        trip_date="2026-08-06",
        route_familiarity="UNFAMILIAR",
        forecast_heat_index_f=70,
        origin_distance_to_stop_meters=120,
    )

    before = validate_success(
        api.trip_eligibility_check(determination["id"], trip_request, rider_headers)
    )
    assert before["eligible"] is True
    assert before["applied_condition_ids"] == [condition_id]
    assert before["evaluated_condition_count"] == 1
    assert before["denial_reason"] is None
    assert before["category"] == "CONDITIONAL"

    enrolled = validate_success(
        api.respond_to_referral(
            referral["id"],
            factories.referral_response_payload("ENROLLED"),
            rider_headers,
        )
    )
    assert enrolled["status"] == "ENROLLED"

    completed = validate_success(
        api.complete_referral(
            referral["id"],
            factories.referral_completion_payload(fixed_route_competency_score=85),
            TRAINER_HEADERS,
        )
    )
    assert completed["status"] == "COMPLETED"
    assert completed["fixed_route_competency_score"] == 85

    rider = validate_success(api.get_applicant(rider["id"], TRAINER_HEADERS))
    assert rider["fixed_route_competency_confirmed"] is True
    refreshed = validate_success(
        api.get_determination(determination["id"], TRAINER_HEADERS)
    )
    assert refreshed["fixed_route_competency_confirmed"] is True
    assert refreshed["status"] == "ISSUED"

    after = validate_success(
        api.trip_eligibility_check(determination["id"], trip_request, rider_headers)
    )
    assert after["eligible"] is False
    assert after["applied_condition_ids"] == []
    assert after["evaluated_condition_count"] == 1
    assert after["denial_reason"] == "NO_CONDITION_MET"


def test_rescheduling_after_a_no_show_charges_the_gap_to_the_applicant(api):
    """The optional back-reference is what turns a booking into a charging one.

    "may set `rescheduled_from_assessment_id` to point at a prior assessment that
    ended in `NO_SHOW` or `CANCELLED_BY_AGENCY`; that field defaults to null and
    is the self-referential link that lets the office walk a reschedule chain."

    "When `rescheduled_from_assessment_id` is supplied, the packet's
    `applicant_delay_days` additionally grows by the whole days between the prior
    assessment's slot start and this slot's start."

    "The slot's `booked_count` decreases by one, and a slot that was `FULL`
    returns to `OPEN` as soon as its `booked_count` falls below its `capacity`."

    "And the parent packet regresses from `ASSESSMENT_SCHEDULED` back to
    `ASSESSMENT_REQUIRED` so a replacement assessment can be booked"

    Design: Corner/endpoints/rescheduling_after_a_no_show_charges_the_gap_to_the_applicant
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Tomas Halvorsen",
        date_of_birth="1948-04-18",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    first_slot = create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-05T09:00:00Z",
        ends_at="2026-08-05T10:00:00Z",
        capacity=1,
        site_is_wheelchair_accessible=True,
    )
    second_slot = create_slot(
        api,
        site_name="Central Mobility Center",
        evaluator_user_id="eval-1",
        starts_at="2026-08-12T09:00:00Z",
        ends_at="2026-08-12T10:00:00Z",
        capacity=1,
        site_is_wheelchair_accessible=True,
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        slot=first_slot,
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=140,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["post-polio syndrome"],
    )
    application_id = context["application"]["id"]
    first_assessment = context["assessment"]

    assert first_assessment["rescheduled_from_assessment_id"] is None
    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_SCHEDULED"
    assert application["applicant_delay_days"] == 0

    set_clock(api, "2026-08-05T09:05:00Z")
    missed = validate_success(
        api.record_attendance(
            first_assessment["id"],
            factories.attendance_payload("NO_SHOW"),
            EVALUATOR_HEADERS,
        )
    )
    assert missed["attendance_status"] == "NO_SHOW"

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_REQUIRED"
    assert application["applicant_delay_days"] == 0

    replacement = validate_success(
        api.book_assessment(
            application_id,
            factories.assessment_booking_payload(
                second_slot["id"],
                rescheduled_from_assessment_id=first_assessment["id"],
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert replacement["rescheduled_from_assessment_id"] == first_assessment["id"]
    assert replacement["attendance_status"] == "SCHEDULED"

    application = validate_success(api.get_application(application_id, CLERK_HEADERS))
    assert application["status"] == "ASSESSMENT_SCHEDULED"
    assert application["applicant_delay_days"] == 7

    _chain, chain_meta = validate_paginated(
        api.list_assessments(
            CLERK_HEADERS,
            params={"rescheduled_from_assessment_id": first_assessment["id"]},
        )
    )
    assert chain_meta["total_count"] == 1

    _on_second, second_meta = validate_paginated(
        api.list_assessments(CLERK_HEADERS, params={"slot_id": second_slot["id"]})
    )
    assert second_meta["total_count"] == 1

    abandoned = validate_success(
        api.get_assessment_slot(first_slot["id"], CLERK_HEADERS)
    )
    assert abandoned["status"] == "OPEN"
    assert abandoned["booked_count"] == 0


def test_a_booking_links_an_assessment_to_a_vehicle_and_both_parents_must_exist(api):
    """The link row resolves from both sides, and neither 404 leaves a remnant.

    "Every reference carried in a request body — `applicant_id`,
    `application_id`, `slot_id`, `vehicle_id`, `assessment_id`,
    `determination_id` — must resolve to a stored record. The affected operations
    are opening an application, booking an assessment, reserving a ride, filing
    an appeal, ingesting a trip event, and referring a rider to travel training;
    the codes are the corresponding not-found identifiers with HTTP 404."

    "The booking is created in `RESERVED` with `cancelled_reason` null, and it
    increments `open_wheelchair_reservations` on the vehicle when it consumes a
    securement position and `open_ambulatory_reservations` when it does not."

    "each counting that vehicle's bookings still in `RESERVED` with
    `requires_wheelchair_position` true and false respectively; both start at 0"

    Design: Corner/endpoints/a_booking_links_an_assessment_to_a_vehicle_and_both_parents_must_exist
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Ursula Beaumont",
        date_of_birth="1952-12-02",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    context = scheduled_assessment(
        api,
        applicant=rider,
        slot=create_slot(
            api,
            site_name="Central Mobility Center",
            evaluator_user_id="eval-1",
            starts_at="2026-08-05T09:00:00Z",
            ends_at="2026-08-05T10:00:00Z",
            capacity=2,
            site_is_wheelchair_accessible=True,
        ),
        functional_answers=factories.functional_answers(
            can_board_bus_steps=False,
            can_navigate_unfamiliar_route=True,
            max_walk_distance_meters=160,
            uses_mobility_aid_outdoors=True,
            has_cognitive_impairment=False,
        ),
        claimed_conditions=["chronic heart failure"],
    )
    assessment_id = context["assessment"]["id"]
    vehicle = create_vehicle(
        api,
        vehicle_number="V-8100",
        wheelchair_positions=1,
        ambulatory_seats=2,
        status="IN_SERVICE",
    )

    validate_error(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                "00000000-0000-4000-8000-0000000000aa",
                vehicle["id"],
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        ERR_ASSESSMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id,
                "00000000-0000-4000-8000-0000000000bb",
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        ERR_VEHICLE_NOT_FOUND,
        404,
    )

    booking = validate_success(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id, vehicle["id"], requires_wheelchair_position=False
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert booking["status"] == "RESERVED"
    assert booking["cancelled_reason"] is None
    assert booking["assessment_id"] == assessment_id
    assert booking["vehicle_id"] == vehicle["id"]

    by_assessment, assessment_meta = validate_paginated(
        api.list_transportation_bookings(
            CLERK_HEADERS, params={"assessment_id": assessment_id}
        )
    )
    assert assessment_meta["total_count"] == 1
    by_vehicle, vehicle_meta = validate_paginated(
        api.list_transportation_bookings(
            CLERK_HEADERS, params={"vehicle_id": vehicle["id"]}
        )
    )
    assert vehicle_meta["total_count"] == 1
    assert by_assessment[0]["id"] == by_vehicle[0]["id"] == booking["id"]

    vehicle = validate_success(api.get_vehicle(vehicle["id"], CLERK_HEADERS))
    assert_vehicle_counters(vehicle, wheelchair=0, ambulatory=1)
