"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the Private Disability Income Insurance PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    POLICYHOLDER = "Policyholder"
    CLAIMS_ADJUDICATOR = "ClaimsAdjudicator"
    SYSTEM_OPERATOR = "SystemOperator"


# ─── Enums ────────────────────────────────────────────
class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    DECLINE = "DECLINE"


class OccupationDefinition(str, Enum):
    OWN_OCC = "OWN_OCC"
    ANY_OCC = "ANY_OCC"


class PolicyLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class PolicyPremiumStatus(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    DEFAULT = "DEFAULT"


class ClaimedDisabilityType(str, Enum):
    TOTAL = "TOTAL"
    RESIDUAL = "RESIDUAL"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_INFO = "PENDING_INFO"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"
    BENEFIT_EXHAUSTED = "BENEFIT_EXHAUSTED"


class BenefitPeriodStatus(str, Enum):
    ACCRUED = "ACCRUED"
    REVERSED = "REVERSED"


class OffsetSource(str, Enum):
    SSDI = "SSDI"
    WORKERS_COMP = "WORKERS_COMP"


class OffsetAwardStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


# ─── Entity TypedDicts ────────────────────────────────
# All of these entities carry the full common-field set
# (id, created_at, updated_at, version) per PRD §2.5, EXCEPT DisabilityProof.

class Insurer(TypedDict):
    id: str
    name: str
    current_month_index: int
    created_at: str
    updated_at: str
    version: int


class OccupationClass(TypedDict):
    id: str
    insurer_id: str
    code: str
    risk_tier: str
    max_benefit_months: int
    min_elimination_days: int
    own_occ_window_months_cap: int
    created_at: str
    updated_at: str
    version: int


class Policyholder(TypedDict):
    id: str
    insurer_id: str
    full_name: str
    pre_disability_monthly_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    insurer_id: str
    policyholder_id: str
    occupation_class_id: str
    monthly_benefit_cents: int
    benefit_period_months: int
    elimination_period_days: int
    occupation_definition: str
    own_occ_window_months: int
    cola_rider: bool
    cola_annual_rate: float
    lifecycle_status: str
    premium_status: str
    benefit_months_consumed: float
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    insurer_id: str
    policy_id: str
    disability_onset_month: int
    claimed_disability_type: str
    elimination_satisfied_month: int
    own_occ_expiry_month: int
    next_proof_due_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncomeReport(TypedDict):
    id: str
    claim_id: str
    effective_month: int
    current_monthly_income_cents: int
    income_loss_ratio: float
    is_superseded: bool
    created_at: str
    updated_at: str
    version: int


# DisabilityProof is append-only / immutable (PRD §2.5): id + created_at only.
class DisabilityProof(TypedDict):
    id: str
    claim_id: str
    attestation_month: int
    still_disabled: bool
    accepted: bool
    created_at: str


class BenefitPeriod(TypedDict):
    id: str
    claim_id: str
    policy_id: str
    coverage_month: int
    benefit_fraction: float
    gross_benefit_cents: int
    offset_applied_cents: int
    net_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OffsetAward(TypedDict):
    id: str
    claim_id: str
    offset_source: str
    monthly_offset_cents: int
    estimated_offset_cents: int
    final_monthly_offset_cents: int
    effective_offset_cents: int
    start_month: int
    end_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLedger(TypedDict):
    id: str
    claim_id: str
    total_gross_paid_cents: int
    total_net_paid_cents: int
    overpayment_balance_cents: int
    created_at: str
    updated_at: str
    version: int
