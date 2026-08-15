"""RBAC: authentication, role denial, segregation of duties."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_kyc_case_payload,
    create_subscription_payload,
    create_nav_period_payload,
    get_fund,
    make_investor_headers,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_missing_x_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Failure to provide both headers in a well-formed shape
        results in ERR_UNAUTHENTICATED."

        Design: Corner/validations/missing_x_user_role_returns_unauthenticated
        """
        # Send request with no auth headers at all.
        resp = api.list_funds(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestForbiddenOnFundCreation:
    def test_investor_cannot_create_fund(self, api, fund_admin_headers):
        """PRD §2.1: "When the headers are present but the role is not
        permitted to invoke the requested operation, the system rejects the
        call with ERR_FORBIDDEN."

        Design: Corner/validations/investor_cannot_create_fund
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        investor_headers = make_investor_headers(inv["id"])
        resp = api.create_fund(create_fund_payload(fund_name="BadFund"), investor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPortfolioManagerReadOnly:
    def test_portfolio_manager_cannot_finalize_nav(
        self, api, fund_admin_headers, portfolio_manager_headers
    ):
        """PRD §2.1: "When the headers are present but the role is not
        permitted to invoke the requested operation, the system rejects the
        call with ERR_FORBIDDEN." PortfolioManager is described in §1 as
        "observe but never mutate".

        Design: Corner/roles/portfolio_manager_cannot_finalize_nav
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        period = validate_success(
            api.create_nav_period(fund["id"], create_nav_period_payload(), fund_admin_headers),
            201,
        )
        fund_now = get_fund(fund["id"])
        resp = api.finalize_nav_period(
            fund["id"], period["id"],
            {"gross_return_bps": 100, "expected_fund_version": fund_now["version"]},
            portfolio_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDuties:
    def test_compliance_cannot_record_funding(
        self,
        api,
        fund_admin_headers,
        compliance_officer_headers,
        transfer_agent_headers,
    ):
        """PRD §1: "TransferAgent staff record wire receipts" while
        "ComplianceOfficer staff control KYC and accreditation decisions" —
        the system enforces segregation of duties. PRD §2.1: calls by a role
        not permitted on the endpoint are rejected with ERR_FORBIDDEN.

        Design: Corner/roles/compliance_cannot_record_funding
        """
        fund = validate_success(api.create_fund(create_fund_payload(), fund_admin_headers), 201)
        cls = validate_success(
            api.create_share_class(
                fund["id"],
                create_share_class_payload(
                    min_initial_investment_cents=100, min_additional_investment_cents=50
                ),
                fund_admin_headers,
            ),
            201,
        )
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        sub = validate_success(
            api.create_subscription(
                fund["id"],
                create_subscription_payload(
                    investor_id=inv["id"], share_class_id=cls["id"],
                    commitment_amount_cents=500, funding_deadline_utc="2026-08-10T00:00:00Z",
                ),
                fund_admin_headers,
            ),
            201,
        )
        api.submit_subscription(fund["id"], sub["id"], transfer_agent_headers)
        api.compliance_approve_subscription(fund["id"], sub["id"], compliance_officer_headers)

        resp = api.record_funding(
            fund["id"], sub["id"],
            {"amount_cents": 500, "received_at_utc": "2026-08-05T00:00:00Z"},
            compliance_officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_investor_cannot_approve_own_kyc(
        self, api, fund_admin_headers, compliance_officer_headers
    ):
        """PRD §1: "ComplianceOfficer staff control KYC and accreditation
        decisions" — Investors cannot approve KYC cases, even their own.
        PRD §2.1: calls by a role not permitted on the endpoint are rejected
        with ERR_FORBIDDEN.

        Design: Corner/roles/investor_cannot_approve_own_kyc
        """
        inv = validate_success(
            api.create_investor(create_investor_payload(), fund_admin_headers), 201
        )
        kyc = validate_success(
            api.create_kyc_case(inv["id"], create_kyc_case_payload(), compliance_officer_headers),
            201,
        )
        investor_headers = make_investor_headers(inv["id"])
        resp = api.approve_kyc_case(inv["id"], kyc["id"], {}, investor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
