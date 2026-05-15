"""Payload factories — one per endpoint that takes a body.

Only fields from PRD §3 / §4 input columns. Each factory accepts
**overrides so individual tests can vary specific values without
re-typing the whole payload.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


def _unique_label(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _unique_serial() -> str:
    """Globally-unique CarbonCredit serial number (PRD §3.6)."""
    return f"SN-{uuid.uuid4().hex[:24].upper()}"


def _unique_code(prefix: str) -> str:
    """1..50 chars from [A-Z0-9_-]+ (PRD §3.3 / §3.4)."""
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ---------------------------------------------------------------------------
# Organization (PRD §3.1)
# Required: legal_name, consolidation_approach, base_year, functional_currency.
# Optional: materiality_threshold_pct (default 1.0).
# ---------------------------------------------------------------------------
def create_organization_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'An organization is created with its legal_name, the chosen
    consolidation_approach (EQUITY_SHARE, FINANCIAL_CONTROL, or
    OPERATIONAL_CONTROL), a base_year that must be between 1990 and 2100
    inclusive, an ISO-4217 functional_currency consisting of exactly three
    uppercase letters, and an optional materiality_threshold_pct.'"""
    payload: Dict[str, Any] = {
        "legal_name": _unique_label("Org"),
        "consolidation_approach": "FINANCIAL_CONTROL",
        "base_year": TEST_DEFAULTS["BASE_YEAR"],
        "functional_currency": TEST_DEFAULTS["FUNCTIONAL_CURRENCY"],
        "materiality_threshold_pct": TEST_DEFAULTS["MATERIALITY_PCT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Facility (PRD §3.1)
# Required: name, country_code, ownership_share_pct, financial_control,
# operational_control.
# ---------------------------------------------------------------------------
def create_facility_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Facilities are added under an organization with a name,
    the two-letter uppercase country_code ..., the ownership_share_pct of
    equity held (between 0.0 and 100.0 percent inclusive, two decimal
    places), and two independent boolean flags financial_control and
    operational_control.'"""
    payload: Dict[str, Any] = {
        "name": _unique_label("Facility"),
        "country_code": TEST_DEFAULTS["COUNTRY_CODE"],
        "ownership_share_pct": 100.00,
        "financial_control": True,
        "operational_control": True,
    }
    payload.update(overrides)
    return payload


def update_facility_payload(**overrides: Any) -> Dict[str, Any]:
    """PATCH body for /facilities/{id}; all fields optional (PRD §4)."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Boundary change (PRD §3.1)
# Required: change_type, effective_date, rationale.
# Optional: facility_id (null when change_type==APPROACH_SWITCH),
#           from_approach/to_approach (set only when APPROACH_SWITCH).
# ---------------------------------------------------------------------------
def create_boundary_change_payload(change_type: str,
                                   effective_date: str,
                                   rationale: Optional[str] = None,
                                   facility_id: Optional[str] = None,
                                   from_approach: Optional[str] = None,
                                   to_approach: Optional[str] = None,
                                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Each event captures organization_id, a change_type of
    ADD_FACILITY, REMOVE_FACILITY, APPROACH_SWITCH, or
    OWNERSHIP_ADJUSTMENT, the affected facility_id (which must be null
    exactly when change_type is APPROACH_SWITCH), from_approach and
    to_approach (which are set only on approach switches), an
    effective_date in UTC ISO 8601, and a 5-to-1000-character rationale.'"""
    payload: Dict[str, Any] = {
        "change_type": change_type,
        "effective_date": effective_date,
        "rationale": rationale or TEST_DEFAULTS["RATIONALE"],
    }
    if facility_id is not None:
        payload["facility_id"] = facility_id
    if from_approach is not None:
        payload["from_approach"] = from_approach
    if to_approach is not None:
        payload["to_approach"] = to_approach
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reporting period (PRD §3.2)
# Required: label, start_date, end_date, revenue, headcount, unit_output.
# ---------------------------------------------------------------------------
def create_reporting_period_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'Each period has a label (such as "FY2025", 1–50
    characters, unique within the organization), a start_date and
    end_date interval ..., a revenue denominator ..., an integer
    headcount denominator, and a unit_output denominator.'"""
    payload: Dict[str, Any] = {
        "label": _unique_label("FY"),
        "start_date": TEST_DEFAULTS["PERIOD_START"],
        "end_date": TEST_DEFAULTS["PERIOD_END"],
        "revenue": TEST_DEFAULTS["REVENUE"],
        "headcount": TEST_DEFAULTS["HEADCOUNT"],
        "unit_output": TEST_DEFAULTS["UNIT_OUTPUT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emission source (PRD §3.3)
# Required: facility_id, code, category, gas_type, factor_code.
# Optional: scope3_category (required when category==VALUE_CHAIN).
# ---------------------------------------------------------------------------
def create_source_payload(facility_id: str,
                          category: str = "STATIONARY_COMBUSTION",
                          gas_type: str = "CO2",
                          factor_code: Optional[str] = None,
                          scope3_category: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'Each source is created with a facility_id ..., a code
    that is 1–50 characters from the set [A-Z0-9_-] and unique within the
    organization, a category from the GHG-Protocol set ..., a gas_type
    from CO2, CH4, N2O, HFC, PFC, SF6, or NF3, and a factor_code that
    points at an emission-factor family.'"""
    payload: Dict[str, Any] = {
        "facility_id": facility_id,
        "code": _unique_code("SRC"),
        "category": category,
        "gas_type": gas_type,
        "factor_code": factor_code or TEST_DEFAULTS["FACTOR_CODE"],
    }
    if scope3_category is not None:
        payload["scope3_category"] = scope3_category
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emission factor (PRD §3.4)
# Required: code, library, gas_type, kg_per_unit, uncertainty_rating,
#           effective_from, traceability_url.
# Optional: scope2_method (null for non-PURCHASED_ENERGY).
# ---------------------------------------------------------------------------
def create_factor_payload(code: Optional[str] = None,
                          gas_type: str = "CO2",
                          kg_per_unit: float = 1.000000,
                          effective_from: Optional[str] = None,
                          library: str = "IPCC_DEFAULT",
                          uncertainty_rating: str = "LOW",
                          scope2_method: Optional[str] = None,
                          traceability_url: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'Each entry has a code that groups versions of the same
    factor, a version integer ..., a library of IPCC_DEFAULT,
    NATIONAL_PUBLISHED, SUPPLIER_SPECIFIC, or MEASURED, a gas_type ..., a
    kg_per_unit value (non-negative, six decimal places), an
    uncertainty_rating of LOW, MEDIUM, or HIGH, an effective_from
    instant, and a traceability_url of 1–500 characters that points at
    the citation.'"""
    payload: Dict[str, Any] = {
        "code": code or TEST_DEFAULTS["FACTOR_CODE"],
        "library": library,
        "gas_type": gas_type,
        "kg_per_unit": kg_per_unit,
        "uncertainty_rating": uncertainty_rating,
        "effective_from": effective_from or "2024-12-01T00:00:00.000Z",
        "traceability_url": traceability_url or TEST_DEFAULTS["TRACEABILITY_URL"],
    }
    if scope2_method is not None:
        payload["scope2_method"] = scope2_method
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Activity data (PRD §3.5)
# Required: emission_source_id, data_source, quantity, unit, activity_start,
#           activity_end.
# Optional: estimation_basis (required when data_source==ESTIMATION).
# ---------------------------------------------------------------------------
def create_activity_data_payload(emission_source_id: str,
                                 data_source: str = "METER_READING",
                                 quantity: float = 1000.0000,
                                 unit: str = "kWh",
                                 activity_start: str = "2025-03-01T00:00:00.000Z",
                                 activity_end: str = "2025-04-01T00:00:00.000Z",
                                 estimation_basis: Optional[str] = None,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'The payload carries an emission_source_id, a data_source
    classification of METER_READING, INVOICE, SUPPLIER_DATA, or
    ESTIMATION, a non-negative quantity (four decimal places) in the
    source's unit (1–20 characters), an activity_start and activity_end
    window in UTC, and an optional estimation_basis free-text
    explanation of 5–500 characters.'"""
    payload: Dict[str, Any] = {
        "emission_source_id": emission_source_id,
        "data_source": data_source,
        "quantity": quantity,
        "unit": unit,
        "activity_start": activity_start,
        "activity_end": activity_end,
    }
    if estimation_basis is not None:
        payload["estimation_basis"] = estimation_basis
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Reduction project (PRD §3.6)
# Required: name, project_type, reduction_kg_co2e, reporting_period_id.
# Optional: facility_id (required iff project_type==INTERNAL_REDUCTION).
# ---------------------------------------------------------------------------
def create_project_payload(reporting_period_id: str,
                           project_type: str = "EXTERNAL_OFFSET",
                           reduction_kg_co2e: float = 0.0000,
                           facility_id: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'Each project is created with a name (1–200 characters),
    a project_type of INTERNAL_REDUCTION or EXTERNAL_OFFSET, a
    reduction_kg_co2e value (non-negative, four decimal places)
    representing the expected or realised reduction attributable to the
    project for its linked reporting_period_id, and — for
    internal-reduction projects only — a facility_id that names the
    facility whose emissions the project reduces.'"""
    payload: Dict[str, Any] = {
        "name": _unique_label("Project"),
        "project_type": project_type,
        "reduction_kg_co2e": reduction_kg_co2e,
        "reporting_period_id": reporting_period_id,
    }
    if facility_id is not None:
        payload["facility_id"] = facility_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Carbon credit (PRD §3.6)
# Required: registry, serial_number, vintage_year, quantity_kg_co2e,
#           linked_reduction_project_id, reporting_period_id.
# ---------------------------------------------------------------------------
def create_credit_payload(reporting_period_id: str,
                          linked_reduction_project_id: str,
                          quantity_kg_co2e: float = 500.0000,
                          vintage_year: int = 2024,
                          registry: str = "VCS",
                          serial_number: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'The payload carries a registry of VCS, GOLD_STANDARD, or
    CCER, a serial_number (1–100 characters) that is globally unique
    across every CarbonCredit row of every organization ..., a
    vintage_year between 1990 and the year of the parent reporting
    period's end_date inclusive, a quantity_kg_co2e strictly greater
    than zero (four decimal places), a linked_reduction_project_id whose
    project must have project_type equal to EXTERNAL_OFFSET, and a
    reporting_period_id against which the credit is applied.'"""
    payload: Dict[str, Any] = {
        "registry": registry,
        "serial_number": serial_number or _unique_serial(),
        "vintage_year": vintage_year,
        "quantity_kg_co2e": quantity_kg_co2e,
        "linked_reduction_project_id": linked_reduction_project_id,
        "reporting_period_id": reporting_period_id,
    }
    payload.update(overrides)
    return payload


def retire_credit_payload(retirement_certificate_url: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'A Discloser retires a credit by transitioning it from
    PURCHASED to RETIRED and supplying a retirement_certificate_url of
    1–500 characters.'"""
    payload: Dict[str, Any] = {
        "retirement_certificate_url": (
            retirement_certificate_url
            or TEST_DEFAULTS["RETIREMENT_CERT_URL"]
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Report (PRD §3.7)
# Required: reporting_period_id, standard.
# ---------------------------------------------------------------------------
def create_report_payload(reporting_period_id: str,
                          standard: str = "GHG_PROTOCOL",
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'A DataSteward creates a report by naming the
    reporting_period_id the report covers and the standard template to
    use — one of GHG_PROTOCOL, ISO_14064, CDP, TCFD, or LOCAL_MANDATORY.'"""
    payload: Dict[str, Any] = {
        "reporting_period_id": reporting_period_id,
        "standard": standard,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance and external sync (PRD §3.8)
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'An admin-only test-driving capability advances the
    logical clock to a supplied to_timestamp instant.'"""
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


def emit_event_payload(source_system: str = "ERP",
                       payload: Optional[dict] = None,
                       **overrides: Any) -> Dict[str, Any]:
    """PRD §3.8: 'a second admin-only capability emits an external sync
    event from a named source_system ... with a free-form payload.'"""
    body: Dict[str, Any] = {
        "source_system": source_system,
        "payload": payload if payload is not None else {"hello": "world"},
    }
    body.update(overrides)
    return body


__all__ = [
    "create_organization_payload",
    "create_facility_payload",
    "update_facility_payload",
    "create_boundary_change_payload",
    "create_reporting_period_payload",
    "create_source_payload",
    "create_factor_payload",
    "create_activity_data_payload",
    "create_project_payload",
    "create_credit_payload",
    "retire_credit_payload",
    "create_report_payload",
    "clock_advance_payload",
    "emit_event_payload",
]
