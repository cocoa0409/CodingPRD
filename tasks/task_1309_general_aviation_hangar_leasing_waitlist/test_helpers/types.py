"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    AIRPORT_MANAGER = "AirportManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    APPLICANT = "Applicant"
    TENANT = "Tenant"


class AirportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EscalationPolicy(str, Enum):
    ANNIVERSARY_COMPOUND = "ANNIVERSARY_COMPOUND"
    ANNIVERSARY_SIMPLE = "ANNIVERSARY_SIMPLE"


class SizeClass(str, Enum):
    T_HANGAR = "T_HANGAR"
    BOX = "BOX"
    EXECUTIVE = "EXECUTIVE"
    CORPORATE = "CORPORATE"


class DoorType(str, Enum):
    SLIDING = "SLIDING"
    BIFOLD = "BIFOLD"
    HYDRAULIC = "HYDRAULIC"


class ConditionRating(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class HangarPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"
    OFFLINE = "OFFLINE"


class HangarStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DECOMMISSIONED = "DECOMMISSIONED"


class RateScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ApplicationStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    LEASED = "LEASED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED_OFFER = "EXPIRED_OFFER"
    REJECTED = "REJECTED"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CURE_PERIOD = "CURE_PERIOD"
    EVICTION_PENDING = "EVICTION_PENDING"
    EVICTED = "EVICTED"
    TERMINATED = "TERMINATED"


class LeaseAircraftStatus(str, Enum):
    BASED = "BASED"
    REMOVED = "REMOVED"


class InsuranceCertificateStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class EnvironmentalRecordType(str, Enum):
    FUEL_STORAGE_PERMIT = "FUEL_STORAGE_PERMIT"
    STORMWATER_PLAN = "STORMWATER_PLAN"
    HAZMAT_DISCLOSURE = "HAZMAT_DISCLOSURE"


class EnvironmentalRecordStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MaintenanceResponsibility(str, Enum):
    TENANT = "TENANT"
    AIRPORT = "AIRPORT"
    SHARED = "SHARED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FindingType(str, Enum):
    NON_AERONAUTICAL_USE = "NON_AERONAUTICAL_USE"
    UNAUTHORIZED_SUBLEASE = "UNAUTHORIZED_SUBLEASE"
    INSURANCE_LAPSE = "INSURANCE_LAPSE"
    ENVIRONMENTAL_LAPSE = "ENVIRONMENTAL_LAPSE"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED_TO_EVICTION = "ESCALATED_TO_EVICTION"


class EvictionReason(str, Enum):
    UNCURED_AUDIT = "UNCURED_AUDIT"
    DELINQUENCY = "DELINQUENCY"
    NON_AERONAUTICAL_USE = "NON_AERONAUTICAL_USE"


class EvictionCaseStatus(str, Enum):
    FILED = "FILED"
    EXECUTED = "EXECUTED"
    CLOSED_AIRCRAFT_REMOVED = "CLOSED_AIRCRAFT_REMOVED"
    CLOSED_AIRCRAFT_ABANDONED = "CLOSED_AIRCRAFT_ABANDONED"


class RentChargeStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"


# All resource types carry the full common set: id, created_at, updated_at,
# version (PRD §2.4).

class Airport(TypedDict):
    id: str
    airport_code: str
    name: str
    escalation_pct: float
    escalation_policy: str
    offer_acceptance_window_hours: int
    cure_window_days: int
    late_fee_grace_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hangar(TypedDict):
    id: str
    airport_id: str
    hangar_code: str
    size_class: str
    door_type: str
    condition_rating: str
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict):
    id: str
    airport_id: str
    size_class: str
    monthly_rate_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistApplication(TypedDict):
    id: str
    airport_id: str
    applicant_name: str
    applicant_contact: str
    size_class_requested: str
    aircraft_n_number: str
    is_based_tenant_transfer: bool
    priority_score: int
    decline_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HangarOffer(TypedDict):
    id: str
    airport_id: str
    hangar_id: str
    application_id: str
    rate_schedule_id: str
    quoted_monthly_rate_cents: int
    offer_sent_at: str
    acceptance_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    airport_id: str
    hangar_id: str
    application_id: str
    offer_id: str
    tenant_name: str
    base_monthly_rate_cents: int
    current_monthly_rate_cents: int
    lease_start_date: str
    last_escalation_anniversary: int
    aeronautical_use_attested: bool
    sublease_allowed: bool
    days_delinquent: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAircraft(TypedDict):
    id: str
    lease_id: str
    n_number: str
    make_model: str
    is_primary: bool
    removed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    lease_id: str
    insurer_name: str
    policy_number: str
    liability_coverage_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalComplianceRecord(TypedDict):
    id: str
    lease_id: str
    record_type: str
    submitted_at: str
    expires_at: str
    review_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HangarConditionInspection(TypedDict):
    id: str
    hangar_id: str
    lease_id: str
    inspected_at: str
    condition_rating: str
    maintenance_responsibility: str
    deficiency_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UseAuditFinding(TypedDict):
    id: str
    lease_id: str
    finding_type: str
    observed_at: str
    cure_deadline: str
    cured_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict):
    id: str
    lease_id: str
    use_audit_finding_id: str
    reason: str
    filed_at: str
    executed_at: Optional[str]
    abandoned_aircraft_storage_cents_per_day: int
    storage_days_already_billed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentCharge(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    due_date: str
    base_amount_cents: int
    late_fee_cents: int
    paid_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
