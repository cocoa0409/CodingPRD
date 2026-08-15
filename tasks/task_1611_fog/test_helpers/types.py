"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities with the standard four
system-managed fields carry id + created_at + updated_at + version; the
Inspection and the DisposalRecord are the append-only exceptions and carry
only id + created_at (PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class CuisineProfile(str, Enum):
    LOW_GREASE = "LOW_GREASE"
    MEDIUM_GREASE = "MEDIUM_GREASE"
    HIGH_GREASE = "HIGH_GREASE"


class RiskClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class InterceptorStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"


class SizingMethod(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    MEASURED = "MEASURED"


class InspectionCategory(str, Enum):
    GREASE_TRAP_MAINTENANCE = "GREASE_TRAP_MAINTENANCE"
    RECORD_KEEPING = "RECORD_KEEPING"
    STRUCTURAL = "STRUCTURAL"
    BMP_PRACTICES = "BMP_PRACTICES"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ViolationStatus(str, Enum):
    NOTICED = "NOTICED"
    CITATION = "CITATION"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ManifestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    DISPOSAL_MISMATCH = "DISPOSAL_MISMATCH"
    MISSING_DISPOSAL_RECORD = "MISSING_DISPOSAL_RECORD"
    HAULER_SUSPENDED = "HAULER_SUSPENDED"
    OTHER = "OTHER"


class HaulerStatus(str, Enum):
    APPLIED = "APPLIED"
    PERMITTED = "PERMITTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BlockageStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    CLOSED = "CLOSED"


class VarianceScope(str, Enum):
    PUMPING_FREQUENCY = "PUMPING_FREQUENCY"
    INTERCEPTOR_SIZE = "INTERCEPTOR_SIZE"


class VarianceStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class OutreachEventStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INSPECTOR = "Inspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FSE_CONTACT = "FseContact"
    HAULER_ADMIN = "HaulerAdmin"


class Establishment(TypedDict, total=False):
    id: str
    name: str
    street_address: str
    seating_capacity: int
    fryer_count: int
    has_charbroiler: bool
    cuisine_profile: str
    risk_score: float
    risk_class: str
    compliance_status: str
    open_violation_count: int
    last_verified_pump_at: Optional[str]
    variance_override_frequency_days: Optional[int]
    pumping_frequency_days: int
    pumping_overdue: bool
    missed_pump_windows: int
    created_at: str
    updated_at: str
    version: int


class GreaseInterceptor(TypedDict, total=False):
    id: str
    establishment_id: str
    nominal_capacity_gal: int
    measured_flow_gpm: Optional[float]
    provisional_required_gal: int
    required_min_capacity_gal: Optional[int]
    sizing_method: Optional[str]
    status: str
    approved_by_user_id: Optional[str]
    commissioned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionItem(TypedDict, total=False):
    category: str
    severity: str


class Inspection(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    establishment_id: str
    items: List[InspectionItem]
    inspector_user_id: str
    score: int
    passed: bool
    created_at: str


class Violation(TypedDict, total=False):
    id: str
    establishment_id: str
    inspection_id: str
    severity: str
    status: str
    cure_deadline: str
    fine_cents: int
    recorded_by_user_id: str
    escalated_at: Optional[str]
    resolved_at: Optional[str]
    dismissed_at: Optional[str]
    dismissed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PumpManifest(TypedDict, total=False):
    id: str
    establishment_id: str
    interceptor_id: str
    hauler_id: str
    pump_date: str
    pumped_volume_gal: float
    status: str
    submitted_by_user_id: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hauler(TypedDict, total=False):
    id: str
    name: str
    permit_number: str
    insurance_expires_on: str
    status: str
    mismatch_count: int
    created_at: str
    updated_at: str
    version: int


class DisposalRecord(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    hauler_id: str
    manifest_id: str
    disposed_volume_gal: float
    disposal_site_name: str
    disposed_at: str
    created_at: str


class BlockageContribution(TypedDict, total=False):
    establishment_id: str
    weight_percent: int
    share_cents: int
    paid_at: Optional[str]


class BlockageEvent(TypedDict, total=False):
    id: str
    location_description: str
    status: str
    total_cleanup_cost_cents: Optional[int]
    contributions: List[BlockageContribution]
    reported_by_user_id: str
    assessed_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VarianceRequest(TypedDict, total=False):
    id: str
    establishment_id: str
    scope: str
    requested_frequency_days: Optional[int]
    justification: str
    effective_from: str
    effective_to: str
    status: str
    approved_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationCampaign(TypedDict, total=False):
    id: str
    name: str
    outreach_zone: str
    start_date: str
    end_date: str
    budget_cents: int
    remaining_budget_cents: int
    created_at: str
    updated_at: str
    version: int


class OutreachEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    event_date: str
    venue_name: str
    attendance_count: int
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
