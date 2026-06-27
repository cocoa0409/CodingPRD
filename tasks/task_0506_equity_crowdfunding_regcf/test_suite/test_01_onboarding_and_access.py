"""Issuer/investor/offering creation, computed fields, existence, RBAC, and auth gates.

Covers queue-B corner instances from the entities, validations, errors, and rbac sections,
plus the dual-variant annual-limit (queue A) which is observable directly on the Investor.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_issuer, assert_investor, assert_offering,
    create_issuer_payload, create_investor_payload, create_offering_payload,
    make_anonymous_headers, make_issuer_headers, make_investor_headers,
    make_compliance_officer_headers,
    create_issuer, create_verified_issuer, create_investor,
)

ANON = make_anonymous_headers()
CO = make_compliance_officer_headers()


# ============================================================================
# Issuer / Investor / Offering creation (entities section)
# ============================================================================

def test_create_issuer_returns_201_with_onboarding_status(api):
    """PRD §3.1: "A freshly registered issuer is created in the `ONBOARDING` status, and its
    trailing-proceeds figure `total_raised_trailing_12mo_cents` begins at zero."
    PRD §3.1: "The payload may also carry a `bad_actor_flag`; when omitted it defaults to `false`."

    Design: Corner/entities/create_issuer_returns_201_with_onboarding_status
    """
    payload = create_issuer_payload(legal_name="Fresh Co")
    resp = api.create_issuer(payload, headers=ANON)
    data = validate_success(resp, expected_status=201)
    assert_issuer(data)
    assert data["status"] == "ONBOARDING"
    assert data["bad_actor_flag"] is False
    assert data["total_raised_trailing_12mo_cents"] == 0


def test_create_investor_computes_annual_limit_default_unaccredited(api):
    """PRD §3.4: "A new investor's `accreditation_status` begins at `UNACCREDITED`, and the system
    computes the investor's `annual_limit_cents` at registration."
    PRD §3.4: "Otherwise — that is, when either figure is below one hundred twenty-four thousand
    dollars — the base percentage is five percent of the *greater* figure, computed as the greater
    figure multiplied by five then integer-divided by one hundred (flooring)."

    Design: Corner/entities/create_investor_computes_annual_limit_default_unaccredited
    """
    # income 10,000,000c, net worth 10,000,000c: both below cap -> 5% of greater(10,000,000)=500,000.
    payload = create_investor_payload(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    resp = api.create_investor(payload, headers=ANON)
    data = validate_success(resp, expected_status=201)
    assert_investor(data)
    assert data["annual_limit_cents"] == 500_000
    assert data["accreditation_status"] == "UNACCREDITED"


def test_get_offering_not_found_returns_404(api):
    """PRD §2.5: "a reference to a missing issuer, offering, investor, investment, accreditation
    request, or update yields `ERR_NOT_FOUND`."

    Design: Corner/entities/get_offering_not_found_returns_404
    """
    resp = api.get_offering(NON_EXISTENT_UUID, headers=ANON)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_offering_missing_required_field_returns_invalid_request(api):
    """PRD §2.8: "and finally request-body well-formedness (`ERR_INVALID_REQUEST`) for malformed
    payloads."
    PRD §3.2: "the `min_target_cents` and `max_target_cents`, the `deadline_at` after which no
    further commitments are accepted, and optionally a `price_per_security_cents` and a
    `per_investor_cap_cents`."

    Design: Corner/entities/create_offering_missing_required_field_returns_invalid_request
    """
    issuer = create_issuer(legal_name="Mr Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    payload = {
        "issuer_id": issuer["id"],
        "regulation": "REG_CF",
        "security_type": "SAFE",
        # min_target_cents omitted
        "max_target_cents": 1_000_000,
        "deadline_at": "2026-12-01T00:00:00Z",
    }
    resp = api.create_offering(payload, headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_create_offering_system_fields_forced_to_defaults(api):
    """PRD §3.2: "A new offering starts with its `form_c_status` at `DRAFT` and its primary
    `status` at `DRAFT`, with `committed_amount_cents` and `swept_amount_cents` at zero,
    `secondary_listing_enabled` at `false`, and `live_at` and `close_at` both null."
    PRD §2.4: "an integer `version` that begins at its initial value and increments by one on
    each mutation."

    Design: Corner/entities/create_offering_system_fields_input_ignored
    """
    issuer = create_issuer(legal_name="Sf Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    payload = create_offering_payload(issuer["id"], min_target_cents=100_000, max_target_cents=1_000_000)
    resp = api.create_offering(payload, headers=issuer_headers)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["form_c_status"] == "DRAFT"
    assert data["committed_amount_cents"] == 0
    assert data["version"] == 1


def test_create_offering_equity_missing_price_returns_invalid_terms(api):
    """PRD §3.2: "For an `EQUITY` offering, `price_per_security_cents` is required and must be
    greater than zero; for a `SAFE` offering, `price_per_security_cents` must be omitted or null.
    Any violation of these term rules is rejected with `ERR_INVALID_OFFERING_TERMS`."

    Design: Corner/entities/create_offering_invalid_terms_equity_missing_price
    """
    issuer = create_issuer(legal_name="Eqt Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    payload = create_offering_payload(
        issuer["id"], security_type="EQUITY", min_target_cents=100_000, max_target_cents=1_000_000)
    payload.pop("price_per_security_cents", None)
    resp = api.create_offering(payload, headers=issuer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_OFFERING_TERMS, expected_status=422)


def test_duplicate_ein_returns_conflict(api):
    """PRD §3.1: "Attempting to register a second issuer with an `ein` that already exists is
    rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/validations/duplicate_ein_returns_conflict
    """
    first = create_issuer_payload(legal_name="Dup1 Co", ein="200000016")
    validate_success(api.create_issuer(first, headers=ANON), expected_status=201)
    second = create_issuer_payload(legal_name="Dup2 Co", ein="200000016",
                                   home_state_code="CA", entity_type="LLC")
    resp = api.create_issuer(second, headers=ANON)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE, expected_status=409)


# ============================================================================
# Auth / RBAC / ownership / segregation-of-duties (rbac + validations sections)
# ============================================================================

def test_investor_cannot_verify_issuer_forbidden_role(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/investor_cannot_verify_issuer_forbidden_role
    """
    issuer = create_issuer(legal_name="Fr Co")
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    resp = api.verify_issuer(issuer["id"], headers=make_investor_headers(investor["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, expected_status=403)


def test_issuer_cannot_act_on_other_issuers_offering_not_owner(api):
    """PRD §2.1: "An `Issuer` may act only on its own offerings and on the investor updates of its
    own offerings, and an `Investor` may act only on its own investments and accreditation
    requests; a write against a resource the caller does not own is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/issuer_cannot_act_on_other_issuers_offering_not_owner
    """
    issuer_a = create_verified_issuer(legal_name="Own A Co")
    issuer_b = create_verified_issuer(legal_name="Own B Co")
    a_headers = make_issuer_headers(issuer_a["id"])
    offering = validate_success(
        api.create_offering(create_offering_payload(issuer_a["id"]), headers=a_headers),
        expected_status=201)
    validate_success(api.submit_form_c(offering["id"], headers=a_headers))
    validate_success(api.qualify_form_c(offering["id"], headers=CO))
    # Issuer B attempts to take issuer A's offering live.
    resp = api.go_live(offering["id"], headers=make_issuer_headers(issuer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    after = validate_success(api.get_offering(offering["id"], headers=a_headers))
    assert after["status"] == "DRAFT"


def test_issuer_cannot_self_qualify_own_form_c_segregation(api):
    """PRD §2.1: "the `ComplianceOfficer` who qualifies or rejects a Form C must not be the same
    principal as the offering's issuer — that is, the officer's `X-User-ID` must not equal the
    offering's owning `Issuer` `id`. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/issuer_cannot_self_qualify_own_form_c_segregation
    """
    issuer = create_verified_issuer(legal_name="Sd Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    offering = validate_success(
        api.create_offering(create_offering_payload(issuer["id"]), headers=issuer_headers),
        expected_status=201)
    validate_success(api.submit_form_c(offering["id"], headers=issuer_headers))
    # ComplianceOfficer whose X-User-ID == issuer id (self-deal).
    self_dealing = make_compliance_officer_headers(issuer["id"])
    resp = api.qualify_form_c(offering["id"], headers=self_dealing)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    after = validate_success(api.get_offering(offering["id"], headers=issuer_headers))
    assert after["form_c_status"] == "SUBMITTED"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "When a protected endpoint is called without a well-formed pair of these headers,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    investor = create_investor(annual_income_cents=10_000_000, net_worth_cents=10_000_000)
    resp = api.create_accreditation_request(
        {"investor_id": investor["id"], "method": "INCOME"}, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_verify_bad_actor_issuer_returns_disqualified(api):
    """PRD §3.1: "Verification is permitted only when the issuer is in `ONBOARDING` and its
    `bad_actor_flag` is `false`; an attempt to verify a flagged issuer is rejected with
    `ERR_BAD_ACTOR_DISQUALIFIED`."

    Design: Corner/errors/verify_bad_actor_issuer_returns_disqualified
    """
    issuer = create_issuer(legal_name="Ba Co", bad_actor_flag=True)
    resp = api.verify_issuer(issuer["id"], headers=CO)
    validate_error(resp, ApiErrorId.ERR_BAD_ACTOR_DISQUALIFIED, expected_status=422)
    after = validate_success(api.get_issuer(issuer["id"], headers=CO))
    assert after["status"] == "ONBOARDING"


# ============================================================================
# Listing / pagination (endpoints section)
# ============================================================================

def test_list_offerings_filter_by_issuer_id_paginated(api):
    """PRD §4: "offerings by `issuer_id`, `regulation`, and `status`".
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside
    the `meta` object of the envelope, where `total_count` is the number of records matching the
    query before pagination and `has_more` indicates whether further records remain beyond the
    returned page."

    Design: Corner/endpoints/list_offerings_filter_by_issuer_id_paginated
    """
    issuer = create_issuer(legal_name="Lf Co")
    issuer_headers = make_issuer_headers(issuer["id"])
    validate_success(api.create_offering(
        create_offering_payload(issuer["id"], deadline_at="2026-12-01T00:00:00Z"),
        headers=issuer_headers), expected_status=201)
    validate_success(api.create_offering(
        create_offering_payload(issuer["id"], deadline_at="2026-12-15T00:00:00Z"),
        headers=issuer_headers), expected_status=201)
    resp = api.list_offerings(headers=ANON, params={"issuer_id": issuer["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 offerings for issuer, got {len(data)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ============================================================================
# Dual-variant annual limit (queue A) — observable on the Investor entity
# ============================================================================

def test_annual_limit_5pct_of_greater_when_one_below_cap(api):
    """PRD §3.4: "Otherwise — that is, when either figure is below one hundred twenty-four thousand
    dollars — the base percentage is five percent of the *greater* figure, computed as the greater
    figure multiplied by five then integer-divided by one hundred (flooring)."

    Design: Difficulty/dual_variant_calc/annual_limit_branch_variants_on_investor
    """
    # income $50,000 (5,000,000c), net worth $30,000 (3,000,000c): one below cap
    # -> 5% of greater(5,000,000) = 250,000c (also equals the floor).
    payload = create_investor_payload(annual_income_cents=5_000_000, net_worth_cents=3_000_000)
    data = validate_success(api.create_investor(payload, headers=ANON), expected_status=201)
    assert data["annual_limit_cents"] == 250_000


def test_annual_limit_10pct_of_lesser_when_both_above_cap(api):
    """PRD §3.4: "When both figures are at least one hundred twenty-four thousand dollars
    (12,400,000 cents), the base percentage is ten percent of the *lesser* figure, computed as the
    lesser figure multiplied by ten then integer-divided by one hundred (flooring)."

    Design: Difficulty/dual_variant_calc/annual_limit_branch_variants_on_investor
    """
    # income $200,000 (20,000,000c), net worth $500,000 (50,000,000c): both above cap
    # -> 10% of lesser(20,000,000) = 2,000,000c.
    payload = create_investor_payload(annual_income_cents=20_000_000, net_worth_cents=50_000_000)
    data = validate_success(api.create_investor(payload, headers=ANON), expected_status=201)
    assert data["annual_limit_cents"] == 2_000_000


def test_annual_limit_mode_a_nested_minmax_both_above_cap(api):
    """PRD §3.4: "The resulting `annual_limit_cents` is then clamped into the range whose floor is
    two thousand five hundred dollars (250,000 cents) and whose ceiling is one hundred twenty-four
    thousand dollars (12,400,000 cents): the system first takes the larger of the floor and the
    computed percentage, then takes the smaller of that result and the ceiling."

    Design: Difficulty/combinatorial_formula/annual_limit_mode_a_nested_minmax_branch
    """
    # income $200,000 / net worth $500,000: both above cap -> 10% of lesser(20,000,000) = 2,000,000c;
    # clamp(max(250,000, 2,000,000)=2,000,000, then min(2,000,000, 12,400,000))=2,000,000c.
    payload = create_investor_payload(annual_income_cents=20_000_000, net_worth_cents=50_000_000)
    data = validate_success(api.create_investor(payload, headers=ANON), expected_status=201)
    assert data["annual_limit_cents"] == 2_000_000


def test_annual_limit_mode_a_ceiling_clamp_applies(api):
    """PRD §3.4: "The resulting `annual_limit_cents` is then clamped into the range whose floor is
    two thousand five hundred dollars (250,000 cents) and whose ceiling is one hundred twenty-four
    thousand dollars (12,400,000 cents): the system first takes the larger of the floor and the
    computed percentage, then takes the smaller of that result and the ceiling."

    Design: Difficulty/combinatorial_formula/annual_limit_mode_a_nested_minmax_branch
    """
    # income $2,000,000 (200,000,000c) / net worth $2,000,000 (200,000,000c): both above cap ->
    # 10% of lesser(200,000,000) = 20,000,000c; nested clamp pulls it down to the 12,400,000c ceiling.
    payload = create_investor_payload(annual_income_cents=200_000_000, net_worth_cents=200_000_000)
    data = validate_success(api.create_investor(payload, headers=ANON), expected_status=201)
    assert data["annual_limit_cents"] == 12_400_000
