"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the McKinney-Vento School Transport PRD (§2, §3).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    STATE_COORDINATOR = "StateCoordinator"
    LIAISON = "Liaison"
    TRANSPORT_COORDINATOR = "TransportCoordinator"
    REGISTRAR = "Registrar"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class StudentStatus(str, Enum):
    INTAKE = "INTAKE"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityStatus(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class PriorityBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LivingSituation(str, Enum):
    SHELTER = "SHELTER"
    UNSHELTERED = "UNSHELTERED"
    HOTEL_MOTEL = "HOTEL_MOTEL"
    DOUBLED_UP = "DOUBLED_UP"
    FOSTER_PLACEMENT = "FOSTER_PLACEMENT"
    HOUSED = "HOUSED"


class SelfDeclaredCategory(str, Enum):
    HOMELESS = "HOMELESS"
    FOSTER = "FOSTER"
    NONE = "NONE"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class DeterminationCategory(str, Enum):
    HOMELESS = "HOMELESS"
    FOSTER = "FOSTER"


class DeterminationBasis(str, Enum):
    NIGHT_TO_NIGHT = "NIGHT_TO_NIGHT"
    SHELTER = "SHELTER"
    HOTEL_MOTEL = "HOTEL_MOTEL"
    DOUBLED_UP = "DOUBLED_UP"
    UNSHELTERED = "UNSHELTERED"
    FOSTER = "FOSTER"


class DeterminationDecision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    TRIP_CHARGE = "TRIP_CHARGE"
    REVERSAL = "REVERSAL"


class BenefitLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DisputeType(str, Enum):
    ELIGIBILITY = "ELIGIBILITY"
    ENROLLMENT = "ENROLLMENT"
    TRANSPORT = "TRANSPORT"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DENIED = "RESOLVED_DENIED"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class ReferralSubject(str, Enum):
    MATH = "MATH"
    READING = "READING"
    OTHER = "OTHER"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELED = "CANCELED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true — id + created_at + updated_at + version
class District(TypedDict):
    id: str
    name: str
    nces_code: str
    transport_budget_cents: int
    committed_cost_cents: int
    transport_balance_cents: int
    categorical_eligible_count: int
    created_at: str
    updated_at: str
    version: int


class Liaison(TypedDict):
    id: str
    district_id: str
    full_name: str
    email: str
    max_caseload: int
    current_caseload: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    first_name: str
    last_name: str
    birthdate: str
    enrolled_district_id: str
    origin_district_id: str
    liaison_id: Optional[str]
    living_situation: str
    self_declared_category: str
    records_received: bool
    status: str
    eligibility_status: str
    priority_score: int
    priority_basis: str
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict):
    id: str
    student_id: str
    category: str
    basis: str
    decision: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportationPlan(TypedDict):
    id: str
    student_id: str
    origin_district_id: str
    serving_district_id: str
    route_miles: int
    estimated_daily_cost_cents: int
    estimated_monthly_cost_cents: int
    actual_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    serving_district_id: str
    label: str
    capacity_students: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripAssignment(TypedDict):
    id: str
    transportation_plan_id: str
    vehicle_id: str
    serving_district_id: str
    scheduled_start: str
    scheduled_end: str
    actual_miles: Optional[int]
    trip_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CostShareAgreement(TypedDict):
    id: str
    transportation_plan_id: str
    origin_district_id: str
    serving_district_id: str
    total_monthly_cents: int
    serving_pct: float
    serving_share_cents: int
    origin_share_cents: int
    actual_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, id + created_at only
class CostLedgerEntry(TypedDict):
    id: str
    cost_share_agreement_id: str
    district_id: str
    trip_assignment_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str


class BenefitLink(TypedDict):
    id: str
    student_id: str
    district_id: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    student_id: str
    dispute_type: str
    description: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TutoringReferral(TypedDict):
    id: str
    student_id: str
    subject: str
    status: str
    created_at: str
    updated_at: str
    version: int
