"""When one request breaks two rules at once, the declared order decides."""
from test_helpers import factories, validate_error, validate_paginated, validate_success
from test_helpers.api_errors import (
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_DETERMINATION_NOT_APPEALABLE,
    ERR_PICKUP_WINDOW_LATE,
    ERR_VEHICLE_NOT_ACCESSIBLE,
)
from test_helpers.fixtures import (
    create_applicant,
    create_vehicle,
    drafted_determination,
    scheduled_assessment,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SPECIALIST_HEADERS,
    make_applicant_headers,
)


def _draft_conditional_grant_at_a_late_clock(api):
    """A never-issued CONDITIONAL draft effective 2026-08-06, clock at 2026-10-20."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Marta Quintero",
        date_of_birth="1958-11-02",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    context = drafted_determination(
        api,
        applicant=rider,
        draft_overrides={
            "category": "CONDITIONAL",
            "effective_date": "2026-08-06",
            "rationale": "Conditional on heat index",
            "trip_conditions": [
                factories.trip_condition_payload(
                    condition_type="HEAT_INDEX_ABOVE",
                    comparator="GTE",
                    threshold_value=90,
                    note="Applies at or above 90F",
                )
            ],
        },
    )
    assert context["determination"]["status"] == "DRAFT"
    set_clock(api, "2026-10-20T00:00:00Z")
    return context


_APPEAL_GROUNDS = "Conditions are too narrow for my medical reality"


def test_a_draft_determination_is_refused_as_unappealable_before_the_window(api):
    """The state gate answers first even though the filing window has also closed.

    "Two gates apply, in this order: the determination must currently be in
    `ISSUED` — a `DRAFT`, `SUPERSEDED`, `VACATED` or `EXPIRED` determination is not
    appealable and yields `ERR_DETERMINATION_NOT_APPEALABLE` (409) — and only then
    is the filing window checked."

    Design: Difficulty/priority_pair_validation_conflict/draft_determination_appeal_after_window_rejects_state_before_temporal
    """
    context = _draft_conditional_grant_at_a_late_clock(api)
    rider_headers = make_applicant_headers(context["applicant"]["id"])

    response = api.create_appeal(
        factories.appeal_payload(
            context["determination"]["id"],
            grounds=_APPEAL_GROUNDS,
            request_hearing=False,
        ),
        rider_headers,
    )

    validate_error(response, ERR_DETERMINATION_NOT_APPEALABLE, 409)
    assert response.status_code != 422

    determination = validate_success(
        api.get_determination(context["determination"]["id"], SPECIALIST_HEADERS)
    )
    assert determination["under_appeal"] is False
    rider = validate_success(
        api.get_applicant(context["applicant"]["id"], CLERK_HEADERS)
    )
    assert rider["continued_service_during_appeal"] is False

    _appeals, meta = validate_paginated(
        api.list_determination_appeals(
            context["determination"]["id"], SPECIALIST_HEADERS
        )
    )
    assert meta["total_count"] == 0


def test_once_issued_the_identical_filing_hits_the_closed_sixty_day_window(api):
    """The control call proves the temporal rule was genuinely violated too.

    "The window is 60 days: the appeal is accepted when the calendar date of
    `filed_at` falls on or before the determination's `effective_date` plus 60
    days, and a filing even one day later is refused with
    `ERR_APPEAL_WINDOW_CLOSED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/draft_determination_appeal_after_window_rejects_state_before_temporal
    """
    context = _draft_conditional_grant_at_a_late_clock(api)
    rider_headers = make_applicant_headers(context["applicant"]["id"])

    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                context["determination"]["id"],
                grounds=_APPEAL_GROUNDS,
                request_hearing=False,
            ),
            rider_headers,
        ),
        ERR_DETERMINATION_NOT_APPEALABLE,
        409,
    )

    validate_success(
        api.issue_determination(
            context["determination"]["id"], factories.issue_payload(), SPECIALIST_HEADERS
        )
    )

    validate_error(
        api.create_appeal(
            factories.appeal_payload(
                context["determination"]["id"],
                grounds=_APPEAL_GROUNDS,
                request_hearing=False,
            ),
            rider_headers,
        ),
        ERR_APPEAL_WINDOW_CLOSED,
        422,
    )

    _appeals, meta = validate_paginated(
        api.list_determination_appeals(
            context["determination"]["id"], SPECIALIST_HEADERS
        )
    )
    assert meta["total_count"] == 0


def _wheelchair_rider_and_a_vehicle_without_positions(api):
    """A scheduled assessment plus a vehicle carrying no securement position."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Owen Prescott",
        date_of_birth="1949-04-18",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="POWER_WHEELCHAIR",
    )
    context = scheduled_assessment(api, applicant=rider)
    context["vehicle"] = create_vehicle(
        api,
        vehicle_number="V-0001",
        wheelchair_positions=0,
        ambulatory_seats=1,
        status="IN_SERVICE",
    )
    return context


def test_the_accessibility_guard_answers_before_capacity_and_before_lateness(api):
    """A securement request against a vehicle with no positions is a safety refusal.

    "Second, a ride that needs a securement position requires the vehicle to have
    at least one `wheelchair_positions`, else `ERR_VEHICLE_NOT_ACCESSIBLE` (422)."

    "Four rules guard a reservation, and when more than one is violated they are
    evaluated in this order."

    Design: Difficulty/priority_pair_validation_conflict/booking_accessibility_safety_precedes_window_conflict_and_late_pickup
    """
    context = _wheelchair_rider_and_a_vehicle_without_positions(api)

    response = api.create_transportation_booking(
        factories.transportation_booking_payload(
            context["assessment"]["id"],
            context["vehicle"]["id"],
            pickup_window_start="2026-08-05T09:30:00Z",
            pickup_window_end="2026-08-05T10:00:00Z",
            requires_wheelchair_position=True,
        ),
        CLERK_HEADERS,
    )

    validate_error(response, ERR_VEHICLE_NOT_ACCESSIBLE, 422)
    assert response.json()["data"]["error_id"] != "ERR_VEHICLE_WINDOW_CONFLICT"
    assert response.json()["data"]["error_id"] != ERR_PICKUP_WINDOW_LATE


def test_peeling_the_ladder_reveals_the_late_pickup_rule_then_a_clean_reservation(api):
    """The same window on the ambulatory lane is refused only for arriving late.

    "Fourth, the ride must actually get the rider there in time:
    `pickup_window_end` must fall at or before the assessment slot's `starts_at`,
    and a later window is refused with `ERR_PICKUP_WINDOW_LATE` (422)."

    "The booking is created in `RESERVED` with `cancelled_reason` null, and it
    increments `open_wheelchair_reservations` on the vehicle when it consumes a
    securement position and `open_ambulatory_reservations` when it does not."

    Design: Difficulty/priority_pair_validation_conflict/booking_accessibility_safety_precedes_window_conflict_and_late_pickup
    """
    context = _wheelchair_rider_and_a_vehicle_without_positions(api)
    assessment_id = context["assessment"]["id"]
    vehicle_id = context["vehicle"]["id"]

    validate_error(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id,
                vehicle_id,
                pickup_window_start="2026-08-05T09:30:00Z",
                pickup_window_end="2026-08-05T10:00:00Z",
                requires_wheelchair_position=True,
            ),
            CLERK_HEADERS,
        ),
        ERR_VEHICLE_NOT_ACCESSIBLE,
        422,
    )

    validate_error(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id,
                vehicle_id,
                pickup_window_start="2026-08-05T09:30:00Z",
                pickup_window_end="2026-08-05T10:00:00Z",
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        ERR_PICKUP_WINDOW_LATE,
        422,
    )

    booking = validate_success(
        api.create_transportation_booking(
            factories.transportation_booking_payload(
                assessment_id,
                vehicle_id,
                pickup_window_start="2026-08-05T08:00:00Z",
                pickup_window_end="2026-08-05T09:00:00Z",
                requires_wheelchair_position=False,
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    assert booking["status"] == "RESERVED"

    vehicle = validate_success(api.get_vehicle(vehicle_id, CLERK_HEADERS))
    assert vehicle["open_ambulatory_reservations"] == 1
    assert vehicle["open_wheelchair_reservations"] == 0

    _bookings, meta = validate_paginated(
        api.list_transportation_bookings(CLERK_HEADERS, params={"vehicle_id": vehicle_id})
    )
    assert meta["total_count"] == 1
