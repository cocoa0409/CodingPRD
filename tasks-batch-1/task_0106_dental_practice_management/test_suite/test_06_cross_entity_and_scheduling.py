"""Cross-entity state dependencies and the operatory/provider overlap rules.

Difficulty queue A: cross_entity_state_dependency, resource_temporal_overlap.
"""
from test_helpers import (
    setup_practice,
    create_plan_with_items,
    propose_plan,
    accept_plan,
    create_predetermination,
    book_appointment,
    create_provider,
    validate_success,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]
BILL = TEST_USERS["billing_headers"]


# ─── cross_entity_state_dependency / item_schedule_requires_predetermination ──

def test_schedule_blocked_when_predetermination_pending():
    """PRD §3.4: "if the item's `requires_predetermination` flag is true, its
    linked predetermination must be `APPROVED` (otherwise
    `ERR_PREDETERMINATION_NOT_APPROVED`)".

    An ACCEPTED plan's item with requires_predetermination=true whose
    predetermination is still PENDING cannot be scheduled; booking is rejected with
    ERR_PREDETERMINATION_NOT_APPROVED and the item stays PLANNED.

    Design: Difficulty/cross_entity_state_dependency/item_schedule_requires_predetermination_approved
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8, "requires_predetermination": True}, clin))
    create_predetermination(item["id"], coverage["id"])  # stays PENDING
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": provider["id"],
         "operatory_id": operatory["id"], "appointment_type": "OPERATIVE",
         "start_at": "2026-11-01T09:00:00Z", "end_at": "2026-11-01T10:00:00Z",
         "treatment_plan_item_id": item["id"]}, FD)
    validate_error(resp, ApiErrorId.ERR_PREDETERMINATION_NOT_APPROVED.value)
    item_after = validate_success(api_client.get_treatment_plan_item(item["id"], clin))
    assert item_after["status"] == "PLANNED"


def test_schedule_allowed_once_predetermination_approved():
    """PRD §3.4: "When an appointment names a `treatment_plan_item_id`, booking it
    bubbles that item from `PLANNED` to `SCHEDULED`, and the item's `appointment_id`
    is set to the new appointment's `id`."
    PRD §3.4: "if the item's `requires_predetermination` flag is true, its linked
    predetermination must be `APPROVED`".

    The positive twin: once the predetermination is APPROVED, the same item books
    successfully and bubbles to SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/item_schedule_requires_predetermination_approved
    """
    ctx = setup_practice()
    patient, provider, operatory, coverage = (
        ctx["patient"], ctx["provider"], ctx["operatory"], ctx["coverage"]
    )
    clin = ctx["clinician_headers"]
    plan = get_success_data(api_client.create_treatment_plan(
        {"patient_id": patient["id"], "provider_id": provider["id"]}, clin))
    item = get_success_data(api_client.add_treatment_plan_item(
        plan["id"], {"cdt_code": "D2740", "category": "MAJOR", "fee_cents": 90_000,
                     "phase_number": 1, "tooth_number": 8, "requires_predetermination": True}, clin))
    pred = create_predetermination(item["id"], coverage["id"])
    validate_success(api_client.approve_predetermination(
        pred["id"], {"approved_benefit_cents": 42_500, "valid_until_date": "2027-01-01"}, BILL))
    propose_plan(plan["id"], provider["id"])
    accept_plan(plan["id"])
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            treatment_plan_item_id=item["id"], appointment_type="OPERATIVE",
                            start_at="2026-11-02T09:00:00Z", end_at="2026-11-02T10:00:00Z")
    assert appt["status"] == "SCHEDULED"
    item_after = validate_success(api_client.get_treatment_plan_item(item["id"], clin))
    assert item_after["status"] == "SCHEDULED"


# ─── cross_entity_state_dependency / appointment_checkin_requires_patient_active

def test_checkin_blocked_when_patient_inactive():
    """PRD §3.4: "`FrontDesk` checks a patient in, moving the appointment from
    `SCHEDULED` to `CHECKED_IN`; this requires the appointment to be `SCHEDULED`
    (otherwise `ERR_INVALID_STATE`) and the patient to be `ACTIVE` (otherwise
    `ERR_PATIENT_INACTIVE`)."

    A SCHEDULED appointment whose patient is then deactivated cannot be checked in;
    the check-in is rejected with ERR_PATIENT_INACTIVE and the appointment stays
    SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/appointment_checkin_requires_patient_active
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            appointment_type="OPERATIVE",
                            start_at="2026-12-01T09:00:00Z", end_at="2026-12-01T10:00:00Z")
    validate_success(api_client.deactivate_patient(patient["id"], FD))
    resp = api_client.check_in_appointment(appt["id"], FD)
    validate_error(resp, ApiErrorId.ERR_PATIENT_INACTIVE.value)
    appt_after = validate_success(api_client.get_appointment(appt["id"], FD))
    assert appt_after["status"] == "SCHEDULED"


def test_checkin_succeeds_when_patient_active():
    """PRD §3.4: "`FrontDesk` checks a patient in, moving the appointment from
    `SCHEDULED` to `CHECKED_IN`; this requires the appointment to be `SCHEDULED`
    (otherwise `ERR_INVALID_STATE`) and the patient to be `ACTIVE`".

    The positive twin: with the patient ACTIVE, check-in moves the SCHEDULED
    appointment to CHECKED_IN.

    Design: Difficulty/cross_entity_state_dependency/appointment_checkin_requires_patient_active
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider, operatory = ctx["patient"], ctx["provider"], ctx["operatory"]
    appt = book_appointment(patient["id"], provider["id"], operatory["id"],
                            appointment_type="OPERATIVE",
                            start_at="2026-12-02T09:00:00Z", end_at="2026-12-02T10:00:00Z")
    checked_in = validate_success(api_client.check_in_appointment(appt["id"], FD))
    assert checked_in["status"] == "CHECKED_IN"


# ─── resource_temporal_overlap / operatory_overlap_uses_turnover_buffer ───────

def test_operatory_buffer_widens_occupancy_interval():
    """PRD §3.4: "a new appointment's interval must not overlap any existing
    non-terminal appointment on the same operatory — where the room's interval is
    widened by that operatory's `turnover_buffer_minutes` of cleanup time appended
    after each booking".

    Appt A 09:00-10:00 in a room with a 15-minute buffer occupies [09:00,10:15);
    a B starting 10:10 (inside the buffer) is rejected with
    ERR_OPERATORY_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/operatory_overlap_uses_turnover_buffer
    """
    ctx = setup_practice(with_coverage=False)
    patient, operatory = ctx["patient"], ctx["operatory"]
    prov_a = create_provider(provider_type="DENTIST")
    prov_b = create_provider(provider_type="DENTIST")
    # operatory from setup_practice has the default 15-min buffer.
    book_appointment(patient["id"], prov_a["id"], operatory["id"], appointment_type="OPERATIVE",
                     start_at="2027-01-04T09:00:00Z", end_at="2027-01-04T10:00:00Z")
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": prov_b["id"],
         "operatory_id": operatory["id"], "appointment_type": "OPERATIVE",
         "start_at": "2027-01-04T10:10:00Z", "end_at": "2027-01-04T11:00:00Z"}, FD)
    validate_error(resp, ApiErrorId.ERR_OPERATORY_DOUBLE_BOOKED.value)


def test_operatory_booking_allowed_after_buffer_clears():
    """PRD §3.4: "a new appointment's interval must not overlap any existing
    non-terminal appointment on the same operatory — where the room's interval is
    widened by that operatory's `turnover_buffer_minutes` of cleanup time appended
    after each booking".

    The other side of the buffer boundary: a B starting 10:15 (exactly when the
    [09:00,10:15) buffered interval ends, half-open) does NOT overlap and books
    successfully.

    Design: Difficulty/resource_temporal_overlap/operatory_overlap_uses_turnover_buffer
    """
    ctx = setup_practice(with_coverage=False)
    patient, operatory = ctx["patient"], ctx["operatory"]
    prov_a = create_provider(provider_type="DENTIST")
    prov_b = create_provider(provider_type="DENTIST")
    book_appointment(patient["id"], prov_a["id"], operatory["id"], appointment_type="OPERATIVE",
                     start_at="2027-01-05T09:00:00Z", end_at="2027-01-05T10:00:00Z")
    ok = book_appointment(patient["id"], prov_b["id"], operatory["id"], appointment_type="OPERATIVE",
                          start_at="2027-01-05T10:15:00Z", end_at="2027-01-05T11:00:00Z")
    assert ok["status"] == "SCHEDULED"


# ─── resource_temporal_overlap / provider_overlap_no_buffer_adjacent_ok ───────

def test_provider_overlap_uses_raw_half_open_no_buffer():
    """PRD §3.4: "nor overlap any existing non-terminal appointment for the same
    provider, for whom no buffer applies."

    The same provider booked [09:00,10:00) in one room and [09:59,10:30) in another
    has a true time overlap (no buffer involved), rejected with
    ERR_OPERATORY_DOUBLE_BOOKED.

    Design: Difficulty/resource_temporal_overlap/provider_overlap_no_buffer_adjacent_ok
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider = ctx["patient"], ctx["provider"]
    op_a = get_success_data(api_client.create_operatory({"room_name": "OP-A", "turnover_buffer_minutes": 0}, FD))
    op_b = get_success_data(api_client.create_operatory({"room_name": "OP-B", "turnover_buffer_minutes": 0}, FD))
    book_appointment(patient["id"], provider["id"], op_a["id"], appointment_type="OPERATIVE",
                     start_at="2027-02-01T09:00:00Z", end_at="2027-02-01T10:00:00Z")
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": provider["id"],
         "operatory_id": op_b["id"], "appointment_type": "OPERATIVE",
         "start_at": "2027-02-01T09:59:00Z", "end_at": "2027-02-01T10:30:00Z"}, FD)
    validate_error(resp, ApiErrorId.ERR_OPERATORY_DOUBLE_BOOKED.value)


def test_provider_adjacent_booking_allowed_when_not_overlapping():
    """PRD §3.4: "nor overlap any existing non-terminal appointment for the same
    provider, for whom no buffer applies."

    The non-overlap side: the same provider booked [09:00,10:00) then [10:00,10:30)
    in another room is back-to-back with no buffer, so the half-open intervals do
    not overlap and the second books successfully.

    Design: Difficulty/resource_temporal_overlap/provider_overlap_no_buffer_adjacent_ok
    """
    ctx = setup_practice(with_coverage=False)
    patient, provider = ctx["patient"], ctx["provider"]
    op_a = get_success_data(api_client.create_operatory({"room_name": "OP-A2", "turnover_buffer_minutes": 0}, FD))
    op_b = get_success_data(api_client.create_operatory({"room_name": "OP-B2", "turnover_buffer_minutes": 0}, FD))
    book_appointment(patient["id"], provider["id"], op_a["id"], appointment_type="OPERATIVE",
                     start_at="2027-02-02T09:00:00Z", end_at="2027-02-02T10:00:00Z")
    ok = book_appointment(patient["id"], provider["id"], op_b["id"], appointment_type="OPERATIVE",
                          start_at="2027-02-02T10:00:00Z", end_at="2027-02-02T10:30:00Z")
    assert ok["status"] == "SCHEDULED"
