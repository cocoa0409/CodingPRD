"""Domain types: entity TypedDicts, status enums, role enum.

All types derived from the Restitution & Court-Fee Collection PRD.
Every top-level resource carries id, created_at, updated_at, version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    COLLECTIONS_CLERK = "CollectionsClerk"
    COLLECTIONS_SUPERVISOR = "CollectionsSupervisor"
    FINANCE_OFFICER = "FinanceOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


# --- Status enums ---
class CaseStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"


class DelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class ObligationType(str, Enum):
    RESTITUTION = "RESTITUTION"
    COURT_FEE = "COURT_FEE"
    FINE = "FINE"
    SURCHARGE = "SURCHARGE"


class ObligationStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class AbilityToPayMethod(str, Enum):
    NET_DISPOSABLE = "NET_DISPOSABLE"
    GROSS_INCOME = "GROSS_INCOME"


class AllocationMethod(str, Enum):
    STATUTORY_PRIORITY = "STATUTORY_PRIORITY"
    PRO_RATA = "PRO_RATA"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    VOIDED = "VOIDED"


class WageAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EnforcementActionType(str, Enum):
    CIVIL_JUDGMENT = "CIVIL_JUDGMENT"
    LICENSE_HOLD = "LICENSE_HOLD"


class EnforcementActionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class WaiverRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --- Entity TypedDicts (all common_fields: true) ---
class Case(TypedDict):
    id: str
    case_number: str
    defendant_name: str
    status: str
    delinquency_status: str
    total_assessed_cents: int
    total_paid_cents: int
    total_waived_cents: int
    total_written_off_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Victim(TypedDict):
    id: str
    name: str
    payable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Obligation(TypedDict):
    id: str
    case_id: str
    victim_id: Optional[str]
    obligation_type: str
    assessed_amount_cents: int
    priority_rank: int
    paid_amount_cents: int
    waived_amount_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    case_id: str
    monthly_income_cents: int
    monthly_expenses_cents: int
    ability_to_pay_method: str
    monthly_amount_cents: int
    next_due_date: Optional[str]
    missed_payment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    obligation_id: str
    amount_cents: int


class Payment(TypedDict):
    id: str
    case_id: str
    amount_cents: int
    allocation_method: str
    allocations: List[Allocation]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    victim_id: str
    case_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WageAssignment(TypedDict):
    id: str
    case_id: str
    employer_name: str
    monthly_withhold_cents: int
    effective_start_date: str
    effective_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    case_id: str
    type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaiverRequest(TypedDict):
    id: str
    case_id: str
    obligation_id: str
    requested_amount_cents: int
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmnestyProgram(TypedDict):
    id: str
    name: str
    start_date: str
    end_date: str
    waiver_pct: float
    created_at: str
    updated_at: str
    version: int
