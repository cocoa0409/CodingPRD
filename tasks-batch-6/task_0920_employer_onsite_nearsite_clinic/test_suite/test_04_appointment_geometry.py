"""Booking geometry: closure dates, operating window, staffing containment,
half-open provider occupation, day capacity, the reschedule cap and the listing."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_appointment,
    assert_same_date,
    assert_same_instant,
    assert_slot_is_thirty_minutes,
    book,
    read_site,
    setup_clinic,
    site_version,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


def test_booking_on_declared_closure_date_rejected():
    """PRD §3.4: "**Site closure** comes first: a `service_date` listed in the site's
    `closure_dates` is refused with `ERR_SITE_CLOSED`."
    PRD §2.6: "**Site not closed.** The appointment's `service_date` does not appear
    in the site's `closure_dates`. Otherwise `ERR_SITE_CLOSED`, HTTP 422. Applies to
    appointment booking and rescheduling."

    Design: Corner/validations/booking_on_a_declared_closure_date_rejected
    """
    world = setup_clinic(
        employer={"legal_name": "Closure Co", "employer_code": "CLS"},
        site={"site_name": "CLS Clinic", "closure_dates": ["2026-06-08"]},
        shift=False,
        eligibility={"subscriber_external_id": "S-4701", "member_external_id": "M-4701"},
        participant={"display_name": "Cls Tester"},
    )

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T09:00:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_SITE_CLOSED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_STAFFING_COVERAGE_REQUIRED.value, (
        "rung 16 must fire before the staffing rung even with no shift published"
    )
    assert read_site(world.site_id)["slots_requested_total"] == 0


def test_booking_before_opening_time_rejected_and_at_opening_time_accepted():
    """PRD §3.4: "**The operating window** is closed containment — the appointment's
    start time of day must be at or after the site's `open_time_utc`, its end time of
    day must be at or before the site's `close_time_utc`, and the ISO weekday of
    `service_date` must appear in the site's `operating_weekdays`; a half-hour slot
    that ends exactly at closing time is inside hours, and a violation of either the
    window or the weekday pattern is refused with `ERR_OUTSIDE_OPERATING_HOURS`."

    Design: Corner/validations/booking_outside_the_daily_operating_window_rejected
    """
    world = setup_clinic(
        employer={"legal_name": "Hours Co", "employer_code": "HRS"},
        site={"site_name": "HRS Clinic"},
        shift={"shift_start": "2026-06-08T07:00:00Z", "shift_end": "2026-06-08T17:00:00Z"},
        eligibility={"subscriber_external_id": "S-4801", "member_external_id": "M-4801"},
        participant={"display_name": "Hrs Tester"},
    )
    version = site_version(world.site_id, world.participant_headers)

    early = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T07:30:00Z",
            "expected_site_version": version,
        },
        world.participant_headers,
    )
    validate_error(early, ApiErrorId.ERR_OUTSIDE_OPERATING_HOURS.value, 422)

    on_open = validate_success(
        api_client.create_appointment(
            {
                "participant_id": world.participant_id,
                "site_id": world.site_id,
                "provider_id": world.clinician_id,
                "visit_type": "PRIMARY_CARE",
                "scheduled_start": "2026-06-08T08:00:00Z",
                "expected_site_version": version,
            },
            world.participant_headers,
        ),
        201,
    )
    assert_appointment(on_open)
    assert_same_instant(on_open["scheduled_end"], "2026-06-08T08:30:00Z")


def test_appointment_ending_exactly_at_shift_end_is_covered():
    """PRD §2.10: "**Staffing containment is closed.** An appointment is covered by a
    staffing shift when the shift starts at or before the appointment's start and
    ends at or after the appointment's end; an appointment ending at exactly the
    shift's `shift_end` **is** covered."
    PRD §3.2: "The server derives `staffed_hours` as the elapsed time between the two
    instants expressed in hours and rounded half-up to two decimal places — a shift
    running from eight in the morning to a quarter past four in the afternoon records
    8.25 staffed hours."

    Design: Difficulty/resource_temporal_overlap/staffing_shift_closed_containment_rejects_appointment_ending_after_shift_end
    """
    world = setup_clinic(
        employer={"legal_name": "Coverage Co", "employer_code": "COV"},
        site={"site_name": "COV On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        shift={"shift_start": "2026-06-08T08:00:00Z", "shift_end": "2026-06-08T10:00:00Z"},
        eligibility={"subscriber_external_id": "S-1901", "member_external_id": "M-1901"},
        participant={"display_name": "Cov Tester"},
    )
    assert world.shift["staffed_hours"] == 2.0

    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z"
    )
    assert appointment["status"] == "BOOKED"
    assert_same_instant(appointment["scheduled_end"], "2026-06-08T10:00:00Z")
    assert_slot_is_thirty_minutes(appointment)


def test_appointment_starting_at_shift_end_lacks_staffing_coverage():
    """PRD §3.4: "**Staffing coverage** is also closed containment, but against a
    published shift rather than the site calendar: some `StaffingShift` of the same
    site and the same provider must start at or before `scheduled_start` and end at
    or after `scheduled_end`, with an appointment ending exactly at `shift_end`
    counting as covered; otherwise the request is refused with
    `ERR_STAFFING_COVERAGE_REQUIRED`."

    Design: Difficulty/resource_temporal_overlap/staffing_shift_closed_containment_rejects_appointment_ending_after_shift_end
    """
    world = setup_clinic(
        employer={"legal_name": "Coverage Co", "employer_code": "COV"},
        site={"site_name": "COV On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        shift={"shift_start": "2026-06-08T08:00:00Z", "shift_end": "2026-06-08T10:00:00Z"},
        eligibility={"subscriber_external_id": "S-1901", "member_external_id": "M-1901"},
        participant={"display_name": "Cov Tester"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z")

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T10:00:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    error = validate_error(
        response, ApiErrorId.ERR_STAFFING_COVERAGE_REQUIRED.value, 422
    )
    assert error["error_id"] != ApiErrorId.ERR_PROVIDER_SLOT_CONFLICT.value, (
        "a touching appointment does not collide under the half-open rule"
    )


def test_back_to_back_provider_appointments_do_not_collide():
    """PRD §2.10: "**Provider occupation intervals are half-open.** An appointment
    occupies the interval from its start instant up to but not including its end
    instant. Two of the same provider's appointments collide only when the candidate
    starts strictly before the existing one ends *and* the existing one starts
    strictly before the candidate ends. There is no buffer between appointments: two
    appointments that merely touch, one ending at exactly the instant the next
    begins, do **not** collide."

    Design: Difficulty/resource_temporal_overlap/provider_touching_appointments_do_not_collide_under_half_open_rule
    """
    world = setup_clinic(
        employer={"legal_name": "Overlap Co", "employer_code": "OVL"},
        site={"site_name": "OVL On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1801", "member_external_id": "M-1801"},
        participant={"display_name": "Ovl Tester"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")

    touching = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z"
    )
    assert touching["status"] == "BOOKED"
    assert_same_instant(touching["scheduled_end"], "2026-06-08T10:00:00Z")
    assert read_site(world.site_id)["slots_held_count"] == 2


def test_straddling_appointment_reports_provider_slot_conflict():
    """PRD §3.4: "**Provider occupation**, by contrast, is deliberately half-open.
    The candidate interval runs from `scheduled_start` up to but not including
    `scheduled_end`, and it collides with an existing appointment of the same
    provider standing at `BOOKED`, `CONSUMED` or `NO_SHOW` only when the candidate
    starts strictly before that appointment ends and that appointment starts strictly
    before the candidate ends."
    PRD §2.6: "**Provider not double-booked.** No other appointment of the same
    provider whose `status` is `BOOKED`, `CONSUMED` or `NO_SHOW` overlaps the
    candidate interval under the half-open rule of §2.10. Otherwise
    `ERR_PROVIDER_SLOT_CONFLICT`, HTTP 409."

    Design: Difficulty/resource_temporal_overlap/provider_touching_appointments_do_not_collide_under_half_open_rule
    """
    world = setup_clinic(
        employer={"legal_name": "Overlap Co", "employer_code": "OVL"},
        site={"site_name": "OVL On-Site Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1801", "member_external_id": "M-1801"},
        participant={"display_name": "Ovl Tester"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T09:15:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_PROVIDER_SLOT_CONFLICT.value, 409)
    assert read_site(world.site_id)["slots_held_count"] == 1


def test_booking_that_fills_the_last_slot_of_the_day_succeeds():
    """PRD §3.4: "**Site day capacity** is the fifth test and is a strict-less-than
    comparison taken before the write: count the site's appointments on the same
    `service_date` whose `status` is `BOOKED`, `CONSUMED` or `NO_SHOW` — cancelled
    ones released their slot and are excluded — and the booking is permitted only
    while that count is strictly less than the site's `daily_slot_capacity`. The
    booking that raises the count to exactly the capacity therefore succeeds, and the
    next one is refused with `ERR_SLOT_CAPACITY_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/site_capacity_accepts_the_last_slot_and_rejects_the_next
    """
    world = setup_clinic(
        employer={"legal_name": "Capacity Co", "employer_code": "CAP"},
        site={"site_name": "CAP On-Site Clinic", "daily_slot_capacity": 2},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1501", "member_external_id": "M-1501"},
        participant={"display_name": "Cap Tester"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")

    second = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z"
    )
    assert second["status"] == "BOOKED"

    site = read_site(world.site_id)
    assert site["slots_held_count"] == 2
    assert site["slots_requested_total"] == 2
    contract = validate_success(api_client.get_vendor_contract(world.contract_id, ADMIN))
    assert contract["quota_visits_consumed"] == 2


def test_booking_beyond_daily_slot_capacity_rejected():
    """PRD §3.4: "**Site day capacity** is the fifth test and is a strict-less-than
    comparison taken before the write: count the site's appointments on the same
    `service_date` whose `status` is `BOOKED`, `CONSUMED` or `NO_SHOW` — cancelled
    ones released their slot and are excluded — and the booking is permitted only
    while that count is strictly less than the site's `daily_slot_capacity`. The
    booking that raises the count to exactly the capacity therefore succeeds, and the
    next one is refused with `ERR_SLOT_CAPACITY_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/site_capacity_accepts_the_last_slot_and_rejects_the_next
    """
    world = setup_clinic(
        employer={"legal_name": "Capacity Co", "employer_code": "CAP"},
        site={"site_name": "CAP On-Site Clinic", "daily_slot_capacity": 2},
        contract={"quota_visits_total": 20},
        eligibility={"subscriber_external_id": "S-1501", "member_external_id": "M-1501"},
        participant={"display_name": "Cap Tester"},
    )
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z")
    book(world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:30:00Z")

    response = api_client.create_appointment(
        {
            "participant_id": world.participant_id,
            "site_id": world.site_id,
            "provider_id": world.clinician_id,
            "visit_type": "PRIMARY_CARE",
            "scheduled_start": "2026-06-08T10:00:00Z",
            "expected_site_version": site_version(world.site_id, world.participant_headers),
        },
        world.participant_headers,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXHAUSTED.value, 409)
    assert read_site(world.site_id)["slots_held_count"] == 2


def test_third_reschedule_rejected_at_the_cap():
    """PRD §3.4: "A reschedule is capped at two: `reschedule_count` rises by one on
    each success, and a third attempt is refused with `ERR_RESCHEDULE_LIMIT_REACHED`."
    PRD §3.4: "The appointment stays at `BOOKED` — this is a capped self-loop, not a
    state change — and the entire geometry above is re-evaluated against the new
    interval exactly as at booking, including site closure, operating hours, staffing
    coverage, provider occupation and site day capacity."

    Design: Corner/state_machines/appointment_third_reschedule_rejected_at_cap
    """
    world = setup_clinic(
        employer={"legal_name": "Reschedule Co", "employer_code": "RSC"},
        site={"site_name": "RSC Clinic"},
        eligibility={"subscriber_external_id": "S-3401", "member_external_id": "M-3401"},
        participant={"display_name": "Resched Tester"},
    )
    appointment = book(
        world.participant_id, world.site_id, world.clinician_id, "2026-06-08T09:00:00Z"
    )

    validate_success(
        api_client.reschedule_appointment(
            appointment["id"],
            {"scheduled_start": "2026-06-08T10:00:00Z"},
            world.participant_headers,
        )
    )
    second = validate_success(
        api_client.reschedule_appointment(
            appointment["id"],
            {"scheduled_start": "2026-06-08T11:00:00Z"},
            world.participant_headers,
        )
    )
    assert second["reschedule_count"] == 2

    validate_error(
        api_client.reschedule_appointment(
            appointment["id"],
            {"scheduled_start": "2026-06-08T12:00:00Z"},
            world.participant_headers,
        ),
        ApiErrorId.ERR_RESCHEDULE_LIMIT_REACHED.value,
        409,
    )

    final = validate_success(
        api_client.get_appointment(appointment["id"], world.participant_headers)
    )
    assert final["reschedule_count"] == 2
    assert final["status"] == "BOOKED"
    assert_same_instant(final["scheduled_start"], "2026-06-08T11:00:00Z")


def test_server_derived_appointment_fields_ignore_supplied_values():
    """PRD §3.4: "Appointments are a fixed half hour: the server derives
    `scheduled_end` as `scheduled_start` plus thirty minutes and `service_date` as
    the UTC date part of `scheduled_start`. A new appointment starts at `BOOKED` with
    a `reschedule_count` of 0 and a null `cancellation_reason`."
    PRD §3.4: "The request never names a vendor contract; the server chooses one and
    pins the answer permanently as `quota_contract_id` so it never has to be
    re-derived."
    PRD §3.3: "On success the server copies `tier` from the backing row, stamps
    `enrolled_on` with the clock's date, and starts the participant on both of its
    axes: `enrollment_status` at `ACTIVE` and `authorization_status` at
    `NOT_REQUESTED`."

    Design: Corner/entities/appointment_system_and_computed_fields_input_ignored
    """
    world = setup_clinic(
        employer={"legal_name": "Ignore Co", "employer_code": "IGN"},
        site={"site_name": "IGN Clinic"},
        eligibility={
            "subscriber_external_id": "S-3101",
            "member_external_id": "M-3101",
            "tier": "SPOUSE",
        },
        participant={"display_name": "Ign Tester"},
    )

    appointment = validate_success(
        api_client.create_appointment(
            {
                "participant_id": world.participant_id,
                "site_id": world.site_id,
                "provider_id": world.clinician_id,
                "visit_type": "PRIMARY_CARE",
                "scheduled_start": "2026-06-08T09:00:00Z",
                "expected_site_version": site_version(
                    world.site_id, world.participant_headers
                ),
                "status": "CONSUMED",
                "scheduled_end": "2026-06-08T23:00:00Z",
                "reschedule_count": 7,
            },
            world.participant_headers,
        ),
        201,
    )

    assert appointment["status"] == "BOOKED", "status is server-owned, not client-supplied"
    assert_same_instant(appointment["scheduled_end"], "2026-06-08T09:30:00Z")
    assert_same_date(appointment["service_date"], "2026-06-08")
    assert appointment["reschedule_count"] == 0
    assert appointment["cancellation_reason"] is None
    assert appointment["quota_contract_id"] == world.contract_id
    assert world.participant["tier"] == "SPOUSE"


def test_appointment_listing_combines_filter_limit_and_offset():
    """PRD §3.4: "Appointments can be listed and filtered by `participant_id`, by
    `site_id`, by `provider_id`, by `quota_contract_id`, by `status` and by
    `service_date`, and reading a single appointment shows which vendor contract's
    quota it consumed."
    PRD §2.3: "The `meta` object of a list response carries `limit` (the effective
    page size actually applied), `offset` (the effective skip actually applied),
    `total_count` (the number of records matching the filters before paging) and
    `has_more` (true when records matching the filters remain beyond the current
    page, false otherwise)."

    Design: Corner/cross_cutting_complexity_layers/appointment_list_combines_filter_limit_and_offset
    """
    world = setup_clinic(
        employer={"legal_name": "Page Co", "employer_code": "PGE"},
        site={"site_name": "PGE Clinic", "daily_slot_capacity": 8},
        eligibility={"subscriber_external_id": "S-5601", "member_external_id": "M-5601"},
        participant={"display_name": "Page Tester"},
    )
    for start in ("09:00", "09:30", "10:00"):
        book(
            world.participant_id,
            world.site_id,
            world.clinician_id,
            f"2026-06-08T{start}:00Z",
        )

    first_page, first_meta = validate_paginated(
        api_client.list_appointments(
            world.participant_headers,
            params={"participant_id": world.participant_id, "limit": 2, "offset": 0},
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    second_page, second_meta = validate_paginated(
        api_client.list_appointments(
            world.participant_headers,
            params={"participant_id": world.participant_id, "limit": 2, "offset": 2},
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    cancelled, cancelled_meta = validate_paginated(
        api_client.list_appointments(
            world.participant_headers,
            params={"participant_id": world.participant_id, "status": "CANCELLED"},
        )
    )
    assert cancelled == []
    assert cancelled_meta["total_count"] == 0
    assert cancelled_meta["has_more"] is False

    body = api_client.list_appointments(world.participant_headers).json()
    assert body["response_type"] == "array"
    assert "api_request_id" in body["meta"]
