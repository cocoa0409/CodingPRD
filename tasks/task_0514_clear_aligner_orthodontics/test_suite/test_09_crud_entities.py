"""Entity CRUD, input validation, system/computed fields, listing (PRD §2-3)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_patient_payload, create_case_payload,
    create_patient, create_case, add_usable_intake,
    api_client, TEST_USERS, make_patient_headers, NON_EXISTENT_UUID,
)

PATIENT = TEST_USERS["patient_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_create_patient_returns_201_with_minor_flag_default_false(api):
    """PRD §3.1: "A `Patient` record is registered with a contact `email`, a
    `full_name`, a two-letter US `state_code`, and a `date_of_birth` given as an
    ISO date."
    PRD §3.1: "true when the patient's age at that instant is less than 18 — and
    defaults to false until an intake exists."

    POST /patients returns 201 with a server-minted id and is_minor_at_intake
    defaulting false.

    Design: Corner/entities/create_patient_returns_201_with_all_fields
    """
    res = api.create_patient(
        create_patient_payload(email="new@x.com", full_name="New Pat",
                               state_code="CA", date_of_birth="1990-01-01"),
        PATIENT,
    )
    patient = validate_success(res, 201)
    assert patient["full_name"] == "New Pat"
    assert patient["is_minor_at_intake"] is False


def test_get_nonexistent_patient_returns_not_found(api):
    """PRD §2.9: "if any path-referenced resource does not exist, the request
    fails with `ERR_NOT_FOUND` (HTTP 404)".

    GET /patients/{id} for a non-existent UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_patient_nonexistent_returns_not_found
    """
    res = api.get_patient(NON_EXISTENT_UUID, BILLING)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_case_missing_list_price_returns_invalid_request(api):
    """PRD §3.2: "A `TreatmentCase` is created for a patient by supplying
    `patient_id`, an `intake_channel` of either `IMPRESSION_KIT` or
    `IN_OFFICE_SCAN`, and a `list_price_cents`".
    PRD §2.10: "A malformed body - a missing required field, an unrecognised
    enum value, or a type mismatch - is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)".

    Omitting the required list_price_cents returns ERR_INVALID_REQUEST (400).

    Design: Corner/entities/create_case_missing_required_list_price_returns_invalid_request
    """
    patient = create_patient(state_code="CA")
    res = api.create_case(
        {"patient_id": patient["id"], "intake_channel": "IMPRESSION_KIT"},
        make_patient_headers(patient["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_case_bad_intake_channel_enum_returns_invalid_request(api):
    """PRD §3.2: "an `intake_channel` of either `IMPRESSION_KIT` or
    `IN_OFFICE_SCAN`".
    PRD §2.10: "A malformed body - a missing required field, an unrecognised
    enum value, or a type mismatch - is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)".

    An intake_channel of MAIL (outside the enum) returns ERR_INVALID_REQUEST.

    Design: Corner/entities/create_case_bad_intake_channel_enum_returns_invalid_request
    """
    patient = create_patient(state_code="CA")
    res = api.create_case(
        {"patient_id": patient["id"], "intake_channel": "MAIL", "list_price_cents": 300000},
        make_patient_headers(patient["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_case_initializes_system_status_and_version(api):
    """PRD §3.2: "A new case begins life in `INTAKE_PENDING`."
    PRD §2.4: "an integer `version` that begins at 1 on creation".

    A new case initializes status=INTAKE_PENDING server-side with version 1.

    Design: Corner/entities/case_system_id_and_status_ignored_from_input
    """
    patient = create_patient(state_code="CA")
    res = api.create_case(
        create_case_payload(patient["id"], intake_channel="IMPRESSION_KIT",
                            list_price_cents=300000),
        make_patient_headers(patient["id"]),
    )
    case = validate_success(res, 201)
    assert case["status"] == "INTAKE_PENDING", case["status"]
    assert case["version"] == 1, case["version"]


def test_is_minor_at_intake_computes_true_after_intake(api):
    """PRD §3.1: "A derived boolean, `is_minor_at_intake`, marks whether the
    patient was under 18 at the moment the case's intake was captured; it is
    computed from `date_of_birth` against the intake record's `captured_at`
    instant - true when the patient's age at that instant is less than 18".
    PRD §2.5: "At server startup the clock reads exactly `2026-05-01T00:00:00Z`".

    A patient born 2012-01-01 with an intake captured at the default clock
    (2026-05-01) is age 14 < 18, so is_minor_at_intake computes true.

    Design: Corner/entities/is_minor_at_intake_computed_true_for_recent_dob
    """
    patient = create_patient(state_code="CA", date_of_birth="2012-01-01")
    case = create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    add_usable_intake(case["id"], patient["id"], channel="IMPRESSION_KIT")
    fetched = validate_success(api.get_patient(patient["id"], BILLING), 200)
    assert fetched["is_minor_at_intake"] is True


def test_list_cases_returns_array_envelope_with_pagination(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object, where `total_count` is the full
    count of matching records ignoring pagination and `has_more` is true when
    records beyond the current page remain."

    GET /cases returns an array envelope; with one case and default limit 10,
    total_count is at least 1 and has_more is false.

    Design: Corner/entities/list_cases_pagination_envelope
    """
    patient = create_patient(state_code="CA")
    create_case(patient["id"], intake_channel="IMPRESSION_KIT")
    data, meta = validate_paginated(api.list_cases(BILLING))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
