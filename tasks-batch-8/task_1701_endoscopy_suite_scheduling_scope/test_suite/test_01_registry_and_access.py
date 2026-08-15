"""Unit registry creation, system defaults, uniqueness, 404s, and access control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    ApiErrorId,
    assert_instants_equal,
    assert_patient,
    assert_provider,
    assert_room,
    assert_scope,
    create_patient,
    create_patient_payload,
    create_procedure_type_payload,
    create_provider,
    create_provider_payload,
    create_room,
    create_scope,
    create_scope_payload,
    is_valid_uuid,
    make_registry,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["unit_admin_headers"]
SCHED = TEST_USERS["scheduler_headers"]
QO = TEST_USERS["quality_officer_headers"]
NURSE = TEST_USERS["nurse_headers"]


class TestPatientRegistration:
    def test_patient_created_with_system_defaults(self, api):
        """PRD §3.1: "An optional `contact_phone` may be recorded and stays null
        when omitted."
        PRD §2.5: "**`version`** (integer): starts at 1 when the resource is
        created and increments by exactly 1 on every mutation, including mutations
        driven by cascades originating on other entities."
        PRD §2.5: "**`id`** (string): a server-minted UUID with no type prefix,
        uniquely addressing the resource."

        Design: Corner/entities/patient_created_with_system_defaults
        """
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-1", full_name="Pat One",
                                   date_of_birth="1990-05-05"), SCHED)
        data = validate_success(resp, 201)
        assert_patient(data)
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert_instants_equal(data["updated_at"], data["created_at"], "updated_at")
        assert data["contact_phone"] is None, "contact_phone defaults to null"

    def test_patient_duplicate_mrn_rejected(self, api):
        """PRD §3.1: "Patients are registered by a `SchedulingCoordinator` or a
        `UnitAdmin`, who supply an `mrn` (the medical record number, unique across
        patients — a duplicate is refused with `ERR_PATIENT_MRN_EXISTS`)".

        Design: Corner/entities/patient_duplicate_mrn_rejected
        """
        create_patient(mrn="MRN-DUP", full_name="Pat Dup")
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-DUP", full_name="Pat Two",
                                   date_of_birth="1985-01-01"), SCHED)
        validate_error(resp, ApiErrorId.ERR_PATIENT_MRN_EXISTS)

    def test_patient_not_found_returns_404(self, api):
        """PRD §2.6: "When a path contains resource identifiers, they are validated
        from left to right, and the first identifier that fails to resolve produces
        its dedicated 404 response."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/entities/patient_not_found_returns_404
        """
        resp = api.get_patient(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_PATIENT_NOT_FOUND)
        assert isinstance(err["message"], str) and err["message"].strip()


class TestProcedureTypeAndScopeUniqueness:
    def test_procedure_type_invalid_enum_rejected(self, api):
        """PRD §2.6: "4. **Request schema** — required fields present, types valid,
        enum values in range, integer ranges honored (BBPS segment scores between
        0 and 3 inclusive, `container_count` at least 1, `base_duration_minutes`
        greater than 0, `withdrawal_time_seconds` and `adenomas_detected` at least
        0, a POSITIVE culture accompanied by its organism and colony count):
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/procedure_type_invalid_enum_rejected
        """
        resp = api.create_procedure_type(
            create_procedure_type_payload(code="BAD", prep_protocol="DEEP_CLEAN"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_procedure_type_duplicate_code_rejected(self, api):
        """PRD §3.1: "A ProcedureType describes a bookable procedure: a unique
        `code` such as COLONOSCOPY (duplicates refused with
        `ERR_PROCEDURE_TYPE_CODE_EXISTS`)".

        Design: Corner/entities/procedure_type_duplicate_code_rejected
        """
        get = api.create_procedure_type(create_procedure_type_payload(code="COLONO"),
                                        ADMIN)
        validate_success(get, 201)
        resp = api.create_procedure_type(
            create_procedure_type_payload(code="COLONO", display_name="Variant",
                                          base_duration_minutes=45), ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_TYPE_CODE_EXISTS)

    def test_scope_duplicate_serial_rejected(self, api):
        """PRD §3.1: "Scopes are registered by a `UnitAdmin` with a manufacturer
        `serial_number` (unique across scopes — duplicates are refused with
        `ERR_SERIAL_NUMBER_EXISTS`)".

        Design: Corner/entities/scope_duplicate_serial_rejected
        """
        create_scope(serial_number="SN-DUP")
        resp = api.create_scope(
            create_scope_payload(serial_number="SN-DUP", scope_type="GASTROSCOPE"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_SERIAL_NUMBER_EXISTS)

    def test_room_and_scope_defaults_on_create(self, api):
        """PRD §3.1: "A room's `status` begins as `ACTIVE`".
        PRD §3.1: "A freshly registered scope is `AVAILABLE`, has a `use_count` of
        zero, and has never been reprocessed, so both its `storage_expires_at` and
        its `awaiting_reprocess_since` are null."
        PRD §3.1: "Scope responses also expose the computed boolean
        `is_storage_current`, which is true when `storage_expires_at` is null or
        the logical now falls strictly before it."

        Design: Corner/entities/room_and_scope_defaults_on_create
        """
        room = validate_success(api.create_room(
            {"name": "R-D", "room_class": "ERCP_CAPABLE", "supports_anesthesia": False},
            ADMIN), 201)
        assert_room(room)
        assert room["status"] == "ACTIVE"

        scope = validate_success(api.create_scope(
            create_scope_payload(serial_number="SN-D", scope_type="SIGMOIDOSCOPE"),
            ADMIN), 201)
        assert_scope(scope)
        assert scope["status"] == "AVAILABLE"
        assert scope["use_count"] == 0
        assert scope["storage_expires_at"] is None
        assert scope["awaiting_reprocess_since"] is None
        assert scope["is_storage_current"] is True


class TestRegistryNotFound:
    def test_provider_not_found_returns_404(self, api):
        """PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised
        for an unresolvable `new_room_id`),
        `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`, `ERR_SCOPE_NOT_FOUND`,
        `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and
        `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/provider_not_found_returns_404
        """
        resp = api.get_provider(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)

    # NOTE on not-found citations: the full reference-mapping sentence is long;
    # each test below quotes it verbatim (C1/C3) so the asserted error id appears
    # in the citation.

    def test_procedure_type_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/procedure_type_not_found_returns_404
        """
        resp = api.get_procedure_type(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROCEDURE_TYPE_NOT_FOUND)

    def test_room_not_found_returns_404(self, api):
        """PRD §2.6: "When a path contains resource identifiers, they are validated
        from left to right, and the first identifier that fails to resolve produces
        its dedicated 404 response."

        Design: Corner/errors/room_not_found_returns_404
        """
        resp = api.get_room(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)

    def test_anesthesia_provider_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/anesthesia_provider_not_found_returns_404
        """
        resp = api.get_anesthesia_provider(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ANESTHESIA_PROVIDER_NOT_FOUND)

    def test_scope_not_found_returns_404(self, api):
        """
        PRD §2.6: "Each unresolved reference maps to its own error:
        `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
        `ERR_PROCEDURE_TYPE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND` (also raised for an
        unresolvable `new_room_id`), `ERR_ANESTHESIA_PROVIDER_NOT_FOUND`,
        `ERR_SCOPE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_SCOPE_USAGE_NOT_FOUND`,
        `ERR_REPROCESSING_CYCLE_NOT_FOUND`, `ERR_CULTURE_TEST_NOT_FOUND`,
        `ERR_QUARANTINE_CASE_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
        `ERR_QUALITY_REPORT_NOT_FOUND`, and `ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND`,
        all HTTP 404."

        Design: Corner/errors/scope_not_found_returns_404
        """
        resp = api.get_scope(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCOPE_NOT_FOUND)


class TestAccessControl:
    def test_patient_create_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/patient_create_missing_auth_header_returns_400
        """
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-NA", full_name="No Auth"), NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_missing_auth_and_wrong_role_returns_400(self, api):
        """PRD §2.6: "When a single request violates several rules, exactly one
        error surfaces, chosen by the following ladder — earlier rungs win over
        later ones:
        1. **Header presence** — missing or empty `X-User-ID` or `X-User-Role`:
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
        2. **Role authorization** — the caller's role is not permitted on the
        endpoint: `ERR_FORBIDDEN_ROLE`."

        Design: Corner/validations/missing_auth_and_wrong_role_returns_400
        """
        # No auth headers at all: the header gate must win over any role check.
        resp = api.create_provider(create_provider_payload(full_name="Dr Nobody"),
                                   NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_endoscopist_create_patient_forbidden(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/patients` | Register a patient |
        SchedulingCoordinator, UnitAdmin |"

        Design: Corner/validations/endoscopist_create_patient_forbidden
        """
        dr1 = create_provider("Dr Fb")
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-FB", full_name="Pat Fb"),
            {"X-User-ID": dr1["id"], "X-User-Role": "Endoscopist",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_unit_admin_exclusive_provider_create(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/providers` | Create an endoscopist |
        UnitAdmin |"

        Design: Corner/rbac/unit_admin_exclusive_provider_create
        """
        resp = api.create_provider(create_provider_payload(full_name="Dr X"), SCHED)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_quality_officer_cannot_create_booking(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/bookings` | Book a procedure; computes the
        time window and validates lead time, overlap, capacity, provider and room
        status | SchedulingCoordinator |"

        Design: Corner/rbac/quality_officer_cannot_create_booking
        """
        reg = make_registry(mrn="MRN-QO", serial="SC-QO")
        resp = api.create_booking(
            {"patient_id": reg["patient"]["id"], "provider_id": reg["provider"]["id"],
             "procedure_type_id": reg["ptype"]["id"], "room_id": reg["room"]["id"],
             "scheduled_start": "2026-08-03T09:00:00Z", "indication": "SCREENING",
             "anesthesia_type": "NONE"}, QO)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_infection_control_nurse_cannot_book(self, api):
        """PRD §2.1: "a caller whose role is not in the endpoint's permitted set
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/endoscopy/bookings` | Book a procedure; computes the
        time window and validates lead time, overlap, capacity, provider and room
        status | SchedulingCoordinator |"

        Design: Corner/rbac/infection_control_nurse_cannot_book
        """
        reg = make_registry(mrn="MRN-IC", serial="SC-IC")
        resp = api.create_booking(
            {"patient_id": reg["patient"]["id"], "provider_id": reg["provider"]["id"],
             "procedure_type_id": reg["ptype"]["id"], "room_id": reg["room"]["id"],
             "scheduled_start": "2026-08-03T09:00:00Z", "indication": "SCREENING",
             "anesthesia_type": "NONE"}, NURSE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestPatientPagination:
    def test_patients_list_pagination_defaults_and_offsets(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, and it accepts a minimum of 1
        and a maximum of 100. The `offset` parameter sets how many items are
        skipped and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/endpoints/patients_list_pagination_defaults_and_offsets
        """
        for i in range(1, 13):
            create_patient(mrn=f"MRN-PG-{i:02d}", full_name=f"P{i}",
                           date_of_birth="1990-01-01")

        data1, meta1 = validate_paginated(api.list_patients(ADMIN))
        assert len(data1) == 10
        assert meta1["total_count"] == 12 and meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0

        data2, meta2 = validate_paginated(api.list_patients(ADMIN, params={"offset": 10}))
        assert len(data2) == 2
        assert meta2["total_count"] == 12 and meta2["has_more"] is False

        data3, meta3 = validate_paginated(api.list_patients(ADMIN, params={"limit": 5}))
        assert len(data3) == 5
        assert meta3["total_count"] == 12 and meta3["has_more"] is True
        for data in (data1, data2, data3):
            for row in data:
                assert_patient(row)
