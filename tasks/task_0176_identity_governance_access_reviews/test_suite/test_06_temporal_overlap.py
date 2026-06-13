"""Temporal-window rules: half-open JIT-grant overlap (and touching adjacency),
and the closed-interval campaign window with its one-day buffer.

Derived from PRD §3.2 (just-in-time windows) and §3.7 (campaign launch
scheduling guards).
"""
from test_helpers import (
    validate_success, validate_error,
    create_entitlement_payload, create_role_payload, create_identity_payload,
    create_grant_payload, create_campaign_payload,
    ApiErrorId,
    TEST_USERS,
)

CATALOG = TEST_USERS["catalog_admin_headers"]
MANAGER = TEST_USERS["access_manager_headers"]
CAMPAIGN = TEST_USERS["campaign_admin_headers"]


def test_jit_window_overlap_rejected(api):
    """PRD §3.2: "treating each window as the half-open interval from
    effective_from up to but not including effective_until, two windows that merely
    touch at an endpoint are allowed, but any genuine overlap is rejected with
    ERR_JIT_WINDOW_OVERLAP."

    A first JIT grant of P spans [10:00, 12:00); a second JIT grant of the same P
    starting at 11:00 (strictly inside) -> 409 ERR_JIT_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/jit_grant_window_half_open_overlap
    """
    jp = validate_success(api.create_entitlement(
        create_entitlement_payload(name="JitP", system_code="JP",
                                   is_privileged=True, risk_weight=20), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Jit", email="jit@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"], create_grant_payload(
        jp["id"], identity["version"], is_just_in_time=True,
        effective_from="2026-06-01T10:00:00Z",
        effective_until="2026-06-01T12:00:00Z"), MANAGER), 201)
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)

    resp = api.create_grant(identity["id"], create_grant_payload(
        jp["id"], fresh["version"], is_just_in_time=True,
        effective_from="2026-06-01T11:00:00Z",
        effective_until="2026-06-01T13:00:00Z"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_JIT_WINDOW_OVERLAP.value)


def test_jit_window_enclosing_overlap_rejected(api):
    """PRD §3.2: "the system checks the proposed window against every other
    just-in-time grant of the same identity and entitlement; treating each window as
    the half-open interval from effective_from up to but not including
    effective_until ... any genuine overlap is rejected with ERR_JIT_WINDOW_OVERLAP."

    A different overlap geometry: the new window [09:00, 13:00) strictly encloses the
    existing [10:00, 12:00) for the same identity+entitlement. It is a genuine
    overlap, not a mere touch, so it is rejected with ERR_JIT_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/jit_grant_window_half_open_overlap
    """
    jp = validate_success(api.create_entitlement(
        create_entitlement_payload(name="JitP2", system_code="JP2",
                                   is_privileged=True, risk_weight=20), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Jit2", email="jit2@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"], create_grant_payload(
        jp["id"], identity["version"], is_just_in_time=True,
        effective_from="2026-06-01T10:00:00Z",
        effective_until="2026-06-01T12:00:00Z"), MANAGER), 201)
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)

    resp = api.create_grant(identity["id"], create_grant_payload(
        jp["id"], fresh["version"], is_just_in_time=True,
        effective_from="2026-06-01T09:00:00Z",
        effective_until="2026-06-01T13:00:00Z"), MANAGER)
    validate_error(resp, ApiErrorId.ERR_JIT_WINDOW_OVERLAP.value)


def test_jit_adjacent_window_touching_allowed(api):
    """PRD §3.2: "treating each window as the half-open interval from
    effective_from up to but not including effective_until, two windows that merely
    touch at an endpoint are allowed".

    A first JIT grant of P spans [10:00, 12:00); a second JIT grant of the same P
    starting exactly at 12:00 (touching) is allowed -> 201.

    Design: Corner/cross_cutting_complexity_layers/jit_adjacent_window_touching_allowed
    """
    ap = validate_success(api.create_entitlement(
        create_entitlement_payload(name="AdjP", system_code="AP",
                                   is_privileged=True, risk_weight=20), CATALOG), 201)
    identity = validate_success(api.create_identity(
        create_identity_payload(display_name="Adj", email="adj@x.com"), MANAGER), 201)
    validate_success(api.create_grant(identity["id"], create_grant_payload(
        ap["id"], identity["version"], is_just_in_time=True,
        effective_from="2026-06-01T10:00:00Z",
        effective_until="2026-06-01T12:00:00Z"), MANAGER), 201)
    fresh = validate_success(api.get_identity(identity["id"], MANAGER), 200)

    second = validate_success(api.create_grant(identity["id"], create_grant_payload(
        ap["id"], fresh["version"], is_just_in_time=True,
        effective_from="2026-06-01T12:00:00Z",
        effective_until="2026-06-01T14:00:00Z"), MANAGER), 201)
    assert second["lifecycle_status"] == "ACTIVE", second["lifecycle_status"]


def test_campaign_window_buffer_violation_rejected(api):
    """PRD §3.7: "this campaign's review_window_start must be on or after the prior
    CLOSED campaign's review_window_end for the same scope_role_id plus a one-day
    buffer", surfaced as ERR_CAMPAIGN_WINDOW_OVERLAP.

    A prior campaign for role R ran [2026-06-01, 2026-06-30] and is CLOSED; a new
    campaign for R whose review_window_start is 2026-06-30 (inside the +1 day
    buffer) is rejected at launch -> 409 ERR_CAMPAIGN_WINDOW_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_gap_overlap
    """
    be = validate_success(api.create_entitlement(
        create_entitlement_payload(name="BufE", system_code="BE", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([be["id"]], name="BufRole"), CATALOG), 201)
    prior = validate_success(api.create_campaign(
        create_campaign_payload(role["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z",
                                name="Prior"), CAMPAIGN), 201)
    validate_success(api.launch_campaign(prior["id"], CAMPAIGN), 200)
    validate_success(api.close_campaign(prior["id"], CAMPAIGN), 200)
    nxt = validate_success(api.create_campaign(
        create_campaign_payload(role["id"], "2026-06-30T00:00:00Z", "2026-07-30T00:00:00Z",
                                name="Next"), CAMPAIGN), 201)

    resp = api.launch_campaign(nxt["id"], CAMPAIGN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP.value)


def test_concurrent_active_campaign_for_same_role_rejected(api):
    """PRD §3.7: "Two scheduling guards protect the launch, both of which surface as
    ERR_CAMPAIGN_WINDOW_OVERLAP: no other campaign for the same scope_role_id may
    currently be in ACTIVE status".

    The other guard of the same rule: with one campaign for role R already launched
    (ACTIVE) and not closed, launching a second campaign for R is rejected with
    ERR_CAMPAIGN_WINDOW_OVERLAP regardless of its window.

    Design: Difficulty/resource_temporal_overlap/campaign_window_buffer_gap_overlap
    """
    be = validate_success(api.create_entitlement(
        create_entitlement_payload(name="BufE2", system_code="BE2", risk_weight=10), CATALOG), 201)
    role = validate_success(api.create_role(
        create_role_payload([be["id"]], name="BufRole2"), CATALOG), 201)
    first = validate_success(api.create_campaign(
        create_campaign_payload(role["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z",
                                name="First"), CAMPAIGN), 201)
    validate_success(api.launch_campaign(first["id"], CAMPAIGN), 200)
    second = validate_success(api.create_campaign(
        create_campaign_payload(role["id"], "2026-08-01T00:00:00Z", "2026-08-30T00:00:00Z",
                                name="Second"), CAMPAIGN), 201)

    resp = api.launch_campaign(second["id"], CAMPAIGN)
    validate_error(resp, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP.value)
