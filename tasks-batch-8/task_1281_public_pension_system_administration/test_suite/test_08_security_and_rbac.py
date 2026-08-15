"""Authentication, authorization, and entity-backed ownership checks."""
from test_helpers import (
    ApiErrorId,
    add_line,
    create_employer,
    create_fund,
    create_member,
    create_report,
    review_line,
    setup_fund_and_employer,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST
from test_helpers.test_users import (
    make_employer_clerk_headers,
    make_member_headers,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        name the system does not recognize, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        fund = create_fund()
        res = api.get_pension_fund(fund["id"], headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleAuthorization:
    def test_member_cannot_review_line(self, api):
        """PRD §3.3: "Review proceeds line by line. For each line the analyst
        records a `decision` of `ACCEPT` or `REJECT`, optionally with a
        `review_note` that is stored on the line as `review_note`."
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/member_cannot_review_line_returns_forbidden
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Review Rachel",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        line = add_line(report["id"], employer["id"], member["id"], 2023,
                        6_000_000, 480_000)
        submit_report(report["id"], employer["id"])
        res = api.review_contribution_line(
            report["id"], line["id"], {"decision": "ACCEPT"},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        lines, _meta = validate_paginated(
            api.list_contribution_lines(report["id"], ANALYST))
        assert lines[0]["status"] == "PENDING"

    def test_member_cannot_finalize_report(self, api):
        """PRD §3.3: "From that point the clerk's role is finished and the
        MemberServicesAnalyst's begins."
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/member_cannot_finalize_report_returns_forbidden
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Finalize Fred",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        line = add_line(report["id"], employer["id"], member["id"], 2023,
                        6_000_000, 480_000)
        submit_report(report["id"], employer["id"])
        review_line(report["id"], line["id"], "ACCEPT")
        res = api.finalize_contribution_report(
            report["id"], make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_contribution_report(report["id"],
                                                             ANALYST), 200)
        assert after["status"] == "SUBMITTED"

    def test_clerk_cannot_create_members(self, api):
        """PRD §3.1: "Once an employer exists, a MemberServicesAnalyst enrolls
        members against it."
        PRD §2.1: "A request whose role is not on the endpoint's authorized
        list, or that fails an entity-backed ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/clerk_cannot_create_members_returns_forbidden
        """
        fund, employer = setup_fund_and_employer()
        res = api.create_member(
            {"employer_id": employer["id"], "full_name": "Clerk Made",
             "date_of_birth": "1990-01-01", "hire_date": "2020-01-01"},
            make_employer_clerk_headers(employer["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestEntityBackedOwnership:
    def test_clerk_cannot_touch_other_employers_reports(self, api):
        """PRD §2.1: "When `X-User-Role` is EmployerClerk, `X-User-ID` is the
        `id` of the acting Employer, and the clerk may only touch that
        employer's contribution reports and lines."

        Design: Corner/validations/clerk_cannot_touch_other_employer_reports
        """
        fund = create_fund()
        e1 = create_employer(name="E1", employer_code="E1")
        e2 = create_employer(name="E2", employer_code="E2")
        report_e2 = create_report(e2["id"], "2023-01-01", "2024-01-01", 100)
        member = create_member(e2["id"], full_name="Member Mary",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")

        res1 = api.create_contribution_report(
            e2["id"],
            {"period_start": "2024-01-01", "period_end": "2025-01-01",
             "declared_total_cents": 100},
            make_employer_clerk_headers(e1["id"]))
        validate_error(res1, ApiErrorId.ERR_FORBIDDEN)

        res2 = api.create_contribution_line(
            report_e2["id"],
            {"member_id": member["id"], "fiscal_year": 2023,
             "period_salary_cents": 1_250, "contribution_amount_cents": 100},
            make_employer_clerk_headers(e1["id"]))
        validate_error(res2, ApiErrorId.ERR_FORBIDDEN)

    def test_member_cannot_touch_other_members_records(self, api):
        """PRD §2.1: "When `X-User-Role` is Member, `X-User-ID` is the `id` of
        the acting Member, and ownership checks compare the owning member id
        of the targeted resource against `X-User-ID`."

        Design: Corner/rbac/member_cannot_touch_other_member_records_returns_forbidden
        """
        fund, employer = setup_fund_and_employer()
        member_a = create_member(employer["id"], full_name="Owner Olga")
        member_b = create_member(employer["id"], full_name="Other Omar")
        res = api.create_retirement_application(
            member_b["id"], {"option_election": "SINGLE_LIFE"},
            make_member_headers(member_a["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)
        _apps, meta = validate_paginated(
            api.list_member_retirement_applications(member_b["id"], ANALYST))
        assert meta["total_count"] == 0
