"""Role lists, tenant isolation and the authentication layer ahead of everything."""

from test_helpers import (
    AcademicStatus,
    AgreementStatus,
    EligibilityStatus,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    FundingModel,
    FundingStatus,
    JobFamily,
    Scenario,
    assert_versioned_record,
    build_vantage_reimbursement_enrolled,
    employer_payload,
    make_benefit_administrator_headers,
    make_coach_headers,
    make_employee_headers,
    make_headers_with_unknown_role,
    make_headers_without_role,
    make_platform_admin_headers,
    make_school_partner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_EMPLOYER_ID = "33333333-3333-4333-8333-333333333333"


def test_a_school_partner_cannot_activate_the_agreement_it_appears_in(api):
    """Being named in the agreement is not authority to activate it.

    PRD §2.1: "If the headers are well-formed but the acting role is not listed
    among the endpoint's authorized roles in §4, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/school_partner_cannot_activate_a_partner_agreement
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.register_school()
    s.draft_agreement(
        negotiated_discount_pct=0.20,
        direct_bill_enabled=True,
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    validate_error(
        api.activate_partner_agreement(s.agreement_id, s.school_partner),
        ERR_UNAUTHORIZED,
        403,
    )
    untouched = s.read_agreement()
    assert untouched["status"] == AgreementStatus.PENDING
    assert_versioned_record(untouched, expected_version=1)

    activated = validate_success(
        api.activate_partner_agreement(s.agreement_id, s.benefit_admin)
    )
    assert activated["status"] == AgreementStatus.ACTIVE


def test_one_employers_administrator_cannot_read_another_employers_employee(api):
    """Cross-tenant ownership failure is 403, not the 404 an unknown id would give.

    PRD §2.1: "When `X-User-Role` is `BenefitAdministrator`, `X-User-ID` is the
    `id` of the acting `Employer`; ownership checks on any resource that references
    an `Employer` compare the resource's employer foreign-key field to
    `X-User-ID`."

    PRD §2.1: "An ownership-scope violation by an entity-backed role is reported as
    `ERR_UNAUTHORIZED` (HTTP 403), the same code as a role that is not permitted on
    the endpoint at all."

    Design: Corner/rbac/benefit_administrator_cannot_read_another_employers_employee
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )
    s.draft_policy(
        effective_from="2026-01-01",
        effective_to="2027-01-01",
        min_tenure_months=6,
        min_weekly_hours=20,
        eligible_job_families=[JobFamily.OPERATIONS],
        annual_cap_cents=1_000_000,
        funding_model=FundingModel.HYBRID,
        reimbursement_pct=0.50,
    )
    s.activate_policy()
    s.register_employee()

    rival = validate_success(
        api.create_employer(
            employer_payload(
                legal_name="Rival Provisions Co",
                benefit_admin_contact_email="benefits@rival-provisions.example",
                fiscal_year_start_month=1,
            ),
            s.platform_admin,
        ),
        201,
    )
    rival_admin = make_benefit_administrator_headers(rival["id"])

    validate_error(
        api.get_employee(s.employee_id, rival_admin), ERR_UNAUTHORIZED, 403
    )

    own = validate_success(api.get_employee(s.employee_id, s.benefit_admin))
    assert own["eligibility_status"] == EligibilityStatus.ELIGIBLE

    _, meta = validate_paginated(api.list_employees(rival["id"], rival_admin))
    assert meta["total_count"] == 0


def test_the_enrollment_read_is_shared_across_exactly_four_roles(api):
    """Four roles read the same row; the opaque Coach needs no ownership at all.

    PRD §2.1: "When `X-User-Role` is `Coach`, `X-User-ID` is likewise an opaque
    operator identifier not tied to any persisted entity; the server records it as
    `coach_user_id` on each `CoachingSession` the coach logs, but never compares it
    to any entity's `id`."

    Design: Corner/rbac/enrollment_read_is_shared_across_four_roles
    """
    s = build_vantage_reimbursement_enrolled(api)
    readers = (
        make_employee_headers(s.employee_id),
        make_benefit_administrator_headers(s.employer_id),
        make_school_partner_headers(s.school_id),
        make_coach_headers("ops-coach-shift-two"),
    )
    for headers in readers:
        enrollment = validate_success(api.get_enrollment(s.enrollment_id, headers))
        assert enrollment["gross_tuition_cents"] == 160_000
        assert enrollment["employer_reserved_cents"] == 80_000
        assert enrollment["academic_status"] == AcademicStatus.REGISTERED
        assert enrollment["funding_status"] == FundingStatus.RESERVED

    other_school = s.register_school(
        primary=False,
        legal_name="Harbor Point Institute",
        state_code="OR",
        contact_email="partners@harborpoint.example",
    )
    validate_error(
        api.get_enrollment(
            s.enrollment_id, make_school_partner_headers(other_school["id"])
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.get_enrollment(s.enrollment_id, make_platform_admin_headers()),
        ERR_UNAUTHORIZED,
        403,
    )


def test_a_request_without_a_usable_role_header_is_unauthenticated(api):
    """Authentication answers first, even when the path names nothing.

    PRD §2.1: "If either header is absent, or `X-User-Role` is not one of the five
    role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/rbac/missing_role_header_is_unauthenticated
    """
    s = Scenario(api)
    s.set_clock("2026-08-01T00:00:00Z")
    s.onboard_employer(
        legal_name="Vantage Foods Group",
        benefit_admin_contact_email="benefits@vantage-foods.example",
        fiscal_year_start_month=1,
    )

    validate_error(
        api.get_employer(s.employer_id, make_headers_without_role(s.employer_id)),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_employer(UNKNOWN_EMPLOYER_ID, {}), ERR_UNAUTHENTICATED, 401
    )
    validate_error(
        api.get_employer(
            s.employer_id, make_headers_with_unknown_role(s.employer_id, "Auditor")
        ),
        ERR_UNAUTHENTICATED,
        401,
    )

    allowed = validate_success(
        api.get_employer(
            s.employer_id, make_benefit_administrator_headers(s.employer_id)
        )
    )
    assert allowed["id"] == s.employer_id
