"""Booking install crews: blackout days, the travel buffer and the calendar guards."""
from test_helpers import (
    abort_install_payload,
    install_job_payload,
    new_install_job,
    new_service_partner,
    read_facility,
    read_install_job,
    read_order,
    read_service_partner,
    setup_released_revision,
    setup_staged_order,
    validate_error,
    validate_paginated,
    validate_success,
)

SATURDAY_EVENING = ("2026-09-12T20:00:00Z", "2026-09-12T22:00:00Z")
SATURDAY_MORNING = ("2026-09-12T08:00:00Z", "2026-09-12T12:00:00Z")
LONG_WEEKEND_JOB = ("2026-09-12T08:00:00Z", "2026-09-13T16:00:00Z")
WEEKEND_BLACKOUT = ["SAT", "SUN"]


def _blackout_and_open_facilities():
    """One partner already booked across a weekend, plus a blacked-out facility."""
    revision = setup_released_revision("T900")
    open_order = setup_staged_order(revision_ctx=revision, quantity=1,
                                    facility_overrides={"account_name": "Open Calendar Gym",
                                                        "freight_zone": "Z1"})
    partner = new_service_partner(name="Meridian Service Co",
                                  certified_categories=["CARDIO"])
    existing = new_install_job(open_order["order"]["id"], partner["id"],
                              *LONG_WEEKEND_JOB, estimated_labor_hours=1.5)
    blacked_out = setup_staged_order(
        revision_ctx=revision, quantity=1,
        facility_overrides={"account_name": "Sabbath Rest Athletic Club",
                            "freight_zone": "Z1",
                            "install_blackout_weekdays": WEEKEND_BLACKOUT},
    )
    control = setup_staged_order(revision_ctx=revision, quantity=1,
                                facility_overrides={"account_name": "Second Open Gym",
                                                    "freight_zone": "Z1"})
    return {"partner": partner, "existing": existing, "blacked_out": blacked_out,
            "control": control, "open": open_order}


def test_blackout_day_outranks_the_partner_window_conflict(api, order_planner_headers):
    """A Saturday booking that also double-books the crew reports the blackout.

    The PRD states that "neither the `window_start` calendar date nor the
    `window_end` calendar date, both evaluated in UTC and both checked inclusively,
    may fall on a weekday listed in the facility's `install_blackout_weekdays`
    (`ERR_INSTALL_BLACKOUT_DAY`)".

    Design: Difficulty/priority_pair_validation_conflict/install_blackout_outranks_partner_window_conflict
    """
    ctx = _blackout_and_open_facilities()
    order = ctx["blacked_out"]["order"]

    response = api.create_install_job(
        install_job_payload(order["id"], ctx["partner"]["id"],
                            *SATURDAY_EVENING, estimated_labor_hours=1.5),
        order_planner_headers,
    )

    error = validate_error(response, "ERR_INSTALL_BLACKOUT_DAY", 422)
    assert error["error_id"] != "ERR_INSTALL_WINDOW_CONFLICT"
    assert response.status_code != 409
    _, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0
    existing = read_install_job(ctx["existing"]["id"])
    assert existing["status"] == "SCHEDULED"
    assert existing["travel_buffer_minutes"] == 120
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 1.5
    facility = read_facility(ctx["blacked_out"]["facility"]["id"])
    assert facility["install_blackout_weekdays"] == WEEKEND_BLACKOUT


def test_the_same_saturday_window_conflicts_when_no_blackout_applies(
    api, order_planner_headers
):
    """At a facility with an empty blackout list the calendar rule fires instead.

    The PRD states that a conflict arises with "an existing job in `SCHEDULED`,
    `ON_SITE` or `PUNCH_LIST`" and that "A genuine intersection is
    `ERR_INSTALL_WINDOW_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/install_blackout_outranks_partner_window_conflict
    """
    ctx = _blackout_and_open_facilities()
    control_order = ctx["control"]["order"]
    assert read_facility(ctx["control"]["facility"]["id"])[
        "install_blackout_weekdays"
    ] == []

    response = api.create_install_job(
        install_job_payload(control_order["id"], ctx["partner"]["id"],
                            *SATURDAY_EVENING, estimated_labor_hours=1.5),
        order_planner_headers,
    )

    validate_error(response, "ERR_INSTALL_WINDOW_CONFLICT", 409)
    _, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers,
                              params={"order_id": control_order["id"]})
    )
    assert meta["total_count"] == 0
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 1.5
    assert read_order(control_order["id"])["fulfillment_status"] == "STAGED"


def _partner_with_a_morning_job():
    """A crew booked 08:00-11:00, so its effective occupation ends at 13:00."""
    revision = setup_released_revision("T900")
    booked = setup_staged_order(revision_ctx=revision, quantity=1,
                                facility_overrides={"account_name": "Harbourview Gym",
                                                    "freight_zone": "Z1"})
    partner = new_service_partner(name="Meridian Service Co",
                                  certified_categories=["CARDIO"])
    existing = new_install_job(booked["order"]["id"], partner["id"],
                              "2026-09-10T08:00:00Z", "2026-09-10T11:00:00Z",
                              estimated_labor_hours=1.5)
    waiting = setup_staged_order(revision_ctx=revision, quantity=1,
                                facility_overrides={"account_name": "Lakeside Gym",
                                                    "freight_zone": "Z1"})
    return {"partner": partner, "existing": existing, "waiting": waiting}


def test_a_job_starting_at_the_buffered_end_is_accepted_but_earlier_starts_are_not(
    api, order_planner_headers
):
    """Eleven and twelve o'clock collide; thirteen hundred exactly does not.

    The PRD states that "Every job carries `travel_buffer_minutes`, a system-set
    field fixed at 120 minutes — two hours of drive time — appended after
    `window_end`" and that "A new job that starts exactly at an existing job's
    effective end is therefore accepted: touching endpoints do not collide".

    Design: Difficulty/resource_temporal_overlap/install_job_travel_buffer_half_open_exclusive_boundary
    """
    ctx = _partner_with_a_morning_job()
    waiting_order = ctx["waiting"]["order"]

    for start, end in (("2026-09-10T11:00:00Z", "2026-09-10T13:00:00Z"),
                       ("2026-09-10T12:00:00Z", "2026-09-10T14:00:00Z")):
        validate_error(
            api.create_install_job(
                install_job_payload(waiting_order["id"], ctx["partner"]["id"],
                                    start, end, estimated_labor_hours=1.5),
                order_planner_headers,
            ),
            "ERR_INSTALL_WINDOW_CONFLICT", 409,
        )

    response = api.create_install_job(
        install_job_payload(waiting_order["id"], ctx["partner"]["id"],
                            "2026-09-10T13:00:00Z", "2026-09-10T15:00:00Z",
                            estimated_labor_hours=1.5),
        order_planner_headers,
    )

    job = validate_success(response, 201)
    assert job["status"] == "SCHEDULED"
    assert job["travel_buffer_minutes"] == 120
    assert job["window_start"] == "2026-09-10T13:00:00Z"
    assert job["actual_labor_hours"] is None
    assert job["punch_list_open_count"] == 0
    assert job["completed_at"] is None
    existing = read_install_job(ctx["existing"]["id"])
    assert existing["status"] == "SCHEDULED"
    assert existing["window_end"] == "2026-09-10T11:00:00Z"
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 3.0
    assert partner["coverage_status"] == "ACTIVE"
    _, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers,
                              params={"service_partner_id": ctx["partner"]["id"]})
    )
    assert meta["total_count"] == 2


def test_an_earlier_job_may_end_its_buffer_exactly_where_the_booked_job_starts(
    api, order_planner_headers
):
    """The buffer is applied to the requested job too, on the other side.

    The PRD states that the buffer forms "the job's effective occupation" and that
    the requested job conflicts "when the requested start falls strictly before
    that job's effective end" and that job's start "falls strictly before the
    requested effective end."

    Design: Difficulty/resource_temporal_overlap/install_job_travel_buffer_half_open_exclusive_boundary
    """
    ctx = _partner_with_a_morning_job()
    waiting_order = ctx["waiting"]["order"]

    validate_error(
        api.create_install_job(
            install_job_payload(waiting_order["id"], ctx["partner"]["id"],
                                "2026-09-10T05:00:00Z", "2026-09-10T07:00:00Z",
                                estimated_labor_hours=1.5),
            order_planner_headers,
        ),
        "ERR_INSTALL_WINDOW_CONFLICT", 409,
    )

    response = api.create_install_job(
        install_job_payload(waiting_order["id"], ctx["partner"]["id"],
                            "2026-09-10T04:00:00Z", "2026-09-10T06:00:00Z",
                            estimated_labor_hours=1.5),
        order_planner_headers,
    )

    job = validate_success(response, 201)
    assert job["status"] == "SCHEDULED"
    assert job["window_end"] == "2026-09-10T06:00:00Z"
    assert job["travel_buffer_minutes"] == 120
    assert read_install_job(ctx["existing"]["id"])["status"] == "SCHEDULED"
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 3.0


def test_only_one_install_job_may_be_open_on_an_order_at_a_time(
    api, order_planner_headers
):
    """A free calendar does not help while the order already has an open job.

    The PRD states that "the order must have no other install job in `SCHEDULED`,
    `ON_SITE` or `PUNCH_LIST` (`ERR_INSTALL_JOB_ALREADY_OPEN`)".

    Design: Corner/validations/only_one_open_install_job_per_order_at_a_time
    """
    ctx = setup_staged_order(preset="T900", quantity=1,
                             partner_overrides={"name": "Meridian Service Co"})
    first = new_install_job(ctx["order"]["id"], ctx["partner"]["id"],
                           "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z",
                           estimated_labor_hours=3.0)
    second_window = ("2026-09-11T08:00:00Z", "2026-09-11T12:00:00Z")

    validate_error(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], ctx["partner"]["id"],
                                *second_window, estimated_labor_hours=3.0),
            order_planner_headers,
        ),
        "ERR_INSTALL_JOB_ALREADY_OPEN", 409,
    )

    aborted = validate_success(
        api.abort_install_job(first["id"],
                              abort_install_payload(
                                  abort_reason="crew reassigned to a storm callout"),
                              order_planner_headers)
    )
    assert aborted["status"] == "ABORTED"

    replacement = validate_success(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], ctx["partner"]["id"],
                                *second_window, estimated_labor_hours=3.0),
            order_planner_headers,
        ),
        201,
    )

    assert replacement["status"] == "SCHEDULED"
    jobs, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers,
                              params={"order_id": ctx["order"]["id"]})
    )
    assert meta["total_count"] == 2
    assert sorted(job["status"] for job in jobs) == ["ABORTED", "SCHEDULED"]
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "STAGED"
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 3.0


def test_blackout_weekdays_bind_only_the_facility_that_configured_them(
    api, order_planner_headers
):
    """The identical Saturday window is refused at one facility and booked at another.

    The PRD states that a facility carries "an optional `install_blackout_weekdays`
    list, which defaults to empty and draws without repetition from `MON`, `TUE`,
    `WED`, `THU`, `FRI`, `SAT` and `SUN`."

    Design: Corner/validations/install_blackout_weekdays_apply_only_to_the_configured_facility
    """
    revision = setup_released_revision("T900")
    blacked_out = setup_staged_order(
        revision_ctx=revision, quantity=1,
        facility_overrides={"account_name": "Sabbath Rest Athletic Club",
                            "freight_zone": "Z1",
                            "install_blackout_weekdays": WEEKEND_BLACKOUT},
    )
    open_calendar = setup_staged_order(
        revision_ctx=revision, quantity=1,
        facility_overrides={"account_name": "Open Calendar Gym", "freight_zone": "Z1"},
    )
    first_partner = new_service_partner(name="Meridian Service Co",
                                        certified_categories=["CARDIO"])
    second_partner = new_service_partner(name="Northwind Service Co",
                                         certified_categories=["CARDIO"])

    validate_error(
        api.create_install_job(
            install_job_payload(blacked_out["order"]["id"], first_partner["id"],
                                *SATURDAY_MORNING, estimated_labor_hours=1.5),
            order_planner_headers,
        ),
        "ERR_INSTALL_BLACKOUT_DAY", 422,
    )
    accepted = validate_success(
        api.create_install_job(
            install_job_payload(open_calendar["order"]["id"], second_partner["id"],
                                *SATURDAY_MORNING, estimated_labor_hours=1.5),
            order_planner_headers,
        ),
        201,
    )

    assert accepted["status"] == "SCHEDULED"
    _, meta = validate_paginated(
        api.list_install_jobs(order_planner_headers,
                              params={"order_id": blacked_out["order"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_service_partner(first_partner["id"])["committed_hours"] == 0.0
    assert read_service_partner(second_partner["id"])["committed_hours"] == 1.5
    assert read_facility(blacked_out["facility"]["id"])[
        "install_blackout_weekdays"
    ] == WEEKEND_BLACKOUT
    assert read_facility(open_calendar["facility"]["id"])[
        "install_blackout_weekdays"
    ] == []


def test_the_crew_must_be_certified_for_every_category_on_the_order(
    api, order_planner_headers
):
    """A cardio-only crew cannot install a strength order; a dual crew can.

    The PRD states that "the partner's `certified_categories` must cover every
    equipment category present on the order
    (`ERR_PARTNER_NOT_CERTIFIED_FOR_CATEGORY`)".

    Design: Corner/validations/install_partner_must_be_certified_for_every_ordered_category
    """
    ctx = setup_staged_order(preset="S500", quantity=1,
                             facility_overrides={"account_name": "Ironworks Institute",
                                                 "freight_zone": "Z1"})
    assert read_order(ctx["order"]["id"])["quoted_total_cents"] == 443_846
    cardio_only = new_service_partner(name="Cardio Only Service Co",
                                      certified_categories=["CARDIO"])
    dual = new_service_partner(name="Full Coverage Service Co",
                               certified_categories=["CARDIO", "STRENGTH"])
    window = ("2026-09-10T08:00:00Z", "2026-09-10T13:00:00Z")

    validate_error(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], cardio_only["id"], *window,
                                estimated_labor_hours=2.5),
            order_planner_headers,
        ),
        "ERR_PARTNER_NOT_CERTIFIED_FOR_CATEGORY", 422,
    )
    job = validate_success(
        api.create_install_job(
            install_job_payload(ctx["order"]["id"], dual["id"], *window,
                                estimated_labor_hours=2.5),
            order_planner_headers,
        ),
        201,
    )

    assert job["status"] == "SCHEDULED"
    assert read_service_partner(cardio_only["id"])["committed_hours"] == 0.0
    assert read_service_partner(dual["id"])["committed_hours"] == 2.5
    assert read_order(ctx["order"]["id"])["fulfillment_status"] == "STAGED"
