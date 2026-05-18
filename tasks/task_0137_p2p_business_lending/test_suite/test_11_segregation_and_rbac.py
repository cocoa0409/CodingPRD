"""Segregation of duties, ownership scoping, and RBAC.

PRD §2.1, §3.4, §3.7, §3.9.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    build_user_headers,
    create_investment_payload,
    create_listing_payload,
    create_payment_payload,
    create_platform_payload,
    make_borrower_headers,
    make_compliance_officer_headers,
    make_investor_headers,
    setup_funded_listing,
    setup_open_listing,
    setup_originated_loan,
    setup_platform_with_officer,
    validate_error,
    validate_success,
)


# ===========================================================================
# Segregation of duties — PRD §3.4
# ===========================================================================
class TestOriginateSegregation:

    def test_compliance_officer_cannot_originate_loan(self, api):
        """PRD §3.4: "A FUNDED listing is originated by a
        PlatformOperator (a ComplianceOfficer may not originate, per
        segregation of duties, and an attempt by them returns
        ERR_SEGREGATION_VIOLATION)."

        Claim: ComplianceOfficer issuing originate ->
        ERR_SEGREGATION_VIOLATION.
        """
        (platform, officer, b, investor, listing,
         investment) = setup_funded_listing(principal_cents=100_000)
        resp = api.originate_listing(
            platform["id"], listing["id"],
            make_compliance_officer_headers(officer["id"]),
        )
        validate_error(resp, "ERR_SEGREGATION_VIOLATION")


class TestInvestmentSegregation:

    def test_borrower_role_cannot_create_investment(self, api):
        """PRD §3.3: "An Investor attempting to pledge on a listing
        whose borrower is themselves (same platform) is rejected with
        ERR_SEGREGATION_VIOLATION."

        PRD §3.9 also says ComplianceOfficer / Borrower are
        structurally barred from POST /investments via roles list;
        which barrier fires for Borrower role on /investments depends
        on whether the implementer treats "investments create" as
        role-gated or business-safety-gated.

        Claim: Borrower role calling POST /investments yields either
        ERR_FORBIDDEN_FOR_ROLE (role list excludes Borrower) or
        ERR_SEGREGATION_VIOLATION (segregation). Either is consistent
        with the PRD; use validate_error_is_one_of.
        """
        from test_helpers import validate_error_is_one_of
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=2500),
            make_borrower_headers(b["id"]),
        )
        validate_error_is_one_of(
            resp,
            ["ERR_FORBIDDEN_FOR_ROLE", "ERR_SEGREGATION_VIOLATION"],
        )


# ===========================================================================
# Ownership scoping — PRD §2.1
# ===========================================================================
class TestBorrowerOwnershipScoping:

    def test_borrower_can_act_on_own_listing(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        a Borrower (its listings, its loans, payments against those
        loans) compare the resource's borrower_id to X-User-ID."

        Claim: a Borrower acting with X-User-ID == their own
        Borrower.id can withdraw their own OPEN listing.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        resp = api.withdraw_listing(
            platform["id"], listing["id"],
            make_borrower_headers(b["id"]),
        )
        # Success expected (Borrower owns the listing).
        body = resp.json()
        assert resp.status_code in (200, 204), (
            f"Borrower acting as own listing's owner expected success; "
            f"got status={resp.status_code} body={body}"
        )

    def test_borrower_cannot_withdraw_other_borrowers_listing(self, api):
        """PRD §2.1: "A borrower who attempts to operate on a loan
        whose borrower_id does not equal their X-User-ID" (the same
        ownership rule applies to listings per PRD §2.1: 'its listings,
        its loans, payments against those loans').

        Claim: Borrower with X-User-ID belonging to borrower-A trying
        to withdraw borrower-B's listing is rejected (ERR_FORBIDDEN_FOR_ROLE
        per the validation taxonomy: structural non-owner -> forbidden).
        """
        # First borrower with an OPEN listing.
        platform, officer, b_a, listing = setup_open_listing(
            principal_cents=100_000,
        )
        # Second borrower on the same platform.
        from test_helpers import (
            attach_plaid_snapshot, approve_borrower, create_borrower,
        )
        b_b = create_borrower(platform["id"])
        attach_plaid_snapshot(platform["id"], b_b["id"])
        approve_borrower(platform["id"], b_b["id"], officer["id"])
        resp = api.withdraw_listing(
            platform["id"], listing["id"],
            make_borrower_headers(b_b["id"]),
        )
        # Must be rejected. PRD §2.1 maps non-owner Borrower action to
        # ERR_FORBIDDEN_FOR_ROLE (the role is permitted on the endpoint
        # in general but not for this specific resource).
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")


# ===========================================================================
# RBAC — endpoint role lists from PRD §4
# ===========================================================================
class TestRbacRoleLists:

    def test_borrower_cannot_create_platform(self, api):
        """PRD §4: POST /platforms is authorized for PlatformOperator
        only. PRD §2.1: "A well-formed header pair whose role is not
        authorized for the endpoint yields ERR_FORBIDDEN_FOR_ROLE."

        Claim: Borrower -> POST /platforms -> ERR_FORBIDDEN_FOR_ROLE.
        """
        resp = api.create_platform(
            create_platform_payload(),
            make_borrower_headers("any-borrower-id"),
        )
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")

    def test_investor_cannot_create_platform(self, api):
        """PRD §4: POST /platforms is authorized for PlatformOperator
        only.

        Claim: Investor -> POST /platforms -> ERR_FORBIDDEN_FOR_ROLE.
        """
        resp = api.create_platform(
            create_platform_payload(),
            make_investor_headers("any-investor-id"),
        )
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE")
