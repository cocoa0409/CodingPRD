"""Procedure-booking scheduling: room half-open + buffer overlap, provider closed-interval
double-booking, the OCC-beats-overlap priority precedence, the touching-endpoint boundary,
and the cross-entity booking-complete / biologic-charge state dependencies."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client,
    create_provider, create_patient, create_encounter, create_room,
    setup_room_with_booking, setup_provider_patient_encounter,
    TEST_USERS,
)
from test_helpers.test_users import make_provider_headers

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADMIN = TEST_USERS["practice_admin_headers"]


def test_occ_stale_room_version_beats_room_temporal_conflict(api):
    """PRD §2.7: "Before any overlap geometry is evaluated, the server compares
    `expected_room_version` against the room's current `version`. If a prior booking has
    advanced the room's version since the client last read it, the create is rejected with
    `ERR_STALE_ROOM_VERSION` (HTTP 412), because the client's view of the room's occupied
    intervals is stale. In both cases the stale-version check runs before the business
    geometry or balance checks of the operation."

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_room_temporal_conflict
    """
    provider = create_provider(full_name="Dr Slot")
    patient = create_patient(full_name="Slot Pat", date_of_birth="1990-10-10")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-08T09:00:00Z")
    room = create_room(name="Suite STD", room_kind="STANDARD", turnover_buffer_minutes=0)
    room_v0 = room["version"]
    # First booking advances room version.
    validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-08T10:00:00Z",
        "end_at": "2026-01-08T11:00:00Z", "expected_room_version": room_v0,
    }, FRONT), 201)

    # Second booking both overlaps geometrically AND carries the stale (pre-first) version.
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-08T10:30:00Z",
        "end_at": "2026-01-08T11:30:00Z", "expected_room_version": room_v0,
    }, FRONT)
    validate_error(res, "ERR_STALE_ROOM_VERSION", expected_status=412)


def test_room_version_check_precedes_mohs_suite_check(api):
    """PRD §2.8: "Within the booking endpoint specifically, this means the room-version check
    precedes the Mohs-suite check, which precedes the credential check, which precedes the
    interval-validity check, which precedes the room-overlap and provider-double-booking
    checks, as detailed in Section 3.4."

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_room_temporal_conflict
    """
    # A MOHS booking into a STANDARD room (would be ERR_MOHS_REQUIRES_MOHS_SUITE) but with a
    # stale room version: the version check fires first -> ERR_STALE_ROOM_VERSION.
    provider = create_provider(full_name="Dr Both Slot", can_perform_mohs=True)
    patient = create_patient(full_name="Both Slot Pat", date_of_birth="1991-10-10")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-03-08T09:00:00Z")
    room = create_room(name="Std Stale", room_kind="STANDARD", turnover_buffer_minutes=0)
    room_v0 = room["version"]
    validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-03-08T13:00:00Z",
        "end_at": "2026-03-08T14:00:00Z", "expected_room_version": room_v0,
    }, FRONT), 201)
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "MOHS", "start_at": "2026-03-08T15:00:00Z",
        "end_at": "2026-03-08T16:00:00Z", "expected_room_version": room_v0,
    }, FRONT)
    validate_error(res, "ERR_STALE_ROOM_VERSION", expected_status=412)


def test_room_touching_endpoints_zero_buffer_allowed(api):
    """PRD §3.4: "Because the window is half-open and the buffer is additive, a new booking
    whose start exactly equals a prior booking's end plus the buffer does **not** overlap and
    is allowed."

    Design: Difficulty/boundary_precision_check/room_touching_endpoints_zero_buffer_allowed
    """
    provider, patient, enc, room, b1, room_v1 = setup_room_with_booking(
        room_overrides={"name": "Suite Adj", "turnover_buffer_minutes": 0},
        booking_overrides={"start_at": "2026-01-11T10:00:00Z",
                           "end_at": "2026-01-11T11:00:00Z"},
    )
    # Isolate the room rule: the second booking touches the prior interval at its
    # endpoint (11:00 == 11:00). Per PRD §3.4 the provider's interval is CLOSED, so a
    # second booking for the SAME provider whose start equals the prior end would be
    # rejected as ERR_PROVIDER_DOUBLE_BOOKED — masking the room rule under test. Use a
    # distinct provider so only the room's half-open + zero-buffer geometry is exercised.
    provider2 = create_provider(full_name="Dr Adj2")
    # Second booking starts exactly at prior end (11:00 == 11:00), buffer 0 -> allowed.
    b2 = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider2["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-11T11:00:00Z",
        "end_at": "2026-01-11T12:00:00Z", "expected_room_version": room_v1,
    }, FRONT), 201)
    assert b2["status"] == "BOOKED"


def test_room_overlapping_interval_zero_buffer_rejected(api):
    """PRD §3.4: "The new booking conflicts if its interval overlaps any such window; a
    conflict is rejected with `ERR_ROOM_INTERVAL_CONFLICT`."

    Design: Difficulty/boundary_precision_check/room_touching_endpoints_zero_buffer_allowed
    """
    provider, patient, enc, room, b1, room_v1 = setup_room_with_booking(
        room_overrides={"name": "Suite Olap", "turnover_buffer_minutes": 0},
        booking_overrides={"start_at": "2026-03-11T10:00:00Z",
                           "end_at": "2026-03-11T11:00:00Z"},
    )
    # Second booking starts 10:59 (strictly inside prior window) -> conflict.
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-03-11T10:59:00Z",
        "end_at": "2026-03-11T11:30:00Z", "expected_room_version": room_v1,
    }, FRONT)
    validate_error(res, "ERR_ROOM_INTERVAL_CONFLICT")


def test_room_overlap_with_turnover_buffer_halfopen(api):
    """PRD §3.4: "each prior `BOOKED` or `COMPLETED` booking on the same room reserves the
    half-open window that begins at that booking's start and extends to its end plus the
    room's `turnover_buffer_minutes`. The new booking conflicts if its interval overlaps any
    such window; a conflict is rejected with `ERR_ROOM_INTERVAL_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnover_buffer_halfopen
    """
    provider, patient, enc, room, b1, room_v1 = setup_room_with_booking(
        room_overrides={"name": "Suite Buf", "turnover_buffer_minutes": 15},
        booking_overrides={"start_at": "2026-01-14T10:00:00Z",
                           "end_at": "2026-01-14T11:00:00Z"},
    )
    # buffer 15 -> prior reserves [10:00, 11:15); new at 11:00 collides.
    res = api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-14T11:00:00Z",
        "end_at": "2026-01-14T11:45:00Z", "expected_room_version": room_v1,
    }, FRONT)
    validate_error(res, "ERR_ROOM_INTERVAL_CONFLICT")


def test_room_after_buffer_boundary_allowed(api):
    """PRD §3.4: "Because the window is half-open and the buffer is additive, a new booking
    whose start exactly equals a prior booking's end plus the buffer does **not** overlap and
    is allowed."

    Design: Difficulty/resource_temporal_overlap/room_overlap_with_turnover_buffer_halfopen
    """
    provider, patient, enc, room, b1, room_v1 = setup_room_with_booking(
        room_overrides={"name": "Suite Buf2", "turnover_buffer_minutes": 15},
        booking_overrides={"start_at": "2026-03-14T10:00:00Z",
                           "end_at": "2026-03-14T11:00:00Z"},
    )
    # prior end 11:00 + buffer 15 = 11:15; new starting exactly 11:15 is allowed.
    b2 = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-03-14T11:15:00Z",
        "end_at": "2026-03-14T12:00:00Z", "expected_room_version": room_v1,
    }, FRONT), 201)
    assert b2["status"] == "BOOKED"


def test_provider_double_booked_closed_interval_touching(api):
    """PRD §3.4: "Because the provider interval is closed, a new booking whose start exactly
    equals a prior booking's end **does** overlap and is rejected — a provider cannot be in
    two procedures whose endpoints merely touch."

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_closed_interval_touching
    """
    provider = create_provider(full_name="Dr Dbl")
    patient = create_patient(full_name="Dbl Pat", date_of_birth="1993-05-05")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-15T09:00:00Z")
    room_a = create_room(name="Room A", room_kind="STANDARD", turnover_buffer_minutes=0)
    room_b = create_room(name="Room B", room_kind="STANDARD", turnover_buffer_minutes=0)
    validate_success(api.create_procedure_booking({
        "room_id": room_a["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-15T10:00:00Z",
        "end_at": "2026-01-15T11:00:00Z", "expected_room_version": room_a["version"],
    }, FRONT), 201)
    # Different room (so room rule passes), same provider, start == prior end -> double-booked.
    res = api.create_procedure_booking({
        "room_id": room_b["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-01-15T11:00:00Z",
        "end_at": "2026-01-15T12:00:00Z", "expected_room_version": room_b["version"],
    }, FRONT)
    validate_error(res, "ERR_PROVIDER_DOUBLE_BOOKED")


def test_provider_overlapping_interval_different_room_rejected(api):
    """PRD §3.4: "**For the provider**, each prior `BOOKED` or `COMPLETED` booking for the
    same provider is treated as a closed interval from its start to its end with no buffer at
    all. The new booking conflicts if its interval overlaps any such closed interval; a
    conflict is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/provider_double_booked_closed_interval_touching
    """
    provider = create_provider(full_name="Dr Dbl2")
    patient = create_patient(full_name="Dbl2 Pat", date_of_birth="1994-05-05")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-03-15T09:00:00Z")
    room_a = create_room(name="Room A2", room_kind="STANDARD", turnover_buffer_minutes=0)
    room_b = create_room(name="Room B2", room_kind="STANDARD", turnover_buffer_minutes=0)
    validate_success(api.create_procedure_booking({
        "room_id": room_a["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-03-15T10:00:00Z",
        "end_at": "2026-03-15T11:00:00Z", "expected_room_version": room_a["version"],
    }, FRONT), 201)
    # Strictly overlapping (10:30) in a different room, same provider -> double-booked.
    res = api.create_procedure_booking({
        "room_id": room_b["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "EXCISION", "start_at": "2026-03-15T10:30:00Z",
        "end_at": "2026-03-15T11:30:00Z", "expected_room_version": room_b["version"],
    }, FRONT)
    validate_error(res, "ERR_PROVIDER_DOUBLE_BOOKED")


def test_booking_complete_requires_encounter_in_progress(api):
    """PRD §3.4: "A `Provider` completes a booking, moving `BOOKED → COMPLETED`, but only
    while the booking is `BOOKED` (otherwise `ERR_BOOKING_BAD_STATE`) and only while the
    linked encounter is `IN_PROGRESS` (otherwise `ERR_ENCOUNTER_NOT_IN_PROGRESS`); completion
    increments the booking's `version`."

    Design: Difficulty/cross_entity_state_dependency/booking_complete_requires_encounter_in_progress
    """
    provider = create_provider(full_name="Dr Mohs", can_perform_mohs=True)
    patient = create_patient(full_name="Mohs Pat", date_of_birth="1962-03-25")
    enc = create_encounter(patient["id"], provider["id"], visit_type="MEDICAL",
                           scheduled_at="2026-01-13T09:00:00Z")  # SCHEDULED, not IN_PROGRESS
    room = create_room(name="Mohs Suite", room_kind="MOHS_SUITE", turnover_buffer_minutes=0)
    booking = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "MOHS", "start_at": "2026-01-13T10:00:00Z",
        "end_at": "2026-01-13T12:00:00Z", "expected_room_version": room["version"],
    }, FRONT), 201)

    prov_headers = make_provider_headers(provider["id"])
    res = api.complete_procedure_booking(booking["id"], prov_headers)
    validate_error(res, "ERR_ENCOUNTER_NOT_IN_PROGRESS")


def test_booking_complete_succeeds_when_encounter_in_progress(api):
    """PRD §3.4: "A `Provider` completes a booking, moving `BOOKED → COMPLETED`, but only
    while the booking is `BOOKED` (otherwise `ERR_BOOKING_BAD_STATE`) and only while the
    linked encounter is `IN_PROGRESS` (otherwise `ERR_ENCOUNTER_NOT_IN_PROGRESS`); completion
    increments the booking's `version`."

    Design: Difficulty/cross_entity_state_dependency/booking_complete_requires_encounter_in_progress
    """
    provider, patient, enc = setup_provider_patient_encounter(
        provider_overrides={"full_name": "Dr Mohs2", "can_perform_mohs": True},
        encounter_overrides={"scheduled_at": "2026-03-13T09:00:00Z"},
    )
    prov_headers = make_provider_headers(provider["id"])
    room = create_room(name="Mohs Suite2", room_kind="MOHS_SUITE", turnover_buffer_minutes=0)
    booking = validate_success(api.create_procedure_booking({
        "room_id": room["id"], "provider_id": provider["id"], "encounter_id": enc["id"],
        "procedure_kind": "MOHS", "start_at": "2026-03-13T10:00:00Z",
        "end_at": "2026-03-13T12:00:00Z", "expected_room_version": room["version"],
    }, FRONT), 201)
    # Drive the encounter to IN_PROGRESS.
    validate_success(api.check_in_encounter(enc["id"], FRONT), 200)
    validate_success(api.start_encounter(enc["id"], prov_headers), 200)
    completed = validate_success(api.complete_procedure_booking(booking["id"], prov_headers), 200)
    assert completed["status"] == "COMPLETED"


def test_biologic_charge_requires_pa_approved_rejected_when_draft(api):
    """PRD §3.7: "A charge whose `charge_kind` is `BIOLOGIC` requires a non-null
    `prior_auth_id` referencing a `PriorAuthorization` whose `status` is `APPROVED`;
    otherwise it is rejected with `ERR_PA_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/biologic_charge_requires_pa_approved
    """
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.0,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-01-12T09:00:00Z"},
    )
    pa = validate_success(api.create_prior_authorization({
        "patient_id": patient["id"], "drug_name": "biologic-W",
        "required_step_count": 0, "list_price_cents": 100000,
    }, BILLING), 201)
    assert pa["status"] == "DRAFT"

    res = api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "BIOLOGIC",
        "billed_amount_cents": 104000, "insurer_allowed_cents": 104000,
        "prior_auth_id": pa["id"],
    }, BILLING)
    validate_error(res, "ERR_PA_NOT_APPROVED")


def test_biologic_charge_succeeds_when_pa_approved(api):
    """PRD §3.7: "A charge whose `charge_kind` is `BIOLOGIC` requires a non-null
    `prior_auth_id` referencing a `PriorAuthorization` whose `status` is `APPROVED`;
    otherwise it is rejected with `ERR_PA_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/biologic_charge_requires_pa_approved
    """
    from test_helpers import setup_approved_pa_round
    _, patient, enc = setup_provider_patient_encounter(
        patient_overrides={"has_active_insurance": True,
                           "insurance_coinsurance_rate": 0.0,
                           "insurance_deductible_remaining_cents": 0},
        encounter_overrides={"scheduled_at": "2026-03-12T09:00:00Z"},
    )
    pa = setup_approved_pa_round(patient, list_price_cents=100000, target_round=1)
    assert pa["status"] == "APPROVED"
    ch = validate_success(api.create_charge({
        "patient_id": patient["id"], "encounter_id": enc["id"],
        "source_kind": "ENCOUNTER", "charge_kind": "BIOLOGIC",
        "billed_amount_cents": 1, "insurer_allowed_cents": 1,
        "prior_auth_id": pa["id"],
    }, BILLING), 201)
    assert ch["status"] == "POSTED"
