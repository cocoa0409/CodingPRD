"""Onboarding, envelope, and access-control claims (PRD §2.1, §2.7, §3.1, §4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_credit_union,
    register_credit_union, register_cuso, setup_investor, submit_investment,
    make_buyer_headers, make_treasury_headers,
)


class TestCreditUnionOnboarding:
    def test_credit_union_creation_defaults(self, api, network_admin_headers):
        """PRD §3.1: "Registration may also carry an optional `concentration_cap_pct`, the maximum share of net worth the credit union will accept as exposure to any single originator; when omitted it defaults to 0.25."
        PRD §3.1: "A new credit union starts in `ACTIVE` status."
        PRD §3.1: "Two figures are derived continuously: `net_worth_ratio`, the unrounded quotient of `net_worth_cents` over `total_assets_cents`, and `total_committed_principal_cents`, the sum of `committed_amount_cents` across the credit union's certificates currently in `PENDING_DILIGENCE`, `COMMITTED`, `ACTIVE`, or `EXCEPTION`."

        Design: Corner/entities/credit_union_creation_defaults
        """
        res = api.create_credit_union(
            {"charter_number": "CU-1", "legal_name": "First CU", "cu_type": "DUAL",
             "total_assets_cents": 20_000_000_000, "net_worth_cents": 2_000_000_000},
            network_admin_headers)
        cu = validate_success(res, 201)
        assert_credit_union(cu)
        assert cu["status"] == "ACTIVE"
        assert cu["concentration_cap_pct"] == 0.25
        assert cu["total_committed_principal_cents"] == 0
        assert cu["net_worth_ratio"] == pytest.approx(0.1)

    def test_credit_union_missing_charter_number_rejected(self, api, network_admin_headers):
        """PRD §2.7: "5. **Request shape** — required fields are present, enum members are valid, integers are positive where required, and end dates fall after start dates, else `ERR_INVALID_REQUEST`. This check applies to all creation endpoints."
        PRD §3.1: "A `NetworkAdmin` registers each participating credit union by supplying its `charter_number` (the NCUA charter number, unique across the network), its `legal_name`, its `cu_type` — one of `ORIGINATOR`, `BUYER`, or `DUAL` — plus `total_assets_cents` and `net_worth_cents`, both denominated in cents."

        Design: Corner/entities/credit_union_missing_required_charter_number
        """
        res = api.create_credit_union(
            {"legal_name": "No Charter CU", "cu_type": "BUYER",
             "total_assets_cents": 1000, "net_worth_cents": 100},
            network_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_credit_union_invalid_cu_type_rejected(self, api, network_admin_headers):
        """PRD §2.7: "5. **Request shape** — required fields are present, enum members are valid, integers are positive where required, and end dates fall after start dates, else `ERR_INVALID_REQUEST`. This check applies to all creation endpoints."
        PRD §3.1: "its `cu_type` — one of `ORIGINATOR`, `BUYER`, or `DUAL`"

        Design: Corner/entities/credit_union_invalid_enum_rejected
        """
        res = api.create_credit_union(
            {"charter_number": "CU-X", "legal_name": "Bad Enum CU", "cu_type": "BANK",
             "total_assets_cents": 1000, "net_worth_cents": 100},
            network_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_commitment_not_found(self, api, network_admin_headers):
        """PRD §2.7: "4. **Existence** — every identifier in the path and body resolves to an existing resource, with path identifiers resolved left to right before body identifiers, else `ERR_NOT_FOUND`."

        Design: Corner/entities/commitment_get_not_found_returns_404
        """
        res = api.get_commitment(NON_EXISTENT_UUID, network_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestAccessControl:
    def test_request_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role outside the declared role set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        res = api.create_cuso({"legal_name": "CUSO One", "service_line": "LENDING"},
                              headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_buyer_role_cannot_create_cuso(self, api, network_admin_headers):
        """PRD §2.1: "When the caller's role is not permitted on the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /network/cusos — Authorized Role(s): NetworkAdmin.

        Design: Corner/rbac/buyer_role_cannot_create_cuso_forbidden
        """
        buyer = register_credit_union(charter_number="CU-BUY", legal_name="Buyer CU")
        res = api.create_cuso({"legal_name": "CUSO X", "service_line": "LENDING"},
                              make_buyer_headers(buyer["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_treasury_role_cannot_approve_investment(self, api):
        """PRD §2.1: "When the caller's role is not permitted on the target endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /network/cuso-investments/{id}/approve — Authorized Role(s): RegulatorUser.

        Design: Corner/rbac/treasury_role_cannot_approve_investment_forbidden
        """
        ctx = setup_investor(total_assets_cents=5_000_000_000, net_worth_cents=500_000_000)
        inv = submit_investment(ctx["investor"]["id"], ctx["cuso"]["id"], 1_000_000)
        res = api.approve_cuso_investment(inv["id"], make_treasury_headers(ctx["investor"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
