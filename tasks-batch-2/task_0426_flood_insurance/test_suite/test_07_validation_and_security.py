"""Validation precedence, RBAC, optimistic-concurrency, authentication, and
coverage-cap / rating-eligibility guards.

Covers difficulty queue A (priority_pair_validation_conflict) and corner queue B
(validations, errors, rbac sections).
"""
from test_helpers import (
    validate_error,
    set_clock,
    create_community,
    create_property,
    setup_quoted_policy,
    setup_claim_with_accepted_proof,
    setup_claim_under_review,
    open_review,
    file_proof_of_loss,
    ApiErrorId,
    TEST_USERS,
    make_policy_holder_headers,
)


# --- Priority-pair conflicts (difficulty) ----------------------------------

def test_not_owner_beats_invalid_state_on_claim_file(api):
    """PRD §3.11: "Resource ownership for holder-scoped operations is checked
    fourth, yielding `ERR_NOT_RESOURCE_OWNER` when the acting holder is not the
    owner/holder/claimant. State correctness for the requested transition is
    checked fifth, yielding `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/not_owner_beats_invalid_state_on_claim_file
    """
    community, prop, policy = setup_quoted_policy(
        owner_id="holder-10", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
    )
    # A different holder (holder-11) files a claim against holder-10's QUOTED policy.
    resp = api.create_claim(
        {
            "policy_id": policy["id"],
            "claimant_id": "holder-11",
            "date_of_loss": "2026-02-01T00:00:00Z",
            "building_loss": 1000,
        },
        make_policy_holder_headers("holder-11"),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)


def test_proof_late_beats_mismatch_on_accept(api):
    """PRD §3.11: "proof-of-loss timeliness and reconciliation" are evaluated in
    fixed precedence with timeliness (priority 12) before reconciliation
    (priority 15).
    PRD §3.9: "a late filing is rejected with `ERR_PROOF_OF_LOSS_LATE` (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/pol_late_beats_pol_mismatch_on_accept
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="holder-12", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
        date_of_loss="2026-04-10T00:00:00Z",
    )
    # Proof filed day 61 (late) AND with mismatched figures (9999 vs 5000).
    set_clock("2026-06-10T00:00:00Z")
    proof = file_proof_of_loss(claim["id"], "holder-12", documented_building_loss=9999)
    resp = api.accept_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    # Timeliness (priority 12) pre-empts the reconciliation mismatch (priority 15).
    validate_error(resp, ApiErrorId.ERR_PROOF_OF_LOSS_LATE, expected_status=409)


# --- Coverage / eligibility guards (corner) --------------------------------

def test_legacy_rating_on_non_sfha_rejected(api):
    """PRD §3.4: "electing `LEGACY_SUBSIDIZED` for a property whose `is_sfha` is
    false is rejected with `ERR_RATING_METHOD_NOT_ELIGIBLE` (HTTP 422)"

    Design: Corner/validations/legacy_rating_on_non_sfha_returns_not_eligible
    """
    community = create_community()
    prop = create_property(
        community["id"], "h-nl", flood_zone="X",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=10.0,
    )
    resp = api.quote_policy(
        prop["id"],
        {"rating_method": "LEGACY_SUBSIDIZED", "building_coverage": 100000, "contents_coverage": 40000},
        make_policy_holder_headers("h-nl"),
    )
    validate_error(resp, ApiErrorId.ERR_RATING_METHOD_NOT_ELIGIBLE, expected_status=422)


def test_building_coverage_above_cap_rejected(api):
    """PRD §3.4: "Coverage limits are capped: `building_coverage` must lie between
    0 and 250000 inclusive and `contents_coverage` between 0 and 100000
    inclusive"
    PRD §3.4: "A request that exceeds a coverage cap or names a deductible outside
    the permitted set is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/coverage_above_building_cap_returns_limit_exceeded
    """
    community = create_community()
    prop = create_property(
        community["id"], "h-cp", flood_zone="AE",
        occupancy="PRIMARY_RESIDENCE", base_flood_elevation_ft=8.0,
    )
    resp = api.quote_policy(
        prop["id"],
        {"rating_method": "LEGACY_SUBSIDIZED", "building_coverage": 300000, "contents_coverage": 100000},
        make_policy_holder_headers("h-cp"),
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_LIMIT_EXCEEDED, expected_status=422)


# --- Authentication / authorization (corner) -------------------------------

def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request whose `X-User-Role` is missing or is not one of these
    four recognized roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unauthenticated_missing_role_header
    """
    resp = api._request(
        "POST", "/communities",
        {"name": "NoAuth", "county_code": "C127"},
        headers={},  # no X-User-Role
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_policyholder_cannot_bind_policy(api):
    """PRD §2.1: "A request from a syntactically valid role that is not permitted
    to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/rbac/policyholder_cannot_bind_policy
    """
    set_clock("2026-03-01T00:00:00Z")
    community, prop, policy = setup_quoted_policy(
        owner_id="h-rb", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10, is_lender_required=True,
        building_coverage=100000, contents_coverage=40000,
    )
    resp = api.bind_policy(policy["id"], make_policy_holder_headers("h-rb"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_underwriter_cannot_approve_claim(api):
    """PRD §2.1: "A request from a syntactically valid role that is not permitted
    to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/rbac/underwriter_cannot_approve_claim
    """
    community, prop, policy, claim, _proof = setup_claim_with_accepted_proof(
        owner_id="h-ra", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True,
        claim_overrides={"building_loss": 5000},
        proof_overrides={"documented_building_loss": 5000},
    )
    # approve is an Adjuster exclusive; the Underwriter is denied.
    resp = api.approve_claim(
        claim["id"], {"expected_claim_version": claim["version"]},
        TEST_USERS["underwriter_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


# --- Optimistic concurrency (corner) ---------------------------------------

def test_stale_claim_version_on_deny_rejected(api):
    """PRD §2.6: "For claim approval and claim denial, the request must carry
    `expected_claim_version` matching the claim's current `version`; because
    rejecting a supporting proof-of-loss legitimately bounces the claim back and
    advances its `version`, an approval or denial still carrying an outdated
    version is acting on a stale view and is rejected with
    `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_claim_version_on_deny_returns_412
    """
    community, prop, policy, claim = setup_claim_under_review(
        owner_id="h-sd", flood_zone="X", base_flood_elevation_ft=10.0,
        lowest_floor_elevation_ft=11.0, crs_class=10,
        building_coverage=100000, contents_coverage=40000,
        quote_as_underwriter=True, claim_overrides={"building_loss": 5000},
    )
    stale_version = claim["version"]  # captured at open-review
    # A proof reject bounces the claim back to SUBMITTED, advancing its version.
    proof = file_proof_of_loss(claim["id"], "h-sd", documented_building_loss=5000)
    api.reject_proof_of_loss(proof["id"], TEST_USERS["adjuster_headers"])
    # Re-open review advances the version again, so stale_version is now behind.
    open_review(claim["id"])

    resp = api.deny_claim(
        claim["id"], {"expected_claim_version": stale_version},
        TEST_USERS["adjuster_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION, expected_status=412)
