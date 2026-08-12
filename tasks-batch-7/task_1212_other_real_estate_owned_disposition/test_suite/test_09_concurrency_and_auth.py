"""Optimistic concurrency on the two guarded writes, plus the auth priority
ladder (unauthenticated beats not-found) and approval-tier overlap validation."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_property,
    create_marketed_property,
    create_appraiser,
    create_appraisal_payload,
    create_offer_payload,
    create_approval_tier_payload,
    get_property,
    setup_approval_tiers,
    set_clock,
    make_appraiser_headers,
)

ADMIN = TEST_USERS["oreo_admin_headers"]
SPEC = TEST_USERS["oreo_specialist_headers"]


class TestOptimisticConcurrency:
    def test_appraisal_create_with_stale_property_version_returns_412(self, api):
        """PRD §2.5: "Creating an appraisal against an OREOProperty requires
        expected_property_version to equal the property's current version. If
        another writer has advanced the property's version since the client
        last read it — the legitimate product case is a prior writer certifying
        a different appraisal, which advances property.version and recomputes
        current_fair_value — the create is rejected with ERR_STALE_VERSION
        (HTTP 412)".

        Design: Corner/cross_cutting_layers/appraisal_create_with_stale_property_version_returns_412
        """
        prop = create_property()
        set_clock("2026-06-01T00:00:00Z")
        appraiser = create_appraiser()
        stale_v = prop["version"]
        # first create succeeds and bumps version
        r1 = api.create_appraisal(
            create_appraisal_payload(
                property_id=prop["id"],
                appraiser_id=appraiser["id"],
                expected_property_version=stale_v,
            ),
            make_appraiser_headers(appraiser["id"]),
        )
        validate_success(r1, expected_status=201)
        # second create with same stale version fails
        r2 = api.create_appraisal(
            create_appraisal_payload(
                property_id=prop["id"],
                appraiser_id=appraiser["id"],
                effective_date="2026-06-02",
                appraised_value=398000.00,
                expected_property_version=stale_v,
            ),
            make_appraiser_headers(appraiser["id"]),
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)
        # only the successful create advanced the version
        after = get_property(prop["id"])
        assert after["version"] == stale_v + 1

    def test_offer_create_with_stale_property_version_returns_412(self, api):
        """PRD §2.5: "Creating an offer against an OREOProperty follows the
        same contract: expected_property_version must equal the property's
        current version, and a mismatch is rejected with ERR_STALE_VERSION
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/offer_create_with_stale_property_version_returns_412
        """
        setup_approval_tiers()
        ctx = create_marketed_property()
        prop = ctx["property"]
        listing = ctx["listing"]
        stale_v = prop["version"]
        # first create succeeds
        r1 = api.create_offer(
            create_offer_payload(
                property_id=prop["id"],
                listing_agreement_id=listing["id"],
                buyer_name="Buyer A",
                expected_property_version=stale_v,
            ),
            SPEC,
        )
        validate_success(r1, expected_status=201)
        # second create with stale version fails
        r2 = api.create_offer(
            create_offer_payload(
                property_id=prop["id"],
                listing_agreement_id=listing["id"],
                buyer_name="Buyer B",
                offer_price=445000.00,
                earnest_money=4000.00,
                expected_property_version=stale_v,
            ),
            SPEC,
        )
        validate_error(r2, ApiErrorId.ERR_STALE_VERSION)
        # only one offer persisted
        list_resp = api.list_offers(ADMIN, params={"property_id": prop["id"]})
        data, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 1


class TestAuthLadder:
    def test_get_property_unauthenticated_returns_401(self, api):
        """PRD §2.1: "A request missing either header, or whose X-User-Role is
        not one of these spellings, is rejected with ERR_UNAUTHENTICATED (HTTP
        401)."
        PRD §2.8: "The ladder is evaluated in this order: authentication
        (ERR_UNAUTHENTICATED) first; then role authorization and entity-backed
        ownership (ERR_FORBIDDEN); ... then existence of path ids and body
        foreign keys, validated left-to-right along the URL template
        (ERR_NOT_FOUND)".

        Design: Corner/validations/get_property_unauthenticated_returns_401
        """
        # anonymous request (no auth headers) against a nonexistent id
        anonymous_headers = {"Content-Type": "application/json"}
        resp = api.get_property(NON_EXISTENT_UUID, anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestApprovalTierOverlap:
    def test_create_overlapping_approval_tier_returns_409(self, api):
        """PRD §3.6: "Tier intervals are validated non-overlapping at creation
        — a new tier whose [min_net_proceeds, max_net_proceeds) interval
        intersects an existing tier is rejected with ERR_TIER_OVERLAP (HTTP
        409), while adjacency is permitted."

        Design: Corner/validations/create_overlapping_approval_tier_returns_409
        """
        # existing T1 [0, 250000)
        api.create_approval_tier(
            create_approval_tier_payload(
                name="T1",
                min_net_proceeds=0.00,
                max_net_proceeds=250000.00,
                required_role="OREOSpecialist",
            ),
            ADMIN,
        )
        # overlap [200000, 300000) intersects [0, 250000)
        resp = api.create_approval_tier(
            create_approval_tier_payload(
                name="T4",
                min_net_proceeds=200000.00,
                max_net_proceeds=300000.00,
                required_role="CreditOfficer",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_TIER_OVERLAP)
        # adjacent [250000, 750000) is allowed
        ok = api.create_approval_tier(
            create_approval_tier_payload(
                name="T2",
                min_net_proceeds=250000.00,
                max_net_proceeds=750000.00,
                required_role="CreditOfficer",
            ),
            ADMIN,
        )
        data = validate_success(ok, expected_status=201)
        assert data["min_net_proceeds"] == 250000.00
