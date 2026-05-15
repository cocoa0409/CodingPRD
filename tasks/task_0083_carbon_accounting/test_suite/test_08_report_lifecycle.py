"""Report lifecycle: compile, verify, request-revisions, reopen, publish
(PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_report,
    build_user_headers,
    create_credit,
    create_active_project,
    retire_credit,
    setup_compilable_report,
    setup_compiled_report,
    setup_verified_report,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Compile (PRD §3.7)
# ---------------------------------------------------------------------------
def test_compile_draft_to_under_review(api, data_steward_headers):
    """PRD §3.7: "Compilation advances the report from DRAFT to
    UNDER_REVIEW and pins every aggregated total on the report row."
    """
    base = setup_compilable_report(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
        kg_per_unit=1.000000, quantity=100.0000,
    )
    res = api.compile_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "UNDER_REVIEW"
    assert rep["compiled_at"] is not None
    # Pinned totals materialized
    assert rep["gross_scope1_kg_co2e"] is not None
    assert rep["net_emissions_kg_co2e"] is not None
    # 100.0 quantity * 1.0 kg_per_unit * 1 GWP(CO2) * weight(1.0) = 100.0
    assert float(rep["gross_scope1_kg_co2e"]) == pytest.approx(100.0000, abs=1e-4)


def test_compile_blocked_by_stale_record(api, data_steward_headers,
                                         factor_manager_headers):
    """PRD §3.7: "Compilation requires the parent reporting period to be
    OPEN or CLOSED and requires that no EmissionRecord for the period
    is in STALE status."
    """
    from test_helpers import create_factor_draft
    base = setup_compilable_report()
    # Create v2 DRAFT with greater effective_from and approve → cascade STALE
    v2 = create_factor_draft(
        base["org"]["id"],
        code=base["factor"]["code"], gas_type="CO2", kg_per_unit=2.0,
        effective_from="2025-08-01T00:00:00.000Z",
    )
    api.approve_factor(
        base["org"]["id"], v2["id"], factor_manager_headers,
    )
    # Now compile should fail
    res = api.compile_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# NOTE: ERR_TRACEABILITY_MISSING (PRD §3.7) is NOT covered here.
# PRD §3.4 already requires factor.traceability_url to be 1..500 chars at
# create time, so a faithful PRD-only implementer never reaches the
# compile-time "non-empty" branch (silence-pattern: branch-asymmetry).


# ---------------------------------------------------------------------------
# Verify (PRD §3.7)
# ---------------------------------------------------------------------------
def test_verify_under_review_to_verified(api, verifier_headers):
    """PRD §3.7: "Verification advances the report from UNDER_REVIEW to
    VERIFIED. A Verifier performs this transition; the report must be
    in UNDER_REVIEW and its assurance_ready must be true."
    """
    base = setup_compiled_report(
        materiality_threshold_pct=0.00,
    )
    # assurance_ready should be true (no STALE records, period OPEN)
    res = api.verify_report(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "VERIFIED"
    assert rep["verified_at"] is not None
    assert rep["verifier_user_id"] == "verifier-001"


def test_verify_blocked_when_in_draft(api, verifier_headers):
    """PRD §3.7: "the report must be in UNDER_REVIEW"; otherwise
    ERR_INVALID_STATE (per §2.8 priority 4)."""
    base = setup_compilable_report()  # report still DRAFT
    res = api.verify_report(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_verify_blocked_by_segregation_of_duties(api):
    """PRD §3.7: "Segregation of duties is strictly enforced here: the
    verifying user's X-User-ID must not equal the entered_by_user_id
    of any ActivityData row whose reporting_period_id matches the
    report's reporting period. ... A violation surfaces as
    ERR_SEGREGATION_OF_DUTIES with HTTP 403."
    """
    shared_id = "soulmate-user-007"
    steward = build_user_headers(shared_id, "DataSteward")
    verifier = build_user_headers(shared_id, "Verifier")
    base = setup_compiled_report(
        materiality_threshold_pct=0.00, steward_headers=steward,
    )
    res = api.verify_report(
        base["org"]["id"], base["report"]["id"], verifier,
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# Request-revisions and reopen (PRD §3.7)
# ---------------------------------------------------------------------------
def test_request_revisions_moves_under_review_to_revisions_required(
        api, verifier_headers):
    """PRD §3.7: "A verifier who finds the report unsatisfactory may
    instead send it back, moving it from UNDER_REVIEW to
    REVISIONS_REQUIRED."
    """
    base = setup_compiled_report(materiality_threshold_pct=0.00)
    res = api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "REVISIONS_REQUIRED"


def test_reopen_clears_pinned_totals(api, data_steward_headers,
                                     verifier_headers):
    """PRD §3.7: "From REVISIONS_REQUIRED, a DataSteward reopens it back
    to DRAFT, at which point compiled_at is cleared to null and every
    pinned total is reset to null."
    """
    base = setup_compiled_report(materiality_threshold_pct=0.00)
    api.request_revisions(
        base["org"]["id"], base["report"]["id"], verifier_headers,
    )
    res = api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "DRAFT"
    assert rep["compiled_at"] is None
    assert rep["gross_scope1_kg_co2e"] is None
    assert rep["gross_scope2_market_kg_co2e"] is None
    assert rep["gross_scope3_kg_co2e"] is None
    assert rep["net_emissions_kg_co2e"] is None


# ---------------------------------------------------------------------------
# Publish (PRD §3.7)
# ---------------------------------------------------------------------------
def test_publish_verified_to_published(api, discloser_headers):
    """PRD §3.7: "Publication advances the report from VERIFIED to
    PUBLISHED."
    """
    base = setup_verified_report(materiality_threshold_pct=0.00)
    res = api.publish_report(
        base["org"]["id"], base["report"]["id"], discloser_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "PUBLISHED"
    assert rep["published_at"] is not None


def test_publish_blocked_when_credits_still_purchased(api, discloser_headers):
    """PRD §3.7: "every external-offset credit that has been booked
    against the report's reporting period must be fully retired — no
    purchased credit may remain in PURCHASED status. A violation is
    rejected with ERR_INVALID_STATE."
    """
    base = setup_verified_report(materiality_threshold_pct=0.00)
    # Add an EXTERNAL_OFFSET project and a still-PURCHASED credit
    proj = create_active_project(
        base["org"]["id"], base["period"]["id"],
        project_type="EXTERNAL_OFFSET", reduction_kg_co2e=100.0,
    )
    credit = create_credit(
        base["org"]["id"], base["period"]["id"], proj["id"],
        quantity_kg_co2e=10.0, vintage_year=2024,
    )
    res = api.publish_report(
        base["org"]["id"], base["report"]["id"], discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
