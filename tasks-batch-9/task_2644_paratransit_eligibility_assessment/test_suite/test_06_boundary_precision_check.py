"""Both boundaries are closed exactly where the contract closes them."""
from test_helpers import factories, validate_paginated, validate_success
from test_helpers.assertions import assert_conduct_mirrors
from test_helpers.fixtures import (
    create_applicant,
    ingest_trip_event,
    run_day_close,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    CONDUCT_OFFICER_HEADERS,
    SPECIALIST_HEADERS,
)


def _packet_submitted_on_the_first_of_august(api):
    """A packet whose statutory clock starts at exactly 2026-08-01T00:00:00Z."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Hilde Novak",
        date_of_birth="1952-07-30",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                application_type="NEW",
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=True,
                    max_walk_distance_meters=400,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    submitted = validate_success(
        api.submit_application(application["id"], factories.submit_payload(), CLERK_HEADERS)
    )
    assert submitted["completeness_established_at"] == "2026-08-01T00:00:00.000Z"
    assert submitted["determination_due_date"] == "2026-08-22"
    return {"rider": rider, "application": submitted}


def test_twenty_pending_days_grants_no_presumptive_eligibility(api):
    """One day short of the threshold, the sweep grants nothing.

    "**Step 4 — presumptive eligibility.** Applications that have been pending at
    least 21 days receive presumptive eligibility, under the conditions and in the
    order described in §3.2."

    "The sweep walks the rider's applications in `created_at` ascending order and
    grants presumptive eligibility to a packet when **all four** of the following
    hold at that moment: `days_pending_statutory` is at least 21; the packet's
    `status` is none of `DRAFT`, `RETURNED_INCOMPLETE` or `DETERMINED`;
    `presumptive_granted_at` is still null; and the rider holds no determination in
    `ISSUED` at that instant."

    Design: Difficulty/boundary_precision_check/presumptive_eligibility_grants_at_exactly_twenty_one_days_not_twenty
    """
    context = _packet_submitted_on_the_first_of_august(api)

    set_clock(api, "2026-08-21T00:00:00Z")
    application = validate_success(
        api.get_application(context["application"]["id"], SPECIALIST_HEADERS)
    )
    assert application["days_pending_statutory"] == 20

    sweep = run_day_close(api)
    assert sweep["presumptive_granted_count"] == 0

    application = validate_success(
        api.get_application(context["application"]["id"], SPECIALIST_HEADERS)
    )
    assert application["presumptive_granted_at"] is None
    rider = validate_success(api.get_applicant(context["rider"]["id"], CLERK_HEADERS))
    assert rider["current_eligibility_status"] == "NONE"


def test_twenty_one_pending_days_grants_presumptive_eligibility_exactly_once(api):
    """At the threshold the sweep grants, and it never grants the same packet twice.

    "When they hold, `presumptive_granted_at` is stamped with the sweep's instant
    and the rider's `current_eligibility_status` becomes `PRESUMPTIVE`."

    "Because `presumptive_granted_at` is checked and set exactly once, a rider
    cannot be granted presumptive eligibility twice for the same packet; and
    because the sweep tests for an issued determination at the moment it runs, a
    rider whose determination lands the day before the breach never becomes
    `PRESUMPTIVE` at all."

    Design: Difficulty/boundary_precision_check/presumptive_eligibility_grants_at_exactly_twenty_one_days_not_twenty
    """
    context = _packet_submitted_on_the_first_of_august(api)

    set_clock(api, "2026-08-21T00:00:00Z")
    assert run_day_close(api)["presumptive_granted_count"] == 0

    set_clock(api, "2026-08-22T00:00:00Z")
    application = validate_success(
        api.get_application(context["application"]["id"], SPECIALIST_HEADERS)
    )
    assert application["days_pending_statutory"] == 21

    sweep = run_day_close(api)
    assert sweep["presumptive_granted_count"] == 1

    application = validate_success(
        api.get_application(context["application"]["id"], SPECIALIST_HEADERS)
    )
    assert application["presumptive_granted_at"] == "2026-08-22T00:00:00.000Z"

    rider = validate_success(api.get_applicant(context["rider"]["id"], CLERK_HEADERS))
    assert rider["current_eligibility_status"] == "PRESUMPTIVE"
    assert rider["eligibility_category"] is None

    third_sweep = run_day_close(api)
    assert third_sweep["presumptive_granted_count"] == 0


def _rider_with_three_january_events(api):
    """Three misses from January, far outside every later conduct window."""
    set_clock(api, "2026-01-15T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Roland Beck",
        date_of_birth="1971-02-08",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="NONE",
    )
    ingest_trip_event(api, rider["id"], trip_date="2026-01-10", event_type="NO_SHOW")
    ingest_trip_event(api, rider["id"], trip_date="2026-01-11", event_type="NO_SHOW")
    ingest_trip_event(api, rider["id"], trip_date="2026-01-12", event_type="LATE_CANCEL")
    set_clock(api, "2026-08-01T00:00:00Z")
    return rider


def test_a_trip_one_day_before_the_window_start_is_outside_the_window(api):
    """The window opens on today minus 89 days, so 2026-05-03 is one day early.

    "The conduct window spans 90 calendar days ending on today's date, so its
    first day is today's date minus 89 days and a trip falling on either boundary
    date is inside the window."

    "When `scheduled_trip_count_90d` is zero, `no_show_ratio_pct` is 0.0."

    Design: Difficulty/boundary_precision_check/conduct_window_start_boundary_excludes_event_one_day_early
    """
    rider = _rider_with_three_january_events(api)

    edge_event = ingest_trip_event(
        api, rider["id"], trip_date="2026-05-03", event_type="NO_SHOW"
    )
    assert edge_event["points_assessed"] == 2
    assert edge_event["recorded_at"] == "2026-08-01T00:00:00.000Z"

    rider = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(
        rider,
        event_basis=0,
        report_basis=2,
        miss_count=0,
        scheduled_count=0,
        ratio_pct=0.0,
    )
    assert rider["no_show_ratio_pct"] == 0.0

    _proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 0


def test_a_trip_on_the_window_start_date_is_inside_the_window(api):
    """One day later the same kind of miss lands inside and moves every mirror.

    "Rolling windows are inclusive at both ends and are anchored deliberately."

    "`chargeable_miss_count_90d` is how many of them are unexcused and of type
    `NO_SHOW` or `LATE_CANCEL`."

    Design: Difficulty/boundary_precision_check/conduct_window_start_boundary_excludes_event_one_day_early
    """
    rider = _rider_with_three_january_events(api)

    ingest_trip_event(api, rider["id"], trip_date="2026-05-03", event_type="NO_SHOW")
    outside = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert outside["no_show_points_event_basis"] == 0

    ingest_trip_event(api, rider["id"], trip_date="2026-05-04", event_type="NO_SHOW")
    inside = validate_success(api.get_applicant(rider["id"], CONDUCT_OFFICER_HEADERS))
    assert_conduct_mirrors(
        inside,
        event_basis=2,
        miss_count=1,
        scheduled_count=1,
        ratio_pct=100.0,
    )
