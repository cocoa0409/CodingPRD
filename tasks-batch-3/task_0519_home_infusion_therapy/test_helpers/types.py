"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at,
and an integer version (PRD 2.4), so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PHARMACIST = "Pharmacist"
    AUTH_SPECIALIST = "AuthSpecialist"
    VISITING_NURSE = "VisitingNurse"
    MEDICAL_DIRECTOR = "MedicalDirector"
    BILLER = "Biller"
    WAREHOUSE_CLERK = "WarehouseClerk"


# --- Status enums ---
class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InfusionOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AUTH = "PENDING_AUTH"
    RELEASED = "RELEASED"
    ON_HOLD = "ON_HOLD"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    COMPLETED = "COMPLETED"


class HoldReason(str, Enum):
    ADVERSE_EVENT = "ADVERSE_EVENT"
    LAB_OVERDUE = "LAB_OVERDUE"


class PriorAuthorizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CompoundStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPOUNDED = "COMPOUNDED"
    DELIVERED = "DELIVERED"
    WASTED = "WASTED"


class PumpStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class SupplyKitStatus(str, Enum):
    PICKING = "PICKING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class NursingVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    ADJUDICATED = "ADJUDICATED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOID = "VOID"


class ClaimVariant(str, Enum):
    ESTIMATE = "ESTIMATE"
    FINAL = "FINAL"


class NurseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"


class TherapyCategory(str, Enum):
    ANTI_INFECTIVE = "ANTI_INFECTIVE"
    AMINOGLYCOSIDE_OR_VANCO = "AMINOGLYCOSIDE_OR_VANCO"
    TPN = "TPN"
    IMMUNE_GLOBULIN = "IMMUNE_GLOBULIN"
    CHEMO = "CHEMO"


# --- Entity TypedDicts (all entities carry common fields) ---
class DrugCatalog(TypedDict):
    id: str
    ndc_code: str
    generic_name: str
    therapy_category: str
    vial_size_mg: int
    awp_per_vial_cents: int
    is_specialty: bool
    requires_trough_lab: bool
    lot_total_vials: int
    on_hand_vials: int
    created_at: str
    updated_at: str
    version: int


class PayerPlan(TypedDict):
    id: str
    plan_code: str
    per_diem_rate_cents: dict
    awp_discount_pct: float
    coinsurance_pct: float
    deductible_remaining_cents: int
    oop_max_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict):
    id: str
    full_name: str
    license_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    service_state: str
    payer_plan_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    patient_id: str
    referring_provider_npi: str
    diagnosis_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InfusionOrder(TypedDict):
    id: str
    referral_id: str
    patient_id: str
    drug_id: str
    route: str
    daily_dose_mg: int
    frequency_per_day: int
    start_date: str
    scheduled_days: int
    administered_days: int
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    order_id: str
    payer_plan_id: str
    requested_units: int
    approved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Compound(TypedDict):
    id: str
    order_id: str
    vials_reserved: int
    pump_id: str
    delivery_at: str
    retrieval_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pump(TypedDict):
    id: str
    asset_tag: str
    model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyKit(TypedDict):
    id: str
    order_id: str
    kit_type: str
    line_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NursingVisit(TypedDict):
    id: str
    order_id: str
    nurse_id: str
    compound_id: Optional[str]
    visit_type: str
    start_at: str
    duration_min: int
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict):
    id: str
    order_id: str
    lab_type: str
    value_num: float
    collected_at: str
    is_critical: bool
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    order_id: str
    visit_id: Optional[str]
    severity_grade: int
    reaction_count: int
    vital_instability: int
    severity_score: int
    reported_by_role: str
    reported_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    order_id: str
    payer_plan_id: str
    expected_order_version: int
    billed_days: int
    per_diem_cents: int
    drug_allowed_cents: int
    allowed_total_cents: int
    patient_responsibility_cents: int
    plan_paid_cents: int
    variant: str
    status: str
    created_at: str
    updated_at: str
    version: int
