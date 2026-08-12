"""Domain types: entity field shapes, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class MemberStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISENROLLED = "DISENROLLED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class PrescriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class MenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MenuCycleStatus(str, Enum):
    PLANNED = "PLANNED"
    FROZEN = "FROZEN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ComplianceStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    PASSED = "PASSED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SPOILED = "SPOILED"


class ColdChainStatus(str, Enum):
    INTACT = "INTACT"
    EXCURSION = "EXCURSION"
    SPOILED = "SPOILED"


class ReauthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class PayerType(str, Enum):
    MEDICAID_WAIVER = "MEDICAID_WAIVER"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"


class DietType(str, Enum):
    RENAL = "RENAL"
    DIABETIC = "DIABETIC"
    RENAL_DIABETIC = "RENAL_DIABETIC"
    CARDIAC = "CARDIAC"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    CARE_COORDINATOR = "CareCoordinator"
    REFERRING_PROVIDER = "ReferringProvider"
    DIETITIAN = "Dietitian"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    DRIVER = "Driver"
    BILLING_SPECIALIST = "BillingSpecialist"
    PAYER_REVIEWER = "PayerReviewer"
    MEMBER = "Member"


# --- Entity record shapes -------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Member(TypedDict, total=False):
    id: str
    full_name: str
    payer_type: str
    payer_member_id: str
    allergies: List[str]
    diagnosis_codes: List[str]
    income_fpl_percent: int
    household_size: int
    status: str
    adherence_delivered_pct: float
    adherence_confirmed_pct: float
    oop_accumulator_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    member_id: str
    provider_user_id: str
    diagnosis_codes: List[str]
    referred_diet_type: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DietPrescription(TypedDict, total=False):
    id: str
    member_id: str
    referral_id: str
    supersedes_id: Optional[str]
    dietitian_user_id: str
    diet_type: str
    daily_sodium_mg_max: int
    daily_potassium_mg_max: int
    daily_phosphorus_mg_max: int
    daily_carbs_g_max: int
    daily_protein_g_min: int
    excluded_allergens: List[str]
    meals_per_week: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    name: str
    sodium_mg: int
    potassium_mg: int
    phosphorus_mg: int
    carbs_g: int
    protein_g: int
    allergen_codes: List[str]
    base_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuCycle(TypedDict, total=False):
    id: str
    member_id: str
    prescription_id: str
    week_start_date: str
    status: str
    compliance_status: str
    meals_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only sub-record: carries ONLY id + created_at (PRD §2.5) — no
# updated_at, no version.
class MenuCycleItem(TypedDict, total=False):
    id: str
    menu_cycle_id: str
    menu_item_id: str
    quantity: int
    created_at: str


class DeliveryRoute(TypedDict, total=False):
    id: str
    driver_id: str
    route_date: str
    start_time: str
    end_time: str
    capacity_stops: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    member_id: str
    menu_cycle_id: str
    route_id: str
    authorization_id: str
    service_date: str
    status: str
    cold_chain_status: str
    cumulative_excursion_minutes: int
    delivered_at: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only sub-record: carries ONLY id + created_at (PRD §2.5).
class ColdChainReading(TypedDict, total=False):
    id: str
    delivery_id: str
    recorded_at: str
    temp_celsius: float
    created_at: str


class Reauthorization(TypedDict, total=False):
    id: str
    member_id: str
    authorized_units: int
    used_units: int
    reserved_units: int
    available_units: int
    max_amount_cents: int
    consumed_amount_cents: int
    start_date: str
    end_date: str
    authorization_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeAssessment(TypedDict, total=False):
    id: str
    member_id: str
    dietitian_user_id: str
    assessed_at: str
    weight_kg: float
    hba1c_pct: float
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    menu_cycle_id: str
    authorization_id: str
    payer_type_snapshot: str
    units_delivered: int
    provisional_gross_cents: int
    member_cost_share_cents: int
    plan_liability_cents: int
    remitted_amount_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
