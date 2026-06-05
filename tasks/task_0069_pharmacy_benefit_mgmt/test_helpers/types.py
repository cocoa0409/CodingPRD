"""Domain types: entity TypedDicts, status enums, role enum (PRD §1-§3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────
class BenefitPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FormularyDrugStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PriorAuthorizationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    EXPIRED = "EXPIRED"


class ClaimAdjudicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    REJECTED = "REJECTED"


class ClaimRebateStatus(str, Enum):
    NONE = "NONE"
    ACCRUED = "ACCRUED"
    CLAWED_BACK = "CLAWED_BACK"


class CopayCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class RebateAccrualStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    CLAWED_BACK = "CLAWED_BACK"


class PharmacyType(str, Enum):
    RETAIL = "RETAIL"
    MAIL_ORDER = "MAIL_ORDER"
    SPECIALTY = "SPECIALTY"


class DrugTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    SPECIALTY = "SPECIALTY"


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    PHARMACIST_REVIEWER = "PharmacistReviewer"
    MEDICAL_DIRECTOR = "MedicalDirector"
    PHARMACY_PROVIDER = "PharmacyProvider"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true — id + created_at + updated_at + version
class BenefitPlan(TypedDict):
    id: str
    name: str
    plan_year: int
    deductible_cents: int
    oop_max_cents: int
    tier_copay_cents: dict
    mail_order_copay_multiplier: float
    specialty_requires_specialty_pharmacy: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FormularyDrug(TypedDict):
    id: str
    plan_id: str
    ndc: str
    drug_name: str
    tier: str
    ingredient_cost_cents: int
    is_specialty: bool
    pa_required: bool
    step_therapy_protocol_id: Optional[str]
    rebate_per_fill_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only reference record: ONLY id + created_at
class StepTherapyProtocol(TypedDict):
    id: str
    plan_id: str
    name: str
    first_line_ndcs: List[str]
    created_at: str


class Member(TypedDict):
    id: str
    plan_id: str
    full_name: str
    deductible_met_cents: int
    oop_met_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    member_id: str
    formulary_drug_id: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    overrides_step_therapy: bool
    status: str
    approved_quantity_remaining: int
    authorized_fills: int
    valid_through_date: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    member_id: str
    formulary_drug_id: str
    copay_card_id: Optional[str]
    days_supply: int
    pharmacy_type: str
    prior_auth_id: Optional[str]
    fill_date: str
    supply_end_date: str
    gross_cost_cents: int
    member_pay_cents: int
    copay_card_paid_cents: int
    plan_paid_cents: int
    adjudication_status: str
    rebate_status: str
    created_at: str
    updated_at: str
    version: int


class CopayCard(TypedDict):
    id: str
    member_id: str
    formulary_drug_id: str
    max_benefit_cents: int
    benefit_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateAgreement(TypedDict):
    id: str
    plan_id: str
    manufacturer_name: str
    clawback_pct: float
    created_at: str
    updated_at: str
    version: int


class RebateAccrual(TypedDict):
    id: str
    claim_id: str
    rebate_agreement_id: str
    accrued_cents: int
    clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
