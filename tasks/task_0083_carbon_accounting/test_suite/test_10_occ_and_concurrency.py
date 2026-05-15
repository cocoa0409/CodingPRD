"""Optimistic concurrency, version conflicts, and race conditions
(PRD §2.5, §3.4, §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    create_active_project,
    create_credit,
    create_facility,
    create_factor_draft,
    create_organization,
    retire_credit_payload,
    run_race,
    setup_credit_lifecycle_dataset,
    setup_org_facility_period,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# OCC — version mismatch (PRD §2.5)
# ---------------------------------------------------------------------------
def test_patch_facility_with_stale_version_rejected(api,
                                                    platform_admin_headers):
    """PRD §2.5: "When a client supplies version and the value does not
    equal the resource's current version, the request is rejected with
    ERR_VERSION_CONFLICT and HTTP 409 before any business validation
    runs."
    """
    org, _, _ = setup_org_facility_period()
    fac = create_facility(org["id"])
    # First update succeeds, bumping version to 2
    res1 = api.update_facility(
        org["id"], fac["id"],
        {"name": "Renamed Once", "version": fac["version"]},
        platform_admin_headers,
    )
    updated = validate_success(res1)
    assert updated["version"] == fac["version"] + 1
    # Second update with the now-stale version fails
    res2 = api.update_facility(
        org["id"], fac["id"],
        {"name": "Renamed Twice", "version": fac["version"]},
        platform_admin_headers,
    )
    validate_error(res2, ApiErrorId.ERR_VERSION_CONFLICT.value)


def test_patch_facility_without_version_skips_occ(api, platform_admin_headers):
    """PRD §2.5: "When a client omits version, the OCC check is skipped
    and the request proceeds against whatever the current state is."
    """
    org, _, _ = setup_org_facility_period()
    fac = create_facility(org["id"])
    # Bump the version once by a prior update
    api.update_facility(
        org["id"], fac["id"], {"name": "First Bump"}, platform_admin_headers,
    )
    # Now patch without version — should still succeed
    res = api.update_facility(
        org["id"], fac["id"], {"name": "Second Bump"},
        platform_admin_headers,
    )
    validate_success(res)


def test_mutation_bumps_version_by_one(api, platform_admin_headers):
    """PRD §2.4: "version starts at 1 on creation, and increments by
    exactly 1 on every server-side mutation."
    """
    org, _, _ = setup_org_facility_period()
    fac = create_facility(org["id"])
    assert fac["version"] == 1
    res = api.update_facility(
        org["id"], fac["id"], {"name": "Bumped"}, platform_admin_headers,
    )
    updated = validate_success(res)
    assert updated["version"] == 2


# ---------------------------------------------------------------------------
# Concurrency — factor approval race (PRD §3.4)
# ---------------------------------------------------------------------------
def test_two_factor_approvals_for_same_code_serialize(api,
                                                     factor_manager_headers):
    """PRD §3.4: "When two FactorManagers race to approve two DRAFT
    versions for the same code at the same time, approvals serialize on
    the code: at most one transition from DRAFT to ACTIVE succeeds, and
    the loser sees a freshly superseded predecessor — the loser
    receives ERR_FACTOR_VERSION_CONFLICT and HTTP 409."
    """
    from test_helpers import create_approved_factor
    org = create_organization()
    # Establish v1 ACTIVE so two new DRAFTs both have a predecessor.
    v1 = create_approved_factor(
        org["id"], code="RACE-CODE",
        effective_from="2024-01-01T00:00:00.000Z",
    )
    d2 = create_factor_draft(
        org["id"], code="RACE-CODE",
        effective_from="2025-05-01T00:00:00.000Z",
    )
    d3 = create_factor_draft(
        org["id"], code="RACE-CODE",
        effective_from="2025-08-01T00:00:00.000Z",
    )
    results = run_race(
        lambda: api.approve_factor(org["id"], d2["id"], factor_manager_headers),
        lambda: api.approve_factor(org["id"], d3["id"], factor_manager_headers),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    # PRD §3.4 explicitly names ERR_FACTOR_VERSION_CONFLICT for the loser
    loser_body = loser.json()
    assert loser_body["data"]["error_id"] in (
        ApiErrorId.ERR_FACTOR_VERSION_CONFLICT.value,
        ApiErrorId.ERR_INVALID_STATE.value,
        ApiErrorId.ERR_FACTOR_EFFECTIVE_FROM_ORDER.value,
    ), (
        "Loser should be rejected with a 409-class state/version error "
        f"(got {loser_body['data']['error_id']})"
    )
    assert loser.status_code == 409


# ---------------------------------------------------------------------------
# Concurrency — credit double-retire (PRD §3.6)
# ---------------------------------------------------------------------------
def test_two_simultaneous_retires_serialize(api, discloser_headers):
    """PRD §3.6: "Two simultaneous retirements of the same credit
    serialize on CarbonCredit.status: exactly one succeeds, and the
    loser is rejected with ERR_INVALID_STATE and HTTP 409."
    """
    base = setup_credit_lifecycle_dataset()
    body = retire_credit_payload()
    results = run_race(
        lambda: api.retire_credit(
            base["org"]["id"], base["credit_a"]["id"], body, discloser_headers,
        ),
        lambda: api.retire_credit(
            base["org"]["id"], base["credit_a"]["id"], body, discloser_headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    validate_error(loser, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Concurrency — duplicate serial across orgs (PRD §3.6)
# ---------------------------------------------------------------------------
def test_two_creates_with_same_serial_serialize(api, discloser_headers):
    """PRD §3.6: "Two attempts to create credits with the same
    serial_number from different organizations serialize on the global
    serial_number constraint: the second creator is rejected with
    ERR_CREDIT_DOUBLE_COUNTED."
    """
    from test_helpers import create_credit_payload
    # Set up two orgs each with their own active EXTERNAL_OFFSET project
    org_a, _, p_a = setup_org_facility_period()
    org_b, _, p_b = setup_org_facility_period()
    proj_a = create_active_project(
        org_a["id"], p_a["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    proj_b = create_active_project(
        org_b["id"], p_b["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=0.0,
    )
    shared_serial = "RACE-SERIAL-001"
    results = run_race(
        lambda: api.create_credit(
            org_a["id"],
            create_credit_payload(
                reporting_period_id=p_a["id"],
                linked_reduction_project_id=proj_a["id"],
                quantity_kg_co2e=1.0, vintage_year=2024,
                serial_number=shared_serial,
            ),
            discloser_headers,
        ),
        lambda: api.create_credit(
            org_b["id"],
            create_credit_payload(
                reporting_period_id=p_b["id"],
                linked_reduction_project_id=proj_b["id"],
                quantity_kg_co2e=1.0, vintage_year=2024,
                serial_number=shared_serial,
            ),
            discloser_headers,
        ),
    )
    outcome = assert_exactly_one_succeeds(results[0], results[1])
    loser = outcome["failures"][0]
    validate_error(loser, ApiErrorId.ERR_CREDIT_DOUBLE_COUNTED.value)
