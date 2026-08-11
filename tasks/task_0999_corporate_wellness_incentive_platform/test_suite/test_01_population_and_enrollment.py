"""Population onboarding, enrollment creation defaults, and read-back (PRD §3.1–§3.3)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_employer,
    assert_enrollment,
    create_employee,
    create_employee_payload,
    create_employer,
    create_employer_payload,
    create_enrollment,
    make_employee_headers,
    setup_employer_with_program,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BA = TEST_USERS["benefits_admin_headers"]


class TestEmployerOnboarding:
    def test_employer_creation_echoes_config(self, api):
        """PRD §3.1: "A `PlatformAdmin` creates an Employer with its legal `name` and
        the eight financial and policy parameters that govern everything downstream:
        `annual_self_only_premium_cents`, the annual self-only medical premium that
        forms the basis of the award cap; ... `k_anonymity_threshold`, the minimum
        cohort size for de-identified reporting; `kiosk_capacity`, the maximum number
        of overlapping biometric-screening appointments permitted per clinic
        location; and `invoice_approval_limit_cents`, above which invoice approvals
        demand an explicit override." (all eight inputs read back verbatim)

        Design: Corner/entities/employer_creation_echoes_config
        """
        created = validate_success(
            api.create_employer(create_employer_payload(), ADMIN), 201
        )
        assert_employer(created)

        fetched = validate_success(api.get_employer(created["id"], ADMIN), 200)
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "Acme"
        assert fetched["annual_self_only_premium_cents"] == 120000
        assert fetched["tobacco_surcharge_cents"] == 50000
        assert fetched["pmpm_fee_cents"] == 10000
        assert fetched["coaching_session_fee_cents"] == 7500
        assert fetched["k_anonymity_threshold"] == 5
        assert fetched["kiosk_capacity"] == 2
        assert fetched["invoice_approval_limit_cents"] == 5000


class TestEmployeeCreation:
    def test_employee_create_missing_required_email_rejected(self, api):
        """PRD §3.1: "Each Employee record carries the `employer_id` of its tenant, a
        work `email` that must be unique within that employer, the member's
        `full_name`, a `department` code that later serves as the report cohort
        filter, a `hire_date` in ISO date form, and a `tobacco_attested` flag
        capturing self-attested tobacco use, which defaults to false when omitted."
        PRD §2.6: "the request body satisfies the endpoint's input schema — required
        fields present, values well-formed, enum members valid, and any
        end-after-start ordering respected; foreign-key fields in the body
        reference existing resources. ... body-schema failures yield
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/employee_create_missing_required_email_rejected
        """
        employer = create_employer()
        payload = create_employee_payload(employer["id"])
        del payload["email"]
        res = api.create_employee(payload, BA)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(api.list_employer_employees(employer["id"], BA))
        assert data == [], "a rejected creation must not persist an employee"
        assert meta["total_count"] == 0


class TestEnrollmentDefaults:
    def test_enrollment_defaults_applied_on_create(self, api):
        """PRD §3.3: "A `BenefitsAdmin` creates an Enrollment from a `program_id` and
        an `employee_id`, optionally setting `ra_eligible` — the
        reasonable-alternative medical-waiver flag, which defaults to false and may
        be established only at creation."
        PRD §3.3: "The first axis, `participation_status`, begins at `INVITED` and is
        terminal at `TERMINATED`."
        PRD §3.3: "The second axis, `verification_status`, begins at `PENDING` and is
        driven entirely by health events rather than by explicit calls."
        PRD §3.3: "all three begin at zero on a fresh enrollment."

        Design: Corner/entities/enrollment_defaults_applied_on_create
        """
        employer, program = setup_employer_with_program(activate=False)
        employee = create_employee(employer["id"])
        enrollment = validate_success(
            api.create_enrollment(
                {"program_id": program["id"], "employee_id": employee["id"]}, BA
            ),
            201,
        )
        assert_enrollment(enrollment)
        assert enrollment["ra_eligible"] is False
        assert enrollment["participation_status"] == "INVITED"
        assert enrollment["verification_status"] == "PENDING"
        assert enrollment["points_balance_provisional"] == 0
        assert enrollment["points_balance_settled"] == 0
        assert enrollment["auto_referral_count"] == 0


class TestProgramRetrieval:
    def test_program_get_not_found_returns_404(self, api):
        """PRD §2.6: "Missing path resources yield `ERR_NOT_FOUND`; body-schema
        failures yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/program_get_not_found_returns_404
        """
        res = api.get_program(NON_EXISTENT_UUID, BA)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestEnrollmentAcceptOwnership:
    def test_employee_cannot_accept_others_enrollment(self, api):
        """PRD §3.3: "Acceptance is the member's own act: the invited member
        transitions `INVITED → ACTIVE`, but only while the program itself is
        `ACTIVE` (otherwise `ERR_PROGRAM_NOT_ACTIVE`) and only when the caller is
        that member — the caller's `X-User-ID` must equal the enrollment's
        `employee_id`, otherwise `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/employee_cannot_accept_others_enrollment
        """
        employer, program = setup_employer_with_program()
        employee_1 = create_employee(employer["id"], n=1)
        employee_2 = create_employee(employer["id"], n=2)
        enrollment = create_enrollment(program["id"], employee_1["id"])

        res = api.accept_enrollment(
            enrollment["id"], make_employee_headers(employee_2["id"])
        )
        validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH, expected_status=403)

        after = validate_success(api.get_enrollment(enrollment["id"], BA), 200)
        assert after["participation_status"] == "INVITED", (
            "rejected acceptance must not change participation_status"
        )
