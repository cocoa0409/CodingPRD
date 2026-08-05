"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD:
- Property, NoiseLimitPolicy, VariancePermit, Complaint, Enforcement, Hearing,
  AbatementOrder, CrossAgencyReferral carry id/created_at/updated_at/version.
- Inspection and Payment are append-only records: id + created_at only
  (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CODE_OFFICER = "CodeOfficer"
    HEARING_OFFICER = "HearingOfficer"
    PERMIT_CLERK = "PermitClerk"
    RESIDENT = "Resident"
    SYSTEM_ADMIN = "SystemAdmin"


class ZoningType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"
    MIXED = "MIXED"


class ChronicStatus(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    DESIGNATED = "DESIGNATED"


class AbatementStatus(str, Enum):
    NONE = "NONE"
    UNDER_ABATEMENT = "UNDER_ABATEMENT"
    ABATED = "ABATED"


class PermitType(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    EVENT = "EVENT"


class VarianceStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class NoiseType(str, Enum):
    CONSTRUCTION = "CONSTRUCTION"
    AMPLIFIED_MUSIC = "AMPLIFIED_MUSIC"
    MACHINERY = "MACHINERY"
    ANIMAL = "ANIMAL"
    VEHICLE = "VEHICLE"
    OTHER = "OTHER"


class ComplaintSource(str, Enum):
    PHONE = "PHONE"
    ONLINE = "ONLINE"
    OFFICER = "OFFICER"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class EnforcementTier(str, Enum):
    WARNING = "WARNING"
    CITATION = "CITATION"


class EnforcementStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    DISMISSED = "DISMISSED"
    PAID = "PAID"


class HearingOutcome(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    DISMISSED = "DISMISSED"
    REMANDED = "REMANDED"


class AbatementTriggerSource(str, Enum):
    CHRONIC_DESIGNATION = "CHRONIC_DESIGNATION"
    DELINQUENT_CITATION = "DELINQUENT_CITATION"


class AbatementOrderStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIED = "COMPLIED"
    ESCALATED = "ESCALATED"
    VACATED = "VACATED"


class ReferralAgency(str, Enum):
    POLICE = "POLICE"
    BUILDING = "BUILDING"
    HEALTH = "HEALTH"
    ANIMAL_CONTROL = "ANIMAL_CONTROL"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


class PaymentKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"


# --- Entity TypedDicts (common_fields: true) ---

class Property(TypedDict):
    id: str
    address: str
    zoning_type: str
    substantiated_violation_count: int
    chronic_status: str
    abatement_status: str
    created_at: str
    updated_at: str
    version: int


class NoiseLimitPolicy(TypedDict):
    id: str
    zoning_type: str
    day_limit_db: float
    night_limit_db: float
    day_start_hour: int
    night_start_hour: int
    created_at: str
    updated_at: str
    version: int


class VariancePermit(TypedDict):
    id: str
    property_id: str
    permit_type: str
    requested_start: str
    requested_end: str
    permitted_max_db: float
    expected_attendees: int
    approved_start: Optional[str]
    approved_end: Optional[str]
    fee_estimate_cents: int
    fee_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    property_id: str
    reported_at: str
    noise_type: str
    reported_decibel: Optional[float]
    source: str
    complainant_contact: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Enforcement(TypedDict):
    id: str
    complaint_id: str
    property_id: str
    tier: str
    escalation_level: int
    assessed_fine_cents: int
    effective_fine_cents: int
    late_penalty_cents: int
    amount_paid_cents: int
    amount_outstanding_cents: int
    issued_by_user_id: str
    issued_at: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    enforcement_id: str
    hearing_officer_id: str
    scheduled_at: str
    duration_minutes: int
    reduction_pct: Optional[float]
    outcome: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbatementOrder(TypedDict):
    id: str
    property_id: str
    enforcement_id: Optional[str]
    trigger_source: str
    compliance_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrossAgencyReferral(TypedDict):
    id: str
    complaint_id: str
    agency: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (common_fields: false) — id + created_at only ---

class Inspection(TypedDict):
    id: str
    complaint_id: str
    measured_decibel: float
    measured_at: str
    effective_limit_db: float
    exceeds_limit: bool
    inspected_by_user_id: str
    created_at: str


class Payment(TypedDict):
    id: str
    enforcement_id: str
    amount_cents: int
    kind: str
    method: str
    status: str
    created_at: str
