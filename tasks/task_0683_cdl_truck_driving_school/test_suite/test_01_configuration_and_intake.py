"""Configuration-layer resources (programs, trucks) and enrollment intake.

Translates queue B (Corner / entities) instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_program_payload, create_truck_payload, create_enrollment_payload,
    NON_EXISTENT_UUID,
    create_program,
)

ADMIN = TEST_USERS["school_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]


def test_create_program_returns_201_with_fields():
    """PRD §3.1: "It is created with a name, a cdl_class that is either CLASS_A or
    CLASS_B, and three required-hour figures". PRD §3.1: "an optional
    skills_pass_threshold ... defaults to 80 when omitted. On creation, a program's
    active flag is set to true".

    Design: Corner/entities/create_program_returns_201_with_fields
    """
    payload = create_program_payload(
        name="Class A ELDT", cdl_class="CLASS_A",
        classroom_required_hours=40, range_required_hours=20,
        road_required_hours=30, tuition_cents=700000)
    # skills_pass_threshold omitted to verify the default.
    resp = api_client.create_program(payload, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["active"] is True, "active must default to true on creation"
    assert data["cdl_class"] == "CLASS_A"
    assert data["skills_pass_threshold"] == 80, "skills_pass_threshold defaults to 80"


def test_get_program_returns_stored_entity():
    """PRD §4: "GET /programs/{id} | Get a program". PRD §3.1: "It also carries a
    tuition_cents sticker price in integer cents (zero or greater)".

    Design: Corner/entities/get_program_returns_stored_entity
    """
    program = create_program(tuition_cents=550000)
    resp = api_client.get_program(program["id"], REGISTRAR)
    data = validate_success(resp, expected_status=200)
    assert data["tuition_cents"] == 550000


def test_get_program_nonexistent_returns_not_found():
    """PRD §2.7: "the system validates each identifier in left-to-right order and
    rejects the request with ERR_NOT_FOUND at the first identifier in the path that
    does not resolve to an existing resource."

    Design: Corner/entities/get_program_nonexistent_returns_not_found
    """
    resp = api_client.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_enrollment_missing_required_field_returns_invalid():
    """PRD §3.2: "A Registrar opens the student lifecycle by creating an Enrollment
    against a program, supplying the program_id and the student_name." PRD §2.8: "a
    body missing a required field ... yields ERR_INVALID_REQUEST".

    Design: Corner/entities/create_enrollment_missing_required_field_returns_invalid
    """
    program = create_program()
    # Omit student_name.
    resp = api_client.create_enrollment({"program_id": program["id"]}, REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_truck_default_buffer_applied():
    """PRD §3.1: "It also accepts an optional turnaround_buffer_minutes ... which
    defaults to 30 and must be zero or greater. At registration the truck's status is
    set to AVAILABLE ... and its reserved_minutes ledger starts at 0."

    Design: Corner/entities/create_truck_default_buffer_applied
    """
    resp = api_client.create_truck(create_truck_payload(unit_number="T9"), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["turnaround_buffer_minutes"] == 30
    assert data["status"] == "AVAILABLE"
    assert data["reserved_minutes"] == 0


def test_create_program_invalid_enum_cdl_class_rejected():
    """PRD §2.8: "a body missing a required field, carrying an invalid enum value ...
    yields ERR_INVALID_REQUEST". PRD §3.1: "a cdl_class that is either CLASS_A or
    CLASS_B".

    Design: Corner/entities/create_program_invalid_enum_cdl_class_rejected
    """
    payload = create_program_payload(cdl_class="CLASS_C")
    resp = api_client.create_program(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_enrollment_computed_logged_hours_zero_on_create():
    """PRD §3.2: "A fresh enrollment begins in APPLIED status with both verification
    flags — dot_medical_verified and permit_verified — false, its sponsoring_carrier_id
    unset, and fmcsa_reported false." PRD §3.2: "Reading an enrollment exposes its
    computed hour totals (logged_classroom_hours, logged_range_hours, logged_road_hours,
    projected_road_hours)".

    Design: Corner/entities/enrollment_computed_logged_hours_zero_on_create
    """
    program = create_program()
    resp = api_client.create_enrollment(
        create_enrollment_payload(program["id"]), REGISTRAR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "APPLIED"
    assert data["logged_classroom_hours"] == 0
    assert data["fmcsa_reported"] is False


def test_enrollment_create_unknown_program_returns_not_found():
    """PRD §2.7: "The same left-to-right rule applies to foreign keys carried in a
    request body: any referenced resource that does not exist yields ERR_NOT_FOUND."

    Design: Corner/entities/enrollment_create_unknown_program_returns_not_found
    """
    resp = api_client.create_enrollment(
        create_enrollment_payload(NON_EXISTENT_UUID), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_enrollments_pagination_envelope():
    """PRD §2.3: "List responses include limit, offset, total_count, and has_more in
    the meta object of the response envelope." PRD §3.2: "Enrollments may be listed and
    filtered by program_id".

    Design: Corner/entities/list_enrollments_pagination_envelope
    """
    program = create_program()
    api_client.create_enrollment(
        create_enrollment_payload(program["id"], student_name="A"), REGISTRAR)
    api_client.create_enrollment(
        create_enrollment_payload(program["id"], student_name="B"), REGISTRAR)
    resp = api_client.list_enrollments(REGISTRAR, params={"program_id": program["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
