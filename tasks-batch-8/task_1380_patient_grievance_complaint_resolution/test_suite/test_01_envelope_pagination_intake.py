"""Envelope shape, pagination, case intake rules, and intake-side RBAC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_patient_case,
    create_case,
    create_case_payload,
    create_holiday_payload,
    create_staff,
    create_unit,
    create_unit_payload,
    get_success_data,
    make_advocate_headers,
    make_director_headers,
    make_investigator_headers,
    register_holiday,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestEnvelopeShape:
    def test_success_envelope_on_detail_read(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." and "The `api_request_id`
        is a server-generated unique identifier for the request that starts
        with `req_`."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        unit = create_unit("ED", "EMERGENCY")
        resp = api.get_unit(unit["id"], ADMIN)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == unit["id"]
        assert body["data"]["name"] == "ED"

    def test_error_envelope_on_missing_unit(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        resp = api.get_unit(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_UNIT_NOT_FOUND"
        assert isinstance(body["data"].get("message"), str)
        assert body["data"]["message"]


class TestPagination:
    def test_list_pagination_envelope_fields(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items;
        when omitted it defaults to 10, and it must lie between a minimum of 1
        and a maximum of 100. The `offset` parameter states how many items to
        skip and defaults to 0." and "The `meta` object of a list response
        carries the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/list_pagination_envelope_fields
        """
        create_unit("Unit A", "ICU")
        create_unit("Unit B", "INPATIENT")
        create_unit("Unit C", "OUTPATIENT")

        page1, meta1 = validate_paginated(
            api.list_units(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_units(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        all_items, meta3 = validate_paginated(api.list_units(ADMIN))
        assert len(all_items) == 3, "omitted limit must apply the default of 10"
        assert meta3["limit"] == 10


class TestCaseIntake:
    def test_case_create_returns_201_with_defaults_and_initial_state(self, api):
        """PRD §3.2: "A successfully registered case is born with
        `lifecycle_status` `INTAKE` and `classification` `UNCLASSIFIED`, and the
        unit's `open_case_count` rises by one." PRD §3.2: "Three optional flags
        shape everything downstream: `alleged_abuse_flag` and
        `vulnerable_patient_flag` (both false unless supplied) and
        `severity_tier` (`STANDARD` unless the coordinator selects `URGENT` or
        `CRITICAL`)."

        Design: Corner/entities/case_create_returns_201_with_defaults_and_initial_state
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED Main", "EMERGENCY")
        resp = api.create_case(
            create_case_payload(patient_ref="P-0001", unit_id=unit["id"],
                                received_at="2026-08-03T09:00:00.000Z",
                                description="Waiting room concern"),
            INTAKE)
        case = validate_success(resp, expected_status=201)
        assert_patient_case(case)
        assert case["severity_tier"] == "STANDARD"
        assert case["classification"] == "UNCLASSIFIED"
        assert case["lifecycle_status"] == "INTAKE"
        assert case["alleged_abuse_flag"] is False
        assert case["vulnerable_patient_flag"] is False
        assert case["reopen_count"] == 0
        assert case["outstanding_recovery_cents"] == 0

        unit_after = get_success_data(api.get_unit(unit["id"], INTAKE))
        assert unit_after["open_case_count"] == 1, (
            "unit open_case_count must rise by one on intake")

    def test_case_create_missing_required_field(self, api):
        """PRD §2.6: "Domain-specific rejections above take precedence over
        generic shape errors whenever both were detectable without the
        malformed field; missing required fields, however, are reported at 400
        before existence checks on the dependent references those fields would
        carry." PRD §2.6: "Required fields present, enum values inside their
        declared sets, integer ranges respected — `ERR_INVALID_REQUEST`,
        `ERR_INVALID_ENUM`, or `ERR_FOLLOWUP_SCORE_INVALID` (HTTP 400, and 422
        for the score)."

        Design: Corner/entities/case_create_missing_required_field
        """
        set_clock("2026-08-03T10:00:00.000Z")
        payload = create_case_payload(patient_ref="P-0002",
                                      received_at="2026-08-03T09:00:00.000Z",
                                      description="No unit supplied")
        assert "unit_id" not in payload
        resp = api.create_case(payload, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_case_not_found_returns_404(self, api):
        """PRD §2.11: "The not-found catalogue is: `ERR_CASE_NOT_FOUND`,
        `ERR_UNIT_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`,
        `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_INVESTIGATION_NOT_FOUND`, `ERR_NOTE_NOT_FOUND`,
        `ERR_LETTER_NOT_FOUND`, `ERR_RECOVERY_NOT_FOUND`,
        `ERR_ESCALATION_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_ROUNDING_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_FOLLOWUP_NOT_FOUND`, `ERR_SUSPENSION_NOT_FOUND`,
        `ERR_SNAPSHOT_NOT_FOUND`, and `ERR_HOLIDAY_NOT_FOUND`."

        Design: Corner/entities/get_case_not_found_returns_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, INTAKE)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)

    def test_filtered_list_by_unit_id(self, api):
        """PRD §3.2: "The case list supports filtering by `unit_id`,
        `lifecycle_status`, `classification`, `grievance_category`, and
        `current_classification_decision_id`."

        Design: Corner/endpoints/filtered_list_by_unit_id
        """
        set_clock("2026-08-03T10:00:00.000Z")
        u1 = create_unit("ED", "EMERGENCY")
        u2 = create_unit("ICU", "ICU")
        create_case(u1["id"], patient_ref="P-0401", channel="PHONE",
                    description="ED case", received_at="2026-08-03T09:00:00.000Z")
        create_case(u2["id"], patient_ref="P-0402", channel="EMAIL",
                    description="ICU case", received_at="2026-08-03T09:00:00.000Z")

        data, meta = validate_paginated(
            api.list_cases(INTAKE, params={"unit_id": u1["id"]}))
        assert len(data) == 1
        assert data[0]["unit_id"] == u1["id"]
        assert meta["total_count"] == 1

    def test_holiday_duplicate_date_rejected(self, api):
        """PRD §3.1: "Registering a `HolidayObservance` takes an
        `observance_date` in `YYYY-MM-DD` form and a `name`; a second
        observance on the same date is rejected with `ERR_DUPLICATE_HOLIDAY`."

        Design: Corner/entities/holiday_duplicate_date_rejected
        """
        register_holiday("2026-09-07", "Labor Day")
        resp = api.create_holiday(
            create_holiday_payload(observance_date="2026-09-07",
                                   name="Duplicate Entry"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOLIDAY)


class TestIntakeRbac:
    def test_create_case_missing_auth_header(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/create_case_missing_auth_header
        """
        resp = api.create_case(
            create_case_payload(patient_ref="P-0301", unit_id="any",
                                received_at="2026-08-03T09:00:00.000Z",
                                description="No headers sent"),
            headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_unit_create_by_advocate_forbidden(self, api):
        """PRD §2.1: "Authorization is then checked against the endpoint's
        permitted role list; a caller whose role is not listed is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/validations/unit_create_by_advocate_forbidden
        """
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        resp = api.create_unit(create_unit_payload(name="Rogue Unit", category="ICU"),
                               make_advocate_headers(adv["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_auditor_create_case_forbidden(self, api):
        """PRD §2.1: "Authorization is then checked against the endpoint's
        permitted role list; a caller whose role is not listed is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_create_case_forbidden
        """
        unit = create_unit("ED", "EMERGENCY")
        resp = api.create_case(
            create_case_payload(patient_ref="P-0501", unit_id=unit["id"],
                                received_at="2026-08-01T00:00:00.000Z",
                                description="Auditor attempt"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_entity_backed_role_without_capability_unauthorized(self, api):
        """PRD §2.1: "When `X-User-Role` is `PatientAdvocate`,
        `DepartmentInvestigator`, `QualityRiskOfficer`, or
        `PatientRelationsDirector`, `X-User-ID` is the `id` of the acting
        `StaffMember`, and that staff member's `capabilities` must contain the
        mapped capability — `ADVOCATE` for `PatientAdvocate`, `INVESTIGATOR`
        for `DepartmentInvestigator`, `QRO` for `QualityRiskOfficer`, and
        `DIRECTOR` for `PatientRelationsDirector` — or authorization fails with
        `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/entities/entity_backed_role_without_capability_unauthorized
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED Main", "EMERGENCY")
        adv = create_staff("Ally Advocate", ["ADVOCATE"])
        case = create_case(unit["id"], patient_ref="P-0006", channel="EMAIL",
                           description="Concern",
                           received_at="2026-08-03T09:00:00.000Z")
        resp = api.create_investigation(case["id"],
                                        make_investigator_headers(adv["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_received_at_in_future_rejected(self, api):
        """PRD §3.2: "A `received_at` that lies ahead of the logical clock is
        rejected with `ERR_RECEIVED_AT_IN_FUTURE`."

        Design: Corner/validations/received_at_in_future_rejected
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ED", "EMERGENCY")
        resp = api.create_case(
            create_case_payload(patient_ref="P-0314", unit_id=unit["id"],
                                received_at="2026-08-04T09:00:00.000Z",
                                description="Future-dated concern"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_RECEIVED_AT_IN_FUTURE)


class TestRestrictedUnitIntake:
    def test_intake_rejected_on_restricted_unit(self, api):
        """PRD §3.2: "Intake on a unit whose posture is `RESTRICTED` is
        rejected with `ERR_UNIT_IN_RESTRICTED_POSTURE`."

        Design: Difficulty/cross_entity_state_dependency/intake_rejected_on_restricted_unit
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("L&D", "INPATIENT")
        director = create_staff("Dana Director", ["DIRECTOR"])
        patched = get_success_data(api.patch_unit(
            unit["id"], {"posture": "RESTRICTED"},
            make_director_headers(director["id"])))
        assert patched["posture"] == "RESTRICTED"

        resp = api.create_case(
            create_case_payload(patient_ref="P-9003", unit_id=unit["id"],
                                received_at="2026-08-03T09:00:00.000Z",
                                description="Visitor policy concern"),
            INTAKE)
        validate_error(resp, ApiErrorId.ERR_UNIT_IN_RESTRICTED_POSTURE)

    def test_intake_accepted_after_posture_restored(self, api):
        """PRD §3.2: "Intake on a unit whose posture is `RESTRICTED` is
        rejected with `ERR_UNIT_IN_RESTRICTED_POSTURE`. A successfully
        registered case is born with `lifecycle_status` `INTAKE` and
        `classification` `UNCLASSIFIED`, and the unit's `open_case_count` rises
        by one."

        Design: Difficulty/cross_entity_state_dependency/intake_rejected_on_restricted_unit
        """
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("L&D", "INPATIENT")
        director = create_staff("Dana Director", ["DIRECTOR"])
        get_success_data(api.patch_unit(unit["id"], {"posture": "RESTRICTED"},
                                        make_director_headers(director["id"])))
        get_success_data(api.patch_unit(unit["id"], {"posture": "STANDARD"},
                                        make_director_headers(director["id"])))

        resp = api.create_case(
            create_case_payload(patient_ref="P-9004", unit_id=unit["id"],
                                received_at="2026-08-03T09:00:00.000Z",
                                description="Visitor policy concern retry"),
            INTAKE)
        case = validate_success(resp, expected_status=201)
        assert case["lifecycle_status"] == "INTAKE"
        unit_after = get_success_data(api.get_unit(unit["id"], INTAKE))
        assert unit_after["open_case_count"] == 1
