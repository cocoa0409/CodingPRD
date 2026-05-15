"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing
assertion failures.

PRD §2.1 identity is opaque for every role — fixtures can use the
TEST_USERS shared constants directly without per-instance header
builders. The single comparison that matters (segregation of duties on
report verification, PRD §3.7) is between two captured X-User-ID values
on different rows, never between X-User-ID and any entity primary key.
"""
from __future__ import annotations
import datetime as _dt
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    clock_advance_payload,
    create_activity_data_payload,
    create_boundary_change_payload,
    create_credit_payload,
    create_facility_payload,
    create_factor_payload,
    create_organization_payload,
    create_project_payload,
    create_report_payload,
    create_reporting_period_payload,
    create_source_payload,
    retire_credit_payload,
)
from .test_users import TEST_USERS


PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
DATA_STEWARD = TEST_USERS["data_steward_headers"]
FACTOR_MANAGER = TEST_USERS["factor_manager_headers"]
VERIFIER = TEST_USERS["verifier_headers"]
DISCLOSER = TEST_USERS["discloser_headers"]


# ===========================================================================
# Time helpers
# PRD §3.8: /_clock/advance accepts a to_timestamp instant and moves the
# logical now forward to that value.
# ===========================================================================
def _parse_iso(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _format_iso(t: _dt.datetime) -> str:
    """PRD §2.4: ISO 8601 UTC, three fractional digits, Z suffix."""
    t = t.astimezone(_dt.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def advance_clock_to(to_timestamp: str) -> None:
    """PRD §3.8: 'An admin-only test-driving capability advances the
    logical clock to a supplied to_timestamp instant.'"""
    res = api_client.advance_clock(
        clock_advance_payload(to_timestamp=to_timestamp), PLATFORM_ADMIN,
    )
    get_success_data(res)


def iso_offset(base_iso: str, days: int = 0, seconds: int = 0) -> str:
    """Return base_iso shifted by the given offset, ISO 8601 with ms."""
    t = _parse_iso(base_iso) + _dt.timedelta(days=days, seconds=seconds)
    return _format_iso(t)


# ===========================================================================
# Tier 1 — Single-entity creation / state progression
# ===========================================================================
def create_organization(**overrides: Any) -> Dict[str, Any]:
    """Create an Organization via POST /organizations (PlatformAdmin)."""
    res = api_client.create_organization(
        create_organization_payload(**overrides), PLATFORM_ADMIN,
    )
    return get_success_data(res)


def create_facility(org_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a Facility via POST /organizations/{org}/facilities."""
    res = api_client.create_facility(
        org_id, create_facility_payload(**overrides), PLATFORM_ADMIN,
    )
    return get_success_data(res)


def create_reporting_period(org_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a ReportingPeriod via POST .../reporting-periods."""
    res = api_client.create_reporting_period(
        org_id, create_reporting_period_payload(**overrides), DATA_STEWARD,
    )
    return get_success_data(res)


def create_factor_draft(org_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT EmissionFactor (FactorManager)."""
    res = api_client.create_factor(
        org_id, create_factor_payload(**overrides), FACTOR_MANAGER,
    )
    return get_success_data(res)


def approve_factor(org_id: str, factor: Dict[str, Any]) -> Dict[str, Any]:
    """Approve a DRAFT factor (DRAFT→ACTIVE)."""
    res = api_client.approve_factor(
        org_id, factor["id"], FACTOR_MANAGER,
    )
    return get_success_data(res)


def create_approved_factor(org_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT factor and immediately approve it. Returns the
    ACTIVE EmissionFactor row."""
    draft = create_factor_draft(org_id, **overrides)
    return approve_factor(org_id, draft)


def create_source(org_id: str, facility_id: str,
                  **overrides: Any) -> Dict[str, Any]:
    """Create an EmissionSource (DataSteward)."""
    res = api_client.create_source(
        org_id,
        create_source_payload(facility_id=facility_id, **overrides),
        DATA_STEWARD,
    )
    return get_success_data(res)


def create_activity_data(org_id: str, period_id: str, source_id: str,
                         headers: Optional[Dict[str, str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Create an ActivityData row (DataSteward). Note: this triggers
    EmissionRecord creation in the same transaction (PRD §3.5)."""
    res = api_client.create_activity_data(
        org_id, period_id,
        create_activity_data_payload(emission_source_id=source_id, **overrides),
        headers if headers is not None else DATA_STEWARD,
    )
    return get_success_data(res)


def create_project(org_id: str, period_id: str,
                   **overrides: Any) -> Dict[str, Any]:
    """Create a ReductionProject (DataSteward)."""
    res = api_client.create_project(
        org_id,
        create_project_payload(reporting_period_id=period_id, **overrides),
        DATA_STEWARD,
    )
    return get_success_data(res)


def activate_project(org_id: str, project_id: str) -> Dict[str, Any]:
    res = api_client.activate_project(org_id, project_id, DATA_STEWARD)
    return get_success_data(res)


def create_active_project(org_id: str, period_id: str,
                          project_type: str = "EXTERNAL_OFFSET",
                          **overrides: Any) -> Dict[str, Any]:
    """Create a project and walk PLANNED→ACTIVE."""
    proj = create_project(
        org_id, period_id, project_type=project_type, **overrides,
    )
    return activate_project(org_id, proj["id"])


def create_credit(org_id: str, period_id: str, project_id: str,
                  **overrides: Any) -> Dict[str, Any]:
    """Create a CarbonCredit (Discloser)."""
    res = api_client.create_credit(
        org_id,
        create_credit_payload(
            reporting_period_id=period_id,
            linked_reduction_project_id=project_id,
            **overrides,
        ),
        DISCLOSER,
    )
    return get_success_data(res)


def retire_credit(org_id: str, credit_id: str,
                  **overrides: Any) -> Dict[str, Any]:
    """Retire a credit (PURCHASED→RETIRED)."""
    res = api_client.retire_credit(
        org_id, credit_id, retire_credit_payload(**overrides), DISCLOSER,
    )
    return get_success_data(res)


def create_report(org_id: str, period_id: str,
                  standard: str = "GHG_PROTOCOL",
                  **overrides: Any) -> Dict[str, Any]:
    """Create a Report (DataSteward)."""
    res = api_client.create_report(
        org_id,
        create_report_payload(
            reporting_period_id=period_id, standard=standard, **overrides,
        ),
        DATA_STEWARD,
    )
    return get_success_data(res)


def compile_report(org_id: str, report_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Compile a DRAFT Report (DRAFT→UNDER_REVIEW)."""
    res = api_client.compile_report(
        org_id, report_id, headers if headers is not None else DATA_STEWARD,
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2 — Composite scenario assembly
# ===========================================================================
def setup_basic_org_with_period(
        consolidation_approach: str = "FINANCIAL_CONTROL",
        materiality_threshold_pct: float = 1.00,
        revenue: float = 1_000_000.00,
        headcount: int = 100,
        unit_output: float = 1000.0000,
        period_start: str = "2025-01-01T00:00:00.000Z",
        period_end: str = "2026-01-01T00:00:00.000Z",
        **org_overrides: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create Org + a single ReportingPeriod. Returns (org, period)."""
    org = create_organization(
        consolidation_approach=consolidation_approach,
        materiality_threshold_pct=materiality_threshold_pct,
        **org_overrides,
    )
    period = create_reporting_period(
        org["id"],
        start_date=period_start,
        end_date=period_end,
        revenue=revenue,
        headcount=headcount,
        unit_output=unit_output,
    )
    return org, period


def setup_org_with_in_boundary_facility(
        consolidation_approach: str = "FINANCIAL_CONTROL",
        ownership_share_pct: float = 100.00,
        financial_control: bool = True,
        operational_control: bool = True,
        country_code: str = "US",
        **org_overrides: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Org + one Facility guaranteed to be included_in_boundary under the
    chosen consolidation_approach."""
    org = create_organization(
        consolidation_approach=consolidation_approach, **org_overrides,
    )
    facility = create_facility(
        org["id"],
        ownership_share_pct=ownership_share_pct,
        financial_control=financial_control,
        operational_control=operational_control,
        country_code=country_code,
    )
    return org, facility


def setup_org_facility_period(
        consolidation_approach: str = "FINANCIAL_CONTROL",
        materiality_threshold_pct: float = 1.00,
        **kwargs: Any) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Org + one in-boundary Facility + one OPEN ReportingPeriod."""
    org, facility = setup_org_with_in_boundary_facility(
        consolidation_approach=consolidation_approach,
        materiality_threshold_pct=materiality_threshold_pct,
        **{k: v for k, v in kwargs.items()
           if k in ("ownership_share_pct", "financial_control",
                    "operational_control", "country_code")},
    )
    period = create_reporting_period(
        org["id"],
        revenue=kwargs.get("revenue", 1_000_000.00),
        headcount=kwargs.get("headcount", 100),
        unit_output=kwargs.get("unit_output", 1000.0000),
        start_date=kwargs.get("period_start", "2025-01-01T00:00:00.000Z"),
        end_date=kwargs.get("period_end", "2026-01-01T00:00:00.000Z"),
    )
    return org, facility, period


def setup_one_source_one_factor(
        org: Dict[str, Any], facility: Dict[str, Any],
        category: str = "STATIONARY_COMBUSTION",
        gas_type: str = "CO2",
        kg_per_unit: float = 1.000000,
        factor_effective_from: str = "2024-12-01T00:00:00.000Z",
        scope2_method: Optional[str] = None,
        factor_code: Optional[str] = None,
        scope3_category: Optional[int] = None,
        **factor_overrides: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one ACTIVE EmissionFactor and one EmissionSource bound to
    it. Returns (factor, source)."""
    code = factor_code or f"F-{uuid.uuid4().hex[:10].upper()}"
    factor = create_approved_factor(
        org["id"],
        code=code,
        gas_type=gas_type,
        kg_per_unit=kg_per_unit,
        effective_from=factor_effective_from,
        scope2_method=scope2_method,
        **factor_overrides,
    )
    source_kwargs: Dict[str, Any] = {
        "category": category,
        "gas_type": gas_type,
        "factor_code": code,
    }
    if scope3_category is not None:
        source_kwargs["scope3_category"] = scope3_category
    source = create_source(org["id"], facility["id"], **source_kwargs)
    return factor, source


# ===========================================================================
# Tier 3 — End-to-end "ready to compile" / "ready to verify" shortcuts
# ===========================================================================
def setup_compilable_report(
        consolidation_approach: str = "FINANCIAL_CONTROL",
        materiality_threshold_pct: float = 1.00,
        category: str = "STATIONARY_COMBUSTION",
        gas_type: str = "CO2",
        kg_per_unit: float = 1.000000,
        quantity: float = 1000.0000,
        activity_start: str = "2025-03-01T00:00:00.000Z",
        activity_end: str = "2025-04-01T00:00:00.000Z",
        scope2_method: Optional[str] = None,
        steward_headers: Optional[Dict[str, str]] = None,
        standard: str = "GHG_PROTOCOL",
) -> Dict[str, Any]:
    """Full stack: Org + Facility + Period + Factor + Source + ActivityData +
    Report (still in DRAFT, but compile would succeed). Returns dict of
    {org, facility, period, factor, source, activity, report,
     emission_records, steward_headers}.

    PRD §3.7 compile preconditions are all satisfied:
      - period.status == OPEN
      - no EmissionRecord is STALE
      - factor traceability_url is non-empty
      - boundary inclusion holds
    """
    org, facility, period = setup_org_facility_period(
        consolidation_approach=consolidation_approach,
        materiality_threshold_pct=materiality_threshold_pct,
    )
    factor, source = setup_one_source_one_factor(
        org, facility,
        category=category, gas_type=gas_type, kg_per_unit=kg_per_unit,
        scope2_method=scope2_method,
    )
    activity = create_activity_data(
        org["id"], period["id"], source["id"],
        headers=steward_headers,
        quantity=quantity,
        activity_start=activity_start,
        activity_end=activity_end,
    )
    report = create_report(org["id"], period["id"], standard=standard)
    return {
        "org": org,
        "facility": facility,
        "period": period,
        "factor": factor,
        "source": source,
        "activity": activity,
        "report": report,
        "steward_headers": steward_headers or DATA_STEWARD,
    }


def setup_compiled_report(
        steward_headers: Optional[Dict[str, str]] = None,
        compile_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any) -> Dict[str, Any]:
    """Same as setup_compilable_report but also compiles the report.
    Returns the same dict, with report updated to UNDER_REVIEW state."""
    base = setup_compilable_report(steward_headers=steward_headers, **kwargs)
    compiled = compile_report(
        base["org"]["id"], base["report"]["id"],
        headers=compile_headers if compile_headers is not None else DATA_STEWARD,
    )
    base["report"] = compiled
    return base


def setup_verified_report(
        steward_headers: Optional[Dict[str, str]] = None,
        verifier_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any) -> Dict[str, Any]:
    """Walk compile + verify. Default steward is DATA_STEWARD_001 and
    default verifier is VERIFIER_001 — distinct X-User-IDs so the
    segregation-of-duties check passes."""
    base = setup_compiled_report(steward_headers=steward_headers, **kwargs)
    res = api_client.verify_report(
        base["org"]["id"], base["report"]["id"],
        verifier_headers if verifier_headers is not None else VERIFIER,
    )
    base["report"] = get_success_data(res)
    return base


# ===========================================================================
# Tier 4 — Targeted state for difficulty design fixtures
# ===========================================================================
def setup_dual_scope2_dataset(
        org_kwargs: Optional[Dict[str, Any]] = None,
        quantity_kwh: float = 10000.0000,
        location_kg_per_unit: float = 0.500000,
        market_kg_per_unit: float = 0.200000,
) -> Dict[str, Any]:
    """Dual Scope-2 setup: one Org with FINANCIAL_CONTROL, one Facility
    in boundary, one Period, two ACTIVE PURCHASED_ENERGY factors
    (LOCATION_BASED vs MARKET_BASED), two PURCHASED_ENERGY sources each
    bound to one of the factors, and one ActivityData row on EACH source
    with the same quantity.

    PRD §3.7: 'gross_scope2_location_kg_co2e is the sum across SCOPE_2
    records whose scope2_method is LOCATION_BASED, gross_scope2_market_kg_co2e
    is the sum across SCOPE_2 records whose scope2_method is MARKET_BASED.'
    """
    org_kwargs = org_kwargs or {}
    org, facility, period = setup_org_facility_period(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=org_kwargs.get(
            "materiality_threshold_pct", 0.00),
    )
    # Two factors: location-based and market-based
    loc_code = f"GRID-{uuid.uuid4().hex[:6].upper()}"
    mkt_code = f"REC-{uuid.uuid4().hex[:6].upper()}"
    factor_loc = create_approved_factor(
        org["id"], code=loc_code, gas_type="CO2",
        kg_per_unit=location_kg_per_unit,
        scope2_method="LOCATION_BASED",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    factor_mkt = create_approved_factor(
        org["id"], code=mkt_code, gas_type="CO2",
        kg_per_unit=market_kg_per_unit,
        scope2_method="MARKET_BASED",
        effective_from="2024-12-01T00:00:00.000Z",
    )
    source_loc = create_source(
        org["id"], facility["id"],
        category="PURCHASED_ENERGY", gas_type="CO2", factor_code=loc_code,
    )
    source_mkt = create_source(
        org["id"], facility["id"],
        category="PURCHASED_ENERGY", gas_type="CO2", factor_code=mkt_code,
    )
    act_loc = create_activity_data(
        org["id"], period["id"], source_loc["id"],
        quantity=quantity_kwh, unit="kWh",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    act_mkt = create_activity_data(
        org["id"], period["id"], source_mkt["id"],
        quantity=quantity_kwh, unit="kWh",
        activity_start="2025-05-01T00:00:00.000Z",
        activity_end="2025-06-01T00:00:00.000Z",
    )
    return {
        "org": org,
        "facility": facility,
        "period": period,
        "factor_location": factor_loc,
        "factor_market": factor_mkt,
        "source_location": source_loc,
        "source_market": source_mkt,
        "activity_location": act_loc,
        "activity_market": act_mkt,
    }


def setup_equity_share_two_facility_dataset(
        ownership_a: float = 33.33,
        ownership_b: float = 66.67,
        quantity_a: float = 100.0001,
        quantity_b: float = 100.0001,
        kg_per_unit: float = 1.000000,
) -> Dict[str, Any]:
    """Build an EQUITY_SHARE org with two facilities at the given shares,
    each with one source and one activity-data row. Used to validate
    round-per-subtotal-then-sum (PRD §3.7).
    """
    org = create_organization(
        consolidation_approach="EQUITY_SHARE",
        materiality_threshold_pct=0.00,
    )
    fac_a = create_facility(
        org["id"], ownership_share_pct=ownership_a,
        financial_control=True, operational_control=True,
    )
    fac_b = create_facility(
        org["id"], ownership_share_pct=ownership_b,
        financial_control=True, operational_control=True,
    )
    period = create_reporting_period(org["id"])
    code = f"F-{uuid.uuid4().hex[:8].upper()}"
    factor = create_approved_factor(
        org["id"], code=code, gas_type="CO2", kg_per_unit=kg_per_unit,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    src_a = create_source(
        org["id"], fac_a["id"], category="STATIONARY_COMBUSTION",
        gas_type="CO2", factor_code=code,
    )
    src_b = create_source(
        org["id"], fac_b["id"], category="STATIONARY_COMBUSTION",
        gas_type="CO2", factor_code=code,
    )
    act_a = create_activity_data(
        org["id"], period["id"], src_a["id"],
        quantity=quantity_a, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    act_b = create_activity_data(
        org["id"], period["id"], src_b["id"],
        quantity=quantity_b, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    return {
        "org": org,
        "facility_a": fac_a,
        "facility_b": fac_b,
        "period": period,
        "factor": factor,
        "source_a": src_a,
        "source_b": src_b,
        "activity_a": act_a,
        "activity_b": act_b,
    }


def setup_supersession_cascade_dataset() -> Dict[str, Any]:
    """Build state for the factor-approve cascade depth-3 difficulty
    instance: one ACTIVE v1 factor, an EmissionRecord pinned to it, and
    a Report at UNDER_REVIEW. A new v2 DRAFT factor is also created and
    returned so the test can approve it to trigger the cascade.

    PRD §3.4: 'Every EmissionRecord whose emission_factor_id equals the
    now-superseded row and whose parent ReportingPeriod is OPEN flips
    from FRESH to STALE. Every Report whose status is DRAFT or
    UNDER_REVIEW ... flips to RECOMPUTE_REQUIRED.'
    """
    org, facility, period = setup_org_facility_period(
        consolidation_approach="FINANCIAL_CONTROL",
        materiality_threshold_pct=0.00,
    )
    code = f"DIESEL-{uuid.uuid4().hex[:6].upper()}"
    v1 = create_approved_factor(
        org["id"], code=code, gas_type="CO2",
        kg_per_unit=2.687000,
        effective_from="2025-01-01T00:00:00.000Z",
    )
    source = create_source(
        org["id"], facility["id"],
        category="STATIONARY_COMBUSTION", gas_type="CO2", factor_code=code,
    )
    activity = create_activity_data(
        org["id"], period["id"], source["id"],
        quantity=100.0000, unit="L",
        activity_start="2025-06-01T00:00:00.000Z",
        activity_end="2025-07-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    report = compile_report(org["id"], report["id"])
    # Build a v2 DRAFT with strictly greater effective_from
    v2 = create_factor_draft(
        org["id"], code=code, gas_type="CO2",
        kg_per_unit=2.700000,
        effective_from="2025-08-01T00:00:00.000Z",
    )
    return {
        "org": org,
        "facility": facility,
        "period": period,
        "factor_v1": v1,
        "factor_v2_draft": v2,
        "source": source,
        "activity": activity,
        "report": report,
    }


def setup_period_close_cascade_dataset(
        period_end: str = "2025-07-01T00:00:00.000Z",
        clock_to: str = "2025-07-01T00:00:01.000Z",
) -> Dict[str, Any]:
    """Build state for the period-close cascade depth-3 difficulty
    instance: an OPEN Period with one ActivityData / EmissionRecord, a
    Report at UNDER_REVIEW, and the clock advanced past end_date so the
    close call is legal.
    """
    org, facility, period = setup_org_facility_period(
        period_end=period_end,
        materiality_threshold_pct=0.00,
    )
    factor, source = setup_one_source_one_factor(
        org, facility, kg_per_unit=1.000000,
    )
    activity = create_activity_data(
        org["id"], period["id"], source["id"],
        quantity=100.0000, unit="L",
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    report = create_report(org["id"], period["id"])
    report = compile_report(org["id"], report["id"])
    advance_clock_to(clock_to)
    return {
        "org": org,
        "facility": facility,
        "period": period,
        "factor": factor,
        "source": source,
        "activity": activity,
        "report": report,
    }


def setup_completeness_dataset(
        materiality_threshold_pct: float = 1.00,
        identified_sources: int = 100,
        covered_sources: int = 99,
) -> Dict[str, Any]:
    """Create `identified_sources` ACTIVE in-boundary sources, then post
    activity-data on exactly `covered_sources` of them. The remaining
    sources stay uncovered so completeness_pct is configurable to
    boundary values around (100 - materiality_threshold_pct).
    """
    org, facility, period = setup_org_facility_period(
        materiality_threshold_pct=materiality_threshold_pct,
    )
    # Single factor that all sources reuse
    code = f"F-{uuid.uuid4().hex[:8].upper()}"
    factor = create_approved_factor(
        org["id"], code=code, gas_type="CO2", kg_per_unit=1.000000,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    sources: List[Dict[str, Any]] = []
    activities: List[Dict[str, Any]] = []
    for i in range(identified_sources):
        src = create_source(
            org["id"], facility["id"],
            category="STATIONARY_COMBUSTION", gas_type="CO2", factor_code=code,
        )
        sources.append(src)
        if i < covered_sources:
            # Use a unique sub-window to avoid interval overlap on a source
            act = create_activity_data(
                org["id"], period["id"], src["id"],
                quantity=1.0000, unit="L",
                activity_start="2025-03-01T00:00:00.000Z",
                activity_end="2025-04-01T00:00:00.000Z",
            )
            activities.append(act)
    return {
        "org": org,
        "facility": facility,
        "period": period,
        "factor": factor,
        "sources": sources,
        "activities": activities,
    }


def setup_credit_lifecycle_dataset() -> Dict[str, Any]:
    """Org + ACTIVE EXTERNAL_OFFSET project + two PURCHASED CarbonCredits
    on the project. Used for branching-terminal-state tests."""
    org, _, period = setup_org_facility_period()
    project = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=1000.0000,
    )
    credit_a = create_credit(
        org["id"], period["id"], project["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    credit_b = create_credit(
        org["id"], period["id"], project["id"],
        quantity_kg_co2e=500.0000, vintage_year=2024,
    )
    return {
        "org": org,
        "period": period,
        "project": project,
        "credit_a": credit_a,
        "credit_b": credit_b,
    }


__all__ = [
    # time
    "advance_clock_to",
    "iso_offset",
    # tier 1
    "create_organization",
    "create_facility",
    "create_reporting_period",
    "create_factor_draft",
    "approve_factor",
    "create_approved_factor",
    "create_source",
    "create_activity_data",
    "create_project",
    "activate_project",
    "create_active_project",
    "create_credit",
    "retire_credit",
    "create_report",
    "compile_report",
    # tier 2
    "setup_basic_org_with_period",
    "setup_org_with_in_boundary_facility",
    "setup_org_facility_period",
    "setup_one_source_one_factor",
    # tier 3
    "setup_compilable_report",
    "setup_compiled_report",
    "setup_verified_report",
    # tier 4
    "setup_dual_scope2_dataset",
    "setup_equity_share_two_facility_dataset",
    "setup_supersession_cascade_dataset",
    "setup_period_close_cascade_dataset",
    "setup_completeness_dataset",
    "setup_credit_lifecycle_dataset",
    # constants re-export
    "PLATFORM_ADMIN",
    "DATA_STEWARD",
    "FACTOR_MANAGER",
    "VERIFIER",
    "DISCLOSER",
]
