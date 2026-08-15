"""Domain types: entity shapes, status enums, and the role enum (PRD §2-§4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    WIRE_OPS_ADMIN = "WireOpsAdmin"
    WIRE_OPERATOR = "WireOperator"
    WIRE_APPROVER = "WireApprover"
    SANCTIONS_SCREENER = "SanctionsScreener"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FRAUD_ANALYST = "FraudAnalyst"
    REPAIR_SPECIALIST = "RepairSpecialist"
    WIRE_INVESTIGATOR = "WireInvestigator"
    BENEFICIARY_BANK = "BeneficiaryBank"
    AUDITOR = "Auditor"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class RiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BusinessDateStatus(str, Enum):
    OPEN = "OPEN"
    CUTOFF_PASSED = "CUTOFF_PASSED"
    CLOSED = "CLOSED"


class WireStatus(str, Enum):
    INITIATED = "INITIATED"
    CALLBACK_PENDING = "CALLBACK_PENDING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RELEASING = "RELEASING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    REPAIR = "REPAIR"
    RECALLED = "RECALLED"


class ScreeningStatus(str, Enum):
    NOT_SCREENED = "NOT_SCREENED"
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    CONFIRMED_HIT = "CONFIRMED_HIT"


class WireMethod(str, Enum):
    FEDWIRE = "Fedwire"
    SWIFT = "SWIFT"
    CHIPS = "CHIPS"


class WirePriority(str, Enum):
    NORMAL = "NORMAL"
    SAME_DAY = "SAME_DAY"


class ChargeMode(str, Enum):
    OUR = "OUR"
    BENEFICIARY_REMUNERATION = "BENEFICIARY_REMUNERATION"


class CallbackStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class CallbackCaseStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class CallbackOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    DENIED = "DENIED"
    UNREACHABLE = "UNREACHABLE"


class HoldReasonCode(str, Enum):
    SANCTIONS_HOLD = "SANCTIONS_HOLD"
    FRAUD_HOLD = "FRAUD_HOLD"
    REPAIR_HOLD = "REPAIR_HOLD"


class ApprovalSequence(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class MatchedList(str, Enum):
    OFAC_SDN = "OFAC_SDN"
    INTERNAL_WATCH = "INTERNAL_WATCH"
    EU_CONSOLIDATED = "EU_CONSOLIDATED"


class SanctionsHitStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED_FALSE_POSITIVE = "RELEASED_FALSE_POSITIVE"
    CONFIRMED = "CONFIRMED"
    ESCALATED = "ESCALATED"


class FraudReasonCode(str, Enum):
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"
    VELOCITY = "VELOCITY"
    MULE_SUSPECT = "MULE_SUSPECT"
    PHISHING = "PHISHING"


class FraudHoldStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    CLEARED = "CLEARED"


class FraudResolution(str, Enum):
    NONE = "NONE"
    CUSTOMER_CONFIRMED = "CUSTOMER_CONFIRMED"
    CUSTOMER_DENIED = "CUSTOMER_DENIED"
    AUTO_LAPSED = "AUTO_LAPSED"


class RecallReason(str, Enum):
    DUPLICATE = "DUPLICATE"
    FRAUD = "FRAUD"
    ERROR_AMOUNT = "ERROR_AMOUNT"
    ERROR_BENEFICIARY = "ERROR_BENEFICIARY"


class RecallStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SENT_TO_BENEFICIARY_BANK = "SENT_TO_BENEFICIARY_BANK"
    BENEFICIARY_RESPONDED = "BENEFICIARY_RESPONDED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class BeneficiaryBankResponse(str, Enum):
    NONE = "NONE"
    FUNDS_RETURNED = "FUNDS_RETURNED"
    FUNDS_DECLINED = "FUNDS_DECLINED"


class FeeKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FeeStatus(str, Enum):
    OPEN = "OPEN"
    BILLED = "BILLED"
    SUPERSEDED = "SUPERSEDED"
    WAIVED = "WAIVED"


class ChargeType(str, Enum):
    OUR = "OUR"
    BENEFICIARY = "BENEFICIARY"
    DEDUCTED_FROM_PRINCIPAL = "DEDUCTED_FROM_PRINCIPAL"


class ChargeSource(str, Enum):
    PROVISIONAL_ESTIMATE = "PROVISIONAL_ESTIMATE"
    ACTUAL_ADVICE = "ACTUAL_ADVICE"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class InvestigationType(str, Enum):
    TRACER = "TRACER"
    NON_RECEIPT = "NON_RECEIPT"
    VALUE_DISPUTE = "VALUE_DISPUTE"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TracerDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


# ---------------------------------------------------------------------------
# Entity shapes. Primary resources carry id/created_at/updated_at/version
# (PRD §2.4); the audit log entry is the deliberate exception (id+created_at).
# ---------------------------------------------------------------------------


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    risk_rating: str
    high_risk_jurisdiction: bool
    status: str
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    customer_id: str
    account_number: str
    currency: str
    status: str
    daily_outgoing_limit_cents: int
    daily_reserved_cents: int
    daily_released_cents: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    customer_id: str
    name: str
    bank_name: str
    account_number: str
    country_code: str
    status: str
    first_used_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BusinessDate(TypedDict, total=False):
    id: str
    business_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WireTransfer(TypedDict, total=False):
    id: str
    ordering_account_id: str
    beneficiary_id: str
    amount_cents: int
    currency: str
    method: str
    priority: str
    charge_mode: str
    purpose: str
    requires_callback: bool
    callback_status: str
    initiated_by: str
    first_approved_by: Optional[str]
    second_approved_by: Optional[str]
    value_date: Optional[str]
    status: str
    screening_status: str
    reservation_active: bool
    risk_score: Optional[int]
    fee_assessed_cents: Optional[int]
    net_principal_cents: Optional[int]
    executed_at: Optional[str]
    hold_reason_code: Optional[str]
    repair_attempts: int
    created_at: str
    updated_at: str
    version: int


class ApprovalRecord(TypedDict, total=False):
    id: str
    wire_id: str
    sequence: str
    approver_user_id: str
    decided_at: str
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class CallbackVerification(TypedDict, total=False):
    id: str
    wire_id: str
    contact_name: Optional[str]
    contact_phone: Optional[str]
    outcome: Optional[str]
    status: str
    opened_at: str
    expires_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanctionsHit(TypedDict, total=False):
    id: str
    wire_id: str
    matched_list: str
    matched_party: str
    match_score: int
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudHold(TypedDict, total=False):
    id: str
    wire_id: str
    reason_code: str
    note: str
    placed_by: str
    status: str
    confirmation_window_hours: int
    expires_at: str
    resolution: str
    created_at: str
    updated_at: str
    version: int


class RecallRequest(TypedDict, total=False):
    id: str
    wire_id: str
    reason: str
    amount_to_recall_cents: int
    status: str
    beneficiary_bank_response: str
    response_due_at: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    wire_id: str
    base_fee_cents: int
    priority_fee_cents: int
    beneficiary_share_cents: int
    correspondent_share_cents: int
    total_fee_cents: int
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrespondentCharge(TypedDict, total=False):
    id: str
    wire_id: str
    correspondent_name: str
    charge_type: str
    amount_cents: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict, total=False):
    id: str
    wire_id: str
    type: str
    note: str
    opened_by: str
    status: str
    max_tracers: int
    tracer_count: int
    created_at: str
    updated_at: str
    version: int


class TracerMessage(TypedDict, total=False):
    id: str
    investigation_id: str
    direction: str
    body: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class AuditLogEntry(TypedDict, total=False):
    # Append-only evidence (PRD §2.4): id + created_at only — no updated_at,
    # no version.
    id: str
    actor_user_id: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str
    wire_id: Optional[str]
    detail: str
    created_at: str
