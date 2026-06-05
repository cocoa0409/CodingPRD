"""Onboarding (policies, coverages, adjusters) and FNOL filing.

Covers: policy creation defaults, required-field/type/range validation, parent
existence, claim filing defaults, listing/pagination, coverage uniqueness,
policy-period overlap, and RBAC on setup/filing operations.
"""
import uuid

import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_policy, assert_claim,
    create_policy_payload, create_adjuster_payload, create_claim_payload,
    create_coverage_payload,
    TEST_USERS,
    make_claims_adjuster_headers,
    create_policy, add_collision_coverage, create_adjuster, file_claim,
    setup_claim_under_review,
)

SUP = TEST_USERS["supervisor_headers"]
SUB = TEST_USERS["subrogation_headers"]


def _u(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_create_policy_returns_201_with_system_fields(api):
    """PRD §3.1: "A newly created policy begins in `ACTIVE` status." PRD §2.4: "an
    integer `version` that begins at 1 and increases by one on each modification to the
    resource." PRD §3.1: "The fault rule is one of `PURE`, `MODIFIED_50`, or
    `MODIFIED_51` and defaults to `MODIFIED_50` when omitted".

    Design: Corner/entities/create_policy_returns_201_with_system_fields
    """
    payload = {
        "policyholder_name": "New Co",
        "policy_number": _u("POL-NEW"),
        "effective_date": "2026-01-01T00:00:00.000Z",
        "expiration_date": "2026-12-31T00:00:00.000Z",
    }
    res = api.create_policy(payload, SUP)
    policy = validate_success(res, 201)
    assert_policy(policy)
    assert policy["status"] == "ACTIVE"
    assert policy["version"] == 1
    assert policy["comparative_fault_rule"] == "MODIFIED_50"


def test_create_policy_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "A policy is created with a `policyholder_name`, a `policy_number`
    (which must be unique across all policies), an `effective_date`, and an
    `expiration_date`". PRD §3.6: "then validates the request body — required fields
    present and well-typed, enum values within their declared set, and any `fault_pct`
    or `insured_fault_pct` within 0 through 100 inclusive — failing with
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_policy_missing_required_field_returns_invalid_request
    """
    payload = {
        "policyholder_name": "No Number Co",
        "effective_date": "2026-01-01T00:00:00.000Z",
        "expiration_date": "2026-12-31T00:00:00.000Z",
    }
    res = api.create_policy(payload, SUP)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_get_claim_nonexistent_returns_not_found(api):
    """PRD §3.6: "resolves all path- and body-referenced resources left to right
    (`ERR_NOT_FOUND` on the first missing one)".

    Design: Corner/entities/get_claim_nonexistent_returns_not_found
    """
    res = api.get_claim("00000000-0000-4000-8000-000000000000", SUP)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_claim_create_defaults_insured_fault_and_disposition(api):
    """PRD §3.2: "Two optional inputs round out the filing: `insured_fault_pct`, the
    insured party's own fault percentage between 0 and 100 inclusive (defaulting to 0),
    and `salvage_value_cents`, the salvage proceeds expected for a totaled vehicle
    (defaulting to 0 and only meaningful on the total-loss path)." PRD §3.2: "A new
    claim begins in `FNOL_SUBMITTED` status with `version` 1, a null `disposition`, a
    `settlement_cents` of 0, a `total_disbursed_cents` of 0, and a null
    `assigned_adjuster_id`."

    Design: Corner/entities/claim_create_defaults_insured_fault_and_disposition
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.create_claim(
        create_claim_payload(policy["id"], loss_type="COLLISION", vehicle_acv_cents=800_000),
        headers,
    )
    claim = validate_success(res, 201)
    assert_claim(claim)
    assert claim["insured_fault_pct"] == 0
    assert claim["status"] == "FNOL_SUBMITTED"
    assert claim["settlement_cents"] == 0


def test_claim_create_bad_loss_type_enum_returns_invalid_request(api):
    """PRD §3.6: "then validates the request body — required fields present and
    well-typed, enum values within their declared set, and any `fault_pct` or
    `insured_fault_pct` within 0 through 100 inclusive — failing with
    `ERR_INVALID_REQUEST`." PRD §3.2: loss_type is `COLLISION` or `COMPREHENSIVE`.

    Design: Corner/entities/claim_create_bad_loss_type_enum_returns_invalid_request
    """
    policy = create_policy(comparative_fault_rule="PURE")
    adjuster = create_adjuster(license_tier="STANDARD")
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.create_claim(
        create_claim_payload(policy["id"], loss_type="FLOOD", vehicle_acv_cents=800_000),
        headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_claim_create_fault_pct_out_of_range_returns_invalid_request(api):
    """PRD §3.6: "then validates the request body — required fields present and
    well-typed, enum values within their declared set, and any `fault_pct` or
    `insured_fault_pct` within 0 through 100 inclusive — failing with
    `ERR_INVALID_REQUEST`." PRD §3.2: insured_fault_pct is "the insured party's own
    fault percentage between 0 and 100 inclusive".

    Design: Corner/entities/claim_create_fault_pct_out_of_range_returns_invalid_request
    """
    policy = create_policy(comparative_fault_rule="PURE")
    adjuster = create_adjuster(license_tier="STANDARD")
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.create_claim(
        create_claim_payload(
            policy["id"], loss_type="COLLISION", vehicle_acv_cents=800_000, insured_fault_pct=150),
        headers,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


def test_claim_create_unknown_policy_returns_not_found(api):
    """PRD §3.6: "resolves all path- and body-referenced resources left to right
    (`ERR_NOT_FOUND` on the first missing one)". The claim's policy_id is a body FK.

    Design: Corner/entities/claim_create_unknown_policy_returns_not_found
    """
    adjuster = create_adjuster(license_tier="STANDARD")
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.create_claim(
        create_claim_payload(
            "00000000-0000-4000-8000-000000000999",
            loss_type="COLLISION", vehicle_acv_cents=800_000),
        headers,
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_claims_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned". PRD §2.2:
    "The `response_type` is either "object" for a single resource or "array" for a
    list of resources." PRD §2.3: "Every list response carries `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_claims_pagination_envelope
    """
    policy = create_policy(comparative_fault_rule="PURE")
    adjuster = create_adjuster(license_tier="STANDARD")
    file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=700_000)

    res = api.list_claims(SUP, params={"policy_id": policy["id"], "limit": 1, "offset": 0})
    body = res.json()
    assert body["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1


def test_coverage_reverse_reachability_list_by_policy(api):
    """PRD §2.5: "Some read endpoints are addressed through a parent path segment — for
    example, listing the coverages of a policy". PRD §2.2: "The `response_type` is
    either "object" for a single resource or "array" for a list of resources." A policy
    with two coverages lists both.

    Design: Corner/endpoints/coverage_reverse_reachability_list_by_policy
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    api.create_coverage(
        policy["id"],
        {"coverage_type": "RENTAL", "limit_cents": 100_000,
         "rental_daily_cap_cents": 5_000, "rental_max_days": 10},
        SUP,
    )
    res = api.list_coverages(policy["id"], SUP)
    body = res.json()
    assert body["response_type"] == "array"
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"expected 2 coverages, got {meta['total_count']}"
    assert len(data) == 2


def test_duplicate_coverage_type_rejected(api):
    """PRD §3.1: "At most one coverage of a given `coverage_type` may exist per policy;
    a second coverage of the same type on the same policy is rejected with
    `ERR_DUPLICATE_COVERAGE`."

    Design: Corner/validations/duplicate_coverage_type_rejected
    """
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    res = api.create_coverage(
        policy["id"],
        create_coverage_payload(coverage_type="COLLISION", limit_cents=2_000_000, deductible_cents=100_000),
        SUP,
    )
    validate_error(res, "ERR_DUPLICATE_COVERAGE", expected_status=409)


def test_duplicate_insured_party_rejected(api):
    """PRD §3.8: "At most one party with `party_role` `INSURED` may exist per claim; a
    second insured party is rejected with `ERR_DUPLICATE_INSURED_PARTY`."

    Design: Corner/validations/duplicate_insured_party_rejected
    """
    policy = create_policy(comparative_fault_rule="PURE")
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    api.create_claim_party(
        {"claim_id": claim["id"], "party_role": "INSURED", "display_name": "The Insured", "fault_pct": 0},
        headers,
    )
    res = api.create_claim_party(
        {"claim_id": claim["id"], "party_role": "INSURED", "display_name": "Another Insured", "fault_pct": 0},
        headers,
    )
    validate_error(res, "ERR_DUPLICATE_INSURED_PARTY", expected_status=409)


# ─── Policy-period overlap (resource_temporal_overlap, difficulty) ───

def test_policy_period_overlap_closed_adjacency_rejected(api):
    """PRD §3.1: "A new policy is rejected with `ERR_POLICY_PERIOD_OVERLAP` if that
    closed interval overlaps the closed interval of any existing policy for the same
    `policyholder_name` whose `status` is either `ACTIVE` or `LAPSED`". PRD §3.1:
    "Adjacency is treated as a collision here: touching endpoints do overlap, so a new
    policy's `effective_date` must fall strictly after the prior policy's
    `expiration_date`."

    Design: Difficulty/resource_temporal_overlap/policy_period_overlap_closed_adjacency_rejected
    """
    holder = _u("Same Holder")
    api.create_policy(
        create_policy_payload(
            policyholder_name=holder, policy_number=_u("POL-SAME-1"),
            effective_date="2026-01-01T00:00:00.000Z", expiration_date="2026-12-31T00:00:00.000Z",
            comparative_fault_rule="PURE"),
        SUP,
    )
    # New policy starting exactly on the prior policy's expiration_date (touching -> collides).
    res = api.create_policy(
        create_policy_payload(
            policyholder_name=holder, policy_number=_u("POL-SAME-2"),
            effective_date="2026-12-31T00:00:00.000Z", expiration_date="2027-12-31T00:00:00.000Z",
            comparative_fault_rule="PURE"),
        SUP,
    )
    validate_error(res, "ERR_POLICY_PERIOD_OVERLAP", expected_status=409)


def test_policy_period_overlap_distinct_holder_allowed(api):
    """PRD §3.1: "A new policy is rejected with `ERR_POLICY_PERIOD_OVERLAP` if that
    closed interval overlaps the closed interval of any existing policy for the same
    `policyholder_name`". A different policyholder_name with the same window must NOT
    collide.

    Design: Difficulty/resource_temporal_overlap/policy_period_overlap_closed_adjacency_rejected
    """
    api.create_policy(
        create_policy_payload(
            policyholder_name=_u("Holder A"), policy_number=_u("POL-A"),
            effective_date="2026-01-01T00:00:00.000Z", expiration_date="2026-12-31T00:00:00.000Z",
            comparative_fault_rule="PURE"),
        SUP,
    )
    res = api.create_policy(
        create_policy_payload(
            policyholder_name=_u("Holder B"), policy_number=_u("POL-B"),
            effective_date="2026-01-01T00:00:00.000Z", expiration_date="2026-12-31T00:00:00.000Z",
            comparative_fault_rule="PURE"),
        SUP,
    )
    policy = validate_success(res, 201)
    assert policy["status"] == "ACTIVE"


# ─── RBAC (rbac section, difficulty) ───

def test_adjuster_cannot_assign_adjuster(api):
    """PRD §2.1: "A `ClaimsSupervisor` is the administrative and fiscal authority: they
    set up policies, coverages, and adjusters, assign adjusters to claims, settle and
    close claims, and are the sole authority permitted to void a disbursement." PRD
    §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/adjuster_cannot_assign_adjuster
    """
    # Build a verified (not yet assigned) claim so the adjuster role is the actor.
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    adj_headers = make_claims_adjuster_headers(adjuster["id"])
    verified = api.verify_coverage(claim["id"], adj_headers).json()["data"]
    res = api.assign_adjuster(
        claim["id"],
        {"adjuster_id": adjuster["id"], "expected_claim_version": verified["version"]},
        adj_headers,  # ClaimsAdjuster acting on a ClaimsSupervisor-exclusive op
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_subrogation_specialist_cannot_author_repair_estimate(api):
    """PRD §2.1: "A `ClaimsAdjuster` is the front-line handler who files losses,
    verifies coverage, authors and submits repair estimates, computes rentals, and
    decides the repair disposition." PRD §2.1: "When the headers are well-formed but
    the named role is not permitted to perform the requested operation, the request is
    rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/subrogation_specialist_cannot_author_repair_estimate
    """
    ctx = setup_claim_under_review()
    res = api.create_repair_estimate(
        {"claim_id": ctx["claim"]["id"], "lines": [{"description": "x", "labor_cents": 1000, "parts_cents": 0}]},
        SUB,  # SubrogationSpecialist acting on a ClaimsAdjuster-exclusive op
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_policy(
        create_policy_payload(policyholder_name="NoAuth Co", policy_number=_u("POL-NA")),
        {"Content-Type": "application/json"},  # no X-User-Role / X-User-ID
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "if `X-User-Role` does not name a role the system recognizes, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_policy(
        create_policy_payload(policyholder_name="Bad Role Co", policy_number=_u("POL-BR")),
        {"X-User-ID": "x", "X-User-Role": "Wizard", "Content-Type": "application/json"},
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
