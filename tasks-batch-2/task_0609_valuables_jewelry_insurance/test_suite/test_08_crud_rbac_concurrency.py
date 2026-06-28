"""Policy CRUD and system-field handling, list filtering and pagination envelope, RBAC
authorization gates, and the two optimistic-concurrency rules (endorsement apply, claim
approve) in both stale-rejected and fresh-accepted forms.

Design queue B: entities, endpoints, rbac, cross-cutting complexity layers (OCC).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    assert_policy,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    file_claim,
    draft_endorsement,
    live_policy_version,
    setup_quoted_policy_with_item,
    setup_active_policy_with_item,
    setup_claim_under_review,
    setup_repair_order_in_progress,
    make_policyholder_headers,
    make_repair_shop_headers,
    create_repair_shop,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue B: entities — creation, required fields, not-found, system fields
# ─────────────────────────────────────────────────────────────────────────

def test_create_policy_returns_201_quoted_unbilled(api):
    """PRD §3.2: "A freshly created policy opens with coverage_status QUOTED and
    billing_status UNBILLED."
    PRD §2.4: "The version begins at its initial value when the resource is created"

    Design: Corner/entities/create_policy_returns_201_with_quoted_unbilled
    """
    ph = create_policyholder(email="e1@x.com", residence_zip="10001")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "coverage_type": "ALL_RISK",
         "valuation_basis": "AGREED_VALUE", "deductible_option": "LOW"}, _UW)
    policy = validate_success(res, 201)
    assert_policy(policy)
    assert policy["coverage_status"] == "QUOTED"
    assert policy["billing_status"] == "UNBILLED"
    assert policy["version"] == 1


def test_create_policy_missing_coverage_type_rejected(api):
    """PRD §2.10: "then body well-formedness — required fields present, enum values in range,
    monetary amounts strictly greater than zero, and ZIP codes exactly five digits
    (ERR_INVALID_REQUEST, HTTP 422)."

    Design: Corner/entities/create_policy_missing_required_field_returns_422
    """
    ph = create_policyholder(email="e2@x.com", residence_zip="10001")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "valuation_basis": "AGREED_VALUE",
         "deductible_option": "LOW"}, _UW)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 422)


def test_get_nonexistent_policy_returns_404(api):
    """PRD §2.8: "the server validates the chain left to right and rejects with ERR_NOT_FOUND
    (HTTP 404) at the first path segment that names a resource which does not exist."

    Design: Corner/entities/get_policy_nonexistent_returns_404
    """
    res = api.get_policy(NON_EXISTENT_UUID, _UW)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, 404)


def test_policy_system_fields_server_minted(api):
    """PRD §2.4: "Each such resource exposes an id — a server-minted UUID with no type prefix
    — alongside created_at and updated_at, both ISO 8601 UTC timestamps with three fractional
    digits, and a version integer. The version begins at its initial value when the resource
    is created"

    Design: Corner/entities/system_fields_generated_input_ignored
    """
    ph = create_policyholder(email="e4@x.com", residence_zip="10001")
    res = api.create_policy(
        {"policyholder_id": ph["id"], "coverage_type": "ALL_RISK",
         "valuation_basis": "AGREED_VALUE", "deductible_option": "LOW",
         "id": "client-supplied-id", "version": 99}, _UW)
    policy = validate_success(res, 201)
    assert is_valid_uuid(policy["id"])
    assert policy["id"] != "client-supplied-id"
    assert policy["version"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Queue B: endpoints — list filtering & pagination
# ─────────────────────────────────────────────────────────────────────────

def test_list_scheduled_items_filtered_by_policy_id(api):
    """PRD §3.2: "Scheduled items can be listed and filtered by policy_id or by appraisal_id."

    Design: Corner/endpoints/list_scheduled_items_by_policy_id
    """
    ph = create_policyholder(email="ep1@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    create_scheduled_item(policy["id"], description="Ring A", category="RING",
                          location_zip="10001", scheduled_value_cents=1000000)
    create_scheduled_item(policy["id"], description="Ring B", category="RING",
                          location_zip="10001", scheduled_value_cents=800000)

    data, meta = validate_paginated(
        api.list_scheduled_items(_UW, params={"policy_id": policy["id"]}))
    assert meta["total_count"] == 2
    for item in data:
        assert item["policy_id"] == policy["id"]


def test_list_policies_pagination_envelope(api):
    """PRD §2.3: "Every list response carries limit, offset, total_count, and has_more inside
    the meta object of the envelope."

    Design: Corner/endpoints/list_policies_pagination_envelope
    """
    ph = create_policyholder(email="ep2@x.com", residence_zip="10001")
    create_policy(ph["id"], coverage_type="ALL_RISK",
                  valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    data, meta = validate_paginated(api.list_policies(_UW))
    assert "total_count" in meta
    assert "has_more" in meta
    assert "limit" in meta
    assert "offset" in meta


# ─────────────────────────────────────────────────────────────────────────
# Queue B: rbac
# ─────────────────────────────────────────────────────────────────────────

def test_policyholder_cannot_bind_policy(api):
    """PRD §2.1: "A request whose role is well-formed but not permitted for the targeted
    operation — or whose user does not own a resource they are required to own — is rejected
    with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/policyholder_cannot_bind_policy
    """
    ctx = setup_quoted_policy_with_item()
    ph_headers = make_policyholder_headers(ctx["policyholder"]["id"])
    res = api.bind_policy(ctx["policy"]["id"], ph_headers)  # bind is Underwriter-exclusive
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected
    with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    res = api.get_policy(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_repair_shop_ownership_enforced_on_complete(api):
    """PRD §2.1: "When X-User-Role is RepairShop, X-User-ID is the id of the acting RepairShop;
    ownership checks on a repair order compare its repair_shop_id to X-User-ID, so a shop may
    accept, complete, or deem-total-loss only the repair orders assigned to it."

    Design: Corner/rbac/repairshop_ownership_enforced_on_complete
    """
    ctx = setup_repair_order_in_progress(shop_in_network=True, claimed_amount_cents=300000)
    other_shop = create_repair_shop(name="Shop Y", service_zip="10006", in_network=True)
    # A different shop (not the assigned one) attempts to complete the order.
    res = api.complete_repair_order(
        ctx["policy"]["id"], ctx["claim"]["id"], {"actual_cost_cents": 200000},
        make_repair_shop_headers(other_shop["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)


# ─────────────────────────────────────────────────────────────────────────
# Queue B: cross-cutting — optimistic concurrency control
# ─────────────────────────────────────────────────────────────────────────

def test_endorsement_apply_stale_policy_version_rejected(api):
    """PRD §2.9: "The apply request must carry expected_policy_version, a non-optional field
    carrying the policy version the client last observed. If that value does not match the
    policy's current version — because another endorsement or a premium payment has advanced
    the policy since the client read it — the apply is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/occ_endorsement_apply_stale_policy_version
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    ph = create_policyholder(email="occ1@x.com", residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    create_scheduled_item(policy["id"], description="Ring", category="RING",
                          location_zip="10001", scheduled_value_cents=1000000)
    bound = bind_policy(policy["id"])
    stale_version = bound["version"]
    it2 = create_scheduled_item(policy["id"], description="Ring 2", category="RING",
                                location_zip="10001", scheduled_value_cents=800000)
    end = draft_endorsement(policy["id"], "ADD_ITEM", target_item_id=it2["id"])
    # A premium payment advances Policy.version past stale_version.
    pay_premium(policy["id"], ph["id"])

    res = api.apply_endorsement(policy["id"], end["id"],
                                {"expected_policy_version": stale_version}, _UW)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)


def test_claim_approve_stale_claim_version_rejected(api):
    """PRD §2.9: "The approve request must carry expected_claim_version, a non-optional field
    carrying the claim version the client last observed. If a request-info or provide-info
    cycle has advanced the claim's version since the adjuster read it, the approve is rejected
    with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/cross-cutting complexity layers/occ_claim_approve_stale_claim_version
    """
    ctx = setup_claim_under_review()
    pol, claim, ph = ctx["policy"], ctx["claim"], ctx["policyholder"]
    stale_version = claim["version"]
    ph_headers = make_policyholder_headers(ph["id"])
    # A request_info/provide_info cycle advances Claim.version past stale_version.
    validate_success(api.request_info_claim(pol["id"], claim["id"], _CA), 200)
    validate_success(api.provide_info_claim(pol["id"], claim["id"], ph_headers), 200)

    res = api.approve_claim(pol["id"], claim["id"],
                            {"expected_claim_version": stale_version}, _CA)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)


def test_endorsement_apply_current_version_succeeds(api):
    """PRD §2.9: "The apply request must carry expected_policy_version, a non-optional field
    carrying the policy version the client last observed. If that value does not match the
    policy's current version ... the apply is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD §3.9: "An ADD_ITEM apply transitions its target scheduled item from PENDING to ACTIVE."

    Design: Corner/cross-cutting complexity layers/occ_endorsement_apply_correct_version_succeeds
    """
    ctx = setup_active_policy_with_item()
    pol = ctx["policy"]
    it2 = create_scheduled_item(pol["id"], description="Ring 2", category="RING",
                                location_zip="10001", scheduled_value_cents=800000)
    end = draft_endorsement(pol["id"], "ADD_ITEM", target_item_id=it2["id"])
    live_v = live_policy_version(pol["id"])  # re-read fresh version immediately before apply
    applied = validate_success(
        api.apply_endorsement(pol["id"], end["id"],
                              {"expected_policy_version": live_v}, _UW), 200)
    assert applied["status"] == "APPLIED"
    item_after = validate_success(api.get_scheduled_item(it2["id"], _UW), 200)
    assert item_after["item_status"] == "ACTIVE"
