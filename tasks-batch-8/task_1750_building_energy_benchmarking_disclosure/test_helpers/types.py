"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BUILDING_OWNER = "BuildingOwner"
    TENANT_REP = "TenantRep"
    DATA_VERIFIER = "DataVerifier"
    UTILITY_AGENT = "UtilityAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class OwnerStanding(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FILING_CLOSED = "FILING_CLOSED"
    PUBLISHED = "PUBLISHED"


class BuildingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PropertyType(str, Enum):
    OFFICE = "OFFICE"
    MULTIFAMILY = "MULTIFAMILY"
    RETAIL = "RETAIL"
    HOTEL = "HOTEL"
    INDUSTRIAL = "INDUSTRIAL"


class SpaceType(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    RESIDENTIAL = "RESIDENTIAL"
    COMMON = "COMMON"
    OTHER = "OTHER"


class ConsentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class Commodity(str, Enum):
    ELECTRICITY = "ELECTRICITY"
    NATURAL_GAS = "NATURAL_GAS"
    DISTRICT_STEAM = "DISTRICT_STEAM"
    FUEL_OIL = "FUEL_OIL"


class UsageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FLAGGED = "FLAGGED"
    VERIFIED = "VERIFIED"
    CERTIFIED = "CERTIFIED"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED_OFF = "SIGNED_OFF"
    REJECTED = "REJECTED"


class AnomalyType(str, Enum):
    CONSUMPTION_SPIKE = "CONSUMPTION_SPIKE"
    VERIFICATION_REOPENED = "VERIFICATION_REOPENED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class AnomalyStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class FineType(str, Enum):
    LATE_SUBMISSION = "LATE_SUBMISSION"
    NON_COMPLIANCE = "NON_COMPLIANCE"
    PERFORMANCE_SHORTFALL = "PERFORMANCE_SHORTFALL"


class FineStatus(str, Enum):
    ASSESSED = "ASSESSED"
    NOTICED = "NOTICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ExemptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"


class RequestType(str, Enum):
    EXEMPTION = "EXEMPTION"
    EXTENSION = "EXTENSION"


class PublicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class LabelGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# All fourteen entity types carry the full common-field set
# (id, created_at, updated_at, version) per PRD §2.4.

class Owner(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    standing: str
    outstanding_fines_cents: int
    created_at: str
    updated_at: str
    version: int


class Verifier(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    accredited: bool
    created_at: str
    updated_at: str
    version: int


class PerformanceStandard(TypedDict, total=False):
    property_type: str
    median_eui: float
    score_slope: float
    baseline_eui_default: float
    annual_reduction_pct: float
    shortfall_tolerance_pct: float
    fine_rate_cents_per_sqft: int
    performance_fine_cap_cents: int


class ReportingCycle(TypedDict, total=False):
    id: str
    cycle_year: int
    filing_deadline_at: str
    covered_floor_area_threshold_sqft: int
    covered_property_types: List[str]
    late_fine_daily_rate_cents: int
    late_fine_cap_days: int
    non_compliance_fine_cents: int
    data_completeness_min_pct: float
    correction_tolerance_pct: float
    anomaly_yoy_threshold_pct: float
    weather_adjustment_factor: float
    performance_standards: List[PerformanceStandard]
    status: str
    created_by_officer_id: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict, total=False):
    id: str
    owner_id: str
    address: str
    gross_floor_area_sqft: int
    property_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TenantUnit(TypedDict, total=False):
    id: str
    building_id: str
    unit_label: str
    floor_area_sqft: int
    space_type: str
    occupied: bool
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict, total=False):
    id: str
    tenant_unit_id: str
    scope: str
    status: str
    valid_from: Optional[str]
    valid_to: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilityAccount(TypedDict, total=False):
    id: str
    building_id: str
    account_number: str
    commodity: str
    created_at: str
    updated_at: str
    version: int


class UsageRecord(TypedDict, total=False):
    id: str
    utility_account_id: str
    period_start: str
    period_end: str
    consumption_value: float
    commodity: str
    kbtu: int
    status: str
    void_reason: Optional[str]
    replaces_usage_record_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenchmarkReport(TypedDict, total=False):
    id: str
    building_id: str
    cycle_id: str
    status: str
    revision_number: int
    aggregated_kbtu: int
    site_eui: float
    data_completeness_pct: float
    score_as_reported: Optional[int]
    score_weather_normalized: Optional[int]
    label_grade: Optional[str]
    target_eui: Optional[float]
    submitted_at: Optional[str]
    verified_at: Optional[str]
    verified_site_eui: Optional[float]
    is_late: bool
    days_late: int
    created_at: str
    updated_at: str
    version: int


class VerificationRecord(TypedDict, total=False):
    id: str
    report_id: str
    verifier_id: str
    status: str
    decided_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnomalyFlag(TypedDict, total=False):
    id: str
    report_id: str
    anomaly_type: str
    status: str
    detail: str
    resolution_note: Optional[str]
    waive_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FineAssessment(TypedDict, total=False):
    id: str
    building_id: str
    cycle_id: str
    fine_type: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    days_late: int
    assessed_at: str
    noticed_at: Optional[str]
    paid_at: Optional[str]
    waive_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionRequest(TypedDict, total=False):
    id: str
    building_id: str
    cycle_id: str
    request_type: str
    reason: str
    requested_extension_days: Optional[int]
    status: str
    appeal_used: bool
    decision_note: Optional[str]
    extended_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosurePublication(TypedDict, total=False):
    id: str
    cycle_id: str
    publication_version: int
    status: str
    included_report_count: int
    published_at: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
