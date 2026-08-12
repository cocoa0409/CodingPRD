"""Referral intake and triage, appointment booking and the day in the field."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_referral,
    acquire_study,
    add_stop,
    arrive_stop,
    assert_disposition_partition,
    depart_stop,
    make_clinic_user_headers,
    make_field_tech_headers,
    new_clinic,
    new_mobile_unit,
    new_referral,
    new_route,
    new_technician,
    set_clock,
    setup_mobile_scene,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# --------------------------------------------------------------------------
# The return / resubmit revision loop — difficulty instance
# --------------------------------------------------------------------------
def _referral_without_history(api):
    set_clock("2026-05-04T09:00:00Z")
    clinic = new_clinic("Loopback Vet", "Z7")
    referral = new_referral(
        clinic["id"], patient_name="Ziggy", species="FELINE",
        study_kind="TELERAD", requested_modality="RADIOGRAPHY",
        priority="ROUTINE", clinical_history=None,
    )
    return clinic, referral


def test_a_referral_may_traverse_the_return_and_resubmit_loop_repeatedly(api):
    """PRD §3.2: "**Returning** the referral moves it `SUBMITTED → RETURNED` and
    records a `return_reason` supplied in the body."
    PRD §3.2: "The clinic answers by resubmitting: that action is available to the
    `ClinicUser` whose `X-User-ID` matches the referral's `clinic_id`, requires the
    referral to be in `RETURNED`, carries a `clinical_history` value that
    **overwrites** whatever was there before, and clears `return_reason` back to null
    as it moves the referral `RETURNED → SUBMITTED`."
    PRD §3.2: "This is a genuine cycle with no cap: a referral may be returned and
    resubmitted any number of times."

    Design: Difficulty/non_linear_state_machine/referral_return_resubmit_revision_loop_twice
    """
    clinic, referral = _referral_without_history(api)
    clinic_headers = make_clinic_user_headers(clinic["id"])

    returned_once = validate_success(
        api.return_referral(referral["id"], {"return_reason": "clinical history missing"}, SCHED)
    )
    assert returned_once["status"] == "RETURNED"

    resubmitted_once = validate_success(
        api.resubmit_referral(referral["id"], {"clinical_history": "vomiting for two days"},
                              clinic_headers)
    )
    assert resubmitted_once["status"] == "SUBMITTED"

    returned_twice = validate_success(
        api.return_referral(referral["id"], {"return_reason": "need prior imaging dates"}, SCHED)
    )
    assert returned_twice["status"] == "RETURNED"

    resubmitted_twice = validate_success(
        api.resubmit_referral(
            referral["id"],
            {"clinical_history": "vomiting for two days; last radiographs 2026-01-14"},
            clinic_headers,
        )
    )
    assert resubmitted_twice["status"] == "SUBMITTED"


def test_only_the_last_resubmitted_history_survives_and_the_return_reason_is_cleared(api):
    """PRD §3.2: "carries a `clinical_history` value that **overwrites** whatever was
    there before, and clears `return_reason` back to null as it moves the referral
    `RETURNED → SUBMITTED`."
    PRD §3.2: "**Accepting** moves the referral `SUBMITTED → ACCEPTED`, and requires
    two things beyond the from-state: the referral's `clinical_history` must not be
    null, and the referring clinic's `status` must be `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/referral_return_resubmit_revision_loop_twice
    """
    clinic, referral = _referral_without_history(api)
    clinic_headers = make_clinic_user_headers(clinic["id"])

    validate_success(api.return_referral(referral["id"], {"return_reason": "clinical history missing"}, SCHED))
    validate_success(api.resubmit_referral(referral["id"], {"clinical_history": "vomiting for two days"},
                                           clinic_headers))
    validate_success(api.return_referral(referral["id"], {"return_reason": "need prior imaging dates"}, SCHED))
    validate_success(
        api.resubmit_referral(
            referral["id"],
            {"clinical_history": "vomiting for two days; last radiographs 2026-01-14"},
            clinic_headers,
        )
    )
    accept_referral(referral["id"])

    final = validate_success(api.get_referral(referral["id"], SCHED))
    assert final["status"] == "ACCEPTED"
    assert final["clinical_history"] == "vomiting for two days; last radiographs 2026-01-14"
    assert final["return_reason"] is None


def test_returning_a_referral_appends_no_notification_at_all(api):
    """PRD §3.2: "A return is a request for more information, not a rejection, and —
    unlike almost every other clinic-visible event in this system — **no notification
    row is appended for a return**."
    PRD §3.9: "Returning a referral to the clinic for more information appends **no**
    notification at all."

    Design: Difficulty/non_linear_state_machine/referral_return_resubmit_revision_loop_twice
    """
    clinic, referral = _referral_without_history(api)

    validate_success(api.return_referral(referral["id"], {"return_reason": "clinical history missing"}, SCHED))

    rows, _meta = validate_paginated(
        api.list_notifications(SCHED, params={"clinic_id": clinic["id"]})
    )
    assert rows == []


# --------------------------------------------------------------------------
# Appointment shape must match the referral's pipeline — rung 14
# --------------------------------------------------------------------------
def test_a_mobile_referral_booked_without_a_route_stop_is_refused(api):
    """PRD §3.4: "Rung 14 enforces the shape: a mobile referral without a
    `route_stop_id` is refused with `ERR_MOBILE_REQUIRES_ROUTE_STOP`, and a telerad
    referral that supplies one is refused with `ERR_TELERAD_HAS_NO_ROUTE_STOP`."

    Design: Corner/validations/mobile_referral_scheduled_without_a_route_stop_returns_error
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("Shapecheck Vet", "VB")
    referral = new_referral(clinic["id"], patient_name="Rue", study_kind="MOBILE")
    accept_referral(referral["id"])

    response = api.create_appointment({"referral_id": referral["id"]}, SCHED)

    validate_error(response, ApiErrorId.ERR_MOBILE_REQUIRES_ROUTE_STOP.value)
    assert validate_success(api.get_referral(referral["id"], SCHED))["status"] == "ACCEPTED"
    rows, _ = validate_paginated(api.list_appointments(SCHED, params={"referral_id": referral["id"]}))
    assert rows == []


# --------------------------------------------------------------------------
# Arrival and departure bubble through the appointment axis
# --------------------------------------------------------------------------
def test_arrival_and_departure_bubble_the_appointment_through_its_status_axis(api):
    """PRD §3.4: "Arriving at a stop moves it `EN_ROUTE → ARRIVED`, requires the owning
    route to be `DISPATCHED` and the acting technician to be that route's
    `technician_id`, stamps `arrived_at` with the logical clock, and fans out to move
    every appointment on that stop whose `status` is `SCHEDULED` to `IN_PROGRESS`."
    PRD §3.4: "Departure fans out to move every appointment on the stop whose `status`
    is `IN_PROGRESS` to `COMPLETED`, and it refreshes the owning route's
    `actual_occupied_minutes`."

    Design: Corner/state_machines/study_acquire_and_stop_arrival_cascade_through_appointment_status
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Bubble Vet", address_zone="ZB", unit_name="Van B",
        equipment_serial="US-B", technician_name="Mira Cole",
        body_regions=("ABDOMEN", "THORAX"), arrive=False,
    )
    first_study, second_study = scene["studies"]
    technician_id = scene["technician"]["id"]
    assert validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))["status"] == "SCHEDULED"

    set_clock("2026-05-04T09:00:00Z")
    arrive_stop(scene["stop"]["id"], technician_id)
    assert validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))["status"] == "IN_PROGRESS"

    acquire_study(first_study["id"], scene["equipment"]["id"], technician_id, image_count=7)
    validate_success(
        api.not_performed_study(second_study["id"], {"cancel_reason": "patient too fractious"},
                                make_field_tech_headers(technician_id))
    )
    set_clock("2026-05-04T09:35:00Z")
    depart_stop(scene["stop"]["id"], technician_id)

    assert validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))["status"] == "COMPLETED"
    assert validate_success(api.get_route_stop(scene["stop"]["id"], SCHED))["actual_service_minutes"] == 35


def test_the_appointments_four_disposition_counters_partition_its_total(api):
    """PRD §3.4: "`ordered_studies_count` is the total number of studies carrying this
    `appointment_id`, with no status filter at all — cascade-created replacement
    studies included. `pending_studies_count` counts those whose `workflow_status` is
    `ORDERED` or `REPEAT_PENDING`. `acquired_studies_count` counts those in
    `ACQUIRED`, `ASSIGNED`, `READ_IN_PROGRESS`, `PRELIM_REPORTED` or `FINALIZED`.
    `cancelled_studies_count` counts those in `CANCELLED`. `not_performed_studies_count`
    counts those in `NOT_PERFORMED`."
    PRD §3.5: "**Not performed.** A `FieldTech` may record that an ordered study could
    not be performed at all, supplying a `cancel_reason`. This moves the study
    `ORDERED → NOT_PERFORMED`, sets `billing_status` to `NON_BILLABLE`, recomputes the
    trip shares of the remaining billable siblings at the same stop, and refreshes the
    appointment's disposition counters."

    Derivation: two studies under one appointment — one acquired, one recorded
    not-performed — give ordered 2 = pending 0 + acquired 1 + cancelled 0 +
    not-performed 1.

    Design: Corner/state_machines/study_acquire_and_stop_arrival_cascade_through_appointment_status
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="Bubble Vet", address_zone="ZB", unit_name="Van B",
        equipment_serial="US-B", technician_name="Mira Cole",
        body_regions=("ABDOMEN", "THORAX"), arrive=False,
    )
    first_study, second_study = scene["studies"]
    technician_id = scene["technician"]["id"]

    set_clock("2026-05-04T09:00:00Z")
    arrive_stop(scene["stop"]["id"], technician_id)
    acquire_study(first_study["id"], scene["equipment"]["id"], technician_id, image_count=7)
    validate_success(
        api.not_performed_study(second_study["id"], {"cancel_reason": "patient too fractious"},
                                make_field_tech_headers(technician_id))
    )

    appointment = validate_success(api.get_appointment(scene["appointment"]["id"], SCHED))
    assert appointment["ordered_studies_count"] == 2
    assert appointment["pending_studies_count"] == 0
    assert appointment["acquired_studies_count"] == 1
    assert appointment["cancelled_studies_count"] == 0
    assert appointment["not_performed_studies_count"] == 1
    assert_disposition_partition(appointment)

    marked = validate_success(api.get_study(second_study["id"], SCHED))
    assert marked["workflow_status"] == "NOT_PERFORMED"
    assert marked["billing_status"] == "NON_BILLABLE"
    assert marked["cancellation_fee_cents"] == 0


# --------------------------------------------------------------------------
# Three entities reject the same shape of mistake with three different codes
# --------------------------------------------------------------------------
def test_dispatching_a_draft_route_reports_the_route_state_code(api):
    """PRD §3.3: "Dispatching takes it `PUBLISHED → DISPATCHED`; it is the
    `FieldTech`'s action, requires the acting technician to be the route's own
    `technician_id` and to be `ACTIVE`, requires the van to be `IN_SERVICE` (gate G3),
    stamps `dispatched_at`, and fans out to move **every** `PLANNED` stop on the route
    to `EN_ROUTE`."
    PRD §2.8 rung 17: "A route in a from-state that does not admit the transition raises
    `ERR_ROUTE_INVALID_STATE` (409)"

    Design: Corner/errors/workflow_state_precondition_sweep_across_route_referral_and_appointment
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("State Sweep Vet", "S1")
    unit = new_mobile_unit("Van S")
    technician = new_technician("T S1", ["ULTRASOUND"])
    route = new_route(unit["id"], technician["id"])
    add_stop(route["id"], clinic["id"], planned_arrival_minute=540,
             service_minutes=45, drive_minutes_from_prev=20)

    response = api.dispatch_route(route["id"], make_field_tech_headers(technician["id"]))

    validate_error(response, ApiErrorId.ERR_ROUTE_INVALID_STATE.value)
    assert validate_success(api.get_route(route["id"], SCHED))["status"] == "DRAFT"


def test_resubmitting_a_referral_that_was_never_returned_reports_the_referral_state_code(api):
    """PRD §3.2: "The clinic answers by resubmitting: that action is available to the
    `ClinicUser` whose `X-User-ID` matches the referral's `clinic_id`, requires the
    referral to be in `RETURNED`, carries a `clinical_history` value that
    **overwrites** whatever was there before, and clears `return_reason` back to null
    as it moves the referral `RETURNED → SUBMITTED`."
    PRD §2.8 rung 18: "`ERR_REFERRAL_INVALID_STATE` (409) and
    `ERR_APPOINTMENT_INVALID_STATE` (409). Applies to `POST
    /referrals/{referral_id}/accept`, `/reject`, `/return` and `/resubmit`, to `POST
    /appointments`, and to `POST /appointments/{appointment_id}/cancel` and
    `/no-show`."

    Design: Corner/errors/workflow_state_precondition_sweep_across_route_referral_and_appointment
    """
    set_clock("2026-05-04T08:00:00Z")
    clinic = new_clinic("State Sweep Vet", "S1")
    referral = new_referral(clinic["id"], patient_name="Sunny", study_kind="TELERAD")

    response = api.resubmit_referral(
        referral["id"], {"clinical_history": "extra detail"},
        make_clinic_user_headers(clinic["id"]),
    )

    validate_error(response, ApiErrorId.ERR_REFERRAL_INVALID_STATE.value)
    assert validate_success(api.get_referral(referral["id"], SCHED))["status"] == "SUBMITTED"


def test_no_showing_an_already_cancelled_appointment_reports_the_appointment_state_code(api):
    """PRD §3.4: "Two preconditions are stated for it: the appointment's `status` must
    be `SCHEDULED`, and the appointment's route stop must be in `ARRIVED`."
    PRD §2.8 rung 18: "`ERR_REFERRAL_INVALID_STATE` (409) and
    `ERR_APPOINTMENT_INVALID_STATE` (409). Applies to `POST
    /referrals/{referral_id}/accept`, `/reject`, `/return` and `/resubmit`, to `POST
    /appointments`, and to `POST /appointments/{appointment_id}/cancel` and
    `/no-show`."

    The stop is deliberately driven to `ARRIVED` first and the appointment is then
    cancelled by its own clinic from `IN_PROGRESS`, so the only precondition still
    failing at the moment of the no-show is the appointment's own status.  The
    appointment carries no studies, so no cancellation-fee arithmetic is involved.

    Design: Corner/errors/workflow_state_precondition_sweep_across_route_referral_and_appointment
    """
    set_clock("2026-05-04T08:00:00Z")
    scene = setup_mobile_scene(
        clinic_name="State Sweep Vet", address_zone="S1", unit_name="Van S",
        equipment_serial="US-S1", technician_name="T S1",
        body_regions=(),
    )
    appointment = scene["appointment"]
    cancelled = validate_success(
        api.cancel_appointment(appointment["id"], {"cancel_reason": "owner withdrew"},
                               make_clinic_user_headers(scene["clinic"]["id"]))
    )
    assert cancelled["status"] == "CANCELLED_BY_CLINIC"
    assert validate_success(api.get_route_stop(scene["stop"]["id"], SCHED))["status"] == "ARRIVED"

    response = api.no_show_appointment(
        appointment["id"], {"cancel_reason": "did not present"},
        make_field_tech_headers(scene["technician"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE.value)
    assert validate_success(api.get_appointment(appointment["id"], SCHED))["status"] == "CANCELLED_BY_CLINIC"
