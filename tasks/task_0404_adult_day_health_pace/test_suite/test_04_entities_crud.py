"""Entity creation, defaults, required fields, not-found, type constraints, listing.

Corner queue B: section entities.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_program, set_clock, create_participant, create_certified_loc,
    create_active_care_plan, create_active_med_order, setup_enrolled_participant,
    create_attendance_day, assert_program, assert_participant,
    TEST_USERS,
)

PA = TEST_USERS["program_admin_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
MD = TEST_USERS["medical_director_headers"]
NS = TEST_USERS["nurse_staff_headers"]
BS = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# entities / create_program_returns_defaults
# ===========================================================================
def test_create_program_returns_defaults():
    """PRD 3.1: "On creation the program's status is OPEN, its enrolled_count is 0, and
    its version is 1."
    PRD 3.1: "The lock_in_days is the number of days after an enrollment becomes
    effective during which a finalized voluntary disenrollment incurs the lock-in
    penalty; it defaults to 30 and is at least 0."

    Design: Corner/entities/create_program_returns_defaults
    """
    resp = api_client.create_program(
        {"name": "P", "state_code": "CA", "daily_census_capacity": 20, "max_roster": 100,
         "medicaid_monthly_rate_cents": 350000, "medicare_monthly_rate_cents": 280000}, PA)
    data = validate_success(resp, expected_status=201)
    assert_program(data)
    assert data["status"] == "OPEN"
    assert data["enrolled_count"] == 0
    assert data["version"] == 1
    assert data["lock_in_days"] == 30


# ===========================================================================
# entities / create_program_missing_required_field
# ===========================================================================
def test_create_program_missing_required_field():
    """PRD 2.5: "After existence, the system checks that the request body is well-formed:
    all required fields present, each value of the correct type, every enum value drawn
    from its legal set, and every integer within its declared range. A malformed,
    mistyped, illegal-enum, or out-of-range body is rejected with ERR_INVALID_REQUEST
    (HTTP 400)."
    PRD 3.1: "Two rate fields, medicaid_monthly_rate_cents and
    medicare_monthly_rate_cents, give the state Medicaid and the Medicare Part C+D
    capitation per member-month in cents, each at least 0."

    Design: Corner/entities/create_program_missing_required_field
    """
    resp = api_client.create_program(
        {"name": "P", "state_code": "CA", "daily_census_capacity": 20, "max_roster": 100,
         "medicare_monthly_rate_cents": 280000}, PA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# entities / get_participant_not_found
# ===========================================================================
def test_get_participant_not_found():
    """PRD 2.5: "The path identifier is checked first; if it names no existing resource,
    the request fails with ERR_NOT_FOUND (HTTP 404) before any body reference is examined."

    Design: Corner/entities/get_participant_not_found
    """
    resp = api_client.get_participant(NON_EXISTENT_UUID, IC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# entities / create_participant_unknown_program_not_found
# ===========================================================================
def test_create_participant_unknown_program_not_found():
    """PRD 2.5: "Body foreign keys are then validated in turn, each producing the same
    ERR_NOT_FOUND if it dangles."

    Design: Corner/entities/create_participant_unknown_program_not_found
    """
    resp = api_client.create_participant(
        {"program_id": NON_EXISTENT_UUID, "full_name": "X", "date_of_birth": "1955-01-01",
         "dual_eligible": True}, IC)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# entities / participant_system_fields_input_ignored
# ===========================================================================
def test_participant_created_with_system_defaults():
    """PRD 3.2: "A new participant starts in APPLICANT status with all ledger fields
    (ledger_billed_cents, ledger_reconciled_cents, lifetime_attendance_days) at 0 and
    version 1."

    Design: Corner/entities/participant_system_fields_input_ignored
    """
    program = create_program()
    participant = get_success_data(api_client.create_participant(
        {"program_id": program["id"], "full_name": "Ign", "date_of_birth": "1955-01-01",
         "dual_eligible": True}, IC))
    assert participant["status"] == "APPLICANT"
    assert participant["ledger_billed_cents"] == 0
    assert participant["version"] == 1


# ===========================================================================
# entities / list_participants_pagination_envelope
# ===========================================================================
def test_list_participants_pagination_envelope():
    """PRD 2.3: "Every list-style response includes limit, offset, total_count, and
    has_more inside the meta object of the envelope, where total_count is the count of
    all matching resources before pagination and has_more indicates whether further
    items remain beyond the current page."

    Design: Corner/entities/list_participants_pagination_envelope
    """
    program = create_program()
    create_participant(program["id"], full_name="One")
    resp = api_client.list_participants(PA, params={"program_id": program["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ===========================================================================
# entities / capitation_immutable_event_admin_count_computed
# ===========================================================================
def test_given_administration_increments_administered_count():
    """PRD 3.6: "When the recorded outcome is GIVEN, the order's administered_count
    increases by 1; other outcomes leave the count unchanged."
    PRD 2.4: "A MedicationAdministration is an append-only event record: once written it
    is never modified. It therefore carries only id and created_at - it has neither an
    updated_at field nor a version field."

    Design: Corner/entities/capitation_immutable_event_admin_count_computed
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-02T08:00:00Z")
    _, participant, care_plan = setup_enrolled_participant(
        program=program, effective_date="2026-06-01")
    med_order = create_active_med_order(participant["id"], care_plan["id"], drug_name="Insulin")
    day = create_attendance_day(participant["id"], "2026-06-02")
    get_success_data(api_client.check_in_attendance_day(day["id"], NS))

    admin = get_success_data(api_client.create_medication_administration(
        {"medication_order_id": med_order["id"], "attendance_day_id": day["id"],
         "outcome": "GIVEN", "administered_at": "2026-06-02T09:00:00Z"}, NS))
    assert "version" not in admin
    assert "updated_at" not in admin

    refreshed = get_success_data(api_client.get_medication_order(med_order["id"], NS))
    assert refreshed["administered_count"] == 1


# ===========================================================================
# entities / transport_invalid_enum_direction
# ===========================================================================
def test_transport_invalid_enum_direction():
    """PRD 2.5: "every enum value drawn from its legal set ... A malformed, mistyped,
    illegal-enum, or out-of-range body is rejected with ERR_INVALID_REQUEST (HTTP 400)."
    PRD 3.5: "the direction (PICKUP or DROPOFF)".

    Design: Corner/entities/transport_invalid_enum_direction
    """
    program = create_program()
    participant = create_participant(program["id"])
    day = create_attendance_day(participant["id"], "2026-06-02")
    resp = api_client.create_transport_leg(
        {"attendance_day_id": day["id"], "direction": "SIDEWAYS",
         "window_start_min": 480, "window_end_min": 540, "vehicle_id": "VAN1"}, NS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# entities / enrollment_fk_reverse_reachability_filtered_list
# ===========================================================================
def test_list_enrollments_by_participant_returns_open_enrollment():
    """PRD 3.4: "On a successful enroll the system creates an Enrollment in OPEN status
    carrying the participant_id and the enrollment_effective_date".
    PRD 2.3: "Unless a specific endpoint states otherwise, list endpoints return their
    resources sorted by the created_at timestamp in ascending order."

    The enroll cascade creates an OPEN enrollment discoverable via the participant-filtered
    list.

    Design: Corner/entities/enrollment_fk_reverse_reachability_filtered_list
    """
    program = create_program(lock_in_days=30)
    set_clock("2026-06-15T12:00:00Z")
    _, participant, _ = setup_enrolled_participant(program=program, effective_date="2026-06-01")
    resp = api_client.list_enrollments(BS, params={"participant_id": participant["id"]})
    data, _ = validate_paginated(resp)
    assert len(data) >= 1
    assert data[0]["status"] == "OPEN"
    assert data[0]["participant_id"] == participant["id"]
