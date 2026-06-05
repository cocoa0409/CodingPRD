"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API expose the full id / created_at / updated_at / version
quartet (PRD §2.4: "There are no immutable-after-creation entities here").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FNOL_SUBMITTED = "FNOL_SUBMITTED"
    COVERAGE_VERIFIED = "COVERAGE_VERIFIED"
    COVERAGE_DENIED = "COVERAGE_DENIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REPAIR_APPROVED = "REPAIR_APPROVED"
    TOTAL_LOSS = "TOTAL_LOSS"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ClaimDisposition(str, Enum):
    REPAIR = "REPAIR"
    TOTAL_LOSS = "TOTAL_LOSS"


class CoverageType(str, Enum):
    COLLISION = "COLLISION"
    COMPREHENSIVE = "COMPREHENSIVE"
    RENTAL = "RENTAL"


class LossType(str, Enum):
    COLLISION = "COLLISION"
    COMPREHENSIVE = "COMPREHENSIVE"


class ComparativeFaultRule(str, Enum):
    PURE = "PURE"
    MODIFIED_50 = "MODIFIED_50"
    MODIFIED_51 = "MODIFIED_51"


class LicenseTier(str, Enum):
    STANDARD = "STANDARD"
    SENIOR = "SENIOR"


class PartyRole(str, Enum):
    INSURED = "INSURED"
    THIRD_PARTY = "THIRD_PARTY"


class CoverageVerificationOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    POLICY_INACTIVE = "POLICY_INACTIVE"
    OUTSIDE_COVERAGE_WINDOW = "OUTSIDE_COVERAGE_WINDOW"
    NO_MATCHING_COVERAGE = "NO_MATCHING_COVERAGE"


class RepairEstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class RentalReimbursementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SubrogationCaseStatus(str, Enum):
    OPEN = "OPEN"
    DEMAND_SENT = "DEMAND_SENT"
    NEGOTIATING = "NEGOTIATING"
    RESOLVED = "RESOLVED"
    CLOSED_NO_RECOVERY = "CLOSED_NO_RECOVERY"


class DisbursementType(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    RENTAL = "RENTAL"
    SUBROGATION_RECOVERY = "SUBROGATION_RECOVERY"


class DisbursementStatus(str, Enum):
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    ClaimsSupervisor = "ClaimsSupervisor"
    ClaimsAdjuster = "ClaimsAdjuster"
    TotalLossAdjuster = "TotalLossAdjuster"
    SubrogationSpecialist = "SubrogationSpecialist"


# ─── Entity TypedDicts (all carry the id/created_at/updated_at/version quartet) ───

class Policy(TypedDict):
    id: str
    policyholder_name: str
    policy_number: str
    status: str
    effective_date: str
    expiration_date: str
    comparative_fault_rule: str
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    policy_id: str
    coverage_type: str
    limit_cents: int
    deductible_cents: int
    rental_daily_cap_cents: int
    rental_max_days: int
    created_at: str
    updated_at: str
    version: int


class Adjuster(TypedDict):
    id: str
    full_name: str
    license_tier: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    assigned_adjuster_id: Optional[str]
    loss_datetime: str
    loss_type: str
    vehicle_acv_cents: int
    insured_fault_pct: int
    status: str
    disposition: Optional[str]
    settlement_cents: int
    salvage_value_cents: int
    total_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class ClaimParty(TypedDict):
    id: str
    claim_id: str
    party_role: str
    display_name: str
    fault_pct: int
    at_fault_carrier_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageVerification(TypedDict):
    id: str
    claim_id: str
    matched_coverage_type: Optional[str]
    outcome: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairEstimate(TypedDict):
    id: str
    claim_id: str
    authored_by_adjuster_id: str
    lines: List[dict]
    repair_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TotalLossEvaluation(TypedDict):
    id: str
    claim_id: str
    evaluated_by_adjuster_id: str
    acv_cents: int
    repair_total_cents: int
    total_loss_ratio: float
    is_total_loss: bool
    salvage_retained_by_insurer: bool
    created_at: str
    updated_at: str
    version: int


class RentalReimbursement(TypedDict):
    id: str
    claim_id: str
    rental_start_date: str
    rental_end_date: str
    daily_rate_cents: int
    reimbursable_days: int
    reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubrogationCase(TypedDict):
    id: str
    claim_id: str
    target_party_id: str
    demand_cents: int
    recoverable_cents: int
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    claim_id: str
    disbursement_type: str
    amount_cents: int
    source_entity_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
