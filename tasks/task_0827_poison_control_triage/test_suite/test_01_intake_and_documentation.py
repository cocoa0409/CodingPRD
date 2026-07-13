"""Call intake, required-field validation, listing, and case documentation.

Translations of Corner-design instances in sections `entities` and `endpoints`.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_case_payload,
    create_note_payload,
    make_specialist_headers,
    seed_specialist,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_exposure_case_success(api):
    """PRD §3.2: "On creation the case enters `INTAKE`, its `intake_specialist_id`
    is stamped from `X-User-ID`, and its computed fields — `status`, `risk_tier`
    (null until an assessment exists), `pending_followup_count` (0), and
    `resolved_at` (null) — take their initial values."
    PRD §2.4: "a `version` — an integer that starts at 1 and increments by one on
    every mutation of that resource, used for optimistic concurrency control as
    described in §2.7."

    Design: Corner/entities/create_exposure_case_success
    """
    spi = seed_specialist(api)
    resp = api.create_case(
        create_case_payload(patient_age_years=4, patient_weight_kg=18,
                            patient_sex="FEMALE", chief_complaint="berry ingestion"),
        make_specialist_headers(spi["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "INTAKE"
    assert data["version"] == 1
    assert data["patient_weight_kg"] == 18


def test_intake_specialist_id_from_header(api):
    """PRD §2.1: "In particular, opening a case stamps `intake_specialist_id` from
    `X-User-ID`."

    Design: Corner/entities/system_field_intake_specialist_from_header
    """
    spi = seed_specialist(api)
    resp = api.create_case(
        create_case_payload(patient_age_years=4, patient_weight_kg=18, patient_sex="MALE"),
        make_specialist_headers(spi["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["intake_specialist_id"] == spi["id"]


def test_get_exposure_case_not_found(api):
    """PRD §2.8: "if the case `id` in the path does not resolve, the request fails
    immediately with `ERR_CASE_NOT_FOUND` (HTTP 404) before any sub-resource is
    considered."

    Design: Corner/entities/get_exposure_case_not_found
    """
    spi = seed_specialist(api)
    resp = api.get_case(NON_EXISTENT_UUID, make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)


def test_create_case_missing_weight_rejected(api):
    """PRD §2.10: "Malformed payloads — a missing required field, a wrong type, or
    an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_case_missing_required_weight_rejected
    """
    spi = seed_specialist(api)
    payload = {"patient_age_years": 4, "patient_sex": "MALE", "chief_complaint": "ingestion"}
    resp = api.create_case(payload, make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_interpreter_language_required_when_flag_set(api):
    """PRD §3.2: "When `interpreter_required` is true, `interpreter_language` must
    be supplied; omitting it is rejected with `ERR_INTERPRETER_LANGUAGE_REQUIRED`
    (HTTP 422)."

    Design: Corner/entities/interpreter_language_required_when_flag_set
    """
    spi = seed_specialist(api)
    payload = create_case_payload(patient_age_years=4, patient_weight_kg=18,
                                  patient_sex="MALE", interpreter_required=True)
    resp = api.create_case(payload, make_specialist_headers(spi["id"]))
    validate_error(resp, ApiErrorId.ERR_INTERPRETER_LANGUAGE_REQUIRED)


def test_list_exposure_cases_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_exposure_cases_pagination_envelope
    """
    spi = seed_specialist(api)
    headers = make_specialist_headers(spi["id"])
    api.create_case(create_case_payload(patient_age_years=4, patient_weight_kg=18,
                                        patient_sex="MALE", chief_complaint="c1"), headers)
    api.create_case(create_case_payload(patient_age_years=5, patient_weight_kg=20,
                                        patient_sex="FEMALE", chief_complaint="c2"), headers)
    resp = api.list_cases(headers, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_case_notes_append_and_list(api):
    """PRD §3.2: "Notes are append-only: each records its `author_ref` from
    `X-User-ID` for attribution only, and this value is never an input to any
    business decision."

    Design: Corner/endpoints/case_notes_append_and_list
    """
    spi = seed_specialist(api)
    headers = make_specialist_headers(spi["id"])
    case = validate_success(api.create_case(create_case_payload(), headers), 201)
    resp = api.create_note(case["id"],
                           create_note_payload(note_type="INTAKE",
                                               body="Caller reports accidental ingestion."),
                           headers)
    note = validate_success(resp, expected_status=201)
    assert note["author_ref"] == spi["id"]
    assert note["note_type"] == "INTAKE"
