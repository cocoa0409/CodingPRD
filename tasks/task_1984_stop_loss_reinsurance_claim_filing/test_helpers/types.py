"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_FORCE = "IN_FORCE"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class ContractBasis(str, Enum):
    POLICY_YEAR = "POLICY_YEAR"
    PAID = "PAID"


class LaserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NoticeStatus(str, Enum):
    NONE = "NONE"
    NOTICE_PENDING = "NOTICE_PENDING"
    NOTICE_FILED = "NOTICE_FILED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ClaimType(str, Enum):
    MEDICAL = "MEDICAL"
    RX = "RX"


class AccumulationScope(str, Enum):
    SPECIFIC = "SPECIFIC"
    AGGREGATE = "AGGREGATE"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class FilingScope(str, Enum):
    SPECIFIC = "SPECIFIC"
    AGGREGATE = "AGGREGATE"


class ReimbursementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTED = "POSTED"


class ForecastBasis(str, Enum):
    PURE_EXPERIENCE = "PURE_EXPERIENCE"
    CREDIBILITY_WEIGHTED = "CREDIBILITY_WEIGHTED"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    STOP_LOSS_ANALYST = "StopLossAnalyst"
    CARRIER_REVIEWER = "CarrierReviewer"
    PLAN_ACCOUNTANT = "PlanAccountant"
    CARRIER_AUDITOR = "CarrierAuditor"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---

class Plan(TypedDict):
    id: str
    plan_name: str
    sponsor_tax_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StopLossContract(TypedDict):
    id: str
    plan_id: str
    policy_year_start: str
    policy_year_end: str
    contract_basis: str
    specific_deductible_cents: int
    aggregate_deductible_cents: int
    aggregating_specific_deductible_cents: Optional[int]
    filing_deadline_days: int
    notice_threshold_pct: float
    run_in_days: int
    run_out_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaseredMemberTerm(TypedDict):
    id: str
    contract_id: str
    member_id: str
    lasered_specific_deductible_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    plan_id: str
    member_external_id: str
    date_of_birth: str
    coverage_start: str
    coverage_end: Optional[str]
    notice_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    plan_id: str
    member_id: str
    service_date: str
    paid_date: Optional[str]
    billed_amount_cents: int
    allowed_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    claim_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimAccumulation(TypedDict):
    id: str
    contract_id: str
    member_id: Optional[str]
    scope: str
    accumulated_cents: int
    excess_cents: int
    applicable_deductible_cents: int
    notice_triggered: bool
    created_at: str
    updated_at: str
    version: int


class StopLossFiling(TypedDict):
    id: str
    contract_id: str
    filing_scope: str
    member_id: Optional[str]
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only line items carry ONLY id + created_at
class FilingLineItem(TypedDict):
    id: str
    filing_id: str
    claim_id: str
    eligible_excess_cents: int
    disputed: bool
    created_at: str


class Reimbursement(TypedDict):
    id: str
    filing_id: str
    received_amount_cents: int
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HighCostClaimantForecast(TypedDict):
    id: str
    plan_id: str
    forecast_basis: str
    projected_excess_cents: int
    projected_member_count: int
    computed_at: str
    created_at: str
    updated_at: str
    version: int


class AuditReview(TypedDict):
    id: str
    filing_id: str
    reason: str
    adjustment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
