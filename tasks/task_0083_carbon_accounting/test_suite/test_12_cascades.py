"""Cross-entity cascades — factor supersession, boundary-resolver
exclusion (PRD §3.1, §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    compile_report,
    create_approved_factor,
    create_facility,
    create_factor_draft,
    create_organization,
    create_report,
    setup_compilable_report,
    setup_one_source_one_factor,
    setup_org_facility_period,
    setup_supersession_cascade_dataset,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Factor approve cascade (PRD §3.4)
# ---------------------------------------------------------------------------
def test_factor_approval_flips_pinned_record_to_stale(
        api, factor_manager_headers, data_steward_headers):
    """PRD §3.4: "Every EmissionRecord whose emission_factor_id equals
    the now-superseded row and whose parent ReportingPeriod is OPEN
    flips from FRESH to STALE."
    """
    base = setup_supersession_cascade_dataset()
    # Approve v2 to fire the cascade
    api.approve_factor(
        base["org"]["id"], base["factor_v2_draft"]["id"], factor_manager_headers,
    )
    res = api.list_emission_records(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    )
    body = res.json()
    rec = next(r for r in body["data"]
               if r["activity_data_id"] == base["activity"]["id"])
    assert rec["status"] == "STALE", (
        "EmissionRecord must flip FRESH→STALE after factor supersession "
        "(PRD §3.4 hop 2)"
    )


def test_factor_approval_flips_under_review_report_to_recompute(
        api, factor_manager_headers, data_steward_headers):
    """PRD §3.4: "Every Report whose status is DRAFT or UNDER_REVIEW and
    whose reporting_period_id lies among the affected periods flips to
    RECOMPUTE_REQUIRED."
    """
    base = setup_supersession_cascade_dataset()
    api.approve_factor(
        base["org"]["id"], base["factor_v2_draft"]["id"], factor_manager_headers,
    )
    res = api.get_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "RECOMPUTE_REQUIRED", (
        "Report should transition to RECOMPUTE_REQUIRED on factor cascade "
        "(PRD §3.4 hop 3)"
    )


def test_predecessor_factor_effective_to_set_to_new_version_effective_from(
        api, factor_manager_headers):
    """PRD §3.4: "the predecessor (if any) transitions from ACTIVE to
    SUPERSEDED and its effective_to is set equal to the new version's
    effective_from."
    """
    base = setup_supersession_cascade_dataset()
    api.approve_factor(
        base["org"]["id"], base["factor_v2_draft"]["id"], factor_manager_headers,
    )
    res = api.list_factors(
        base["org"]["id"], factor_manager_headers,
        params={"code": base["factor_v1"]["code"], "limit": 100},
    )
    body = res.json()
    v1 = next(f for f in body["data"] if f["id"] == base["factor_v1"]["id"])
    assert v1["status"] == "SUPERSEDED"
    assert v1["effective_to"] == base["factor_v2_draft"]["effective_from"]


def test_reopen_recomputes_pinned_totals_to_null(api, data_steward_headers,
                                                 factor_manager_headers):
    """PRD §3.7: "From REVISIONS_REQUIRED, a DataSteward reopens it back
    to DRAFT, at which point compiled_at is cleared to null and every
    pinned total is reset to null. The same reopen handles the parallel
    case where the report has been auto-flipped to RECOMPUTE_REQUIRED
    by a factor supersession cascade; the same clear-and-reset side
    effect applies."
    """
    base = setup_supersession_cascade_dataset()
    api.approve_factor(
        base["org"]["id"], base["factor_v2_draft"]["id"], factor_manager_headers,
    )
    # Report should now be RECOMPUTE_REQUIRED — reopen back to DRAFT
    res = api.reopen_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep = validate_success(res)
    assert rep["status"] == "DRAFT"
    assert rep["compiled_at"] is None
    assert rep["gross_scope1_kg_co2e"] is None


# ---------------------------------------------------------------------------
# Boundary resolver cascade (PRD §3.1)
# ---------------------------------------------------------------------------
def test_excluding_facility_retires_sources_and_stales_records(
        api, platform_admin_headers, data_steward_headers):
    """PRD §3.1: "If the resolver causes a facility to flip from included
    to excluded, every EmissionSource whose facility_id points at that
    facility is automatically moved to RETIRED in the same transaction,
    and every FRESH EmissionRecord referencing those sources flips to
    STALE."
    """
    # Set up EQUITY_SHARE org with a 50% facility (in boundary)
    org = create_organization(
        consolidation_approach="EQUITY_SHARE",
        materiality_threshold_pct=0.00,
    )
    fac = create_facility(
        org["id"], ownership_share_pct=50.00,
        financial_control=True, operational_control=True,
    )
    assert fac["included_in_boundary"] is True
    from test_helpers import create_reporting_period
    period = create_reporting_period(org["id"])
    factor, src = setup_one_source_one_factor(
        org, fac, kg_per_unit=1.0, gas_type="CO2",
    )
    from test_helpers import create_activity_data
    act = create_activity_data(
        org["id"], period["id"], src["id"],
        quantity=100.0, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )

    # Drop share to 0 — facility flips to excluded; cascade should fire
    res = api.update_facility(
        org["id"], fac["id"], {"ownership_share_pct": 0.00},
        platform_admin_headers,
    )
    updated_fac = validate_success(res)
    assert updated_fac["included_in_boundary"] is False

    # Source should be RETIRED
    res_src = api.list_sources(
        org["id"], data_steward_headers, params={"limit": 100},
    )
    src_after = next(s for s in res_src.json()["data"] if s["id"] == src["id"])
    assert src_after["status"] == "RETIRED", (
        "EmissionSource must be retired when its facility is excluded "
        "from boundary (PRD §3.1)"
    )

    # EmissionRecord should be STALE
    res_rec = api.list_emission_records(
        org["id"], period["id"], data_steward_headers, params={"limit": 100},
    )
    rec_after = next(
        r for r in res_rec.json()["data"]
        if r["activity_data_id"] == act["id"]
    )
    assert rec_after["status"] == "STALE", (
        "EmissionRecord must flip FRESH→STALE when source's facility "
        "exits boundary (PRD §3.1)"
    )
