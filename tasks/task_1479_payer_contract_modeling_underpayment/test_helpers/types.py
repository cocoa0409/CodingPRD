"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CONTRACT_ANALYST = "ContractAnalyst"
    CONTRACT_MANAGER = "ContractManager"
    REVENUE_INTEGRITY_ANALYST = "RevenueIntegrityAnalyst"
    RECOVERY_MANAGER = "RecoveryManager"
    FINANCE_DIRECTOR = "FinanceDirector"
    SYSTEM_ADMIN = "SystemAdmin"
    AUDITOR = "Auditor"


class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID_MCO = "MEDICAID_MCO"
    WORKERS_COMP = "WORKERS_COMP"


class PayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


class ServiceCategory(str, Enum):
    INPATIENT_MEDICAL = "INPATIENT_MEDICAL"
    INPATIENT_SURGICAL = "INPATIENT_SURGICAL"
    OUTPATIENT_SURGERY = "OUTPATIENT_SURGERY"
    EMERGENCY = "EMERGENCY"
    OBSERVATION = "OBSERVATION"
    IMAGING = "IMAGING"
    LAB = "LAB"


class RateModel(str, Enum):
    PER_DIEM = "PER_DIEM"
    CASE_RATE = "CASE_RATE"
    PERCENT_OF_CHARGE = "PERCENT_OF_CHARGE"
    DRG_BASE = "DRG_BASE"


class CarveType(str, Enum):
    IMPLANT = "IMPLANT"
    HIGH_COST_DRUG = "HIGH_COST_DRUG"
    TRANSPLANT = "TRANSPLANT"
    NICU = "NICU"


class CarveRateModel(str, Enum):
    PERCENT_OF_CHARGE = "PERCENT_OF_CHARGE"
    INVOICE_COST_PLUS = "INVOICE_COST_PLUS"


class ProvisionType(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    OUTLIER = "OUTLIER"


class EscalatorStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class NetworkAgreementStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFIED = "VERIFIED"
    FLAGGED_SUSPECT = "FLAGGED_SUSPECT"
    RETIRED = "RETIRED"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"
    REPRICED = "REPRICED"


class ClaimRemittanceStatus(str, Enum):
    AWAITING_REMITTANCE = "AWAITING_REMITTANCE"
    REMITTANCE_POSTED = "REMITTANCE_POSTED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    RECONCILED = "RECONCILED"


class NetworkFlag(str, Enum):
    NONE = "NONE"
    WRAP_CONFIRMED = "WRAP_CONFIRMED"
    SILENT_PPO_SUSPECT = "SILENT_PPO_SUSPECT"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class PricingVariant(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    RETROSPECTIVE = "RETROSPECTIVE"


class RemittanceStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class RemittanceSource(str, Enum):
    REMITTANCE_835 = "REMITTANCE_835"
    APPEAL_RECOVERY = "APPEAL_RECOVERY"


class AdjustmentReasonCode(str, Enum):
    CONTRACTUAL = "CONTRACTUAL"
    DENIAL = "DENIAL"
    SILENT_PPO_DISCOUNT = "SILENT_PPO_DISCOUNT"
    APPEAL_RECOVERY = "APPEAL_RECOVERY"
    OTHER = "OTHER"


class CaseStatus(str, Enum):
    QUEUED = "QUEUED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPEAL_L1 = "APPEAL_L1"
    APPEAL_L2 = "APPEAL_L2"
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"
    RECOVERED = "RECOVERED"
    DENIED_FINAL = "DENIED_FINAL"
    WRITTEN_OFF = "WRITTEN_OFF"
    WITHDRAWN = "WITHDRAWN"


CASE_TERMINAL_STATUSES = {"RECOVERED", "DENIED_FINAL", "WRITTEN_OFF", "WITHDRAWN"}


class AppealStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class AppealOutcome(str, Enum):
    PENDING = "PENDING"
    PAID_IN_FULL = "PAID_IN_FULL"
    PARTIAL_PAYMENT = "PARTIAL_PAYMENT"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AppealChannel(str, Enum):
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    FORMAL_APPEAL = "FORMAL_APPEAL"
    MEDIATION = "MEDIATION"
    ARBITRATION = "ARBITRATION"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AlertType(str, Enum):
    TERM_EXPIRING_90 = "TERM_EXPIRING_90"
    TERM_EXPIRING_30 = "TERM_EXPIRING_30"
    TERM_EXPIRED = "TERM_EXPIRED"
    ESCALATOR_UPCOMING = "ESCALATOR_UPCOMING"
    AMENDMENT_EFFECTIVE = "AMENDMENT_EFFECTIVE"


class AlertStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"


# All fifteen resources carry the full quartet id/created_at/updated_at/version (PRD §2.5).


class Payer(TypedDict, total=False):
    id: str
    name: str
    payer_type: str
    appeal_deadline_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayerContract(TypedDict, total=False):
    id: str
    payer_id: str
    contract_code: str
    effective_date: str
    expiration_date: str
    prior_contract_id: Optional[str]
    payment_terms_days: int
    underpayment_threshold_cents: int
    underpayment_threshold_bp: int
    volume_tiers: List[Dict[str, Any]]
    status: str
    open_underpayment_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractTerm(TypedDict, total=False):
    id: str
    contract_id: str
    service_category: str
    rate_model: str
    base_rate_cents: Optional[int]
    percent_of_charge_bp: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CarveOutProvision(TypedDict, total=False):
    id: str
    contract_id: str
    carve_type: str
    revenue_codes: List[str]
    rate_model: str
    percent_bp: Optional[int]
    invoice_markup_bp: Optional[int]
    max_cap_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StopLossProvision(TypedDict, total=False):
    id: str
    contract_id: str
    provision_type: str
    service_category: Optional[str]
    threshold_cents: int
    rate_bp: int
    created_at: str
    updated_at: str
    version: int


class RateEscalator(TypedDict, total=False):
    id: str
    contract_id: str
    effective_date: str
    escalator_bp: int
    applies_to_category: Optional[str]
    compounding: bool
    status: str
    applied_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateAmendment(TypedDict, total=False):
    id: str
    contract_id: str
    supersedes_amendment_id: Optional[str]
    effective_date: str
    retroactive_to_date: Optional[str]
    term_overrides: List[Dict[str, Any]]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NetworkAgreement(TypedDict, total=False):
    id: str
    payer_id: str
    network_name: str
    wrap_rate_bp: int
    precedence_rank: int
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    payer_id: str
    claim_number: str
    patient_account_number: str
    service_category: str
    admission_date: str
    discharge_date: str
    total_billed_charges_cents: int
    drg_weight: Optional[float]
    pricing_status: str
    remittance_status: str
    priced_contract_id: Optional[str]
    network_agreement_id: Optional[str]
    network_flag: str
    pricing_variant: Optional[str]
    expected_reimbursement_cents: Optional[int]
    original_expected_cents: Optional[int]
    paid_amount_cents: Optional[int]
    variance_cents: Optional[int]
    pricing_trace: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    revenue_code: str
    service_date: str
    charge_cents: int
    units: int
    invoice_cost_cents: Optional[int]
    is_carve_out: Optional[bool]
    priced_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    claim_id: str
    appeal_id: Optional[str]
    paid_amount_cents: int
    remittance_date: str
    adjustment_reason_code: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnderpaymentCase(TypedDict, total=False):
    id: str
    claim_id: str
    payer_id: str
    contract_id: Optional[str]
    original_variance_cents: int
    current_outstanding_cents: int
    recovered_to_date_cents: int
    write_off_amount_cents: int
    escalation_level: int
    status: str
    claimed_by_user_id: Optional[str]
    queued_date: str
    appeal_filing_deadline: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    case_id: str
    level: int
    channel: str
    status: str
    outcome: str
    filed_date: Optional[str]
    response_due_date: Optional[str]
    outcome_recorded_date: Optional[str]
    recovered_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractProposal(TypedDict, total=False):
    id: str
    contract_id: str
    round_number: int
    proposed_terms: List[Dict[str, Any]]
    projected_volume_mix: List[Dict[str, Any]]
    modeled_contract_version: Optional[int]
    baseline_same_store_cents: Optional[int]
    delta_same_store_cents: Optional[int]
    baseline_mix_shifted_cents: Optional[int]
    delta_mix_shifted_cents: Optional[int]
    is_stale: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractAlert(TypedDict, total=False):
    id: str
    contract_id: str
    escalator_id: Optional[str]
    amendment_id: Optional[str]
    alert_type: str
    trigger_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
