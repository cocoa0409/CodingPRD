"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common system fields id, created_at, updated_at, version.
Every monetary figure is an integer number of cents.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TPA_ADMIN = "TPAAdmin"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    FUND_MANAGER = "FundManager"
    AUDITOR = "Auditor"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class StopLossPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"


class ContractBasis(str, Enum):
    PAID = "PAID"
    INCURRED = "INCURRED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class FundAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"


class CheckRunStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class ReimbursementType(str, Enum):
    SPECIFIC = "SPECIFIC"
    AGGREGATE = "AGGREGATE"


class Plan(TypedDict):
    id: str
    sponsor_name: str
    sponsor_tax_id: str
    plan_year_start: str
    plan_year_end: str
    individual_deductible_cents: int
    oop_max_cents: int
    plan_coinsurance_pct: float
    run_out_days: int
    terminated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    name: str
    tax_id: str
    npi: str
    in_network: bool
    ppo_discount_pct: float
    ytd_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    plan_id: str
    first_name: str
    last_name: str
    coverage_effective_date: str
    coverage_term_date: Optional[str]
    status: str
    deductible_met_cents: int
    oop_met_cents: int
    member_plan_paid_ytd_cents: int
    spec_reimbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class StopLossPolicy(TypedDict):
    id: str
    plan_id: str
    carrier_name: str
    contract_basis: str
    effective_date: str
    expiry_date: str
    specific_deductible_cents: int
    aggregate_attachment_cents: int
    total_specific_reimbursed_cents: int
    total_aggregate_reimbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Laser(TypedDict):
    id: str
    stop_loss_policy_id: str
    member_id: str
    laser_deductible_cents: int
    effective_date: str
    expiry_date: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    member_id: str
    provider_id: str
    service_date: str
    billed_lines: List[dict]
    billed_total_cents: int
    ucr_amount_cents: Optional[int]
    allowed_amount_cents: Optional[int]
    deductible_applied_cents: Optional[int]
    member_coinsurance_cents: Optional[int]
    member_responsibility_cents: Optional[int]
    plan_paid_cents: Optional[int]
    denial_reason: Optional[str]
    pended_by_user_id: Optional[str]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FundAccount(TypedDict):
    id: str
    plan_id: str
    balance_cents: int
    total_deposited_cents: int
    total_disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CheckRun(TypedDict):
    id: str
    fund_account_id: str
    claim_ids: List[str]
    total_amount_cents: int
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StopLossReimbursement(TypedDict):
    id: str
    stop_loss_policy_id: str
    claim_id: Optional[str]
    member_id: Optional[str]
    reimbursement_type: str
    amount_cents: int
    basis_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Form1099(TypedDict):
    id: str
    provider_id: str
    tax_year: int
    total_paid_cents: int
    reportable: bool
    created_at: str
    updated_at: str
    version: int
