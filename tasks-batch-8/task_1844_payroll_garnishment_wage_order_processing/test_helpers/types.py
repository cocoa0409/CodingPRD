"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    EMPLOYER_PAYROLL_ADMIN = "employer_payroll_admin"
    PAYROLL_SPECIALIST = "payroll_specialist"
    PAYROLL_MANAGER = "payroll_manager"
    COMPLIANCE_AUDITOR = "compliance_auditor"


class RemittanceTiming(str, Enum):
    SAME_DAY = "SAME_DAY"
    NEXT_BUSINESS_DAY = "NEXT_BUSINESS_DAY"
    THREE_BUSINESS_DAYS = "THREE_BUSINESS_DAYS"


class AdminFeePolicy(str, Enum):
    NONE = "NONE"
    PER_ORDER = "PER_ORDER"


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"


class AuthorityType(str, Enum):
    COURT = "COURT"
    CHILD_SUPPORT_AGENCY = "CHILD_SUPPORT_AGENCY"
    FEDERAL_AGENCY = "FEDERAL_AGENCY"
    STATE_AGENCY = "STATE_AGENCY"


class OrderType(str, Enum):
    CHILD_SUPPORT = "CHILD_SUPPORT"
    FEDERAL_TAX_LEVY = "FEDERAL_TAX_LEVY"
    STUDENT_LOAN = "STUDENT_LOAN"
    CREDITOR = "CREDITOR"


class AmountModel(str, Enum):
    PERCENT_OF_DISPOSABLE = "PERCENT_OF_DISPOSABLE"
    FIXED_AMOUNT_PER_PERIOD = "FIXED_AMOUNT_PER_PERIOD"
    LUMP_SUM_BALANCE = "LUMP_SUM_BALANCE"


class OrderProcessingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    EMPLOYEE_NOTIFIED = "EMPLOYEE_NOTIFIED"
    ACTIVE = "ACTIVE"
    ANSWER_FILED = "ANSWER_FILED"
    SUSPENDED = "SUSPENDED"
    SATISFIED = "SATISFIED"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class RemitPosture(str, Enum):
    REMITTING = "REMITTING"
    HELD = "HELD"
    CLOSED = "CLOSED"


class HoldReason(str, Enum):
    REFUND_PENDING = "REFUND_PENDING"
    DISPUTED = "DISPUTED"


class PayrollRunStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOIDED = "VOIDED"


class RemittanceStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    LATE_CONFIRMED = "LATE_CONFIRMED"
    CANCELLED = "CANCELLED"


class WithholdingEventType(str, Enum):
    WITHHOLD = "WITHHOLD"
    REFUND = "REFUND"


class WithholdingBasis(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"
    CAPPED_BY_STATE = "CAPPED_BY_STATE"
    CAPPED_BY_POOL = "CAPPED_BY_POOL"
    CAPPED_BY_BALANCE = "CAPPED_BY_BALANCE"
    FINAL_PARTIAL = "FINAL_PARTIAL"
    BLOCKED_BY_SUPPORT = "BLOCKED_BY_SUPPORT"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# StateRule, WithholdingEvent, AuditLogEntry are leaner: only id + created_at.


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    remittance_timing: str
    payroll_calendar: Dict[str, Any]
    administrative_fee_policy: str
    admin_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employer_id: str
    full_name: str
    work_state_code: str
    pay_frequency: str
    hourly_rate_cents: int
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict, total=False):
    id: str
    employer_id: str
    period_start: str
    period_end: str
    pay_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayStatement(TypedDict, total=False):
    id: str
    payroll_run_id: str
    employer_id: str
    employee_id: str
    gross_earnings_cents: int
    mandatory_deductions_cents: int
    hours_worked: Optional[float]
    disposable_earnings_cents: int
    total_withheld_cents: int
    total_admin_fee_cents: int
    net_pay_cents: int
    computation_breakdown: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class IssuingAuthority(TypedDict, total=False):
    id: str
    name: str
    authority_type: str
    state_code: str
    accepted_case_number_pattern: str
    created_at: str
    updated_at: str
    version: int


class GarnishmentOrder(TypedDict, total=False):
    id: str
    employee_id: str
    employer_id: str
    issuing_authority_id: str
    case_number: str
    order_type: str
    amount_model: str
    amount_value: int
    total_balance_cents: int
    remaining_balance_cents: int
    withheld_cents: int
    refunded_cents: int
    effective_date: str
    received_at: str
    answer_due_date: str
    notification_due_at: str
    notification_sent_at: Optional[str]
    processing_status: str
    remit_posture: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    employer_id: str
    authority_id: str
    payroll_run_id: str
    amount_due_cents: int
    status: str
    due_date: str
    confirmed_at: Optional[str]
    member_event_ids: List[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — configuration, immutable; carries ONLY id + created_at
class StateRule(TypedDict, total=False):
    id: str
    state_code: str
    caps: Dict[str, float]
    min_wage_multiplier: float
    hourly_floor_cents: int
    fee_deductible_from_wages: bool
    created_at: str


# common_fields: false — append-only ledger; carries ONLY id + created_at
class WithholdingEvent(TypedDict, total=False):
    id: str
    garnishment_order_id: str
    employer_id: str
    payroll_run_id: str
    pay_statement_id: str
    event_type: str
    amount_cents: int
    computation_proof: Dict[str, Any]
    created_logical_at: str
    created_at: str


# common_fields: false — append-only audit record; carries ONLY id + created_at
class AuditLogEntry(TypedDict, total=False):
    id: str
    employer_id: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    actor_id: str
    payload_hash: str
    prev_hash: str
    entry_hash: str
    created_at: str
