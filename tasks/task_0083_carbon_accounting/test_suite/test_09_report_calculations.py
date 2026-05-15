"""Report compile totals, net emissions, intensity indicators, completeness
(PRD §3.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    compile_report,
    create_activity_data,
    create_approved_factor,
    create_facility,
    create_organization,
    create_report,
    create_reporting_period,
    create_source,
    setup_compilable_report,
    setup_compiled_report,
    setup_completeness_dataset,
    setup_dual_scope2_dataset,
    setup_one_source_one_factor,
    setup_org_facility_period,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Gross scope-1 total + consolidation weight (PRD §3.7)
# ---------------------------------------------------------------------------
def test_gross_scope1_uses_financial_control_weight_one(api):
    """PRD §3.7: "under FINANCIAL_CONTROL, the weight is 1 when the
    facility's financial_control flag is true and 0 otherwise."
    """
    base = setup_compiled_report(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
        kg_per_unit=1.000000, quantity=1000.0000,
    )
    # 1000 * 1.0 * 1 (GWP CO2) * 1.0 (weight) = 1000.0000
    assert float(base["report"]["gross_scope1_kg_co2e"]) == pytest.approx(
        1000.0000, abs=1e-4)


def test_gross_scope1_uses_equity_share_weight(api):
    """PRD §3.7: "under EQUITY_SHARE, the weight is the facility's
    ownership_share_pct divided by 100."
    """
    org = create_organization(
        consolidation_approach="EQUITY_SHARE",
        materiality_threshold_pct=0.00,
    )
    fac = create_facility(
        org["id"], ownership_share_pct=30.00,
        financial_control=True, operational_control=False,
    )
    assert fac["included_in_boundary"] is True  # 30% > 0
    period = create_reporting_period(org["id"])
    factor, src = setup_one_source_one_factor(
        org, fac, kg_per_unit=1.000000, gas_type="CO2",
    )
    create_activity_data(
        org["id"], period["id"], src["id"],
        quantity=1000.0000, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    # 1000 * 1.0 * 1 * 0.30 = 300.0000
    assert float(rep["gross_scope1_kg_co2e"]) == pytest.approx(300.0000, abs=1e-4)


# ---------------------------------------------------------------------------
# Dual Scope-2 readout (PRD §3.7)
# ---------------------------------------------------------------------------
def test_dual_scope2_returns_distinct_totals(api, data_steward_headers):
    """PRD §3.7: "The report exposes a dual-scope-2 readout that returns
    three numbers — net_with_location_scope2, net_with_market_scope2,
    and delta_kg_co2e."
    """
    base = setup_dual_scope2_dataset(
        quantity_kwh=10000.0000,
        location_kg_per_unit=0.500000,
        market_kg_per_unit=0.200000,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    compile_report(base["org"]["id"], report["id"])
    res = api.get_report_dual_scope2(
        base["org"]["id"], report["id"], data_steward_headers,
    )
    data = validate_success(res)
    # 10000 * 0.500000 * 1 = 5000.0000 ; 10000 * 0.200000 * 1 = 2000.0000
    assert float(data["net_with_location_scope2"]) == pytest.approx(5000.0000, abs=1e-4)
    assert float(data["net_with_market_scope2"]) == pytest.approx(2000.0000, abs=1e-4)
    assert float(data["delta_kg_co2e"]) == pytest.approx(3000.0000, abs=1e-4)


# ---------------------------------------------------------------------------
# Net emissions = scope1 + market-scope2 + scope3 - offsets, floored at 0
# (PRD §3.7)
# ---------------------------------------------------------------------------
def test_net_emissions_uses_market_based_scope2_and_floor(api,
                                                          data_steward_headers,
                                                          discloser_headers):
    """PRD §3.7: "net_emissions_kg_co2e is the canonical net figure ...
    It is computed as gross_scope1_kg_co2e plus gross_scope2_market_kg_co2e
    (market-based is canonical under the GHG-Protocol Scope-2 Guidance)
    plus gross_scope3_kg_co2e minus applied_offsets_kg_co2e, with the
    result rounded half up to four decimal places and floored at zero —
    negative nets are not exposed, the floor takes the larger of the
    rounded difference and 0.0."
    """
    from test_helpers import (
        create_active_project, create_credit, retire_credit,
    )
    base = setup_compilable_report(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
        kg_per_unit=1.000000, quantity=100.0000,
    )
    # Add a hugely-retired credit (RETIRED) to drive gross < offsets
    proj = create_active_project(
        base["org"]["id"], base["period"]["id"],
        project_type="EXTERNAL_OFFSET", reduction_kg_co2e=0.0,
    )
    cr = create_credit(
        base["org"]["id"], base["period"]["id"], proj["id"],
        quantity_kg_co2e=5000.0000, vintage_year=2024,
    )
    retire_credit(base["org"]["id"], cr["id"])
    rep = compile_report(base["org"]["id"], base["report"]["id"])
    # gross = 100, offsets >= 5000, net floored at 0
    assert float(rep["net_emissions_kg_co2e"]) == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Intensity indicators — zero-denominator rule (PRD §3.7)
# ---------------------------------------------------------------------------
def test_intensity_zero_when_revenue_zero(api):
    """PRD §3.7: "when revenue is zero, intensity_per_revenue is recorded
    as 0."
    """
    org, fac = (
        __import__("test_helpers").setup_org_with_in_boundary_facility()
    )
    period = create_reporting_period(
        org["id"], revenue=0.00, headcount=10, unit_output=1.0000,
    )
    factor, src = setup_one_source_one_factor(org, fac, kg_per_unit=1.0)
    create_activity_data(
        org["id"], period["id"], src["id"],
        quantity=10.0000, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    assert float(rep["intensity_per_revenue"]) == 0


def test_intensity_zero_when_headcount_zero(api):
    """PRD §3.7: "when headcount is zero, intensity_per_employee is
    recorded as 0."
    """
    from test_helpers import setup_org_with_in_boundary_facility
    org, fac = setup_org_with_in_boundary_facility()
    period = create_reporting_period(
        org["id"], revenue=100.00, headcount=0, unit_output=1.0000,
    )
    factor, src = setup_one_source_one_factor(org, fac, kg_per_unit=1.0)
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=10.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    assert float(rep["intensity_per_employee"]) == 0


def test_intensity_zero_when_unit_output_zero(api):
    """PRD §3.7: "when unit_output is zero, intensity_per_unit_output is
    recorded as 0."
    """
    from test_helpers import setup_org_with_in_boundary_facility
    org, fac = setup_org_with_in_boundary_facility()
    period = create_reporting_period(
        org["id"], revenue=100.00, headcount=10, unit_output=0.0000,
    )
    factor, src = setup_one_source_one_factor(org, fac, kg_per_unit=1.0)
    create_activity_data(
        org["id"], period["id"], src["id"], quantity=10.0,
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    rep = compile_report(org["id"], report["id"])
    assert float(rep["intensity_per_unit_output"]) == 0


# ---------------------------------------------------------------------------
# Completeness check (PRD §3.7)
# ---------------------------------------------------------------------------
def test_completeness_passes_when_all_sources_covered(api):
    """PRD §3.7: "completeness_passes is true when completeness_pct is
    greater than or equal to the threshold (the comparison is inclusive
    — >=, not strict >)."
    """
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=10, covered_sources=10,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["completeness_pct"]) == pytest.approx(100.00, abs=1e-2)
    assert rep["completeness_passes"] is True


def test_completeness_passes_at_boundary(api):
    """PRD §3.7: ">=, not strict >" boundary precision."""
    # threshold = 100 - 1 = 99.00 ; cover 99/100 sources → 99.00 == 99.00 → pass
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=100, covered_sources=99,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["completeness_pct"]) == pytest.approx(99.00, abs=1e-2)
    assert rep["completeness_passes"] is True


def test_completeness_fails_below_threshold(api):
    """PRD §3.7: below threshold ⇒ completeness_passes false."""
    # threshold = 99 ; cover 98/100 → 98 < 99 → fail
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=100, covered_sources=98,
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    rep = compile_report(base["org"]["id"], report["id"])
    assert float(rep["completeness_pct"]) == pytest.approx(98.00, abs=1e-2)
    assert rep["completeness_passes"] is False


# ---------------------------------------------------------------------------
# Verify blocked when assurance_ready false (PRD §3.7)
# ---------------------------------------------------------------------------
def test_verify_blocked_when_completeness_fails(api, verifier_headers):
    """PRD §3.7: "the report must be in UNDER_REVIEW and its
    assurance_ready must be true — otherwise the call is rejected with
    ERR_ASSURANCE_NOT_READY."
    PRD §3.7: "assurance_ready is true when completeness_passes is true,
    no EmissionRecord of the period is in STALE status, and the parent
    reporting period's status is OPEN or CLOSED."
    """
    base = setup_completeness_dataset(
        materiality_threshold_pct=1.00,
        identified_sources=100, covered_sources=98,  # below threshold
    )
    report = create_report(base["org"]["id"], base["period"]["id"])
    compiled = compile_report(base["org"]["id"], report["id"])
    assert compiled["assurance_ready"] is False
    res = api.verify_report(
        base["org"]["id"], report["id"], verifier_headers,
    )
    validate_error(res, ApiErrorId.ERR_ASSURANCE_NOT_READY.value)
