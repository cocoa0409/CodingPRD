"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COLLECTIONS_AGENT = "CollectionsAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRUST_ACCOUNTANT = "TrustAccountant"
    ASSOCIATION_MANAGER = "AssociationManager"


class AccountStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    PAYMENT_PLAN = "PAYMENT_PLAN"
    LIEN = "LIEN"
    FORECLOSURE = "FORECLOSURE"
    BANKRUPTCY = "BANKRUPTCY"
    CHARGED_OFF = "CHARGED_OFF"
    CLOSED = "CLOSED"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ChargeType(str, Enum):
    REGULAR = "REGULAR"
    SPECIAL = "SPECIAL"
    LATE_FEE = "LATE_FEE"
    INTEREST = "INTEREST"
    ATTORNEY_COST = "ATTORNEY_COST"
    FINE = "FINE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class NoticeType(str, Enum):
    VALIDATION = "VALIDATION"
    DEMAND = "DEMAND"
    INTENT_TO_LIEN = "INTENT_TO_LIEN"
    INTENT_TO_FORECLOSE = "INTENT_TO_FORECLOSE"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class PaymentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    BREACHED = "BREACHED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LienStatus(str, Enum):
    RECORDED = "RECORDED"
    STAYED = "STAYED"
    FORECLOSING = "FORECLOSING"
    RELEASED = "RELEASED"


class ForeclosureReferralStatus(str, Enum):
    REFERRED = "REFERRED"
    FILED = "FILED"
    STAYED = "STAYED"
    SALE_COMPLETED = "SALE_COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class BankruptcyChapter(str, Enum):
    CH7 = "CH7"
    CH13 = "CH13"


class BankruptcyStatus(str, Enum):
    FILED = "FILED"
    DISCHARGED = "DISCHARGED"
    DISMISSED = "DISMISSED"


class RemittanceBasis(str, Enum):
    CASH = "CASH"
    NET = "NET"


class RemittanceStatus(str, Enum):
    PENDING = "PENDING"
    REMITTED = "REMITTED"
    VOID = "VOID"


# --- Entity TypedDicts (all entities carry common_fields: true) ---

class Association(TypedDict):
    id: str
    name: str
    state_code: str
    interest_rate_annual_pct: float
    late_fee_cents: int
    management_fee_pct: float
    trust_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    association_id: str
    unit_number: str
    owner_name: str
    status: str
    total_balance_cents: int
    aging: dict
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    account_id: str
    charge_type: str
    amount_cents: int
    due_date: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    received_date: str
    allocations: List[dict]
    unapplied_cents: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Notice(TypedDict):
    id: str
    account_id: str
    notice_type: str
    status: str
    sent_date: Optional[str]
    dispute_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    account_id: str
    total_amount_cents: int
    installment_cents: int
    num_installments: int
    first_due_date: str
    final_due_date: str
    amount_paid_cents: int
    missed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    account_id: str
    recorded_amount_cents: int
    recorded_date: str
    recorded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeclosureReferral(TypedDict):
    id: str
    account_id: str
    lien_id: str
    attorney_name: str
    referred_by_user_id: str
    referred_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BankruptcyCase(TypedDict):
    id: str
    account_id: str
    chapter: str
    case_number: str
    filed_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    association_id: str
    period_start: str
    period_end: str
    basis: str
    gross_amount_cents: int
    management_fee_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
