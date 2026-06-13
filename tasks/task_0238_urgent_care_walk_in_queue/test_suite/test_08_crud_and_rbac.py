"""CRUD, input-validation, listing/pagination, computed-field, FK, and RBAC tests
(PRD §2.1, §2.3, §2.4, §2.5, §2.6, §3.1, §3.4, §3.5, §3.9).
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_valid_uuid,
    is_iso8601_timestamp,
    make_provider_headers,
    TEST_USERS,
    assert_clinic,
    create_clinic,
    create_exam_room,
    create_provider,
    create_walk_in,
    triage,
    setup_ready_entry,
    get_clinic_version,
)

_ANON = TEST_USERS["anonymous_headers"]
_MGR = TEST_USERS["clinic_manager_headers"]
_CLERK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["triage_nurse_headers"]
_PROVIDER = TEST_USERS["provider_headers"]

NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ─── entities / create_clinic_returns_201_with_computed_defaults ───

def test_create_clinic_returns_computed_defaults():
    """PRD §2.9: "A clinic continuously reports its operating posture"; a clinic is
    "created with a display name and an exam_room_capacity"; PRD §4: "Operations
    that create a new resource return 201 Created." PRD §2.4: version "begins at its
    initial value and increments by one on each mutation."

    Design: Corner/entities/create_clinic_returns_201_with_computed_defaults
    """
    res = api_client.create_clinic({"name": "Fresh Clinic", "exam_room_capacity": 5}, _ANON)
    clinic = validate_success(res, 201)
    assert_clinic(clinic)
    assert clinic["posture"] == "OPEN", f"new clinic posture should be OPEN, got {clinic['posture']}"
    assert clinic["active_queue_depth"] == 0 and clinic["rooms_occupied"] == 0
    assert clinic["version"] == 1, f"initial version should be 1, got {clinic['version']}"


# ─── entities / get_clinic_not_found_returns_404 ───

def test_get_clinic_not_found_returns_404():
    """PRD §2.5: "The server validates path identifiers strictly left to right and
    rejects the first one that does not resolve with ERR_NOT_FOUND."

    Design: Corner/entities/get_clinic_not_found_returns_404
    """
    res = api_client.get_clinic(NON_EXISTENT, _MGR)
    validate_error(res, "ERR_NOT_FOUND")


# ─── entities / create_queue_entry_missing_required_chief_complaint_returns_invalid_request ───

def test_create_queue_entry_missing_chief_complaint_rejected():
    """PRD §2.6: "the request body checked for well-formedness — required fields
    present ... which on failure returns ERR_INVALID_REQUEST (HTTP 400)." PRD §3.1:
    "Either way the entry captures a free-text chief_complaint."

    Design: Corner/entities/create_queue_entry_missing_required_chief_complaint_returns_invalid_request
    """
    clinic = create_clinic(name="ReqClinic", exam_room_capacity=2)
    res = api_client.create_queue_entry(clinic["id"], {"arrival_channel": "WALK_IN"}, _CLERK)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entities / create_exam_room_default_room_type_standard_applied ───

def test_exam_room_defaults_to_standard_available():
    """PRD §3.9: "A new room carries a room_label and a room_type of STANDARD (the
    default), ISOLATION, or PROCEDURE"; "A room's status lifecycle is AVAILABLE,
    OCCUPIED, CLEANING, and OUT_OF_SERVICE" (rooms begin AVAILABLE).

    Design: Corner/entities/create_exam_room_default_room_type_standard_applied
    """
    clinic = create_clinic(name="DefClinic", exam_room_capacity=2)
    res = api_client.create_exam_room(clinic["id"], {"room_label": "RoomDef"}, _MGR)
    room = validate_success(res, 201)
    assert room["room_type"] == "STANDARD", (
        f"omitted room_type should default to STANDARD, got {room['room_type']}")
    assert room["status"] == "AVAILABLE", (
        f"new room should be AVAILABLE, got {room['status']}")


# ─── entities / patient_is_minor_computed_from_dob_ignores_client_value ───

def test_patient_is_minor_computed_from_dob():
    """PRD §3.4: "At registration the server computes whether the patient is a minor
    and records it in is_minor. Age in whole years is the floor of the elapsed time
    between the patient's date_of_birth and the current clock date, and the patient
    is a minor when that age is below the majority age of 18."

    Design: Corner/entities/patient_is_minor_computed_from_dob_ignores_client_value
    """
    api_client.set_clock({"to_iso8601": "2026-06-08T12:00:00Z"}, _ANON)
    clinic = create_clinic(name="MinorClinic2", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="minor")
    triage(clinic["id"], qe["id"], esi_level=4)
    res = api_client.create_patient(
        {"queue_entry_id": qe["id"], "legal_name": "Kid Pat", "date_of_birth": "2015-01-01",
         "guarantor_name": "Parent", "consent_signed": True}, _CLERK)
    patient = validate_success(res, 201)
    assert patient["is_minor"] is True, (
        f"age-11 patient should be is_minor=true, got {patient['is_minor']}")


# ─── entities / create_queue_entry_invalid_arrival_channel_enum_returns_invalid_request ───

def test_create_queue_entry_invalid_channel_enum_rejected():
    """PRD §2.6: well-formedness requires "enum values in range"; PRD §3.1
    distinguishes entries "by arrival_channel" as ONLINE or WALK_IN only.

    Design: Corner/entities/create_queue_entry_invalid_arrival_channel_enum_returns_invalid_request
    """
    clinic = create_clinic(name="EnumClinic", exam_room_capacity=2)
    res = api_client.create_queue_entry(
        clinic["id"], {"arrival_channel": "MAIL", "chief_complaint": "x"}, _CLERK)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entities / triage_esi_level_out_of_range_returns_invalid_request ───

def test_triage_esi_level_out_of_range_rejected():
    """PRD §2.6: well-formedness requires "esi_level between 1 and 5 inclusive ...
    which on failure returns ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/triage_esi_level_out_of_range_returns_invalid_request
    """
    clinic = create_clinic(name="EsiClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="esi-range")
    res = api_client.triage_queue_entry(clinic["id"], qe["id"], {"esi_level": 6}, _NURSE)
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entities / create_charge_zero_amount_returns_invalid_request ───

def test_create_charge_zero_amount_rejected():
    """PRD §2.6: well-formedness requires "amount_cents greater than 0 ... which on
    failure returns ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_charge_zero_amount_returns_invalid_request
    """
    setup = _setup_open_visit()
    res = api_client.create_charge(
        setup["visit"]["id"], {"cpt_code": "BAD", "amount_cents": 0},
        make_provider_headers(setup["provider"]["id"]))
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── entities / create_patient_wrong_queue_entry_fk_returns_fk_not_found ───

def test_create_patient_unresolvable_queue_entry_fk_rejected():
    """PRD §2.5: "When a create or action body names a foreign resource — a ...
    queue_entry_id ... — and that reference does not resolve to an existing record,
    the request is rejected with ERR_FK_NOT_FOUND."

    Design: Corner/entities/create_patient_wrong_queue_entry_fk_returns_fk_not_found
    """
    res = api_client.create_patient(
        {"queue_entry_id": "00000000-0000-4000-8000-000000000001", "legal_name": "No QE",
         "date_of_birth": "1990-01-01", "consent_signed": True}, _CLERK)
    validate_error(res, "ERR_FK_NOT_FOUND")


# ─── entities / system_fields_id_created_at_generated_input_ignored ───

def test_system_fields_id_and_created_at_server_minted():
    """PRD §2.4: "Every resource carries a system-generated id formatted as a UUID
    ... It also carries a created_at timestamp, an ISO 8601 UTC value with three
    fractional digits, recorded when the resource is first created."

    Design: Corner/entities/system_fields_id_created_at_generated_input_ignored
    """
    res = api_client.create_clinic({"name": "SysClinic", "exam_room_capacity": 3}, _ANON)
    clinic = validate_success(res, 201)
    assert is_valid_uuid(clinic["id"]), f"id should be a UUID, got {clinic['id']}"
    assert is_iso8601_timestamp(clinic["created_at"]), (
        f"created_at should be ISO 8601, got {clinic['created_at']}")


# ─── endpoints / list_queue_entries_paginated_envelope ───

def test_list_queue_entries_paginated_envelope():
    """PRD §2.3: "The meta object of a list response carries the four pagination
    fields limit, offset, total_count, and has_more." The limit parameter "caps how
    many items are returned".

    Design: Corner/endpoints/list_queue_entries_paginated_envelope
    """
    clinic = create_clinic(name="ListClinic", exam_room_capacity=4)
    api_client.seed_queue_depth({"clinic_id": clinic["id"], "count": 2}, _ANON)
    data, meta = validate_paginated(
        api_client.list_clinic_queue_entries(clinic["id"], _CLERK, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert len(data) == 1, f"limit=1 should return 1 item, got {len(data)}"
    assert meta["has_more"] is True, f"has_more should be true, got {meta['has_more']}"


# ─── endpoints / pagination_limit_out_of_bounds_returns_validation_error ───

def test_pagination_limit_zero_rejected():
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_VALIDATION_PAGINATION."

    Design: Corner/endpoints/pagination_limit_out_of_bounds_returns_validation_error
    """
    clinic = create_clinic(name="PageClinic", exam_room_capacity=2)
    res = api_client.list_clinic_queue_entries(clinic["id"], _CLERK, params={"limit": 0})
    validate_error(res, "ERR_VALIDATION_PAGINATION")


# ─── rbac / front_desk_cannot_create_visit_returns_forbidden ───

def test_front_desk_cannot_create_visit_forbidden():
    """PRD §2.1: "if the acting role is not permitted to perform the requested
    operation, the request is rejected with ERR_FORBIDDEN_ROLE." PRD §4 lists POST
    /visits as authorized for Provider only.

    Design: Corner/rbac/front_desk_cannot_create_visit_returns_forbidden
    """
    clinic = create_clinic(name="RbacClinic", exam_room_capacity=2)
    room = create_exam_room(clinic["id"], room_label="RB1")
    provider = create_provider(clinic["id"], full_name="Dr RB", credential="MD")
    ready = setup_ready_entry(clinic["id"], esi_level=3, coverage_type="SELF_PAY")
    cv = get_clinic_version(clinic["id"], _CLERK)
    res = api_client.create_visit(
        {"queue_entry_id": ready["queue_entry"]["id"], "provider_id": provider["id"],
         "exam_room_id": room["id"], "expected_clinic_version": cv}, _CLERK)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── rbac / triage_without_auth_role_returns_unauthenticated ───

def test_triage_without_auth_headers_unauthenticated():
    """PRD §2.1: "A request missing either header on an authentication-required
    endpoint is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/triage_without_auth_role_returns_unauthenticated
    """
    clinic = create_clinic(name="AuthClinic", exam_room_capacity=2)
    qe = create_walk_in(clinic["id"], chief_complaint="auth")
    res = api_client.triage_queue_entry(clinic["id"], qe["id"], {"esi_level": 3}, headers={})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── rbac / provider_cannot_run_ops_returns_forbidden ───

def test_provider_cannot_run_ops_forbidden():
    """PRD §2.1: an operation "is gated by role"; PRD §4 lists POST
    /clinics/{id}/run-ops as authorized for ClinicManager only.

    Design: Corner/rbac/provider_cannot_run_ops_returns_forbidden
    """
    clinic = create_clinic(name="OpsClinic", exam_room_capacity=2)
    res = api_client.run_ops(clinic["id"], _PROVIDER)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


# ─── local helper ───

def _setup_open_visit():
    """Roomed SELF_PAY visit, billing OPEN, no charges yet."""
    from test_helpers import setup_roomed_visit
    return setup_roomed_visit(clinic_overrides={"self_pay_discount_pct": 0.30})
