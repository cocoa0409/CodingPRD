"""Role-based access control and the authentication-context gate.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_policy_effective,
    make_policyholder_headers,
    open_cancellation_case,
    setup_active_policy,
    validate_error,
)
from test_helpers import fixtures as fx

OFFICER = TEST_USERS["compliance_officer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestRoleDenials:
    def test_policyholder_cannot_approve_cancellation(self, api):
        """PRD §2.1: "Access to every endpoint is restricted by role, and an
        attempt to perform an operation outside the caller's designated role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE`." Approval belongs to a
        `ComplianceOfficer` (PRD §3.4 and the §4 routing table).

        Design: Corner/roles/policyholder_cannot_approve_cancellation
        """
        _profile, holder, policy = setup_active_policy("AS", clock="2026-08-01T00:00:00Z")
        case = open_cancellation_case(
            policy, ground_code="INSURED_REQUEST", by_policyholder=True, holder_id=holder["id"]
        )

        resp = api.approve_cancellation_case(
            case["id"], {"scheduled_effective_date": "2026-09-01"},
            make_policyholder_headers(holder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert fx.get_cancellation_case(case["id"])["status"] == "PENDING_APPROVAL"

    def test_underwriter_cannot_finalize_report(self, api):
        """PRD §2.1: "Access to every endpoint is restricted by role, and an
        attempt to perform an operation outside the caller's designated role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE`." Finalization is reserved
        to a `ComplianceOfficer` (PRD §2.10 and the §4 routing table).

        Design: Corner/roles/underwriter_cannot_finalize_report
        """
        bundle = cancel_policy_effective(
            "MP",
            request_clock="2026-08-01T00:00:00Z",
            scheduled_effective_date="2026-08-20",
            mailed_on_date="2026-08-01",
            policy_number="P-MP-1",
        )
        fx.set_clock("2026-09-01T00:00:00Z")
        report = fx.find_report(bundle["profile"]["id"], "2026-08")

        resp = api.finalize_regulatory_report(report["id"], UNDERWRITER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert fx.get_success_data(api.get_regulatory_report(report["id"], OFFICER))["status"] == "OPEN"


class TestAuthContext:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the
        acting operator and `X-User-Role` to specify their operational
        capacity. A request in which either header is missing or malformed is
        rejected with `ERR_MISSING_AUTH_CONTEXT`."
        PRD §2.11: "Every request passes through the same ordered gauntlet,
        and a failure at any tier masks every later tier. The tiers, evaluated
        in this order, are: 1. Authentication context ..."

        Design: Corner/roles/missing_auth_headers_rejected
        """
        resp = api.get_policy("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)
