"""Foreign travel extensions: cross-policy prerequisites, posture-gated
approval, and half-open overlap / envelope rules (PRD §3.1, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_policy_payload, create_travel_extension_payload,
    set_logical_clock, create_production, create_and_bind_policy,
    get_production_version, setup_travel_ready_production,
    request_travel_extension, assert_travel_extension,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
UW = TEST_USERS["underwriter_headers"]


# ─── Approval requires bound GL-backed FT policy (difficulty) ───

def test_foreign_travel_approve_succeeds_with_bound_policies(api):
    """PRD §3.6: "A `FOREIGN_TRAVEL` policy on the production must be `BOUND`,
    `ENDORSED_PENDING`, or `ACTIVE`, and the travel window must overlap that
    policy's effective window."
    PRD §3.6: "The production's posture must be `BOUND_PARTIAL` or
    `BOUND_FULL`, or approval is refused with `ERR_POSTURE_BLOCKS_FOREIGN`."

    Design: Difficulty/cross_entity_state_dependency/foreign_travel_requires_bound_gl_policy
    """
    prod, gl, ft = setup_travel_ready_production()
    ext = request_travel_extension(prod["id"], territory_code="FR")
    approved = validate_success(
        api.approve_travel_extension(prod["id"], ext["id"], UW), 200)
    assert approved["status"] == "APPROVED"
    assert_travel_extension(approved)


def test_foreign_travel_policy_bind_requires_bound_gl(api):
    """PRD §3.1: "Binding a `FOREIGN_TRAVEL` policy requires a
    `GENERAL_LIABILITY` policy on the same production to already be `BOUND`,
    `ENDORSED_PENDING`, or `ACTIVE`; otherwise the refusal is
    `ERR_GL_PREREQUISITE_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/foreign_travel_requires_bound_gl_policy
    """
    set_logical_clock()
    prod = create_production()
    ft = validate_success(
        api.create_policy(
            prod["id"],
            create_policy_payload(coverage_line="FOREIGN_TRAVEL",
                                  carrier_code="TRAVELERS"),
            BROKER),
        201)
    version = get_production_version(prod["id"])
    res = api.bind_policy(prod["id"], ft["id"],
                          {"expected_production_version": version}, BROKER)
    validate_error(res, "ERR_GL_PREREQUISITE_MISSING", expected_status=422)


# ─── Half-open overlap semantics (difficulty) ─────────

def test_foreign_travel_adjacent_window_allowed(api):
    """PRD §3.6: "for the same production and the same `territory_code`, no
    `APPROVED` or `ACTIVE` extension may overlap the requested window, where
    intervals are half-open — an extension starting exactly when another ends
    does not overlap"

    Existing APPROVED window [2026-07-01, 2026-07-15); the new window starts
    exactly at 2026-07-15, touching but not overlapping, and must approve.

    Design: Difficulty/resource_temporal_overlap/foreign_travel_half_open_overlap
    """
    prod, gl, ft = setup_travel_ready_production()
    first = request_travel_extension(
        prod["id"], territory_code="FR",
        travel_window_start="2026-07-01T00:00:00Z",
        travel_window_end="2026-07-15T00:00:00Z")
    validate_success(api.approve_travel_extension(prod["id"], first["id"], UW), 200)

    adjacent = request_travel_extension(
        prod["id"], territory_code="FR",
        travel_window_start="2026-07-15T00:00:00Z",
        travel_window_end="2026-07-25T00:00:00Z",
        travelers_count=3, repatriation_limit_cents=300000)
    approved = validate_success(
        api.approve_travel_extension(prod["id"], adjacent["id"], UW), 200)
    assert approved["status"] == "APPROVED"


def test_foreign_travel_overlapping_window_rejected(api):
    """PRD §3.6: "Either violation is rejected with
    `ERR_FOREIGN_TRAVEL_OVERLAP` (HTTP 422)."
    PRD §3.6: "for the same production and the same `territory_code`, no
    `APPROVED` or `ACTIVE` extension may overlap the requested window, where
    intervals are half-open — an extension starting exactly when another ends
    does not overlap"

    The new window [2026-07-10, 2026-07-20) starts strictly inside the
    existing APPROVED window [2026-07-01, 2026-07-15).

    Design: Difficulty/resource_temporal_overlap/foreign_travel_half_open_overlap
    """
    prod, gl, ft = setup_travel_ready_production()
    first = request_travel_extension(
        prod["id"], territory_code="FR",
        travel_window_start="2026-07-01T00:00:00Z",
        travel_window_end="2026-07-15T00:00:00Z")
    validate_success(api.approve_travel_extension(prod["id"], first["id"], UW), 200)

    overlapping = request_travel_extension(
        prod["id"], territory_code="FR",
        travel_window_start="2026-07-10T00:00:00Z",
        travel_window_end="2026-07-20T00:00:00Z",
        travelers_count=2, repatriation_limit_cents=200000)
    res = api.approve_travel_extension(prod["id"], overlapping["id"], UW)
    validate_error(res, "ERR_FOREIGN_TRAVEL_OVERLAP", expected_status=422)
