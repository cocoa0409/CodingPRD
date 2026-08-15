"""Partner admission: computed fields, request validation, reads, pagination,
and entity-backed Investor access."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_investor_headers,
    create_fund, create_partner, create_partner_payload, assert_partner,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]


class TestPartnerComputedFields:
    def test_partner_create_computes_is_foreign_and_zero_balances(self, api):
        """PRD §3.2: "A newly admitted partner starts `ACTIVE` with all
        computed balances at zero."
        PRD §3.2: "The derived flag `is_foreign` is true exactly when the
        `partner_type` is `FOREIGN_INDIVIDUAL` or `FOREIGN_ENTITY`."

        Design: Corner/entities/partner_create_computes_is_foreign_and_zero_balances
        """
        fund = create_fund()
        resp_fr = api.create_partner(
            create_partner_payload(
                fund["id"], legal_name="FR", partner_type="FOREIGN_ENTITY",
                residency_state="XX", ownership_pct_bps=5000,
                capital_commitment_cents=100,
            ),
            ADMIN,
        )
        p_fr = validate_success(resp_fr, 201)
        resp_us = api.create_partner(
            create_partner_payload(
                fund["id"], legal_name="US", partner_type="US_ENTITY",
                residency_state="DE", ownership_pct_bps=5000,
                capital_commitment_cents=100,
            ),
            ADMIN,
        )
        p_us = validate_success(resp_us, 201)
        assert_partner(p_fr)
        assert_partner(p_us)
        assert p_fr["is_foreign"] is True, "FOREIGN_ENTITY must yield is_foreign true"
        assert p_us["is_foreign"] is False, "US_ENTITY must yield is_foreign false"
        for p in (p_fr, p_us):
            assert p["capital_account_balance_cents"] == 0
            assert p["tax_basis_cents"] == 0
            assert p["excess_distribution_gain_cents"] == 0
            assert p["current_ownership_pct_bps"] == p["ownership_pct_bps"] == 5000
            assert p["status"] == "ACTIVE"


class TestPartnerRequestValidation:
    def test_create_partner_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.8: "Request well-formedness — required fields are present,
        enum values are valid, and integer and date ranges are sane:
        basis-point shares between one and ten thousand inclusive, quarter
        between one and four, event amounts non-zero, `effective_from` strictly
        before `effective_to`, and `settlement_date` on or after
        `effective_date`, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_partner_missing_required_field_returns_invalid_request
        """
        fund = create_fund()
        payload = create_partner_payload(fund["id"], legal_name="NoType")
        del payload["partner_type"]
        resp = api.create_partner(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_partner_invalid_enum_returns_invalid_request(self, api):
        """PRD §2.8: "Request well-formedness — required fields are present,
        enum values are valid, and integer and date ranges are sane:
        basis-point shares between one and ten thousand inclusive, quarter
        between one and four, event amounts non-zero, `effective_from` strictly
        before `effective_to`, and `settlement_date` on or after
        `effective_date`, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_partner_invalid_enum_returns_invalid_request
        """
        fund = create_fund()
        payload = create_partner_payload(fund["id"], legal_name="BadEnum", partner_type="ALIEN")
        resp = api.create_partner(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_partner_returns_not_found(self, api):
        """PRD §2.8: "Path existence — every identifier in the path resolves to
        an existing resource, validated left to right, else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_partner_returns_not_found
        """
        resp = api.get_partner(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPartnerListing:
    def test_list_partners_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets the number of items skipped and defaults to
        0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_partners_pagination_envelope
        """
        fund = create_fund()
        for i in range(12):
            create_partner(
                fund["id"], legal_name=f"P{i + 1:02d}", ownership_pct_bps=1,
                capital_commitment_cents=1,
            )
        page1, meta1 = validate_paginated(api.list_partners(ADMIN, params={"fund_id": fund["id"]}))
        assert len(page1) == 10, f"default page must hold 10 items, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_partners(ADMIN, params={"fund_id": fund["id"], "offset": 10})
        )
        assert len(page2) == 2, f"offset 10 must return the remaining 2, got {len(page2)}"
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False

    def test_investor_cannot_list_partners_but_can_read_self(self, api):
        """PRD §2.1: "Consequently an `Investor` may read only their own partner
        record, their own K-1 packages, and their own tickets; may acknowledge
        delivery only of a package whose `partner_id` equals their `X-User-ID`;
        and may open or reopen tickets only where the ticket's `partner_id`
        equals their `X-User-ID`."
        PRD §2.8: "Role authorization — the role is permitted for the endpoint
        and, for the entity-backed `Investor`, the `X-User-ID` equals the
        `partner_id` of the accessed resource on partner-scoped reads,
        acknowledgements, and ticket creation or reopening, else
        `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/investor_cannot_list_partners_but_can_read_self
        """
        fund = create_fund()
        p1 = create_partner(fund["id"], legal_name="P1")
        investor = make_investor_headers(p1["id"])
        resp_list = api.list_partners(investor, params={"fund_id": fund["id"]})
        validate_error(resp_list, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        resp_self = api.get_partner(p1["id"], investor)
        data = validate_success(resp_self, 200)
        assert data["legal_name"] == "P1"
        assert data["id"] == p1["id"]
