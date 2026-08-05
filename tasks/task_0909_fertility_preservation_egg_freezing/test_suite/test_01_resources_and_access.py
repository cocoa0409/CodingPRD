"""Foundational resource creation, listing, access control, and consistency.

Translates queue-B (corner) instances from the entities, errors, rbac, and
consistency_model sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_patient, assert_storage_tank,
    create_patient_payload, create_consultation_payload, create_storage_tank_payload,
    create_cycle_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
EMB = TEST_USERS["embryologist_headers"]


def test_create_patient_returns_201_with_version_1(api):
    """PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by one
    on every mutation of the resource." PRD §3.1: "The journey begins with a `Patient`,
    onboarded by a `Coordinator` or a `BillingAdmin` with a `full_name`, a `date_of_birth`, an
    `email`, and an optional `employer_name`."

    Design: Corner/entities/create_patient_success
    """
    resp = api.create_patient(
        create_patient_payload(full_name="Ada Lovelace", date_of_birth="1990-12-10T00:00:00Z",
                               email="ada@x.com"),
        COORD)
    data = validate_success(resp, 201)
    assert data["full_name"] == "Ada Lovelace", "created patient must echo full_name"
    assert data["version"] == 1, "a freshly created resource starts at version 1"
    assert_patient(data)


def test_get_unknown_patient_returns_not_found(api):
    """PRD §2.9: "existence of every referenced resource, whether named in the path or in
    the body, validated left-to-right (ERR_NOT_FOUND)."

    Design: Corner/entities/get_patient_not_found
    """
    resp = api.get_patient(NON_EXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_consultation_missing_amh_rejected(api):
    """PRD §2.9: "request-body schema validation such as missing required fields, unknown
    enum values, wrong types, values that violate a non-negative or positive constraint ...
    (ERR_VALIDATION)." PRD §3.2: "opens a Consultation for a patient by supplying the
    patient_id, the patient_age_years ..., the amh_level ..., and the antral_follicle_count."

    Design: Corner/entities/create_consultation_missing_amh_returns_invalid_request
    """
    patient = fx.create_patient()
    payload = create_consultation_payload(patient["id"])
    del payload["amh_level"]
    resp = api.create_consultation(payload, COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_new_storage_tank_has_zero_used_slots(api):
    """PRD §3.1: "A tank's used_slots starts at 0 and its is_full starts false; both are
    derived thereafter as described in §2.7 and observable by reading the tank."

    Design: Corner/entities/storage_tank_used_slots_computed_zero
    """
    resp = api.create_storage_tank(create_storage_tank_payload(name="T-new", capacity_slots=5), EMB)
    data = validate_success(resp, 201)
    assert data["used_slots"] == 0, "new tank must have used_slots 0"
    assert data["is_full"] is False, "new tank must have is_full false"
    assert_storage_tank(data)


def test_list_consultations_returns_array_envelope(api):
    """PRD §2.3: "Every list response echoes limit, offset, total_count, and has_more inside
    the meta object of the envelope, where total_count is the number of records matching the
    query before pagination and has_more indicates whether records remain beyond the current page."

    Design: Corner/entities/list_consultations_pagination_envelope
    """
    patient = fx.create_patient()
    api.create_consultation(create_consultation_payload(patient["id"], amh_level=2.0,
                                                        antral_follicle_count=12), COORD)
    resp = api.list_consultations(COORD, params={"patient_id": patient["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one consultation, got {len(data)}"
    assert meta["total_count"] == 1, "total_count must reflect the one matching consultation"
    assert "has_more" in meta, "meta must carry has_more"


def test_create_patient_without_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or presenting a role the system does not
    recognize, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/errors/create_patient_missing_headers_returns_unauthenticated
    """
    resp = api.create_patient(
        create_patient_payload(full_name="No Auth", date_of_birth="1990-01-01T00:00:00Z",
                               email="na@x.com"),
        {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_coordinator_cannot_authorize_thaw(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED." PRD §4 lists
    POST /thaw-transfer-authorizations/{id}/authorize as Physician-only.

    Design: Corner/rbac/coordinator_cannot_authorize_thaw
    """
    resp = api.authorize_thaw("22222222-2222-2222-2222-222222222222", COORD)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_patient_cannot_create_stimulation_cycle(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_UNAUTHORIZED." PRD §3.3: "A
    Coordinator creates a StimulationCycle by supplying the patient_id and the consultation_id."

    Design: Corner/rbac/patient_cannot_create_stimulation_cycle
    """
    pid = "33333333-3333-3333-3333-333333333333"
    headers = fx.make_patient_headers(pid)
    resp = api.create_stimulation_cycle(
        create_cycle_payload(pid, "44444444-4444-4444-4444-444444444444"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_patient_immediately_readable_after_create(api):
    """PRD §2.7 (consistency: immediate) and §3.1: a patient onboarded by a Coordinator is a
    persisted resource; PRD §4 exposes GET /patients/{id}. PRD §2.4: "id is a server-minted
    UUID with no type prefix."

    Design: Corner/consistency_model/immediate_read_after_write_patient
    """
    patient = fx.create_patient()
    resp = api.get_patient(patient["id"], COORD)
    data = validate_success(resp, 200)
    assert data["id"] == patient["id"], "patient must be immediately readable by id"
