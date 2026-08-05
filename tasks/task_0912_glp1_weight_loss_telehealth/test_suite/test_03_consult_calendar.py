"""Booking, closing and rescheduling the telehealth consult."""

from test_helpers import (
    assert_consult,
    assert_same_instant,
    book_consult,
    close_consult,
    create_consult_payload,
    enroll_patient,
    make_patient_headers,
    make_provider_headers,
    platform_admin_headers,
    register_clinician,
    set_clock,
    setup_eligible_member,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_consult_starting_fifteen_minutes_after_the_previous_end_is_accepted(api):
    """PRD §3.3: "A collision exists when the new consult's `scheduled_start_at`
    falls earlier than the other consult's `scheduled_end_at` plus fifteen
    minutes, *and* the other consult's `scheduled_start_at` falls earlier than the
    new consult's `scheduled_end_at` plus fifteen minutes."
    PRD §3.3: "Both conditions must hold for a collision; if either fails there is
    no collision."

    Design: Difficulty/resource_temporal_overlap/consult_fifteen_minute_buffer_on_provider_calendar
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician(full_name="Dr Nia Cole")
    member = enroll_patient(email="zed@example.com", full_name="Zed Marek")
    book_consult(
        member["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )

    response = api.create_consult(
        create_consult_payload(
            member["id"],
            clinician["id"],
            scheduled_start_at="2026-06-03T15:45:00Z",
            scheduled_end_at="2026-06-03T16:15:00Z",
        ),
        make_patient_headers(member["id"]),
    )
    second = validate_success(response, 201)

    assert_consult(second)
    assert second["status"] == "SCHEDULED", (
        "15:45 is exactly fifteen minutes after the 15:30 end, so no collision exists"
    )
    assert second["reschedule_count"] == 0


def test_consult_starting_fourteen_minutes_after_the_previous_end_collides(api):
    """PRD §3.3: "A collision is rejected with `ERR_CONSULT_SLOT_CONFLICT` (409)."
    PRD §3.3: "Because both sides are widened, two consults that merely abut — one
    ending exactly when the next begins — do collide, and so do two separated by
    anything less than the full buffer."

    Design: Difficulty/resource_temporal_overlap/consult_fifteen_minute_buffer_on_provider_calendar
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician(full_name="Dr Nia Cole")
    member = enroll_patient(email="zed2@example.com", full_name="Zed Marek")
    book_consult(
        member["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )
    book_consult(
        member["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:45:00Z",
        scheduled_end_at="2026-06-03T16:15:00Z",
    )

    response = api.create_consult(
        create_consult_payload(
            member["id"],
            clinician["id"],
            scheduled_start_at="2026-06-03T16:29:00Z",
            scheduled_end_at="2026-06-03T16:59:00Z",
        ),
        make_patient_headers(member["id"]),
    )
    validate_error(response, "ERR_CONSULT_SLOT_CONFLICT")

    rows, meta = validate_paginated(
        api.list_consults(platform_admin_headers(), params={"provider_id": clinician["id"]})
    )
    assert meta["total_count"] == 2, "the refused booking must not be written"


def test_no_showed_consult_reschedules_back_to_scheduled(api):
    """PRD §3.3: "A `NO_SHOW` outcome moves it `SCHEDULED → NO_SHOW`."
    PRD §3.3: "Rescheduling moves it `NO_SHOW → SCHEDULED` at a new
    `scheduled_start_at` and `scheduled_end_at`, re-running both the
    clinician-suitability test and the same fifteen-minute buffered overlap test
    against the clinician's other `SCHEDULED` consults, and incrementing
    `reschedule_count` by one."

    Design: Corner/state_machines/consult_no_show_then_reschedule_returns_to_scheduled
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(email="sm2@example.com", full_name="Sm Two")
    clinician = register_clinician()
    consult = book_consult(
        member["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )

    no_showed = validate_success(
        api.complete_consult(
            consult["id"], {"outcome": "NO_SHOW"}, make_provider_headers(clinician["id"])
        )
    )
    assert no_showed["status"] == "NO_SHOW"

    moved = validate_success(
        api.reschedule_consult(
            consult["id"],
            {
                "scheduled_start_at": "2026-06-04T15:00:00Z",
                "scheduled_end_at": "2026-06-04T15:30:00Z",
            },
            make_patient_headers(member["id"]),
        )
    )
    assert_consult(moved)
    assert moved["status"] == "SCHEDULED"
    assert moved["reschedule_count"] == 1
    assert_same_instant(
        moved["scheduled_start_at"], "2026-06-04T15:00:00Z", "scheduled_start_at"
    )


def test_completing_an_already_closed_consult_is_refused(api):
    """PRD §3.3: "A `PRESCRIBE` outcome moves the consult `SCHEDULED →
    COMPLETED_PRESCRIBED` and additionally requires that the member's
    `eligibility_status` currently read `ELIGIBLE`; closing a consult as
    prescribing for a member who is `NOT_SCREENED`, `INELIGIBLE` or `DEFERRED` is
    rejected with `ERR_INVALID_STATE` (409)."
    PRD §2.7: "**State admissibility.** The target row is in a state from which the
    requested transition is declared (`ERR_INVALID_STATE`, 409)"

    Design: Corner/state_machines/consult_complete_twice_returns_invalid_state
    """
    scenario = setup_eligible_member(
        patient={"email": "sm4@example.com", "full_name": "Sm Four"}
    )
    consult = book_consult(
        scenario["patient"]["id"],
        scenario["clinician"]["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )
    close_consult(consult["id"], scenario["clinician"]["id"], "PRESCRIBE")

    response = api.complete_consult(
        consult["id"],
        {"outcome": "DECLINE"},
        make_provider_headers(scenario["clinician"]["id"]),
    )
    validate_error(response, "ERR_INVALID_STATE")

    still = validate_success(api.get_consult(consult["id"], platform_admin_headers()))
    assert still["status"] == "COMPLETED_PRESCRIBED"


def test_unlicensed_clinician_pre_empts_the_calendar_collision(api):
    """PRD §3.3: "Two gates guard the booking, and their order is fixed. First the
    clinician is checked for suitability: the named practitioner must have
    `provider_type` `CLINICIAN`, must have `status` `ACTIVE`, and must list the
    member's `state_code` among their `licensed_state_codes`. A practitioner
    failing any of those three tests is rejected with `ERR_PROVIDER_NOT_ELIGIBLE`
    (422). Only if the clinician is suitable does the calendar test run."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_consult_booking
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician(full_name="Dr Ray Ito", licensed_state_codes=["NY"])
    pia = enroll_patient(email="pia@example.com", full_name="Pia Nolan", state_code="NY")
    quin = enroll_patient(email="quin@example.com", full_name="Quin Ade", state_code="CA")
    book_consult(
        pia["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )

    response = api.create_consult(
        create_consult_payload(
            quin["id"],
            clinician["id"],
            scheduled_start_at="2026-06-03T15:10:00Z",
            scheduled_end_at="2026-06-03T15:40:00Z",
        ),
        make_patient_headers(quin["id"]),
    )

    validate_error(response, "ERR_PROVIDER_NOT_ELIGIBLE")
    assert response.json()["data"]["error_id"] != "ERR_CONSULT_SLOT_CONFLICT", (
        "the licensure gate runs before the calendar gate"
    )


def test_refused_booking_leaves_the_existing_consult_untouched(api):
    """PRD §3.3: "A practitioner failing any of those three tests is rejected with
    `ERR_PROVIDER_NOT_ELIGIBLE` (422)."
    PRD §2.7: "Rules are evaluated in a strict ascending order, and the first rule
    that fails determines the response — no later rule runs, and no partial
    mutation is persisted."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_consult_booking
    """
    set_clock("2026-06-01T00:00:00Z")
    clinician = register_clinician(full_name="Dr Ray Ito", licensed_state_codes=["NY"])
    pia = enroll_patient(email="pia2@example.com", full_name="Pia Nolan", state_code="NY")
    quin = enroll_patient(email="quin2@example.com", full_name="Quin Ade", state_code="CA")
    held = book_consult(
        pia["id"],
        clinician["id"],
        scheduled_start_at="2026-06-03T15:00:00Z",
        scheduled_end_at="2026-06-03T15:30:00Z",
    )

    response = api.create_consult(
        create_consult_payload(
            quin["id"],
            clinician["id"],
            scheduled_start_at="2026-06-03T15:10:00Z",
            scheduled_end_at="2026-06-03T15:40:00Z",
        ),
        make_patient_headers(quin["id"]),
    )
    validate_error(response, "ERR_PROVIDER_NOT_ELIGIBLE")

    untouched = validate_success(api.get_consult(held["id"], platform_admin_headers()))
    assert untouched["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_consults(platform_admin_headers(), params={"provider_id": clinician["id"]})
    )
    assert meta["total_count"] == 1
