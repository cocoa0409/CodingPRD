"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FIDUCIARY_MANAGER = "FiduciaryManager"
    BILL_PAY_SPECIALIST = "BillPaySpecialist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CARE_COORDINATOR = "CareCoordinator"
    CLIENT = "Client"
    FAMILY_RECIPIENT = "FamilyRecipient"


class ClientStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CapacityDetermination(str, Enum):
    NOT_DETERMINED = "NOT_DETERMINED"
    RETAINS_CAPACITY = "RETAINS_CAPACITY"
    DIMINISHED_CAPACITY = "DIMINISHED_CAPACITY"
    LACKS_CAPACITY = "LACKS_CAPACITY"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class ScopeTier(str, Enum):
    LIMITED_BILLPAY = "LIMITED_BILLPAY"
    FULL_AGENCY = "FULL_AGENCY"
    REP_PAYEE = "REP_PAYEE"


class AccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    REP_PAYEE_TRUST = "REP_PAYEE_TRUST"


class FraudPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    FROZEN = "FROZEN"


class PayeeType(str, Enum):
    RECURRING_BILLER = "RECURRING_BILLER"
    ESSENTIAL = "ESSENTIAL"
    DISCRETIONARY = "DISCRETIONARY"


class PayeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class VarianceDirection(str, Enum):
    UNDER = "UNDER"
    EXACT = "EXACT"
    OVER = "OVER"


class BondStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    SUPERSEDED = "SUPERSEDED"


class PaymentChannel(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    BILLER_DIRECT = "BILLER_DIRECT"


class ApprovalStatus(str, Enum):
    PREPARED = "PREPARED"
    PENDING_SECOND_APPROVAL = "PENDING_SECOND_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_FLIGHT = "IN_FLIGHT"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"


class DisputeReasonCode(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    WRONG_AMOUNT = "WRONG_AMOUNT"
    GOODS_NOT_RECEIVED = "GOODS_NOT_RECEIVED"
    SCAM_INDUCED = "SCAM_INDUCED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    PROVISIONAL_CREDITED = "PROVISIONAL_CREDITED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    LOCKED = "LOCKED"


class MatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"
    RESOLVED_MATCHED = "RESOLVED_MATCHED"
    RESOLVED_WRITTEN_OFF = "RESOLVED_WRITTEN_OFF"


class LedgerEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    DISBURSEMENT = "DISBURSEMENT"
    SERVICE_FEE = "SERVICE_FEE"
    STOP_PAYMENT_FEE = "STOP_PAYMENT_FEE"
    RETURN_REVERSAL = "RETURN_REVERSAL"
    NSF_FEE = "NSF_FEE"
    DISPUTE_PROVISIONAL_CREDIT = "DISPUTE_PROVISIONAL_CREDIT"
    DISPUTE_CREDIT_REVERSAL = "DISPUTE_CREDIT_REVERSAL"
    BENEFIT_AWARD = "BENEFIT_AWARD"


class FraudReasonCode(str, Enum):
    UNRECOGNIZED_PAYEE = "UNRECOGNIZED_PAYEE"
    AMOUNT_ANOMALY = "AMOUNT_ANOMALY"
    CHANNEL_ANOMALY = "CHANNEL_ANOMALY"
    THIRD_PARTY_REPORT = "THIRD_PARTY_REPORT"


class FraudAlertStatus(str, Enum):
    NEW = "NEW"
    ESCALATED = "ESCALATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    DISMISSED = "DISMISSED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BenefitProgram(str, Enum):
    SSI = "SSI"
    MEDICAID = "MEDICAID"
    SNAP = "SNAP"
    LIHEAP = "LIHEAP"


class ResourceItemType(str, Enum):
    HOME = "HOME"
    VEHICLE = "VEHICLE"
    BURIAL_FUND = "BURIAL_FUND"
    RETIREMENT = "RETIREMENT"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    CASH = "CASH"


class BenefitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class Relationship(str, Enum):
    CHILD = "CHILD"
    SPOUSE = "SPOUSE"
    SIBLING = "SIBLING"
    OTHER_RELATIVE = "OTHER_RELATIVE"
    TRUSTED_FRIEND = "TRUSTED_FRIEND"


class DisclosureCategory(str, Enum):
    BILL_PAY = "BILL_PAY"
    BUDGET = "BUDGET"
    BENEFITS = "BENEFITS"
    FRAUD = "FRAUD"
    CARE_TEAM = "CARE_TEAM"
    BALANCES = "BALANCES"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CoordinationTier(str, Enum):
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"
    INFORMATIONAL = "INFORMATIONAL"


class CoordinationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"


class AuditOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"


# --- entity shapes ---------------------------------------------------------
# Resources that carry id + created_at + updated_at + version.


class Client(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    intake_reference: str
    status: str
    capacity_determination: str
    capacity_determined_on: Optional[str]
    activated_on: Optional[str]
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    client_id: str
    scope_tier: str
    instrument_reference: str
    effective_date: str
    expiry_date: str
    status: str
    executed_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    cascaded_payments_cancelled: int
    cascaded_recipients_terminated: int
    cascaded_applications_withdrawn: int
    created_at: str
    updated_at: str
    version: int


class ClientAccount(TypedDict):
    id: str
    client_id: str
    institution_name: str
    account_label: str
    account_type: str
    opening_balance_cents: int
    cleared_balance_cents: int
    pending_holds_cents: int
    committed_disbursements_cents: int
    available_balance_cents: int
    fraud_posture: str
    fraud_posture_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payee(TypedDict):
    id: str
    client_id: str
    payee_name: str
    payee_type: str
    remittance_reference: str
    status: str
    blocked_reason: Optional[str]
    settled_payment_count: int
    created_at: str
    updated_at: str
    version: int


class BudgetCategory(TypedDict):
    id: str
    client_id: str
    category_name: str
    budget_month: str
    allocation_cents: int
    override_granted_cents: int
    override_count: int
    last_override_reason: Optional[str]
    committed_cents: int
    settled_cents: int
    remaining_cents: int
    variance_full_cents: int
    variance_ptd_cents: int
    variance_direction: str
    created_at: str
    updated_at: str
    version: int


class SuretyBond(TypedDict):
    id: str
    carrier_name: str
    bond_number: str
    coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    exposure_committed_cents: int
    exposure_settled_inclusive_cents: int
    headroom_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    account_id: str
    payee_id: str
    authorization_id: str
    budget_category_id: str
    amount_cents: int
    channel: str
    memo: Optional[str]
    requested_send_date: Optional[str]
    duplicate_override: bool
    service_fee_cents: int
    total_charge_cents: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    approval_status: str
    settlement_status: str
    projected_settlement_date: str
    effective_settlement_date: Optional[str]
    released_at: Optional[str]
    settled_on: Optional[str]
    revision_count: int
    return_reason: Optional[str]
    stop_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    payment_id: str
    reason_code: str
    disputed_amount_cents: int
    filed_on: str
    days_since_settlement: int
    provisional_credit_cents: int
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationPeriod(TypedDict):
    id: str
    account_id: str
    period_month: str
    status: str
    imported_line_count: int
    open_exception_count: int
    unreconciled_entry_count: int
    closed_at: Optional[str]
    reopen_count: int
    has_retro_adjustment: bool
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict):
    id: str
    period_id: str
    external_ref: str
    amount_cents: int
    line_date: str
    line_description: Optional[str]
    match_status: str
    matched_ledger_entry_id: Optional[str]
    exception_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudAlert(TypedDict):
    id: str
    account_id: str
    payment_id: str
    reason_code: str
    detail: Optional[str]
    intake_risk_score: int
    intake_risk_band: str
    review_risk_score: Optional[int]
    review_risk_band: Optional[str]
    ack_due_at: str
    acknowledged_at: Optional[str]
    status: str
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitApplication(TypedDict):
    id: str
    client_id: str
    authorization_id: str
    program: str
    asserted_monthly_income_cents: int
    resource_items: List[Dict[str, Any]]
    countable_resources_gross_cents: int
    countable_resources_net_cents: int
    status: str
    appeal_count: int
    submitted_on: Optional[str]
    decision_date: Optional[str]
    award_effective_date: Optional[str]
    award_monthly_amount_cents: Optional[int]
    retro_months: int
    retro_award_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FamilyRecipient(TypedDict):
    id: str
    client_id: str
    authorization_id: str
    full_name: str
    contact_email: str
    relationship: str
    permitted_categories: List[str]
    subscription_status: str
    consent_recorded_by_role: Optional[str]
    consent_recorded_at: Optional[str]
    report_count: int
    created_at: str
    updated_at: str
    version: int


class CoordinationRequest(TypedDict):
    id: str
    client_id: str
    subject: str
    tier: str
    assigned_member_user_id: str
    ack_due_at: str
    acknowledged_at: Optional[str]
    reroute_count: int
    status: str
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- immutable resources: id + created_at only -----------------------------


class LedgerEntry(TypedDict):
    id: str
    account_id: str
    period_id: Optional[str]
    source_payment_id: Optional[str]
    entry_type: str
    amount_cents: int
    entry_date: str
    retro_period_month: Optional[str]
    memo: Optional[str]
    frozen: bool
    created_at: str


class FamilyReport(TypedDict):
    id: str
    recipient_id: str
    report_month: str
    requested_categories: List[str]
    included_categories: List[str]
    withheld_categories: List[str]
    is_provisional: bool
    total_disbursed_cents: int
    closing_available_balance_cents: int
    generated_at: str
    created_at: str


class AuditEntry(TypedDict):
    id: str
    client_id: Optional[str]
    actor_role: str
    actor_user_id: str
    operation: str
    subject_entity: str
    subject_id: Optional[str]
    outcome: str
    error_id: Optional[str]
    disclosure_category: str
    recorded_at: str
    created_at: str


IMMUTABLE_ENTITIES = ("LedgerEntry", "FamilyReport", "AuditEntry")
