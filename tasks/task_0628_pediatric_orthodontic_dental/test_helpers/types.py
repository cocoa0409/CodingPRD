"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable and carry the full common-field set
(id, created_at, updated_at, version), per the PRD's common resource properties.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    ORTHODONTIST = "Orthodontist"
    BILLING_SPECIALIST = "BillingSpecialist"
    GUARDIAN = "Guardian"
    CLINIC_ADMIN = "ClinicAdmin"


# --- Status enums ------------------------------------------------------------

class GrowthRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class InsurancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TreatmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETENTION = "RETENTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ContractBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class ContractLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    MISSED = "MISSED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    AUTOPAY = "AUTOPAY"
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"


class InsuranceClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RetainerStatus(str, Enum):
    ISSUED = "ISSUED"
    REPLACED = "REPLACED"


class VisitType(str, Enum):
    BONDING = "BONDING"
    ADJUSTMENT = "ADJUSTMENT"
    EMERGENCY = "EMERGENCY"
    DEBOND = "DEBOND"


class RecordType(str, Enum):
    PANO = "PANO"
    CEPH = "CEPH"


class RetainerType(str, Enum):
    HAWLEY = "HAWLEY"
    CLEAR = "CLEAR"
    FIXED = "FIXED"


# --- Entity TypedDicts (all common_fields: true) -----------------------------

class FamilyAccount(TypedDict):
    id: str
    family_name: str
    billing_email: str
    guardian_user_id: str
    discount_tier_pct: float
    active_plan_count: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    family_account_id: str
    full_name: str
    date_of_birth: str
    is_minor: bool
    records_complete: bool
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    provider_user_id: str
    full_name: str
    npi: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Chair(TypedDict):
    id: str
    label: str
    turnover_buffer_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class GrowthRecord(TypedDict):
    id: str
    patient_id: str
    record_type: str
    taken_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    patient_id: str
    carrier_name: str
    ortho_rider: bool
    ortho_coverage_pct: float
    lifetime_max_cents: int
    remaining_max_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict):
    id: str
    patient_id: str
    policy_id: Optional[str]
    modality: str
    planned_visit_interval_weeks: int
    gross_fee_cents: int
    discount_pct_applied: float
    net_fee_cents: int
    estimated_insurance_benefit_cents: int
    estimated_patient_responsibility_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TreatmentPhase(TypedDict):
    id: str
    plan_id: str
    sequence_no: int
    label: str
    phase_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    plan_id: str
    expected_plan_version: int
    down_payment_cents: int
    term_months: int
    autopay_enabled: bool
    financed_amount_cents: int
    balance_remaining_cents: int
    billing_status: str
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    contract_id: str
    sequence_no: int
    due_at: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    contract_id: str
    installment_id: Optional[str]
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    policy_id: str
    plan_id: str
    billed_amount_cents: int
    benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    provider_id: str
    chair_id: str
    plan_id: Optional[str]
    visit_type: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Retainer(TypedDict):
    id: str
    plan_id: str
    retainer_type: str
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
