"""Cross-cutting behavior: RBAC denials and ownership, PATCH guards (fair-housing,
posture suspension, OCC), mutation visibility, and the list envelope with
pagination and filters (PRD §2.1, §2.2, §2.3, §2.8, §2.9, §2.10, §3.1)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_listing,
    create_agent_payload, create_listing_payload, create_patch_listing_payload,
    create_portal_account_payload,
    create_agent, owner_headers, create_draft_listing, create_active_listing,
    create_submittable_listing, submit_listing, reject_review, get_listing,
    TEST_USERS, make_listing_agent_headers, NON_EXISTENT_UUID,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
MD = TEST_USERS["marketing_director_headers"]
PW = TEST_USERS["portal_webhook_headers"]


# ─── RBAC (PRD §2.1, §4) ──────────────────────────────

def test_compliance_officer_cannot_create_portal(api):
    """PRD §2.1: "A request whose role is recognized but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."
    PRD §4: POST /portal-accounts is authorized for MarketingDirector only.

    Design: Corner/rbac/compliance_officer_cannot_create_portal
    """
    res = api.create_portal_account(create_portal_account_payload(portal_name="PortalX"), CO)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    portals = get_success_data(api.list_portal_accounts(MC), 200)
    assert portals == []


def test_portal_webhook_cannot_create_listing(api, marketing_director_headers):
    """PRD §2.1: "`PortalWebhook` — the external portal callback identity; it can
    only acknowledge or fail feed events and read job state."
    PRD §2.1: "A request whose role is recognized but not permitted on the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/portal_webhook_cannot_create_listing
    """
    agent = validate_success(
        api.create_agent(create_agent_payload(license_number="LIC-1"), marketing_director_headers), 201)
    res = api.create_listing(create_listing_payload(agent["id"], complete=False), PW)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_listing_agent_cannot_patch_others_listing(api, marketing_director_headers):
    """PRD §2.1: "a listing-scoped mutation attempted by a `ListingAgent` on a
    listing whose `agent_id` does not equal their `X-User-ID` is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/listing_agent_cannot_patch_others_listing
    """
    a1 = validate_success(api.create_agent(
        create_agent_payload(full_name="A1", license_number="LIC-1", email="a1@x.com"),
        marketing_director_headers), 201)
    a2 = validate_success(api.create_agent(
        create_agent_payload(full_name="A2", license_number="LIC-2", email="a2@x.com"),
        marketing_director_headers), 201)
    listing = validate_success(api.create_listing(
        create_listing_payload(a1["id"], complete=False),
        make_listing_agent_headers(a1["id"])), 201)

    res = api.patch_listing(
        listing["id"],
        create_patch_listing_payload(listing["version"], bedrooms=4),
        make_listing_agent_headers(a2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, expected_status=403)

    assert get_listing(listing["id"]).get("bedrooms") is None


def test_marketing_coordinator_can_patch_any_listing(api, marketing_director_headers):
    """PRD §2.1: "`MarketingCoordinator` — brokerage marketing staff who operate on
    any listing without an ownership restriction."
    PRD §3.1: "Every update is OCC-guarded per §2.8, increments the listing's
    `version` by one, and refreshes `updated_at`."

    Design: Corner/rbac/marketing_coordinator_can_patch_any_listing
    """
    a1 = validate_success(api.create_agent(
        create_agent_payload(full_name="A1", license_number="LIC-1", email="a1@x.com"),
        marketing_director_headers), 201)
    listing = validate_success(api.create_listing(
        create_listing_payload(a1["id"], complete=False),
        make_listing_agent_headers(a1["id"])), 201)

    patched = validate_success(api.patch_listing(
        listing["id"],
        create_patch_listing_payload(listing["version"], bedrooms=4),
        MC), 200)
    assert patched["bedrooms"] == 4
    assert patched["version"] == listing["version"] + 1


# ─── Authentication (PRD §2.1) ────────────────────────

def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system does
    not recognize, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_header_returns_unauthenticated
    """
    res = api.list_listings({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# ─── PATCH guards (PRD §2.8, §2.9, §2.10) ─────────────

def test_patch_rejects_fair_housing_language(api):
    """PRD §2.10: "The scan runs at four moments: when a listing is created with
    `marketing_remarks` present, when a listing update changes `marketing_remarks`,
    when a listing is submitted for review, and when a listing is relisted — where it
    screens `new_marketing_remarks` when that field is supplied and the stored
    `marketing_remarks` otherwise. Any match rejects the request with
    `ERR_FAIR_HOUSING_VIOLATION`."

    Design: Corner/validations/patch_rejects_fair_housing_language
    """
    agent = create_agent()
    draft = create_draft_listing(agent, complete=False)
    res = api.patch_listing(
        draft["id"],
        create_patch_listing_payload(draft["version"],
                                     marketing_remarks="No children allowed"),
        owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_FAIR_HOUSING_VIOLATION, expected_status=422)
    assert get_listing(draft["id"])["version"] == draft["version"]


def test_patch_compliance_hold_returns_posture_suspended(api):
    """PRD §2.9: "Posture suspension — marketing mutations are forbidden while the
    listing's posture is `SUSPENDED`, else `ERR_POSTURE_SUSPENDED`."
    PRD §2.9: "The posture guard at step 7 applies to exactly this set of operations:
    updating a listing, posting a price change, creating a media asset, marking an
    asset ready, designating a primary photo, archiving an asset, and creating a
    showing window."
    PRD §2.6: "If the listing's `lifecycle_status` is `COMPLIANCE_HOLD`, `WITHDRAWN`,
    `EXPIRED`, or `SOLD`, the posture is `SUSPENDED`."

    Design: Corner/validations/patch_compliance_hold_returns_posture_suspended
    """
    agent, listing, _ = create_submittable_listing()
    review = submit_listing(listing, agent)
    reject_review(review)
    held = get_listing(listing["id"])
    assert held["lifecycle_status"] == "COMPLIANCE_HOLD"
    assert held["syndication_posture"] == "SUSPENDED"

    res = api.patch_listing(
        listing["id"],
        create_patch_listing_payload(held["version"], bedrooms=3),
        owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_POSTURE_SUSPENDED, expected_status=409)
    assert get_listing(listing["id"])["version"] == held["version"]


def test_occ_stale_version_on_patch(api):
    """PRD §2.8: "Updating a listing's editable fields requires the request to carry
    `expected_listing_version`, holding the listing `version` the client last
    observed."
    PRD §2.8: "In both cases, if `expected_listing_version` does not match the
    listing's current `version`, the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412): another writer has advanced the listing since the client last read
    it, and the client's input is based on stale data."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_patch
    """
    agent = create_agent()
    draft = create_draft_listing(agent, complete=False)
    stale_version = draft["version"]
    validate_success(api.patch_listing(
        draft["id"],
        create_patch_listing_payload(stale_version, bedrooms=3),
        owner_headers(agent)), 200)

    res = api.patch_listing(
        draft["id"],
        create_patch_listing_payload(stale_version, bathrooms=3),
        owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    listing = get_listing(draft["id"])
    assert listing.get("bathrooms") is None, "the stale PATCH must not apply"
    assert listing["version"] == stale_version + 1, "version incremented exactly once"


def test_immediate_mutation_visibility_in_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."
    PRD §3.1: "Every update is OCC-guarded per §2.8, increments the listing's
    `version` by one, and refreshes `updated_at`."

    Design: Corner/consistency_model/immediate_mutation_visibility_in_response
    """
    agent = create_agent()
    draft = create_draft_listing(agent, complete=False)
    patched = validate_success(api.patch_listing(
        draft["id"],
        create_patch_listing_payload(draft["version"], bedrooms=5),
        owner_headers(agent)), 200)
    assert patched["bedrooms"] == 5
    assert patched["version"] == draft["version"] + 1
    assert_listing(patched)


# ─── List envelope, pagination, filters (PRD §2.2, §2.3, §3.1) ──

def test_response_envelope_and_pagination(api, marketing_director_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."
    PRD §2.2: "The `response_type` is either \"object\" for a single resource or
    \"array\" for a list of resources."

    Design: Corner/endpoints/response_envelope_and_pagination
    """
    for i in range(3):
        validate_success(api.create_agent(
            create_agent_payload(full_name=f"A{i+1}", license_number=f"LIC-{i+1}",
                                 email=f"a{i+1}@x.com"),
            marketing_director_headers), 201)

    res = api.list_agents(marketing_director_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert res.json()["response_type"] == "array"
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2 and meta["offset"] == 0
    assert isinstance(meta["api_request_id"], str)
    assert isinstance(meta["api_request_timestamp"], str)

    res2 = api.list_agents(marketing_director_headers, params={"limit": 2, "offset": 2})
    data2, meta2 = validate_paginated(res2)
    assert len(data2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_listings_filter_by_lifecycle_status(api):
    """PRD §3.1: "Listings can be browsed with optional `agent_id` and
    `lifecycle_status` filters, and a single listing read returns the stored record
    with its derived posture, scores, and breach counters computed fresh."

    Design: Corner/endpoints/listings_filter_by_lifecycle_status
    """
    agent = create_agent()
    draft = create_draft_listing(agent, complete=False)
    _agent2, active = create_active_listing(agent=agent,
                                            address_line1="2 Oak Ave",
                                            postal_code="78702",
                                            property_type="SINGLE_FAMILY",
                                            list_price_cents=60000000,
                                            mls_number="MLS-2")

    data_active, meta_active = validate_paginated(
        api.list_listings(MC, params={"lifecycle_status": "ACTIVE"}))
    assert [l["id"] for l in data_active] == [active["id"]]

    data_draft, meta_draft = validate_paginated(
        api.list_listings(MC, params={"lifecycle_status": "DRAFT"}))
    assert [l["id"] for l in data_draft] == [draft["id"]]
