"""Domain types: entity TypedDicts, status enums, role enum.

All field names and status values follow the Pet Wellness-Plan PRD exactly.
"""
from enum import Enum
from typing import TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    MEMBER = "Member"
    CLINIC_STAFF = "ClinicStaff"
    BILLING_ADMIN = "BillingAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ClinicStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MemberAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"


class EnrolledPetStatus(str, Enum):
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ContractTermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ServiceCreditStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    FORFEITED = "FORFEITED"


class ServiceVisitStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class BillingCycleStatus(str, Enum):
    BILLED = "BILLED"


class PlanChangeRequestStatus(str, Enum):
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


class PlanChangeKind(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class ServiceCode(str, Enum):
    EXAM = "EXAM"
    VACCINE = "VACCINE"
    DENTAL = "DENTAL"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class PlanTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Entities carrying the full common-field set (id, created_at, updated_at,
# version): Plan, PlanService, Clinic, MemberAccount, Membership, EnrolledPet,
# ContractTerm, ServiceCredit, ServiceVisit, BillingCycle, PlanChangeRequest.
#
# ClockState carries only id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------
class Plan(TypedDict):
    id: str
    tier: str
    name: str
    monthly_fee_cents: int
    annual_value_cents: int
    alacarte_discount_pct: float
    enrollment_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanService(TypedDict):
    id: str
    plan_id: str
    service_code: str
    included_quantity: int
    unit_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict):
    id: str
    name: str
    region_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberAccount(TypedDict):
    id: str
    email: str
    full_name: str
    home_clinic_id: str
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_account_id: str
    plan_id: str
    billing_anchor_day: int
    monthly_fee_cents: int
    pet_count: int
    auto_renew: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EnrolledPet(TypedDict):
    id: str
    membership_id: str
    name: str
    species: str
    weight_kg: float
    enrolled_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractTerm(TypedDict):
    id: str
    membership_id: str
    plan_id: str
    term_index: int
    starts_at: str
    ends_at: str
    entitlement_granted_cents: int
    entitlement_consumed_cents: int
    entitlement_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict):
    id: str
    contract_term_id: str
    service_code: str
    granted_quantity: int
    consumed_quantity: int
    unit_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    membership_id: str
    enrolled_pet_id: str
    clinic_id: str
    contract_term_id: str
    service_code: str
    visited_at: str
    covered_by_credit: bool
    charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    membership_id: str
    period_start: str
    period_end: str
    fee_charged_cents: int
    proration_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanChangeRequest(TypedDict):
    id: str
    membership_id: str
    from_plan_id: str
    to_plan_id: str
    change_kind: str
    proration_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
