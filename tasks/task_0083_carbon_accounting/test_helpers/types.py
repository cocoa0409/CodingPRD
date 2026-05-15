"""Domain types for the Carbon Accounting API.

Entity TypedDicts, status enums, and role enum derived from PRD §2.4
(common resource properties) and §3 (per-entity lifecycles).

PRD §2.4 — Two entities (BoundaryChange, AuditLog) are append-only event
records carrying only id and created_at; all other entities carry the
full envelope (id + created_at + updated_at + version).
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DATA_STEWARD = "DataSteward"
    FACTOR_MANAGER = "FactorManager"
    VERIFIER = "Verifier"
    DISCLOSER = "Discloser"


# ---------------------------------------------------------------------------
# Organization (PRD §3.1)
# ---------------------------------------------------------------------------
class ConsolidationApproach(str, Enum):
    EQUITY_SHARE = "EQUITY_SHARE"
    FINANCIAL_CONTROL = "FINANCIAL_CONTROL"
    OPERATIONAL_CONTROL = "OPERATIONAL_CONTROL"


class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Facility (PRD §3.1)
# ---------------------------------------------------------------------------
class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# ---------------------------------------------------------------------------
# BoundaryChange (PRD §3.1, append-only)
# ---------------------------------------------------------------------------
class BoundaryChangeType(str, Enum):
    ADD_FACILITY = "ADD_FACILITY"
    REMOVE_FACILITY = "REMOVE_FACILITY"
    APPROACH_SWITCH = "APPROACH_SWITCH"
    OWNERSHIP_ADJUSTMENT = "OWNERSHIP_ADJUSTMENT"


# ---------------------------------------------------------------------------
# ReportingPeriod (PRD §3.2)
# ---------------------------------------------------------------------------
class ReportingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# EmissionSource (PRD §3.3)
# ---------------------------------------------------------------------------
class EmissionCategory(str, Enum):
    STATIONARY_COMBUSTION = "STATIONARY_COMBUSTION"
    MOBILE_COMBUSTION = "MOBILE_COMBUSTION"
    PROCESS = "PROCESS"
    FUGITIVE = "FUGITIVE"
    PURCHASED_ENERGY = "PURCHASED_ENERGY"
    VALUE_CHAIN = "VALUE_CHAIN"


class EmissionScope(str, Enum):
    SCOPE_1 = "SCOPE_1"
    SCOPE_2 = "SCOPE_2"
    SCOPE_3 = "SCOPE_3"


class GasType(str, Enum):
    CO2 = "CO2"
    CH4 = "CH4"
    N2O = "N2O"
    HFC = "HFC"
    PFC = "PFC"
    SF6 = "SF6"
    NF3 = "NF3"


class EmissionSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


# ---------------------------------------------------------------------------
# EmissionFactor (PRD §3.4)
# ---------------------------------------------------------------------------
class FactorLibrary(str, Enum):
    IPCC_DEFAULT = "IPCC_DEFAULT"
    NATIONAL_PUBLISHED = "NATIONAL_PUBLISHED"
    SUPPLIER_SPECIFIC = "SUPPLIER_SPECIFIC"
    MEASURED = "MEASURED"


class Scope2Method(str, Enum):
    LOCATION_BASED = "LOCATION_BASED"
    MARKET_BASED = "MARKET_BASED"


class UncertaintyRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EmissionFactorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


# ---------------------------------------------------------------------------
# ActivityData (PRD §3.5)
# ---------------------------------------------------------------------------
class DataSource(str, Enum):
    METER_READING = "METER_READING"
    INVOICE = "INVOICE"
    SUPPLIER_DATA = "SUPPLIER_DATA"
    ESTIMATION = "ESTIMATION"


class ActivityDataStatus(str, Enum):
    RECORDED = "RECORDED"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# EmissionRecord (PRD §3.5)
# ---------------------------------------------------------------------------
class EmissionRecordStatus(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# ReductionProject (PRD §3.6)
# ---------------------------------------------------------------------------
class ProjectType(str, Enum):
    INTERNAL_REDUCTION = "INTERNAL_REDUCTION"
    EXTERNAL_OFFSET = "EXTERNAL_OFFSET"


class ReductionProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# CarbonCredit (PRD §3.6)
# ---------------------------------------------------------------------------
class CreditRegistry(str, Enum):
    VCS = "VCS"
    GOLD_STANDARD = "GOLD_STANDARD"
    CCER = "CCER"


class CarbonCreditStatus(str, Enum):
    PURCHASED = "PURCHASED"
    RETIRED = "RETIRED"
    TRANSFERRED = "TRANSFERRED"


# ---------------------------------------------------------------------------
# Report (PRD §3.7)
# ---------------------------------------------------------------------------
class DisclosureStandard(str, Enum):
    GHG_PROTOCOL = "GHG_PROTOCOL"
    ISO_14064 = "ISO_14064"
    CDP = "CDP"
    TCFD = "TCFD"
    LOCAL_MANDATORY = "LOCAL_MANDATORY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISIONS_REQUIRED = "REVISIONS_REQUIRED"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    RECOMPUTE_REQUIRED = "RECOMPUTE_REQUIRED"


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.9, append-only)
# ---------------------------------------------------------------------------
class AuditEventType(str, Enum):
    ACTIVITY_ENTRY = "ACTIVITY_ENTRY"
    ACTIVITY_ARCHIVE = "ACTIVITY_ARCHIVE"
    FACTOR_APPROVE = "FACTOR_APPROVE"
    FACTOR_SUPERSEDE = "FACTOR_SUPERSEDE"
    REPORT_COMPILE = "REPORT_COMPILE"
    REPORT_VERIFY = "REPORT_VERIFY"
    REPORT_PUBLISH = "REPORT_PUBLISH"
    BOUNDARY_CHANGE = "BOUNDARY_CHANGE"
    CREDIT_RETIRE = "CREDIT_RETIRE"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


# ===========================================================================
# Entity TypedDicts
# PRD §2.4: All entities except BoundaryChange and AuditLog carry id +
# created_at + updated_at + version. BoundaryChange and AuditLog are
# append-only and carry ONLY id + created_at.
# ===========================================================================
class Organization(TypedDict, total=False):
    id: str
    legal_name: str
    consolidation_approach: str
    base_year: int
    functional_currency: str
    materiality_threshold_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    organization_id: str
    name: str
    country_code: str
    ownership_share_pct: float
    financial_control: bool
    operational_control: bool
    included_in_boundary: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4 — BoundaryChange is append-only, no updated_at / version
class BoundaryChange(TypedDict, total=False):
    id: str
    organization_id: str
    previous_change_id: Optional[str]
    change_type: str
    facility_id: Optional[str]
    from_approach: Optional[str]
    to_approach: Optional[str]
    effective_date: str
    rationale: str
    recorded_by_user_id: str
    created_at: str


class ReportingPeriod(TypedDict, total=False):
    id: str
    organization_id: str
    label: str
    start_date: str
    end_date: str
    revenue: float
    headcount: int
    unit_output: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionSource(TypedDict, total=False):
    id: str
    organization_id: str
    facility_id: str
    code: str
    category: str
    scope: str
    scope3_category: Optional[int]
    gas_type: str
    factor_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionFactor(TypedDict, total=False):
    id: str
    organization_id: str
    code: str
    version: int  # factor version — distinct from envelope version per PRD §3.4
    library: str
    gas_type: str
    scope2_method: Optional[str]
    kg_per_unit: float
    uncertainty_rating: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    traceability_url: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str


class ActivityData(TypedDict, total=False):
    id: str
    reporting_period_id: str
    emission_source_id: str
    data_source: str
    quantity: float
    unit: str
    activity_start: str
    activity_end: str
    data_quality_score: float
    estimation_basis: Optional[str]
    entered_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionRecord(TypedDict, total=False):
    id: str
    reporting_period_id: str
    activity_data_id: str
    emission_factor_id: str
    gas_type: str
    gwp_factor: float
    kg_co2e: float
    scope2_method: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReductionProject(TypedDict, total=False):
    id: str
    organization_id: str
    name: str
    project_type: str
    facility_id: Optional[str]
    reduction_kg_co2e: float
    reporting_period_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CarbonCredit(TypedDict, total=False):
    id: str
    organization_id: str
    registry: str
    serial_number: str
    vintage_year: int
    quantity_kg_co2e: float
    linked_reduction_project_id: str
    reporting_period_id: str
    retired_at: Optional[str]
    retirement_certificate_url: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    organization_id: str
    reporting_period_id: str
    standard: str
    gross_scope1_kg_co2e: Optional[float]
    gross_scope2_location_kg_co2e: Optional[float]
    gross_scope2_market_kg_co2e: Optional[float]
    gross_scope3_kg_co2e: Optional[float]
    applied_offsets_kg_co2e: Optional[float]
    net_emissions_kg_co2e: Optional[float]
    intensity_per_revenue: Optional[float]
    intensity_per_employee: Optional[float]
    intensity_per_unit_output: Optional[float]
    completeness_pct: Optional[float]
    completeness_passes: Optional[bool]
    assurance_ready: Optional[bool]
    compiled_at: Optional[str]
    verified_at: Optional[str]
    verifier_user_id: Optional[str]
    published_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4 + §2.9: AuditLog — append-only, no updated_at / version
class AuditLog(TypedDict, total=False):
    id: str
    organization_id: str
    actor_user_id: str
    actor_role: str
    event_type: str
    target_entity: str
    target_id: str
    payload_json: dict
    created_at: str


__all__ = [
    "UserRole",
    "ConsolidationApproach",
    "OrganizationStatus",
    "FacilityStatus",
    "BoundaryChangeType",
    "ReportingPeriodStatus",
    "EmissionCategory",
    "EmissionScope",
    "GasType",
    "EmissionSourceStatus",
    "FactorLibrary",
    "Scope2Method",
    "UncertaintyRating",
    "EmissionFactorStatus",
    "DataSource",
    "ActivityDataStatus",
    "EmissionRecordStatus",
    "ProjectType",
    "ReductionProjectStatus",
    "CreditRegistry",
    "CarbonCreditStatus",
    "DisclosureStandard",
    "ReportStatus",
    "AuditEventType",
    "Organization",
    "Facility",
    "BoundaryChange",
    "ReportingPeriod",
    "EmissionSource",
    "EmissionFactor",
    "ActivityData",
    "EmissionRecord",
    "ReductionProject",
    "CarbonCredit",
    "Report",
    "AuditLog",
]
