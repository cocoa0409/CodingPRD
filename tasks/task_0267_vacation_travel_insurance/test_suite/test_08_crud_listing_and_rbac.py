"""Resource creation/validation, filtered listings, and role-based access control
(§2.1, §2.3, §2.5, §2.10, §3.1).

Covers the corner entity, endpoint and rbac instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_plan, NON_EXISTENT_UUID,
    create_plan_payload, create_traveler_payload,
    setup_active_policy, setup_claim_under_review, set_clock, create_plan, create_traveler,
    create_quoted_policy, add_insured, file_claim, create_named_storm,
    create_claim_payload, make_traveler_headers, TEST_USERS,
)

ADMIN = TEST_USERS["carrier_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


# ─── Corner: entity creation & validation ──────────────────────────────────

def test_create_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "A plan is created with `status` `ACTIVE`".
    PRD §2.4: "The `version` field is an integer that begins at 1".

    POST /plans echoes code/tier and mints status ACTIVE, version 1.

    Design: Corner/entities/create_plan_returns_201_with_all_fields
    """
    res = api.create_plan(create_plan_payload(code="P-CR-ALPHA", tier="STANDARD"), ADMIN)
    plan = validate_success(res, 201)
    assert_plan(plan)
    assert plan["code"] == "P-CR-ALPHA"
    assert plan["tier"] == "STANDARD"
    assert plan["status"] == "ACTIVE"
    assert plan["version"] == 1


def test_get_policy_not_found_returns_404(api):
    """PRD §2.5: "a `plan_id`, `owner_traveler_id`, `policy_id`, `insured_traveler_id`,
    `named_storm_id`, `traveler_id`, or `claim_id` that does not point at a live record causes
    the request to be rejected".
    PRD §2.10: "Existence comes third: any unresolved path identifier or foreign key yields
    `ERR_NOT_FOUND` (404)".

    Design: Corner/entities/get_policy_not_found_returns_404
    """
    res = api.get_policy(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_plan_missing_required_field_returns_invalid_request(api):
    """PRD §2.10: "Request well-formedness comes fifth: a missing required field, an invalid
    enum value, or a negative or zero integer where the field forbids it yields
    `ERR_INVALID_REQUEST` (422)."
    PRD §3.1: "`base_rate_bps` is the premium base rate expressed in basis points of insured
    trip cost and must be at least 1".

    base_rate_bps has no default, so omitting it -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_plan_missing_required_field_returns_invalid_request
    """
    payload = create_plan_payload(code="P-MISS-BR")
    del payload["base_rate_bps"]
    res = api.create_plan(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_plan_invalid_tier_enum_returns_invalid_request(api):
    """PRD §3.1: "a `tier` that is one of `BASIC`, `STANDARD`, or `PREMIER`."
    PRD §2.10: "Request well-formedness comes fifth: a missing required field, an invalid enum
    value, or a negative or zero integer where the field forbids it yields `ERR_INVALID_REQUEST`
    (422)."

    tier='GOLD' is not an allowed enum value -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_plan_invalid_tier_enum_returns_invalid_request
    """
    res = api.create_plan(create_plan_payload(code="P-ENUM-X", tier="GOLD"), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_duplicate_plan_code_returns_conflict(api):
    """PRD §3.1: "a `code` that must be non-empty and unique among plans (a collision is rejected
    with `ERR_DUPLICATE_CODE`)".

    Design: Corner/entities/duplicate_plan_code_returns_conflict
    """
    validate_success(api.create_plan(create_plan_payload(code="DUP-CODE-1", tier="BASIC"), ADMIN), 201)
    res = api.create_plan(create_plan_payload(code="DUP-CODE-1", tier="STANDARD"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_CODE")


def test_duplicate_traveler_email_returns_conflict(api):
    """PRD §3.1: "an `email` that must be non-empty and unique among travelers (a duplicate is
    rejected with `ERR_DUPLICATE_EMAIL`)".

    Design: Corner/entities/duplicate_traveler_email_returns_conflict
    """
    validate_success(api.create_traveler(create_traveler_payload(email="dup-mail@x.com"), ADMIN), 201)
    res = api.create_traveler(create_traveler_payload(email="dup-mail@x.com"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_EMAIL")


# ─── Corner: filtered listings ──────────────────────────────────────────────

def test_list_policies_filtered_by_owner(api):
    """PRD §4: "List policies (filter by `plan_id`, `owner_traveler_id`, `coverage_status`,
    `payment_status`)".
    PRD §2.3: "Every list-based response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` is the number of items
    matching the query before pagination and `has_more` indicates whether items remain beyond
    the current page."

    Design: Corner/endpoints/list_policies_filtered_by_owner_returns_array_envelope
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    data, meta = validate_paginated(
        api.list_policies(ADMIN, params={"owner_traveler_id": traveler["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == policy["id"]


def test_list_claims_filtered_by_named_storm(api):
    """PRD §4: "List claims (filter by `policy_id`, `insured_traveler_id`, `named_storm_id`,
    `peril`, `status`)".
    PRD §2.3: "`total_count` is the number of items matching the query before pagination".

    A storm-cancellation claim citing a storm is returned when listing claims filtered by that
    named_storm_id.

    Design: Corner/endpoints/list_claims_filtered_by_named_storm_reverse_reachability
    """
    set_clock("2026-06-10T00:00:00Z")
    storm = create_named_storm(name="Storm Listing EP", basin="ATLANTIC",
                               named_at="2026-06-20T00:00:00Z")
    active = setup_active_policy(
        plan_overrides={"base_rate_bps": 600, "cancellation_limit_pct": 100},
        policy_overrides={"initial_deposit_at": "2026-06-05T00:00:00Z"},
        clock=None)
    claim = file_claim(active["policy"]["id"], active["insured"]["id"], active["traveler_id"],
                       "CANCELLATION", "2026-06-12T00:00:00Z",
                       cancellation_reason="NAMED_STORM", named_storm_id=storm["id"])
    data, meta = validate_paginated(
        api.list_claims(ADMIN, params={"named_storm_id": storm["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == claim["id"]


def test_list_insured_travelers_subresource(api):
    """PRD §3.2: "The created roster entry records its `policy_id`, begins with per-insured
    `status` `COVERED`".
    PRD §2.3: "Every list-based response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` is the number of items
    matching the query before pagination and `has_more` indicates whether items remain beyond
    the current page."

    The insured-travelers roster sub-list returns the policy's COVERED insured entry under the
    standard array envelope.

    Design: Corner/endpoints/list_insured_travelers_subresource_returns_array
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    policy = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000)
    insured = add_insured(policy["id"], traveler["id"], covered_trip_cost_cents=500000)
    data, meta = validate_paginated(
        api.list_policy_insured_travelers(policy["id"], ADMIN))
    assert meta["total_count"] == 1
    assert data[0]["id"] == insured["id"]


# ─── Corner: RBAC ───────────────────────────────────────────────────────────

def test_traveler_cannot_approve_claim_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "The `ClaimsAdjuster` adjudicates claims and manages payouts."

    Approve is ClaimsAdjuster-only; a Traveler calling it -> ERR_FORBIDDEN.

    Design: Corner/rbac/traveler_cannot_approve_claim_forbidden
    """
    bundle = setup_claim_under_review(plan_overrides={"base_rate_bps": 600}, peril="MEDICAL",
                                      incident_at="2026-06-02T00:00:00Z", doc_type="MEDICAL_REPORT")
    res = api.approve_claim(bundle["claim"]["id"], bundle["owner_headers"])
    validate_error(res, "ERR_FORBIDDEN")


def test_non_owner_traveler_cannot_file_claim(api):
    """PRD §2.1: "A `Traveler` who attempts to mutate a policy or claim they do not own is
    rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.10: "Resource ownership comes fourth: a `Traveler` acting on a policy or claim they do
    not own yields `ERR_NOT_RESOURCE_OWNER` (403)."

    Traveler B (not the owner) filing a claim on Traveler A's policy -> ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/non_owner_traveler_cannot_file_claim_on_others_policy
    """
    active = setup_active_policy(plan_overrides={"base_rate_bps": 600}, clock="2026-06-01T00:00:00Z")
    other = create_traveler()
    other_headers = make_traveler_headers(other["id"])
    res = api.create_claim(create_claim_payload(
        active["policy"]["id"], active["insured"]["id"], "MEDICAL", "2026-06-02T00:00:00Z"),
        other_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_AUTH`."
    PRD §2.10: "Authentication comes first: a missing or malformed header yields
    `ERR_MISSING_AUTH` (401) before anything else."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    res = api.create_plan(create_plan_payload(code="NO-AUTH-1", tier="BASIC"), {})
    validate_error(res, "ERR_MISSING_AUTH")
