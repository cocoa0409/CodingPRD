"""Roster onboarding, derived restriction defaults, and role-based access control."""
from test_helpers import (
    ApiErrorId,
    create_active_license,
    create_employee,
    create_employee_payload,
    create_license,
    create_license_type,
    create_renewal_request,
    make_employee_headers,
    setup_rn_type_with_staff_nurse_requirement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]
HR = TEST_USERS["hr_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestEmployeeDerivedDefaults:
    def test_employee_in_mandatory_role_starts_restricted_missing_license(self, api):
        """PRD §3.2: "an employee whose role mandates a license they do not yet
        hold enters the roster already `RESTRICTED` with reason `MISSING_LICENSE`".

        Design: Corner/entities/employee_created_with_derived_restriction_defaults
        """
        setup_rn_type_with_staff_nurse_requirement()
        data = validate_success(api.create_employee(
            create_employee_payload(work_email="nora.ent@example.com"), HR), 201)
        assert data["work_authorization"] == "RESTRICTED"
        assert data["restriction_reason"] == "MISSING_LICENSE"

    def test_employee_defaults_and_uncovered_role_authorized(self, api):
        """PRD §3.2: "`screening_posture` starts `CLEAR`, both money counters —
        `reimbursement_committed_cents` and `reimbursement_paid_cents` — start at
        zero"; "an employee with no unmet mandatory rows enters `AUTHORIZED`".

        Design: Corner/entities/employee_created_with_derived_restriction_defaults
        """
        setup_rn_type_with_staff_nurse_requirement()
        nora = validate_success(api.create_employee(
            create_employee_payload(work_email="nora.ent2@example.com"), HR), 201)
        assert nora["screening_posture"] == "CLEAR"
        assert nora["reimbursement_committed_cents"] == 0
        assert nora["reimbursement_paid_cents"] == 0

        walt = validate_success(api.create_employee(
            create_employee_payload(full_name="Walt Warehouse",
                                    work_email="walt.ent@example.com",
                                    role_code="WAREHOUSE"), HR), 201)
        assert walt["work_authorization"] == "AUTHORIZED"
        assert walt["restriction_reason"] is None


class TestRosterValidation:
    def test_create_employee_missing_required_role_code(self, api):
        """PRD §2.8: "required fields are present, types match, enums are in range,
        numeric ranges are honored, and sanity dates (`screened_on`,
        `effective_on`, `completed_on`) are not in the future
        (`ERR_INVALID_REQUEST`)".

        Design: Corner/entities/create_employee_missing_required_role_code_returns_invalid_request
        """
        create_license_type()
        resp = api.create_employee(
            {"full_name": "No Role", "work_email": "norole@example.com"}, HR)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_duplicate_employee_email_case_insensitive(self, api):
        """PRD §3.2: "a `work_email` that is unique case-insensitively (a second
        registration differing only in letter case fails with
        `ERR_DUPLICATE_EMAIL`)".

        Design: Corner/entities/duplicate_employee_email_rejected_case_insensitive
        """
        create_employee(work_email="nora.dup@example.com")
        resp = api.create_employee(
            create_employee_payload(full_name="Nora Again",
                                    work_email="NORA.DUP@example.com"), HR)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL, 409)


class TestEmployeeListing:
    def test_list_employees_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/list_employees_pagination_envelope
        """
        create_employee(work_email="nora.page@example.com")
        create_employee(work_email="nick.page@example.com")

        page1, meta1 = validate_paginated(
            api.list_employees(OFFICER, params={"limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_employees(OFFICER, params={"limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False

    def test_employee_licenses_reverse_listing(self, api):
        """PRD §3.3: "The inventory supports listing with `employee_id`,
        `license_type_id`, `state_code`, `status`, `verification_posture`, or
        `alert_tier` filters, plus a per-employee listing of everything one
        holder carries."

        Design: Corner/entities/fk_reverse_licenses_listed_under_employee
        """
        lt = create_license_type()
        nora = create_employee(work_email="nora.fk@example.com")
        walt = create_employee(full_name="Walt Warehouse",
                               work_email="walt.fk@example.com",
                               role_code="WAREHOUSE")
        lic = create_license(nora["id"], lt["id"])

        nora_list, nora_meta = validate_paginated(
            api.list_employee_licenses(nora["id"], OFFICER))
        assert nora_meta["total_count"] == 1
        assert nora_list[0]["id"] == lic["id"]

        walt_list, walt_meta = validate_paginated(
            api.list_employee_licenses(walt["id"], OFFICER))
        assert walt_list == []
        assert walt_meta["total_count"] == 0


class TestAuthContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request whose headers are missing or whose role is not
        one of these five is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        create_employee(work_email="nora.auth@example.com")
        resp = api.list_employees({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT, 400)


class TestRbacDenials:
    def test_employee_cannot_create_license_type(self, api):
        """PRD §4: the `POST /licensing/license-types` row names only
        `ComplianceAdmin`; PRD §2.1: "A request whose role is well-formed but not
        permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/employee_cannot_create_license_type
        """
        emp = create_employee(work_email="nora.rbac1@example.com")
        from test_helpers import create_license_type_payload
        resp = api.create_license_type(create_license_type_payload(),
                                       make_employee_headers(emp["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_hrpartner_cannot_verify_license(self, api):
        """PRD §3.3: "Primary-source verification is the cadence that keeps the
        inventory trustworthy, and it is a `ComplianceOfficer` duty."
        PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/hrpartner_cannot_verify_license
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.rbac2@example.com")
        lic = create_license(emp["id"], lt["id"])

        resp = api.verify_license(lic["id"], {
            "verified_on": "2026-08-01", "source": "STATE_BOARD_API",
            "outcome": "VERIFIED",
        }, HR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_officer_cannot_void_renewal_request(self, api):
        """PRD §3.6: "Administrative cleanup is the `ComplianceAdmin`'s: voiding
        is permitted from `DRAFT`, `SUBMITTED`, `MORE_INFO`, or `APPROVED`".
        PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/officer_cannot_void_renewal_request
        """
        lt = create_license_type()
        emp = create_employee(work_email="nora.rbac3@example.com")
        lic = create_active_license(emp["id"], lt["id"])
        rr = create_renewal_request(lic["id"], 50_000)

        resp = api.void_renewal_request(rr["id"], "Officer attempting admin void",
                                        OFFICER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_employee_cannot_submit_other_employees_request(self, api):
        """PRD §2.1: "the license's `employee_id` must equal the caller's
        `X-User-ID`"; PRD §3.6: "When the actor is an `Employee`, the license
        must be their own (`ERR_UNAUTHORIZED_ROLE`)".

        Design: Corner/rbac/employee_cannot_submit_other_employees_request
        """
        lt = create_license_type()
        nora = create_employee(work_email="nora.rbac4@example.com")
        nick = create_employee(full_name="Nick Nurse",
                               work_email="nick.rbac4@example.com")
        lic = create_active_license(nora["id"], lt["id"])
        rr = create_renewal_request(lic["id"], 50_000)

        resp = api.submit_renewal_request(rr["id"], make_employee_headers(nick["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_auditor_shared_read_allowed_write_denied(self, api):
        """PRD §4: the `GET /licensing/employees` row is authorized for all roles
        while the `POST /licensing/employees` row names only `HRPartner`.
        PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_shared_read_allowed_write_denied
        """
        create_employee(work_email="nora.rbac5@example.com")

        _, meta = validate_paginated(api.list_employees(AUDITOR))
        assert meta["total_count"] == 1

        resp = api.create_employee(
            create_employee_payload(full_name="Mallory Fake",
                                    work_email="mallory@example.com"), AUDITOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
