"""Two published day counts, and two point totals, that legitimately disagree."""
from test_helpers import factories, validate_paginated, validate_success
from test_helpers.assertions import assert_conduct_mirrors
from test_helpers.fixtures import (
    create_applicant,
    ingest_trip_event,
    set_clock,
)
from test_helpers.test_users import CLERK_HEADERS, CONDUCT_OFFICER_HEADERS


def _packet_with_five_excluded_verification_days(api):
    """Submit a packet on 2026-08-01 and answer its verification on 2026-08-06."""
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Rosa Vance",
        date_of_birth="1958-04-12",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="WALKER",
    )
    application = validate_success(
        api.create_application(
            factories.application_payload(
                rider["id"],
                application_type="NEW",
                functional_answers=factories.functional_answers(
                    can_board_bus_steps=False,
                    can_navigate_unfamiliar_route=False,
                    max_walk_distance_meters=120,
                    uses_mobility_aid_outdoors=True,
                    has_cognitive_impairment=False,
                ),
                claimed_conditions=["limited stamina"],
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    validate_success(
        api.submit_application(application["id"], factories.submit_payload(), CLERK_HEADERS)
    )
    verification = validate_success(
        api.request_verification(
            application["id"],
            factories.verification_request_payload(
                provider_name="Dr. A Lin",
                provider_type="PHYSICIAN",
                provider_license_number="MD-44821",
            ),
            CLERK_HEADERS,
        ),
        201,
    )
    set_clock(api, "2026-08-06T00:00:00Z")
    received = validate_success(
        api.receive_verification(
            application["id"],
            verification["id"],
            factories.verification_accepted_payload(
                attests_conditions=["limited stamina"], attests_permanent=True
            ),
            CLERK_HEADERS,
        )
    )
    return {"rider": rider, "application": application, "verification": received}


def test_statutory_and_net_agency_pending_days_diverge_by_the_excluded_days(api):
    """The two published pending-day counts answer different questions.

    "`days_pending_statutory` is the governing number: it is zero whenever
    `completeness_established_at` is null, and otherwise it is the whole number
    of days elapsed from `completeness_established_at` to the logical clock's
    current instant, discarding any partial day."

    "`days_pending_net_agency` is the internal performance number reported to
    management as agency-controlled processing time: take
    `days_pending_statutory`, subtract `verification_excluded_days`, subtract
    `applicant_delay_days`, and if the result is below zero report zero instead."

    Design: Difficulty/dual_variant_calc/application_pending_days_statutory_vs_net_agency
    """
    context = _packet_with_five_excluded_verification_days(api)

    assert context["verification"]["wait_days"] == 5

    set_clock(api, "2026-08-22T00:00:00Z")
    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )

    assert application["verification_excluded_days"] == 5
    assert application["applicant_delay_days"] == 0
    assert application["days_pending_statutory"] == 21
    assert application["days_pending_net_agency"] == 16
    assert (
        application["days_pending_statutory"] - application["days_pending_net_agency"]
    ) == 5


def test_the_statutory_clock_starts_at_completeness_and_fixes_the_due_date(api):
    """Submission establishes completeness and the twenty-one-day due date.

    "It sets `completeness_established_at` equal to `submitted_at`, which is the
    moment the statutory determination window begins. It sets
    `determination_due_date` to the calendar date of
    `completeness_established_at` plus 21 days."

    Design: Difficulty/dual_variant_calc/application_pending_days_statutory_vs_net_agency
    """
    context = _packet_with_five_excluded_verification_days(api)

    set_clock(api, "2026-08-22T00:00:00Z")
    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )

    assert application["completeness_established_at"] == "2026-08-01T00:00:00.000Z"
    assert application["determination_due_date"] == "2026-08-22"


def test_the_verification_wait_is_added_to_the_excluded_days_of_the_packet(api):
    """The whole days a professional took are excluded from the net figure.

    "`verification_excluded_days` grows by the whole number of days a
    professional verification waited — from its `requested_at` to its
    `received_at`, discarding any partial day — every time a response is
    recorded, whichever way that response goes."

    Design: Difficulty/dual_variant_calc/application_pending_days_statutory_vs_net_agency
    """
    context = _packet_with_five_excluded_verification_days(api)

    verifications, _meta = validate_paginated(
        api.list_verifications(context["application"]["id"], CLERK_HEADERS)
    )
    verification = verifications[0]

    assert verification["wait_days"] == 5
    application = validate_success(
        api.get_application(context["application"]["id"], CLERK_HEADERS)
    )
    assert application["verification_excluded_days"] == 5


def test_event_basis_and_report_basis_point_totals_diverge_on_one_stream(api):
    """One miss dated outside the window but keyed inside it splits the totals.

    "The **event-date basis** tests window membership against the event's
    `trip_date`, so a miss ingested late still counts in the period in which it
    actually happened; this is the governing total and it is published as
    `no_show_points_event_basis`."

    "The **report-date basis** tests membership against the calendar date of
    `recorded_at`, so a trip that happened before the window but was keyed in
    during it counts here and not on the event basis; this total is published as
    `no_show_points_report_basis` and is used only for the monthly conduct
    report — it never gates anything."

    Design: Difficulty/dual_variant_calc/conduct_points_event_basis_vs_report_basis
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Dell Okafor",
        date_of_birth="1962-11-30",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )

    early_miss = ingest_trip_event(
        api, rider["id"], trip_date="2026-05-02", event_type="NO_SHOW"
    )
    late_cancel = validate_success(
        api.create_trip_event(
            factories.trip_event_payload(
                rider["id"], trip_date="2026-06-15", event_type="LATE_CANCEL"
            ),
            CONDUCT_OFFICER_HEADERS,
        ),
        201,
    )

    assert early_miss["points_assessed"] == 2
    assert late_cancel["points_assessed"] == 1

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert rider["no_show_points_event_basis"] == 1
    assert rider["no_show_points_report_basis"] == 3
    assert (
        rider["no_show_points_report_basis"] - rider["no_show_points_event_basis"]
    ) == 2


def test_the_event_basis_window_drives_the_ratio_and_leaves_the_thresholds_unmet(api):
    """Only the events dated inside the window feed the ratio and the thresholds.

    "Take the rider's events whose `trip_date` falls inside the inclusive 90-day
    window: `scheduled_trip_count_90d` is how many there are, counting every
    event type including excused ones, and `chargeable_miss_count_90d` is how
    many of them are unexcused and of type `NO_SHOW` or `LATE_CANCEL`."

    "Three thresholds together define a suspendable pattern, and all three must
    hold simultaneously: `no_show_points_event_basis` at least 6,
    `chargeable_miss_count_90d` at least 3, and `no_show_ratio_pct` strictly
    greater than 10.0 percent."

    Design: Difficulty/dual_variant_calc/conduct_points_event_basis_vs_report_basis
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    rider = create_applicant(
        api,
        full_name="Dell Okafor",
        date_of_birth="1962-11-30",
        residence_zone="IN_SERVICE_AREA",
        mobility_aid="CANE",
    )
    ingest_trip_event(api, rider["id"], trip_date="2026-05-02", event_type="NO_SHOW")
    ingest_trip_event(api, rider["id"], trip_date="2026-06-15", event_type="LATE_CANCEL")

    rider = validate_success(api.get_applicant(rider["id"], CLERK_HEADERS))
    assert_conduct_mirrors(
        rider,
        event_basis=1,
        report_basis=3,
        miss_count=1,
        scheduled_count=1,
        ratio_pct=100.0,
    )

    proceedings, meta = validate_paginated(
        api.list_suspension_proceedings(rider["id"], CONDUCT_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 0
    assert proceedings == []
