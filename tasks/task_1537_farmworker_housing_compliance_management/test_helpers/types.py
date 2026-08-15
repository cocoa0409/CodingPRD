"""Domain types: entity TypedDicts, status enums, role enum.

All fifteen resources share the identity contract of PRD §2.5: every entity
carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    OPERATOR_ADMIN = "OperatorAdmin"
    SITE_MANAGER = "SiteManager"
    MAINTENANCE_LEAD = "MaintenanceLead"
    COMPLIANCE_INSPECTOR = "ComplianceInspector"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    RESIDENT = "Resident"


class HousingSiteStatus(str, Enum):
    DRAFT = "DRAFT"
    OPENING = "OPENING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"


class SeasonWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class HousingUnitStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"
    OCCUPIED = "OCCUPIED"
    HABITABILITY_HOLD = "HABITABILITY_HOLD"
    CONDEMNED = "CONDEMNED"
    DECOMMISSIONED = "DECOMMISSIONED"


class UnitType(str, Enum):
    FAMILY_UNIT = "FAMILY_UNIT"
    SEASONAL_DORM = "SEASONAL_DORM"


class UnitCertificationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class EligibilityStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class Relationship(str, Enum):
    HEAD = "HEAD"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    OTHER = "OTHER"


class TenancyStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    ACTIVE = "ACTIVE"
    NOTICE = "NOTICE"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class NoticeReason(str, Enum):
    RESIDENT = "RESIDENT"
    OPERATOR = "OPERATOR"
    CONDEMNATION = "CONDEMNATION"


class LedgerEntryType(str, Enum):
    RENT = "RENT"
    UTILITY_OVERAGE = "UTILITY_OVERAGE"
    DAMAGE = "DAMAGE"
    SUBSIDY_CREDIT = "SUBSIDY_CREDIT"
    PAYMENT = "PAYMENT"


class LedgerEntryStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class UtilityType(str, Enum):
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"
    WATER = "WATER"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class AuthorizationPurpose(str, Enum):
    RENT = "RENT"
    RENT_AND_UTILITIES = "RENT_AND_UTILITIES"


class WorkOrderStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WorkOrderCategory(str, Enum):
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    STRUCTURAL = "STRUCTURAL"
    PEST = "PEST"
    APPLIANCE = "APPLIANCE"
    OTHER = "OTHER"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class PestTreatmentType(str, Enum):
    ROUTINE = "ROUTINE"
    TARGETED = "TARGETED"
    FUMIGATION = "FUMIGATION"


class PestTreatmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class ComplaintCategory(str, Enum):
    HABITABILITY = "HABITABILITY"
    RENT = "RENT"
    UTILITY = "UTILITY"
    HARASSMENT = "HARASSMENT"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    ESCALATED_TO_AGENCY = "ESCALATED_TO_AGENCY"
    CLOSED = "CLOSED"


class InspectionAgency(str, Enum):
    STATE_HOUSING = "STATE_HOUSING"
    USDA_RD = "USDA_RD"
    HUD = "HUD"
    COUNTY_HEALTH = "COUNTY_HEALTH"


class RegulatoryInspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CURE_CERTIFIED = "CURE_CERTIFIED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReferralType(str, Enum):
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"


class ServiceReferralStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED_BY_AGENCY = "ACCEPTED_BY_AGENCY"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries the common fields of PRD §2.5
# (id, created_at, updated_at, version).
# ---------------------------------------------------------------------------


class HousingSite(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    status: str
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class SeasonWindow(TypedDict, total=False):
    id: str
    site_id: str
    label: str
    planned_open_date: str
    planned_close_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class HousingUnit(TypedDict, total=False):
    id: str
    building_id: str
    site_id: str
    unit_code: str
    unit_type: str
    max_occupancy: int
    monthly_rent_cents: int
    status: str
    current_occupancy: int
    habitability_score_cumulative: float
    habitability_score_worst_case: float
    under_pest_exclusion: bool
    pest_exclusion_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnitCertification(TypedDict, total=False):
    id: str
    unit_id: str
    inspector_id: str
    status: str
    deficiency_count: int
    notes: Optional[str]
    inspection_date: Optional[str]
    expiry_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    head_of_household_name: str
    annual_family_income_cents: int
    ag_work_verified: bool
    eligibility_status: str
    eligibility_notes: Optional[str]
    member_count: int
    minor_count: int
    rehousing_priority: bool
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    relationship: str
    is_minor: bool
    created_at: str
    updated_at: str
    version: int


class Tenancy(TypedDict, total=False):
    id: str
    household_id: str
    unit_id: str
    move_in_date: str
    move_out_date: Optional[str]
    status: str
    notice_reason: Optional[str]
    balance_cents: int
    rent_bucket_balance_cents: int
    utility_bucket_balance_cents: int
    damage_bucket_balance_cents: int
    is_delinquent: bool
    oldest_unpaid_charge_date: Optional[str]
    subsidy_tier_percent: float
    created_at: str
    updated_at: str
    version: int


class UsageLine(TypedDict):
    utility_type: str
    usage_units: int


class ChargeLedgerEntry(TypedDict, total=False):
    id: str
    tenancy_id: str
    entry_type: str
    amount_cents: int
    usage_lines: Optional[List[UsageLine]]
    source_work_order_id: Optional[str]
    description: Optional[str]
    charge_date: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeductionAuthorization(TypedDict, total=False):
    id: str
    household_id: str
    cap_percent: float
    purpose: str
    effective_date: str
    status: str
    superseded_by_id: Optional[str]
    created_by: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    unit_id: str
    complaint_id: Optional[str]
    category: str
    severity: str
    description: str
    status: str
    assignee_name: Optional[str]
    completed_by: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PestTreatment(TypedDict, total=False):
    id: str
    unit_id: str
    treatment_type: str
    scheduled_date: str
    reentry_buffer_days: int
    status: str
    applied_date: Optional[str]
    exclusion_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    tenancy_id: str
    category: str
    description: str
    status: str
    filed_at: str
    acknowledged_at: Optional[str]
    sla_breached: bool
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict):
    unit_id: str
    severity: str
    code: str


class RegulatoryInspection(TypedDict, total=False):
    id: str
    site_id: str
    agency: str
    scheduled_date: str
    status: str
    findings: Optional[List[InspectionFinding]]
    open_critical_count: int
    issued_by: Optional[str]
    cure_certified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceReferral(TypedDict, total=False):
    id: str
    household_id: str
    referral_type: str
    agency_name: str
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
