"""Booking capacity, interval semantics, rescheduling, check-in and cancellation."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_appointment,
    assert_same_instant,
    check_in_payload,
    create_appointment_payload,
    make_applicant_headers,
    new_appointment,
    new_applicant,
    set_clock,
    setup_registry,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]

WINDOW_START = "2026-06-01T10:00:00Z"


def _site_with_four_overlapping_bookings(capacity=5):
    world = setup_registry(clock_start="2026-06-01T08:00:00Z", with_device=False,
                           site_overrides={"concurrent_capacity": capacity})
    applicant = new_applicant(full_name="Kim Ruiz")
    world["applicant"] = applicant
    for _ in range(4):
        new_appointment(applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START)
    return world


def test_walkin_channel_is_capped_one_slot_below_the_floor(api):
    """PRD 3.2: "From that capacity a second ceiling is derived at creation for every site of either
    kind: `walkin_usable_capacity` is `concurrent_capacity` reduced by twenty percent of
    `concurrent_capacity` rounded **up** to a whole number. A site with a capacity of 5 therefore
    reserves 1 slot and admits 4 walk-ins; a site with a capacity of 10 reserves 2 and admits 8; a
    site with a capacity of 1 reserves 1 and admits none."
    PRD 3.3: "If the candidate's `booking_channel` is `BOOKED`, that count plus one must not exceed
    the site's `concurrent_capacity`; if it is `WALK_IN`, that count plus one must not exceed the
    site's `walkin_usable_capacity`. Either violation is `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/walkin_reserve_boundary_at_four_while_booked_still_fits_five
    """
    world = _site_with_four_overlapping_bookings()
    assert world["site"]["walkin_usable_capacity"] == 4

    response = api.create_appointment(
        create_appointment_payload(
            world["applicant"]["id"],
            world["site"]["id"],
            world["service_type"]["id"],
            WINDOW_START,
            booking_channel="WALK_IN",
        ),
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)

    _rows, meta = validate_paginated(api.list_appointments(TECH, {"site_id": world["site"]["id"]}))
    assert meta["total_count"] == 4, "the refused walk-in is not persisted"


def test_fifth_booked_interval_still_fits_the_floor(api):
    """PRD 3.3: "Consider a site with a `concurrent_capacity` of 5, and therefore a
    `walkin_usable_capacity` of 4, already carrying four booked thirty-minute appointments across
    10:00 to 10:30. A fifth `BOOKED` appointment in that window is accepted, because five does not
    exceed five; a `WALK_IN` in the same window is refused, because five exceeds four."

    Design: Difficulty/boundary_precision_check/walkin_reserve_boundary_at_four_while_booked_still_fits_five
    """
    world = _site_with_four_overlapping_bookings()

    fifth = validate_success(
        api.create_appointment(
            create_appointment_payload(
                world["applicant"]["id"],
                world["site"]["id"],
                world["service_type"]["id"],
                WINDOW_START,
                booking_channel="BOOKED",
            ),
            TECH,
        ),
        201,
    )

    assert_appointment(fifth)
    assert fifth["status"] == "BOOKED"
    assert_same_instant(fifth["scheduled_end"], "2026-06-01T10:30:00Z", "scheduled_end")

    _rows, meta = validate_paginated(api.list_appointments(TECH, {"site_id": world["site"]["id"]}))
    assert meta["total_count"] == 5


def test_appointment_beginning_where_another_ends_does_not_overlap(api):
    """PRD 3.3: "The server derives `scheduled_end` by adding the service type's
    `slot_duration_minutes` to `scheduled_start`, and every appointment interval is treated as
    half-open — it includes its start instant and excludes its end instant, so an appointment ending
    at 10:30 and one beginning at 10:30 do not overlap and adjacency is free."

    Design: Difficulty/resource_temporal_overlap/appointment_intervals_are_half_open_so_adjacency_is_free
    """
    world = setup_registry(
        clock_start="2026-06-01T08:00:00Z",
        with_device=False,
        site_overrides={"name": "Single Chair", "concurrent_capacity": 1},
    )
    applicant = new_applicant(full_name="Pia Sun")
    first = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START
    )

    adjacent = validate_success(
        api.create_appointment(
            create_appointment_payload(
                applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-01T10:30:00Z"
            ),
            TECH,
        ),
        201,
    )

    assert_same_instant(adjacent["scheduled_start"], "2026-06-01T10:30:00Z", "scheduled_start")
    assert_same_instant(first["scheduled_end"], "2026-06-01T10:30:00Z", "first.scheduled_end")


def test_appointment_straddling_two_adjacent_intervals_is_refused(api):
    """PRD 3.3: "count the appointments at that same site, other than the candidate itself, whose
    `status` is `BOOKED`, `CHECKED_IN` or `IN_CAPTURE` and whose interval genuinely overlaps the
    candidate's — that is, whose `scheduled_start` is strictly before the candidate's
    `scheduled_end` and whose `scheduled_end` is strictly after the candidate's `scheduled_start`."

    Design: Difficulty/resource_temporal_overlap/appointment_intervals_are_half_open_so_adjacency_is_free
    """
    world = setup_registry(
        clock_start="2026-06-01T08:00:00Z",
        with_device=False,
        site_overrides={"name": "Single Chair", "concurrent_capacity": 1},
    )
    applicant = new_applicant(full_name="Pia Sun")
    new_appointment(applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START)
    new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-01T10:30:00Z"
    )

    response = api.create_appointment(
        create_appointment_payload(
            applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-01T10:15:00Z"
        ),
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value)

    _rows, meta = validate_paginated(api.list_appointments(TECH, {"site_id": world["site"]["id"]}))
    assert meta["total_count"] == 2


def _late_checkin_world():
    world = setup_registry(
        clock_start="2026-06-01T09:00:00Z",
        with_device=False,
        service_type_overrides={
            "code": "VOL",
            "applicant_type": "VOLUNTEER",
            "slot_duration_minutes": 15,
            "required_document_codes": ["PHOTO_ID", "AGENCY_AUTH_FORM"],
            "accepted_id_document_types": ["DRIVER_LICENSE"],
            "retention_offered": False,
        },
    )
    applicant = new_applicant(
        full_name="Jo Fields", id_document_type="PASSPORT", id_document_expires_on="2033-01-01"
    )
    world["applicant"] = applicant
    world["appointment"] = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START
    )
    set_clock("2026-06-01T10:30:00Z")
    return world


def test_late_checkin_reports_the_window_not_the_document_type(api):
    """PRD 2.9: "The ladder is strictly ordered: the **first** rung whose condition fails determines
    the response, and no later rung is evaluated."
    PRD 2.9 rung 12: "**Check-in window.** The logical clock is at or after the appointment's
    `scheduled_start` minus 30 minutes and at or before its `scheduled_start` plus 10 minutes,
    inclusive at both ends. Otherwise `ERR_CHECKIN_WINDOW_CLOSED`, HTTP 422. Scope:
    `POST /livescan/appointments/{id}/check-in`."
    PRD 2.9 rung 15: "**Identity document type.** The `presented_document_type` is a member of the
    appointment's service type's `accepted_id_document_types`. Otherwise
    `ERR_REQUIRED_DOCUMENT_MISSING`, HTTP 422. Scope: `POST /livescan/appointments/{id}/check-in`."

    Design: Difficulty/priority_pair_validation_conflict/checkin_window_outranks_document_type_mismatch
    """
    world = _late_checkin_world()

    response = api.check_in_appointment(
        world["appointment"]["id"],
        check_in_payload(presented_document_type="PASSPORT", presented_documents=["PHOTO_ID"]),
        TECH,
    )

    error = validate_error(response, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value)
    assert error["error_id"] != ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value


def test_a_refused_late_checkin_writes_nothing_to_the_appointment(api):
    """PRD 3.3: "Check-in is a technician-only operation that moves the appointment
    `BOOKED → CHECKED_IN` and unlocks capture. It is admitted only while the logical clock lies
    between the `scheduled_start` less 30 minutes and the `scheduled_start` plus 10 minutes,
    inclusive at both ends; outside that band it is `ERR_CHECKIN_WINDOW_CLOSED`."
    PRD 3.3: "A successful check-in stamps `checked_in_at` with the logical clock and records both
    `presented_document_type` and `presented_documents`."

    Design: Difficulty/priority_pair_validation_conflict/checkin_window_outranks_document_type_mismatch
    """
    world = _late_checkin_world()

    api.check_in_appointment(
        world["appointment"]["id"],
        check_in_payload(presented_document_type="PASSPORT", presented_documents=["PHOTO_ID"]),
        TECH,
    )

    unchanged = validate_success(api.get_appointment(world["appointment"]["id"], TECH), 200)
    assert unchanged["status"] == "BOOKED"
    assert unchanged["checked_in_at"] is None
    assert unchanged["presented_document_type"] is None


def _document_check_world():
    world = setup_registry(
        clock_start="2026-06-01T09:00:00Z",
        with_device=False,
        service_type_overrides={
            "required_document_codes": ["PHOTO_ID", "AGENCY_AUTH_FORM"],
            "accepted_id_document_types": ["DRIVER_LICENSE"],
        },
    )
    applicant = new_applicant(full_name="Finn Oak", id_document_expires_on="2026-05-31")
    world["applicant"] = applicant
    world["appointment"] = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START
    )
    set_clock("2026-06-01T09:55:00Z")
    return world


def test_identity_document_that_expired_yesterday_blocks_checkin(api):
    """PRD 3.3: "the applicant's `id_document_expires_on` must be on or after the clock date, with a
    document expiring exactly today still valid and an earlier one failing as
    `ERR_IDENTITY_DOCUMENT_EXPIRED`"

    Design: Corner/validations/checkin_rejects_an_expired_document_then_an_incomplete_document_set
    """
    world = _document_check_world()

    response = api.check_in_appointment(
        world["appointment"]["id"],
        check_in_payload(presented_documents=["PHOTO_ID", "AGENCY_AUTH_FORM"]),
        TECH,
    )

    validate_error(response, ApiErrorId.ERR_IDENTITY_DOCUMENT_EXPIRED.value)


def test_presented_set_must_cover_every_required_code(api):
    """PRD 3.3: "and the presented document set must cover every code in the service type's
    `required_document_codes`, failing which the response is again `ERR_REQUIRED_DOCUMENT_MISSING`."
    PRD 3.3: "A successful check-in stamps `checked_in_at` with the logical clock and records both
    `presented_document_type` and `presented_documents`."

    Design: Corner/validations/checkin_rejects_an_expired_document_then_an_incomplete_document_set
    """
    world = _document_check_world()
    validate_success(
        api.patch_applicant(world["applicant"]["id"], {"id_document_expires_on": "2026-06-01"}, TECH), 200
    )

    incomplete = api.check_in_appointment(
        world["appointment"]["id"], check_in_payload(presented_documents=["PHOTO_ID"]), TECH
    )
    validate_error(incomplete, ApiErrorId.ERR_REQUIRED_DOCUMENT_MISSING.value)

    accepted = validate_success(
        api.check_in_appointment(
            world["appointment"]["id"],
            check_in_payload(presented_documents=["PHOTO_ID", "AGENCY_AUTH_FORM"]),
            TECH,
        ),
        200,
    )
    assert accepted["status"] == "CHECKED_IN", "a document expiring exactly today is still valid"
    assert accepted["presented_documents"] == ["PHOTO_ID", "AGENCY_AUTH_FORM"]
    assert_same_instant(accepted["checked_in_at"], "2026-06-01T09:55:00Z", "checked_in_at")


def _reschedule_world():
    world = setup_registry(clock_start="2026-06-01T09:00:00Z", with_device=False)
    applicant = new_applicant(full_name="Gus Reed")
    world["applicant"] = applicant
    world["applicant_headers"] = make_applicant_headers(applicant["id"])
    world["appointment"] = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-10T10:00:00Z"
    )
    world["near_appointment"] = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], "2026-06-02T10:00:00Z"
    )
    return world


def test_third_reschedule_exhausts_the_budget(api):
    """PRD 3.3: "It is admitted only while the clock is at or before the appointment's *current*
    `scheduled_start` minus 24 hours, only while `reschedule_count` is below 2, and only when the new
    interval clears the capacity rule for the target site — with the appointment's own current
    interval excluded from the count, so that moving an appointment thirty minutes later does not
    have it collide with itself."
    PRD 3.3: "A third reschedule attempt is `ERR_APPOINTMENT_STATE_INVALID`; an attempt inside the
    final 24 hours is `ERR_RESCHEDULE_WINDOW_CLOSED`."

    Design: Corner/validations/reschedule_is_capped_at_two_and_closes_24_hours_before_start
    """
    world = _reschedule_world()
    headers = world["applicant_headers"]

    first = validate_success(
        api.reschedule_appointment(world["appointment"]["id"], "2026-06-11T10:00:00Z", headers), 200
    )
    assert first["reschedule_count"] == 1

    second = validate_success(
        api.reschedule_appointment(world["appointment"]["id"], "2026-06-12T10:00:00Z", headers), 200
    )
    assert second["reschedule_count"] == 2

    third = api.reschedule_appointment(world["appointment"]["id"], "2026-06-13T10:00:00Z", headers)
    validate_error(third, ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value)

    unchanged = validate_success(api.get_appointment(world["appointment"]["id"], TECH), 200)
    assert_same_instant(unchanged["scheduled_start"], "2026-06-12T10:00:00Z", "scheduled_start")


def test_reschedule_inside_the_final_day_is_refused_on_the_window(api):
    """PRD 2.9 rung 13: "**Reschedule window.** The logical clock is at or before the appointment's
    current `scheduled_start` minus 24 hours. Otherwise `ERR_RESCHEDULE_WINDOW_CLOSED`, HTTP 422.
    Scope: `POST /livescan/appointments/{id}/reschedule`."

    Design: Corner/validations/reschedule_is_capped_at_two_and_closes_24_hours_before_start
    """
    world = _reschedule_world()
    set_clock("2026-06-01T11:00:00Z")

    response = api.reschedule_appointment(
        world["near_appointment"]["id"], "2026-06-05T10:00:00Z", world["applicant_headers"]
    )

    validate_error(response, ApiErrorId.ERR_RESCHEDULE_WINDOW_CLOSED.value)

    unchanged = validate_success(api.get_appointment(world["near_appointment"]["id"], TECH), 200)
    assert unchanged["reschedule_count"] == 0
    assert_same_instant(unchanged["scheduled_start"], "2026-06-02T10:00:00Z", "scheduled_start")


def test_cancelling_a_cancelled_appointment_is_a_state_violation(api):
    """PRD 2.9 rung 10: "**State precondition.** The target resource is in a state from which the
    requested transition is declared. An appointment in the wrong state raises
    `ERR_APPOINTMENT_STATE_INVALID`; a fingerprint card in the wrong state raises
    `ERR_CARD_STATE_INVALID`, and that includes any write attempted against a `SUPERSEDED` card"
    PRD 3.3: "Both legs release the interval back to the site's capacity pool, and — stated
    explicitly because the parallel branch does bill — **cancellation creates no fee assessment of
    any kind**."

    Design: Corner/state_machines/second_cancel_on_cancelled_appointment_is_rejected
    """
    world = setup_registry(clock_start="2026-06-01T08:00:00Z", with_device=False)
    applicant = new_applicant(full_name="Vic Hale")
    appointment = new_appointment(
        applicant["id"], world["site"]["id"], world["service_type"]["id"], WINDOW_START
    )
    headers = make_applicant_headers(applicant["id"])

    cancelled = validate_success(api.cancel_appointment(appointment["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED"

    response = api.cancel_appointment(appointment["id"], headers)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_STATE_INVALID.value)

    still_cancelled = validate_success(api.get_appointment(appointment["id"], TECH), 200)
    assert still_cancelled["status"] == "CANCELLED"

    _rows, meta = validate_paginated(
        api.list_fee_assessments(VA, {"appointment_id": appointment["id"]})
    )
    assert meta["total_count"] == 0
