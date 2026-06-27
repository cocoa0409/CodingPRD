"""Role-based access control: authentication, role permission, resource ownership.

Queue B: rbac corner instances.
"""
import pytest
from test_helpers import (
    validate_error, get_success_data,
    make_admin_headers, make_brand_headers, make_creator_headers,
    ApiErrorId,
    create_brand, create_creator, create_draft_campaign,
)

ADMIN = make_admin_headers()


class TestRBAC:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or malformed, the request is rejected with
        ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.list_creators({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_creator_cannot_create_campaign_forbidden_role(self, api):
        """PRD §2.1: "If the headers are well-formed but the role named in X-User-Role is not
        permitted to perform the requested operation, the request is rejected with
        ERR_FORBIDDEN_ROLE (HTTP 403)."

        POST /campaigns is Brand-exclusive; a Creator attempt -> ERR_FORBIDDEN_ROLE.

        Design: Corner/rbac/creator_cannot_create_campaign_forbidden_role
        """
        brand = create_brand(budget_cents=100_000)
        creator = create_creator(handle="@fr1", primary_platform="INSTAGRAM")
        ch = make_creator_headers(creator["id"])
        resp = api.create_campaign(
            {"brand_id": brand["id"], "title": "FR", "campaign_budget_cents": 50000,
             "requires_ftc_disclosure": False,
             "starts_at": "2026-02-01T00:00:00Z", "ends_at": "2026-03-01T00:00:00Z"}, ch)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    def test_brand_cannot_open_other_brands_campaign(self, api):
        """PRD §2.1: "a brand owns a campaign when the campaign's brand_id equals the caller's
        X-User-ID, and it owns an offer or contract by virtue of owning the underlying campaign."
        PRD §2.1: "When an entity-backed actor targets a resource it does not own, the request
        is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

        Brand B opening Brand A's campaign -> ERR_NOT_RESOURCE_OWNER.

        Design: Corner/rbac/brand_cannot_open_other_brands_campaign_not_owner
        """
        brand_a = create_brand(budget_cents=100_000, legal_name="A", contact_email="a@a.com")
        brand_b = create_brand(budget_cents=100_000, legal_name="Bb", contact_email="bb@bb.com")
        campaign, _ = create_draft_campaign(brand_a["id"], with_deliverable=True,
                                            campaign_budget_cents=50_000, base_rate_cents=40_000)
        bh_b = make_brand_headers(brand_b["id"])
        resp = api.open_campaign(
            campaign["id"], {"expected_campaign_version": campaign["version"]}, bh_b)
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
