"""Queue A - rule ``resource_temporal_overlap``.

Two contended resources with deliberately different interval semantics: a crew
occupied over half-open instant windows widened by a one-sided 45-minute travel
buffer, and a street project whose capacity is counted per closed calendar date.
"""

from test_helpers import ApiClient, factories, fixtures, validate_error
from test_helpers.test_users import ADMIN_HEADERS, CONTRACTOR_HEADERS
from test_helpers.types import (
    AppointmentState,
    ConsentOutcome,
    FulfillmentState,
    FundingMode,
    SampleType,
    SourceKind,
    VerificationMethod,
)


# ---------------------------------------------------------------------------
# crew_window_overlap_uses_half_open_interval_plus_45_minute_travel_buffer
# ---------------------------------------------------------------------------


def _crew_with_two_windows(api: ApiClient):
    """A crew holding 09:00-10:00 and 10:45-11:30 on 2026-08-05."""
    system = fixtures.create_water_system(
        api,
        "IL2031018",
        system_name="Alderbrook Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(api, system["id"], address_label="101 Elm St")
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew Charlie",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=5,
        certified_methods=[VerificationMethod.VISUAL_INSPECTION],
    )
    first = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.VISUAL_INSPECTION,
        window_start_utc="2026-08-05T09:00:00Z",
        window_end_utc="2026-08-05T10:00:00Z",
    )
    second = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.VISUAL_INSPECTION,
        window_start_utc="2026-08-05T10:45:00Z",
        window_end_utc="2026-08-05T11:30:00Z",
    )
    return {"system": system, "line": line, "crew": crew, "first": first, "second": second}


def test_window_starting_exactly_forty_five_minutes_after_the_previous_end_is_accepted(
    api: ApiClient,
) -> None:
    """10:45:00Z is exactly the buffered end of a 09:00-10:00 window and must book.

    PRD 3.3: "Third, the crew must not already be committed elsewhere at that time,
    and the collision test carries a travel buffer: measured against every other
    appointment of the same `crew_id` whose `state` is `SCHEDULED`, `ON_SITE` or
    `COMPLETED`, the booking is refused with `ERR_CREW_WINDOW_CONFLICT` when the
    new window's start is earlier than three quarters of an hour past the existing
    appointment's end **and** the new window's end is strictly later than the
    existing appointment's start."
    PRD 3.3: "The buffer is applied to the existing appointment's end only, and the
    comparison at the new window's start is strict-less-than, so a new window
    beginning exactly 45 minutes after an existing one ends is accepted."

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_uses_half_open_interval_plus_45_minute_travel_buffer
    """
    scenario = _crew_with_two_windows(api)

    assert scenario["second"]["state"] == AppointmentState.SCHEDULED
    assert fixtures.read_crew(api, scenario["crew"]["id"])["scheduled_appointment_count"] == 2


def test_window_one_minute_inside_the_buffer_conflicts_with_the_earlier_appointment(
    api: ApiClient,
) -> None:
    """10:44-10:45 breaches the buffer of the 09:00-10:00 window and books nothing.

    PRD 3.3: "Third, the crew must not already be committed elsewhere at that time,
    and the collision test carries a travel buffer: measured against every other
    appointment of the same `crew_id` whose `state` is `SCHEDULED`, `ON_SITE` or
    `COMPLETED`, the booking is refused with `ERR_CREW_WINDOW_CONFLICT` when the
    new window's start is earlier than three quarters of an hour past the existing
    appointment's end **and** the new window's end is strictly later than the
    existing appointment's start."
    PRD 3.3: "Second, the window's UTC clock times must both fall inside the crew's
    shift, between `shift_start_utc_time` and `shift_end_utc_time` inclusive, and
    must sit on a single UTC calendar date; a window that escapes the shift or
    straddles midnight is refused with `ERR_CREW_OUTSIDE_SHIFT`."
    PRD 3.3: "For the UTC calendar date on which the requested `window_start_utc`
    falls, the number of appointments of the same crew whose `state` is
    `SCHEDULED`, `ON_SITE` or `COMPLETED` and whose own `window_start_utc` falls on
    that same date must be strictly fewer than the crew's
    `daily_appointment_capacity`; a crew already holding its full day's load is
    refused with `ERR_CREW_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/crew_window_overlap_uses_half_open_interval_plus_45_minute_travel_buffer
    """
    scenario = _crew_with_two_windows(api)

    response = api.create_verification_appointment(
        factories.verification_appointment_payload(
            scenario["line"]["id"],
            scenario["crew"]["id"],
            method=VerificationMethod.VISUAL_INSPECTION,
            window_start_utc="2026-08-05T10:44:00Z",
            window_end_utc="2026-08-05T10:45:00Z",
        ),
        ADMIN_HEADERS,
    )

    error = validate_error(response, "ERR_CREW_WINDOW_CONFLICT", 409)
    assert error["error_id"] != "ERR_CREW_DAILY_CAPACITY_EXCEEDED"
    assert error["error_id"] != "ERR_CREW_OUTSIDE_SHIFT"

    assert fixtures.read_crew(api, scenario["crew"]["id"])["scheduled_appointment_count"] == 2


# ---------------------------------------------------------------------------
# street_project_excavation_capacity_uses_closed_inclusive_date_overlap
# ---------------------------------------------------------------------------


def _project_with_one_scheduled_window(api: ApiClient):
    """A capacity-1 project holding a SCHEDULED 08-10..08-12 order and a FUNDED sibling."""
    system = fixtures.create_water_system(
        api,
        "IL2031019",
        system_name="Copperfield Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    project = fixtures.create_street_project(
        api,
        system["id"],
        project_name="Oak Ave Reconstruction",
        moratorium_start_date="2026-12-01",
        moratorium_end_date="2026-12-31",
        paving_start_date="2027-03-01",
        max_concurrent_excavations=1,
    )
    line_one = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", street_project_id=project["id"]
    )
    line_two = fixtures.make_lead_line(
        api, system["id"], address_label="205 Oak Ave", street_project_id=project["id"]
    )

    batch = fixtures.open_batch(api, system["id"], stratum_code="STR-A", stratum_line_count=20)
    for line_id, ppb, stamp in (
        (line_one["id"], 1.0, "2026-07-11T09:00:00Z"),
        (line_one["id"], 2.0, "2026-07-12T09:00:00Z"),
        (line_two["id"], 3.0, "2026-07-13T09:00:00Z"),
        (line_two["id"], 4.0, "2026-07-14T09:00:00Z"),
        (line_two["id"], 5.0, "2026-07-15T09:00:00Z"),
    ):
        fixtures.append_sample(
            api, batch["id"], line_id, ppb, stamp, sample_type=SampleType.FIRST_DRAW
        )
    fixtures.validate_batch(api, batch["id"])
    advanced = fixtures.advance_to_validation_pending(api, system["id"])
    publication = fixtures.draft_publication(api, system["id"], advanced["version"])
    fixtures.certify_publication(api, publication["id"])
    fixtures.publish_publication(api, publication["id"])
    fixtures.deliver_notification_for_line(
        api, line_one["id"], delivered_at="2026-08-01T09:00:00Z"
    )
    fixtures.deliver_notification_for_line(
        api, line_two["id"], delivered_at="2026-08-01T09:05:00Z"
    )
    fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=1000000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )

    order_a = fixtures.open_order(
        api,
        line_one["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-12",
        street_project_id=project["id"],
    )
    fixtures.resolve_consent(api, order_a["id"], outcome=ConsentOutcome.GRANTED)
    fixtures.plan_funding(api, order_a["id"])
    scheduled = fixtures.schedule_order(api, order_a["id"], "2026-08-10", "2026-08-12")
    assert scheduled["fulfillment_state"] == FulfillmentState.SCHEDULED

    order_b = fixtures.open_order(
        api,
        line_two["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-12",
        excavation_end_date="2026-08-14",
        street_project_id=project["id"],
    )
    fixtures.resolve_consent(api, order_b["id"], outcome=ConsentOutcome.GRANTED)
    fixtures.plan_funding(api, order_b["id"])
    return {"system": system, "project": project, "order_a": order_a, "order_b": order_b}


def test_excavation_capacity_counts_a_single_shared_calendar_date_as_a_breach(
    api: ApiClient,
) -> None:
    """08-12..08-14 touches the scheduled 08-10..08-12 window on one date and is refused.

    PRD 3.7: "And street capacity must hold for **every** calendar date in the
    requested closed window: for each such date, the number of *other* replacement
    orders of the same `street_project_id` whose `fulfillment_state` is `SCHEDULED`
    or `IN_PROGRESS` and whose own closed excavation window includes that date must
    be strictly fewer than the project's `max_concurrent_excavations`, else
    `ERR_EXCAVATION_CAPACITY_EXCEEDED`."
    PRD 3.7: "The requested window must not intersect the linked street project's
    moratorium: with both windows treated as closed inclusive date ranges, the
    request is refused with `ERR_MORATORIUM_CONFLICT` when the excavation start
    falls on or before the moratorium end and the excavation end falls on or after
    the moratorium start."

    Design: Difficulty/resource_temporal_overlap/street_project_excavation_capacity_uses_closed_inclusive_date_overlap
    """
    scenario = _project_with_one_scheduled_window(api)
    project_id = scenario["project"]["id"]
    assert fixtures.read_street_project(api, project_id)["active_excavation_order_count"] == 1

    response = api.schedule_order(
        scenario["order_b"]["id"],
        factories.schedule_order_payload("2026-08-12", "2026-08-14"),
        CONTRACTOR_HEADERS,
    )

    error = validate_error(response, "ERR_EXCAVATION_CAPACITY_EXCEEDED", 409)
    assert error["error_id"] != "ERR_MORATORIUM_CONFLICT"
    assert error["error_id"] != "ERR_CCT_NOT_OPTIMIZED"
    assert error["error_id"] != "ERR_PROGRAM_POSTURE_RESTRICTED"

    assert (
        fixtures.read_order(api, scenario["order_b"]["id"])["fulfillment_state"]
        == FulfillmentState.FUNDED
    )
    assert fixtures.read_street_project(api, project_id)["active_excavation_order_count"] == 1


def test_shifting_the_window_off_the_shared_date_satisfies_the_same_capacity(
    api: ApiClient,
) -> None:
    """08-13..08-14 shares no date with 08-10..08-12 and schedules under a capacity of 1.

    PRD 3.7: "And street capacity must hold for **every** calendar date in the
    requested closed window: for each such date, the number of *other* replacement
    orders of the same `street_project_id` whose `fulfillment_state` is `SCHEDULED`
    or `IN_PROGRESS` and whose own closed excavation window includes that date must
    be strictly fewer than the project's `max_concurrent_excavations`, else
    `ERR_EXCAVATION_CAPACITY_EXCEEDED`."
    PRD 3.7: "On success the supplied dates are written onto the order, the street
    project's `active_excavation_order_count` is refreshed, and the order's
    `version` advances by one."

    Design: Difficulty/resource_temporal_overlap/street_project_excavation_capacity_uses_closed_inclusive_date_overlap
    """
    scenario = _project_with_one_scheduled_window(api)

    scheduled = fixtures.schedule_order(
        api, scenario["order_b"]["id"], "2026-08-13", "2026-08-14"
    )

    assert scheduled["fulfillment_state"] == FulfillmentState.SCHEDULED
    assert scheduled["excavation_start_date"] == "2026-08-13"
    assert scheduled["excavation_end_date"] == "2026-08-14"
    assert (
        fixtures.read_street_project(api, scenario["project"]["id"])[
            "active_excavation_order_count"
        ]
        == 2
    )
