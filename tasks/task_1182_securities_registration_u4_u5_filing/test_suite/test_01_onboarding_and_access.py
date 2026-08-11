"""Onboarding, access control, and validation-order tests (PRD Sections 2, 3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_firm,
    assert_registration_request,
    create_active_registration,
    create_active_registration_with_invoice,
    create_applicant,
    create_disclosure_event,
    create_firm,
    create_firm_applicant_request,
    create_fingerprint_submission,
    create_registration_request,
    create_submitted_request,
    get_firm,
    get_request,
    issue_renewal_invoice,
    list_exam_requirements,
    make_applicant_payload,
    make_firm_payload,
    make_registration_request_payload,
    make_user_headers,
    pass_exam_requirement,
    process_fingerprint,
    set_clock,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_EXISTENT_APPLICANT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestFirmOnboarding:
    def test_firm_creation_success_and_defaults(self, api, system_operator_headers):
        """PRD Section 3.1: "A firm record is born with `status` `ACTIVE` (the
        lifecycle also defines `SUSPENDED`) and an `open_inquiry_count` of zero".
        PRD Section 2.4: "`version` (integer): a system-managed integer that
        increments by one on every mutation."

        Design: Corner/entities/firm_creation_success_and_defaults
        """
        created = validate_success(
            api.create_firm(
                make_firm_payload(crd_number="3001", legal_name="Default Firm"),
                system_operator_headers,
            ),
            expected_status=201,
        )
        assert_firm(created)
        assert created["status"] == "ACTIVE"
        assert created["open_inquiry_count"] == 0
        assert created["version"] == 1

        fetched = validate_success(api.get_firm(created["id"], system_operator_headers))
        assert_firm(fetched)
        assert fetched["status"] == "ACTIVE"
        assert fetched["open_inquiry_count"] == 0
        assert fetched["version"] == 1

    def test_firm_crd_number_uniqueness(self, api, system_operator_headers):
        """PRD Section 3.1: "its `crd_number` — the Central Registration
        Depository number, one to seven digits and unique across all firms,
        with duplicates rejected `ERR_DUPLICATE`".

        Design: Corner/entities/firm_crd_number_uniqueness
        """
        validate_success(
            api.create_firm(
                make_firm_payload(crd_number="3002", legal_name="Dup Firm A"),
                system_operator_headers,
            ),
            expected_status=201,
        )
        resp = api.create_firm(
            make_firm_payload(crd_number="3002", legal_name="Dup Firm B"),
            system_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestApplicantOnboarding:
    def test_applicant_missing_required_field_rejected(
        self, api, registration_principal_headers
    ):
        """PRD Section 2.10 step 9: "required fields present, enum values
        inside their declared sets, minimum lengths honored ... otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/applicant_missing_required_field_rejected
        """
        resp = api.create_applicant(
            {"crd_number": "3003"}, registration_principal_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_applicant_not_found_returns_404(self, api, system_operator_headers):
        """PRD Section 2.10 step 3: "every path identifier and every body
        foreign key must resolve to an existing entity ... the first
        unresolvable reference yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/applicant_not_found_returns_404
        """
        resp = api.get_applicant(NON_EXISTENT_APPLICANT_ID, system_operator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_computed_fingerprint_required_field(self, api, system_operator_headers):
        """PRD Section 3.1: "it is derived on read and is true whenever the
        applicant has no fingerprint submission in `CLEARED` status, false
        once one exists. Every applicant starts out needing fingerprints."

        Design: Corner/entities/computed_fingerprint_required_field
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        before = validate_success(
            api.get_applicant(applicant["id"], system_operator_headers)
        )
        assert before["fingerprint_required"] is True

        fp = create_fingerprint_submission(request["id"], channel="HARD_CARD")
        process_fingerprint(fp["id"], "CLEARED")

        after = validate_success(
            api.get_applicant(applicant["id"], system_operator_headers)
        )
        assert after["fingerprint_required"] is False


class TestRegistrationRequestCreation:
    def test_registration_request_initial_state_draft(
        self, api, registration_principal_headers
    ):
        """PRD Section 3.2: "A new request enters `DRAFT` status with a
        `deficiency_count` of zero and no `submitted_at` or `approved_at` yet."

        Design: Corner/entities/registration_request_initial_state_draft
        """
        firm = create_firm(crd_number="3004", legal_name="Init Firm")
        applicant = create_applicant(
            crd_number="3005", full_name="Init Rep", date_of_birth="1980-05-05"
        )
        created = validate_success(
            api.create_registration_request(
                make_registration_request_payload(
                    applicant["id"], firm["id"], registration_category="PRINCIPAL"
                ),
                registration_principal_headers,
            ),
            expected_status=201,
        )
        assert_registration_request(created)
        assert created["status"] == "DRAFT"
        assert created["deficiency_count"] == 0
        assert created["version"] == 1

    def test_invalid_enum_value_rejected(self, api, registration_principal_headers):
        """PRD Section 2.10 step 9: "required fields present, enum values
        inside their declared sets ... otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/invalid_enum_value_rejected
        """
        firm = create_firm(crd_number="3501", legal_name="Enum Firm")
        applicant = create_applicant(
            crd_number="3502", full_name="Enum Rep", date_of_birth="1980-02-26"
        )
        resp = api.create_registration_request(
            make_registration_request_payload(
                applicant["id"], firm["id"], registration_category="BROKER"
            ),
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDisclosureFieldShape:
    def test_disclosure_explanation_min_length_enforced(
        self, api, registration_principal_headers
    ):
        """PRD Section 3.2: "when `answer` is true the `explanation_text` is
        mandatory at no fewer than 20 characters, and a short or missing
        explanation is rejected `ERR_INVALID_REQUEST`."

        Design: Corner/entities/disclosure_explanation_min_length_enforced
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        resp = api.create_background_disclosure(
            {
                "registration_request_id": request["id"],
                "question_code": "CRIMINAL",
                "answer": True,
                "explanation_text": "too short",
            },
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuthenticationAndRoles:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD Section 2.1: "A request missing either header, or presenting a
        role outside this set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.get_firm(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_on_exclusive_operation(self, api, finance_clerk_headers):
        """PRD Section 2.1: "A request whose role is authenticated but not on
        the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/validations/forbidden_role_on_exclusive_operation
        """
        resp = api.create_firm(
            make_firm_payload(crd_number="3301", legal_name="Role Firm"),
            finance_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_regulator_cannot_file_amendment(self, api, regulator_headers):
        """PRD Section 2.1: "A `Regulator` is an external examiner who can open
        regulatory inquiries and otherwise reads." PRD Section 2.1: "A request
        whose role is authenticated but not on the endpoint's authorized list
        is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/regulator_cannot_file_amendment
        """
        firm = create_firm(crd_number="3601", legal_name="Rbac Firm")
        applicant = create_applicant(
            crd_number="3602", full_name="Rbac Rep", date_of_birth="1982-04-28"
        )
        event = create_disclosure_event(
            applicant["id"], event_type="BANKRUPTCY", event_date="2026-05-01"
        )
        resp = api.create_amendment_filing(
            {
                "disclosure_event_id": event["id"],
                "narrative_text": "Regulator attempting to file an amendment directly.",
            },
            regulator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_compliance_officer_cannot_pay_invoice(self, api):
        """PRD Section 2.1: "A `FinanceClerk` issues, collects, and voids
        renewal invoices." PRD Section 2.1: "A request whose role is
        authenticated but not on the endpoint's authorized list is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/compliance_officer_cannot_pay_invoice
        """
        ctx = create_active_registration_with_invoice(
            cycle_year=2027,
            invoice_clock="2026-12-01T00:00:00Z",
            submitter_user_id="rp-rb2",
            reviewer_user_id="co-rb2",
        )
        invoice = ctx["invoice"]
        resp = api.pay_renewal_invoice(
            invoice["id"],
            {"expected_renewal_invoice_version": invoice["version"]},
            make_user_headers("co-rb2", "ComplianceOfficer"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestSegregationAndGates:
    def test_segregation_of_duties_same_user_approve(self, api):
        """PRD Section 2.9: "Six review actions require the acting
        `ComplianceOfficer`'s `X-User-ID` to differ from the `X-User-ID`
        recorded as the filer or submitter of the target: approving a
        registration request ... A violation is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/segregation_of_duties_same_user_approve
        """
        ctx = create_submitted_request(
            category="IA", jurisdictions=("CA",), submitter_user_id="rp-sod"
        )
        request = ctx["request"]
        fp = create_fingerprint_submission(request["id"])
        process_fingerprint(fp["id"], "CLEARED")
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                ctx["exams"][code]["id"],
                "2026-06-01T00:00:00Z",
                "2026-06-03T00:00:00Z",
                pass_clock="2026-06-01T00:00:00Z",
            )
        set_clock("2026-06-02T00:00:00Z")
        resp = api.approve_registration_request(
            request["id"], make_user_headers("rp-sod", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_regulatory_gate_blocks_approve_without_fingerprint(self, api):
        """PRD Section 3.5: "the gate itself ... demands all of the following
        at once: every exam requirement on the request is in `PASSED` or
        `WAIVED` status; at least one fingerprint submission for the request is
        `CLEARED`; every disclosure row with `answer` true has `review_status`
        `CLEARED`; and the applicant's `fingerprint_required` reads false."
        PRD Section 2.10 step 8: "otherwise `ERR_REGULATORY_GATE` (422)."

        Design: Corner/validations/regulatory_gate_blocks_approve_without_fingerprint
        """
        ctx = create_submitted_request(
            category="IA", jurisdictions=("CA",), submitter_user_id="rp-gt"
        )
        request = ctx["request"]
        # Fingerprint submission exists but is never processed (stays SUBMITTED).
        create_fingerprint_submission(request["id"])
        for code in ("SIE", "S66"):
            pass_exam_requirement(
                ctx["exams"][code]["id"],
                "2026-06-01T00:00:00Z",
                "2026-06-03T00:00:00Z",
                pass_clock="2026-06-01T00:00:00Z",
            )
        set_clock("2026-06-02T00:00:00Z")
        resp = api.approve_registration_request(
            request["id"], make_user_headers("co-gt", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_REGULATORY_GATE)

    def test_state_vs_business_safety_on_approve(self, api):
        """PRD Section 2.10: "when several problems exist at once, the check
        earliest in this order determines the error returned." Step 5 is
        "State legality ... otherwise `ERR_INVALID_STATE` (409)" and step 8 is
        "Regulatory gate ... otherwise `ERR_REGULATORY_GATE` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        # Request is still DRAFT: violates state legality (step 5) and would
        # also fail the regulatory gate (step 8); the state error must win.
        resp = api.approve_registration_request(
            request["id"], make_user_headers("co-prio-s", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_vs_business_safety_on_approve_from_deficient(self, api):
        """PRD Section 2.10: "when several problems exist at once, the check
        earliest in this order determines the error returned." Step 5 is
        "**State legality** (all action endpoints): the target entity's
        current status must permit the requested transition, and terminal
        states accept no further transitions — otherwise `ERR_INVALID_STATE`
        (409).", ordered ahead of step 8's regulatory gate.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-ps2"
        )
        request = ctx["request"]
        # Return once -> DEFICIENT; no fingerprint, no exams passed, so the
        # regulatory gate (step 8) would also fail on an approve attempt.
        resp = api.return_deficient_registration_request(
            request["id"], make_user_headers("co-ps2", "ComplianceOfficer")
        )
        deficient = validate_success(resp)
        assert deficient["status"] == "DEFICIENT"
        resp = api.approve_registration_request(
            request["id"], make_user_headers("co-ps2", "ComplianceOfficer")
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_vs_temporal_on_termination_filing(self, api):
        """PRD Section 2.10: "when several problems exist at once, the check
        earliest in this order determines the error returned." Step 5 is
        "State legality ... otherwise `ERR_INVALID_STATE` (409)" and step 10 is
        "Temporal rules ... no future-dated `event_date` or
        `termination_date` ... otherwise `ERR_TEMPORAL_VIOLATION` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_termination_filing
        """
        ctx = create_submitted_request(
            category="IA", jurisdictions=("WA",), submitter_user_id="rp-prio-t"
        )
        set_clock("2026-06-15T00:00:00Z")
        # Request is SUBMITTED (not ACTIVE) and the termination_date is
        # future-dated: both step 5 and step 10 fail; state must win.
        resp = api.create_termination_filing(
            {
                "registration_request_id": ctx["request"]["id"],
                "termination_reason": "VOLUNTARY",
                "termination_date": "2026-12-31",
            },
            make_user_headers("rp-prio-t", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_state_vs_temporal_on_termination_filing_from_draft(self, api):
        """PRD Section 2.10: "when several problems exist at once, the check
        earliest in this order determines the error returned." PRD Section 3.9:
        "the `termination_date`, an ISO date that may not be in the future
        relative to the server clock (a future date is rejected
        `ERR_TEMPORAL_VIOLATION`)" — but the step-5 state legality check fires
        first for a non-ACTIVE registration.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_termination_filing
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        set_clock("2026-06-15T00:00:00Z")
        # DRAFT request (step-5 violation) plus a future termination_date
        # (step-10 violation): the earlier state check must surface.
        resp = api.create_termination_filing(
            {
                "registration_request_id": request["id"],
                "termination_reason": "DISCHARGED",
                "termination_date": "2026-12-31",
            },
            make_user_headers("rp-pt2", "RegistrationPrincipal"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTemporalAndReferentialValidation:
    def test_future_event_date_rejected(self, api, registration_principal_headers):
        """PRD Section 3.6: "the `event_date`, an ISO date that may not lie in
        the future relative to the server clock (future-dating is rejected
        `ERR_TEMPORAL_VIOLATION`)."

        Design: Corner/validations/future_event_date_rejected
        """
        firm = create_firm(crd_number="3306", legal_name="Fut Firm")
        applicant = create_applicant(
            crd_number="3307", full_name="Fut Rep", date_of_birth="1995-08-20"
        )
        set_clock("2026-06-15T00:00:00Z")
        resp = api.create_disclosure_event(
            {
                "applicant_id": applicant["id"],
                "event_type": "CRIMINAL_CHARGE",
                "event_date": "2026-07-01",
            },
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_VIOLATION)

    def test_same_firm_affiliation_rejected(self, api, registration_principal_headers):
        """PRD Section 3.8: "The second firm must differ from the firm on that
        first registration — a same-firm request is rejected
        `ERR_REFERENTIAL_VIOLATION`".

        Design: Corner/validations/same_firm_affiliation_rejected
        """
        firm, applicant, request, _ = create_firm_applicant_request(
            category="RR", jurisdictions=("CA",)
        )
        resp = api.create_affiliation_request(
            {
                "applicant_id": applicant["id"],
                "second_firm_id": firm["id"],
                "first_registration_request_id": request["id"],
            },
            registration_principal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENTIAL_VIOLATION)

    def test_renewal_invoice_requires_active_registration(
        self, api, finance_clerk_headers
    ):
        """PRD Section 3.7: "Issuing against a registration that is not
        `ACTIVE` is rejected `ERR_FISCAL_VIOLATION`".

        Design: Corner/validations/renewal_invoice_requires_active_registration
        """
        ctx = create_submitted_request(
            category="RR", jurisdictions=("CA",), submitter_user_id="rp-fi"
        )
        resp = api.create_renewal_invoice(
            {
                "registration_request_id": ctx["request"]["id"],
                "cycle_year": 2027,
            },
            finance_clerk_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FISCAL_VIOLATION)
