"""Applicant screening, PRIA records pipeline, auth envelopes, and the clock."""
import re

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_applicant,
    assert_same_instant,
    create_applicant_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_records_request,
    drive_records_request_to_verified,
    issue_first_class_medical,
    make_applicant,
    make_cleared_applicant,
    run_daily_scan,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

REC = TEST_USERS["recruiter_headers"]


class TestApplicantCreation:
    def test_create_applicant_returns_201_with_initial_state(self, api):
        """PRD §3.1: "New applicants start in `SCREENING`, with
        `seniority_number`, `current_equipment_id`, and `cleared_at` all null
        and `ledger_balance_cents` at zero."
        PRD §2.5: "an integer `version` that starts at 1 on creation and
        increments by one whenever the resource mutates."

        Design: Corner/entities/create_applicant_success_returns_201_and_initial_state
        """
        resp = api.create_applicant(
            create_applicant_payload(full_name="Ini Tial", email="init@x.com",
                                     license_number="L400",
                                     total_flight_hours=1800), REC)
        applicant = validate_success(resp, 201)
        assert_applicant(applicant)
        assert applicant["status"] == "SCREENING", "A new applicant starts SCREENING"
        assert applicant["version"] == 1, "version starts at 1"
        assert applicant["ledger_balance_cents"] == 0
        assert applicant["seniority_number"] is None
        assert applicant["current_equipment_id"] is None
        assert applicant["cleared_at"] is None

        fetched = validate_success(api.get_applicant(applicant["id"], REC))
        assert fetched["status"] == "SCREENING"
        assert fetched["version"] == 1

    def test_create_applicant_missing_required_field_returns_400(self, api):
        """PRD §3.1: "A `Recruiter` opens a file by creating an applicant with
        `full_name`, `email`, `license_number`, and `total_flight_hours`."
        PRD §2.8: "(16) the constraint band — malformed input, uniqueness rules,
        phase discipline, attempt ceilings, and slot-booking blocks"

        Design: Corner/entities/create_applicant_missing_required_field_returns_400
        """
        payload = {"full_name": "No Hours", "email": "noh@x.com",
                   "license_number": "L401"}
        resp = api.create_applicant(payload, REC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _data, meta = validate_paginated(api.list_applicants(REC))
        assert meta["total_count"] == 0, "The rejected create must not persist"

    def test_applicant_computed_fields_ignore_client_input(self, api):
        """PRD §3.1: "New applicants start in `SCREENING`, with
        `seniority_number`, `current_equipment_id`, and `cleared_at` all null
        and `ledger_balance_cents` at zero."
        PRD §2.5: "Every resource carries an `id` — a server-minted UUID with
        no type prefix"

        Design: Corner/entities/applicant_computed_fields_ignore_client_input
        """
        resp = api.create_applicant(
            create_applicant_payload(full_name="Sneaky Pete", email="snek@x.com",
                                     license_number="L402",
                                     total_flight_hours=2000), REC)
        applicant = validate_success(resp, 201)
        assert applicant["seniority_number"] is None, (
            "seniority_number is system-computed and starts null")
        assert applicant["ledger_balance_cents"] == 0
        assert is_valid_uuid(applicant["id"]), "id is a server-minted bare UUID"
        assert is_iso8601_timestamp(applicant["created_at"])

    def test_get_nonexistent_applicant_returns_per_entity_404(self, api):
        """PRD §2.8: "with the per-entity codes `ERR_APPLICANT_NOT_FOUND`,
        `ERR_RECORDS_REQUEST_NOT_FOUND`, `ERR_TRAINING_CLASS_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_TRAINING_EVENT_NOT_FOUND`,
        `ERR_CHECKRIDE_NOT_FOUND`, `ERR_QUALIFICATION_NOT_FOUND`,
        `ERR_MEDICAL_CERTIFICATE_NOT_FOUND`, and `ERR_BID_PERIOD_NOT_FOUND`
        (all 404) taking precedence where declared"

        Design: Corner/entities/get_nonexistent_entities_return_per_entity_404
        """
        resp = api.get_applicant(NON_EXISTENT_UUID, REC)
        validate_error(resp, ApiErrorId.ERR_APPLICANT_NOT_FOUND)

    def test_invalid_request_type_enum_rejected(self, api):
        """PRD §3.1: "Each records request is created with an `applicant_id`
        and a `request_type` of `PRIA`, `DRUG_TEST`, or `TRAINING_HISTORY`, and
        starts in `DRAFT`."
        PRD §2.8: "(16) the constraint band — malformed input, uniqueness rules,
        phase discipline, attempt ceilings, and slot-booking blocks"

        Design: Corner/entities/invalid_enum_value_rejected
        """
        ap = make_applicant("enum@x.com", "L403", full_name="Enum Test")
        resp = api.create_records_request(
            {"applicant_id": ap["id"], "request_type": "NOT_A_TYPE"}, REC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_email_rejected(self, api):
        """PRD §3.1: "The email must be a well-formed RFC-5322 address and
        unique across all applicants; a duplicate is rejected with
        `ERR_DUPLICATE_EMAIL` (409)."

        Design: Corner/entities/duplicate_email_rejected
        """
        first = api.create_applicant(
            create_applicant_payload(full_name="First Dup", email="dup@x.com",
                                     license_number="L404"), REC)
        validate_success(first, 201)
        resp = api.create_applicant(
            create_applicant_payload(full_name="Second Dup", email="dup@x.com",
                                     license_number="L405"), REC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestEnvelopesAndPagination:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a data
        object carrying "`error_id`" and "`message`".
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_applicant(NON_EXISTENT_UUID, REC)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_APPLICANT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        # PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601
        # UTC timestamp with three fractional digits."
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
                        body["meta"]["api_request_timestamp"]), (
            "meta.api_request_timestamp carries three fractional digits")

    def test_list_applicants_pagination_defaults(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        defaulting to 10 with a minimum of 1 and a maximum of 100, and
        `offset`, defaulting to 0. List responses report `limit`, `offset`,
        `total_count`, and `has_more` inside the `meta` envelope."

        Design: Corner/endpoints/list_applicants_pagination_defaults
        """
        make_applicant("pg1@x.com", "L450", full_name="Pg One")
        make_applicant("pg2@x.com", "L451", full_name="Pg Two")
        resp = api.list_applicants(REC)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "limit defaults to 10"
        assert meta["offset"] == 0, "offset defaults to 0"
        assert len(data) == 2

    def test_writes_visible_immediately_in_same_response(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.1: "A successful advance refreshes the applicant's `updated_at`
        and increments `version`."

        Design: Corner/consistency_model/writes_visible_immediately_in_same_response
        """
        ap = make_applicant("imm@x.com", "L480", full_name="Imm Ed")
        data = validate_success(api.advance_screening(ap["id"], REC))
        assert data["status"] == "PRIA_PENDING", (
            "The mutation response itself carries the new state")
        assert data["version"] == 2, "version 1 at creation, incremented on advance"

        fetched = validate_success(api.get_applicant(ap["id"], REC))
        assert fetched["status"] == "PRIA_PENDING"
        assert fetched["version"] == 2, "A subsequent read agrees"


class TestLogicalClock:
    def test_logical_clock_default_is_fixed(self, api):
        """PRD §2.4: "Before any clock-setting call, the logical clock starts
        at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock
        time afterwards."
        PRD §3.1: "Sending moves the request `DRAFT` → `SENT`, stamps `sent_at`
        with the current logical time, and computes `due_at` as thirty days
        after `sent_at` — the regulatory response window."

        Design: Corner/cross_cutting_layers/logical_clock_default_is_fixed
        """
        ap = make_applicant("clk@x.com", "L472", full_name="Clk Def")
        rr = make_records_request(ap["id"], "PRIA")
        sent = validate_success(api.send_records_request(rr["id"], REC))
        assert_same_instant(sent["sent_at"], "2026-08-01T00:00:00Z",
                            "sent_at reflects the pinned startup clock")
        assert_same_instant(sent["due_at"], "2026-08-31T00:00:00Z",
                            "due_at is thirty days after sent_at")


class TestApplicantStateMachine:
    def test_terminal_withdrawn_lockdown(self, api):
        """PRD §3.1: "Withdrawal moves the same three pre-clear states to
        `WITHDRAWN`, which is terminal"
        PRD §3.1: "Any applicant action attempted from a disallowed state —
        clearing from `SCREENING`, advancing a `CLEARED` applicant, and so on —
        is rejected with `ERR_APPLICANT_INVALID_STATE`."

        Design: Corner/state_machines/applicant_terminal_withdrawn_lockdown
        """
        ap = make_applicant("wil@x.com", "L410", full_name="Wil Tara")
        withdrawn = validate_success(api.withdraw_applicant(ap["id"], REC))
        assert withdrawn["status"] == "WITHDRAWN"
        resp = api.advance_screening(ap["id"], REC)
        validate_error(resp, ApiErrorId.ERR_APPLICANT_INVALID_STATE)

    def test_appeal_loop_rejected_to_screening(self, api):
        """PRD §3.1: "Appeal loops `REJECTED` → `SCREENING`, and an applicant
        may cycle through rejection and appeal repeatedly."

        Design: Corner/state_machines/applicant_appeal_loop_rejected_to_screening
        """
        ap = make_applicant("app@x.com", "L411", full_name="App Eal")
        rejected = validate_success(api.reject_applicant(ap["id"], REC, reason="docs"))
        assert rejected["status"] == "REJECTED"
        appealed = validate_success(api.appeal_applicant(ap["id"], REC))
        assert appealed["status"] == "SCREENING", "The appeal loop closes"

    def test_advance_screening_hours_boundary_1499_vs_1500(self, api):
        """PRD §3.1: "Advancement from `SCREENING` to `PRIA_PENDING` is gated
        on the ATP minimum: `total_flight_hours` must be at least 1,500."
        PRD §3.1: "and only then the hours gate, which rejects a short
        applicant with `ERR_INSUFFICIENT_FLIGHT_HOURS` (422)."

        Design: Corner/validations/advance_screening_hours_boundary_1499_vs_1500
        """
        low = make_applicant("low@x.com", "L430", full_name="Low Hrs", hours=1499)
        exact = make_applicant("min@x.com", "L431", full_name="Min Hrs", hours=1500)

        resp_low = api.advance_screening(low["id"], REC)
        validate_error(resp_low, ApiErrorId.ERR_INSUFFICIENT_FLIGHT_HOURS)
        assert validate_success(api.get_applicant(low["id"], REC))["status"] == "SCREENING"

        advanced = validate_success(api.advance_screening(exact["id"], REC))
        assert advanced["status"] == "PRIA_PENDING", "1,500 hours meets the gate"


class TestRecordsPipeline:
    def test_verify_before_receive_rejected(self, api):
        """PRD §3.1: "Verification moves `RECEIVED` → `VERIFIED`."
        PRD §3.1: "Each of these actions requires the request to sit in the
        stated from-state, otherwise `ERR_RECORDS_REQUEST_INVALID_STATE` (409),
        and each increments the request's `version`."

        Design: Corner/state_machines/records_request_verify_before_receive_rejected
        """
        ap = make_applicant("rec@x.com", "L412", full_name="Rec Ord")
        rr = make_records_request(ap["id"], "PRIA")
        sent = validate_success(api.send_records_request(rr["id"], REC))
        assert sent["status"] == "SENT"
        resp = api.verify_records_request(rr["id"], REC)
        validate_error(resp, ApiErrorId.ERR_RECORDS_REQUEST_INVALID_STATE)

    def test_send_stamps_due_at_plus_30_days(self, api):
        """PRD §3.1: "Sending moves the request `DRAFT` → `SENT`, stamps
        `sent_at` with the current logical time, and computes `due_at` as
        thirty days after `sent_at` — the regulatory response window."

        Design: Corner/state_machines/records_request_send_stamps_due_at_plus_30_days
        """
        ap = make_applicant("due@x.com", "L413", full_name="Due At")
        rr = make_records_request(ap["id"], "DRUG_TEST")
        sent = validate_success(api.send_records_request(rr["id"], REC))
        assert sent["status"] == "SENT"
        assert_same_instant(sent["sent_at"], "2026-08-01T00:00:00Z",
                            "sent_at is the current logical time")
        assert_same_instant(sent["due_at"], "2026-08-31T00:00:00Z",
                            "due_at is sent_at + 30 days")

    def test_records_request_expires_via_daily_scan(self, api):
        """PRD §3.1: "Independently of operator action, the daily scan expires
        any request still `SENT` once the logical clock passes its `due_at`."

        Design: Corner/state_machines/records_request_expires_via_daily_scan
        """
        ap = make_applicant("exp@x.com", "L414", full_name="Exp Ire")
        rr = make_records_request(ap["id"], "PRIA")
        validate_success(api.send_records_request(rr["id"], REC))
        set_clock("2026-09-01T00:00:00Z")
        run_daily_scan()
        after = validate_success(api.get_records_request(rr["id"], REC))
        assert after["status"] == "EXPIRED", (
            "2026-09-01 is past due_at 2026-08-31, so the scan expires it")


class TestClearGate:
    def test_clear_with_unverified_records_returns_records_incomplete(self, api):
        """PRD §3.1: "Its checks run in a fixed order: first, every records
        request for the applicant must be `VERIFIED` with at least one `PRIA`
        request present, otherwise the clear is rejected with
        `ERR_RECORDS_INCOMPLETE` (409); then a valid first-class medical must
        exist — a certificate with `cert_class` `FIRST` and status `VALID` —
        otherwise the rejection is `ERR_NO_VALID_MEDICAL` (422)."
        PRD §2.8: the from-state guard (priority 4) runs before the clear-gate
        referential checks (priority 9), so the records gate is observable only
        from `PRIA_VERIFIED` — a fresh DRAFT request re-opens the file.

        Design: Corner/validations/clear_with_unverified_records_returns_records_incomplete
        """
        ap = make_applicant("inc@x.com", "L432", full_name="Inc Omplete")
        get_success_data(api.advance_screening(ap["id"], REC))
        rr = make_records_request(ap["id"], "PRIA")
        drive_records_request_to_verified(rr["id"])
        assert validate_success(api.get_applicant(ap["id"], REC))["status"] == (
            "PRIA_VERIFIED"), "Setup: the verified file bubbled the applicant up"
        # A fresh DRAFT request makes the file incomplete again while the
        # applicant stays PRIA_VERIFIED, so the records gate (not the
        # from-state guard) is the check that fires on clear.
        make_records_request(ap["id"], "DRUG_TEST")
        # A VALID first-class medical exists, so only the records gate can fire.
        issue_first_class_medical(ap["id"])
        resp = api.clear_applicant(ap["id"], REC)
        validate_error(resp, ApiErrorId.ERR_RECORDS_INCOMPLETE)

    def test_clear_without_medical_returns_no_valid_medical(self, api):
        """PRD §3.1: "then a valid first-class medical must exist — a
        certificate with `cert_class` `FIRST` and status `VALID` — otherwise
        the rejection is `ERR_NO_VALID_MEDICAL` (422)."

        Design: Corner/validations/clear_without_medical_returns_no_valid_medical
        """
        ap = make_applicant("nom@x.com", "L433", full_name="No Med")
        get_success_data(api.advance_screening(ap["id"], REC))
        rr = make_records_request(ap["id"], "PRIA")
        drive_records_request_to_verified(rr["id"])
        verified = validate_success(api.get_applicant(ap["id"], REC))
        assert verified["status"] == "PRIA_VERIFIED"
        resp = api.clear_applicant(ap["id"], REC)
        validate_error(resp, ApiErrorId.ERR_NO_VALID_MEDICAL)

    def test_seniority_assignment_is_sequential_per_clear_order(self, api):
        """PRD §3.1: "A successful clear stamps `cleared_at` with the current
        logical time and runs seniority assignment: `seniority_number` becomes
        one plus the count of applicants who already hold a seniority number,
        producing a gapless sequence that is never renumbered afterwards, and
        the applicant's `version` increments."

        Design: Corner/calculations/seniority_assignment_is_sequential_per_clear_order
        """
        first = make_cleared_applicant("snr1@x.com", "L423",
                                       full_name="Sen First")
        assert first["seniority_number"] == 1, "First clear takes seniority 1"
        assert first["cleared_at"] is not None
        second = make_cleared_applicant("snr2@x.com", "L424",
                                        full_name="Sen Second")
        assert second["seniority_number"] == 2, (
            "Assignment order follows clear order, never id")
