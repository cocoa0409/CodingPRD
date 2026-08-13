"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3, §4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    UTILIZATION_REVIEWER = "UtilizationReviewer"
    CLEARANCE_SUPERVISOR = "ClearanceSupervisor"
    SYSTEM_ADMIN = "SystemAdmin"


class SnapshotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PricingMode(str, Enum):
    INSURED = "INSURED"
    UNINSURED_GFE = "UNINSURED_GFE"


class BundlingRule(str, Enum):
    NONE = "NONE"
    MULTIPLE_PROCEDURE_REDUCTION = "MULTIPLE_PROCEDURE_REDUCTION"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PaymentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"


class DepositStatus(str, Enum):
    PLEDGED = "PLEDGED"
    POSTED = "POSTED"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class DepositMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"


class RefundReason(str, Enum):
    SERVICE_CANCELLED = "SERVICE_CANCELLED"
    OVERPAYMENT = "OVERPAYMENT"


class VarianceClassification(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OVER_TOLERANCE = "OVER_TOLERANCE"
    UNDER_TOLERANCE = "UNDER_TOLERANCE"


class VarianceStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"


class EscalationReason(str, Enum):
    HIGH_DOLLAR = "HIGH_DOLLAR"
    AUTH_EXCEPTION = "AUTH_EXCEPTION"
    GFE_DISPUTE = "GFE_DISPUTE"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClearancePosture(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class ChargeItem(TypedDict, total=False):
    id: str
    cpt_code: str
    description: str
    list_price_cents: int
    requires_auth_prior: bool
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict, total=False):
    id: str
    payer_code: str
    payer_name: str
    bundling_rule: str
    reduction_pct: int
    created_at: str
    updated_at: str
    version: int


class ContractRate(TypedDict, total=False):
    id: str
    contract_id: str
    cpt_code: str
    rate_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilitySnapshot(TypedDict, total=False):
    id: str
    patient_id: str
    payer_code: str
    member_id: str
    deductible_total_cents: int
    deductible_met_cents: int
    oop_max_cents: int
    oop_met_cents: int
    coinsurance_pct: int
    verified_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialClearanceCase(TypedDict, total=False):
    id: str
    patient_id: str
    service_date: str
    service_description: str
    status: str
    active_estimate_id: Optional[str]
    auth_required: bool
    auth_satisfied: bool
    required_deposit_cents: int
    deposit_posted_cents: int
    deposit_satisfied: bool
    high_dollar_flag: bool
    escalation_cleared: bool
    clearance_posture: str
    created_at: str
    updated_at: str
    version: int


class EstimateLine(TypedDict, total=False):
    cpt_code: str
    quantity: int
    unit_rate_cents: int
    line_amount_cents: int


class Estimate(TypedDict, total=False):
    id: str
    case_id: str
    eligibility_snapshot_id: Optional[str]
    pricing_mode: str
    revision: int
    lines: List[EstimateLine]
    status: str
    allowed_amount_cents: int
    deductible_applied_cents: int
    coinsurance_cents: int
    patient_responsibility_cents: int
    insurance_pays_cents: int
    gfe_total_cents: int
    gfe_required: bool
    gfe_delivery_deadline: Optional[str]
    presented_at: Optional[str]
    accepted_at: Optional[str]
    first_presented_patient_resp_cents: Optional[int]
    finalized_actual_billed_cents: Optional[int]
    high_dollar_flag: bool
    dispute_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict, total=False):
    id: str
    case_id: str
    payer_code: str
    cpt_codes: List[str]
    status: str
    medical_necessity_met: Optional[bool]
    auth_number: Optional[str]
    valid_from: Optional[str]
    valid_to: Optional[str]
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    seq: int
    due_date: Optional[str]
    amount_cents: int
    paid_cents: int
    status: str


class PaymentPlan(TypedDict, total=False):
    id: str
    case_id: str
    principal_cents: int
    num_installments: int
    installment_amount_cents: int
    installments: List[Installment]
    principal_outstanding_cents: int
    missed_payment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    case_id: str
    amount_cents: int
    method: str
    status: str
    posted_at: Optional[str]
    applied_amount_cents: Optional[int]
    refund_amount_cents: Optional[int]
    refund_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VarianceRecord(TypedDict, total=False):
    id: str
    estimate_id: str
    baseline_first_presented_resp_cents: int
    baseline_last_accepted_resp_cents: int
    actual_billed_cents: int
    variance_vs_first_cents: int
    variance_vs_accepted_cents: int
    variance_pct: float
    classification: str
    dispute_eligible: bool
    status: str
    root_cause: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict, total=False):
    id: str
    case_id: str
    estimate_id: Optional[str]
    reason: str
    trigger_amount_cents: int
    status: str
    opened_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
