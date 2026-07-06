"""In-home design & measure visit: booking, designer slot geometry, completion.

Queue A (difficulty): resource_temporal_overlap / designer_appointment_overlap_within_buffer.
Queue B (corner): validations + state_machines instances around appointments.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_designer_headers,
    create_customer_payload, create_designer_payload, create_project_payload,
    create_design_appointment_payload,
    create_project, create_customer, create_designer,
    setup_designer_with_appointment, setup_design_complete_project,
)

PA = TEST_USERS["platform_admin_headers"]
IC = TEST_USERS["install_coordinator_headers"]


def test_appointment_within_60min_buffer_rejected(api):
    """PRD §3.2: "The requested window must neither overlap any such appointment
    nor fall within a 60-minute (one-hour) buffer of one — there must be a gap of
    at least 60 minutes on either side between the new visit and every existing
    scheduled visit for that designer. A violation is rejected with
    ERR_DESIGNER_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/designer_appointment_overlap_within_buffer
    """
    ctx = setup_designer_with_appointment(api)  # appt1 14:00-15:00 on the designer
    resp = api.create_design_appointment(
        create_design_appointment_payload(
            ctx["proj2"]["id"], ctx["designer"]["id"],
            scheduled_start="2026-05-10T15:30:00Z", scheduled_end="2026-05-10T16:30:00Z"), IC)
    validate_error(resp, ApiErrorId.ERR_DESIGNER_SLOT_CONFLICT.value)


def test_appointment_with_exactly_60min_gap_allowed(api):
    """PRD §3.2: "The requested window must neither overlap any such appointment
    nor fall within a 60-minute (one-hour) buffer of one — there must be a gap of
    at least 60 minutes on either side between the new visit and every existing
    scheduled visit for that designer. A violation is rejected with
    ERR_DESIGNER_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/designer_appointment_overlap_within_buffer
    """
    ctx = setup_designer_with_appointment(api)  # appt1 14:00-15:00 on the designer
    # A new visit at 16:00-17:00 leaves exactly a 60-minute gap after the 15:00 end.
    resp = api.create_design_appointment(
        create_design_appointment_payload(
            ctx["proj2"]["id"], ctx["designer"]["id"],
            scheduled_start="2026-05-10T16:00:00Z", scheduled_end="2026-05-10T17:00:00Z"), IC)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED", "a >=60-minute gap must be accepted"


def test_book_appointment_on_inactive_designer_rejected(api):
    """PRD §3.2: "The chosen designer must be active, or the booking is refused
    with ERR_DESIGNER_INACTIVE."

    Design: Corner/validations/book_appointment_inactive_designer_rejected
    """
    designer = create_designer(api, active=False)
    customer = create_customer(api)
    project = create_project(api, customer["id"])
    resp = api.create_design_appointment(
        create_design_appointment_payload(project["id"], designer["id"]), IC)
    validate_error(resp, ApiErrorId.ERR_DESIGNER_INACTIVE.value)


def test_designer_completing_foreign_appointment_denied(api):
    """PRD §3.2: "Completion is allowed only by the designer assigned to the
    project (ERR_NOT_RESOURCE_OWNER) and only while the appointment is still
    SCHEDULED (ERR_APPOINTMENT_INVALID_STATE)."

    Design: Corner/validations/designer_complete_foreign_appointment_denied
    """
    des_a = create_designer(api)
    des_b = create_designer(api)
    customer = create_customer(api)
    project = create_project(api, customer["id"])
    appt = validate_success(api.create_design_appointment(
        create_design_appointment_payload(project["id"], des_a["id"]), IC), 201)
    resp = api.complete_design_appointment(
        appt["id"], {"measured_wall_area_sqft": 100}, make_designer_headers(des_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_complete_already_completed_appointment_rejected(api):
    """PRD §3.2: "Completion is allowed only by the designer assigned to the
    project (ERR_NOT_RESOURCE_OWNER) and only while the appointment is still
    SCHEDULED (ERR_APPOINTMENT_INVALID_STATE)."

    Design: Corner/state_machines/appointment_complete_twice_returns_invalid_state
    """
    ctx = setup_design_complete_project(api, area=100.0)  # appointment already COMPLETED
    resp = api.complete_design_appointment(
        ctx["appointment"]["id"], {"measured_wall_area_sqft": 120},
        make_designer_headers(ctx["designer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_INVALID_STATE.value)
