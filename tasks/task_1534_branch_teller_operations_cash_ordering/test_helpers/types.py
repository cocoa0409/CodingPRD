"""Domain types: status enums and role enum (PRD §2.1, §3)."""
from enum import Enum


class UserRole(str, Enum):
    BRANCH_MANAGER = "BranchManager"
    HEAD_TELLER = "HeadTeller"
    TELLER = "Teller"
    AUDITOR = "Auditor"


class BranchStatus(str, Enum):
    OPEN = "OPEN"
    AUDIT_FROZEN = "AUDIT_FROZEN"


class TellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DrawerStatus(str, Enum):
    OPEN = "OPEN"
    COUNTING = "COUNTING"
    BALANCED = "BALANCED"
    OUT_OF_BALANCE = "OUT_OF_BALANCE"
    CLOSED = "CLOSED"


class TransactionType(str, Enum):
    CASH_DEPOSIT = "CASH_DEPOSIT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    CHECK_DEPOSIT = "CHECK_DEPOSIT"
    CASHIERS_CHECK_PURCHASE = "CASHIERS_CHECK_PURCHASE"
    MONEY_ORDER_PURCHASE = "MONEY_ORDER_PURCHASE"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class CashOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class RequestType(str, Enum):
    ISSUE_INSTRUMENT = "ISSUE_INSTRUMENT"
    FEE_WAIVER = "FEE_WAIVER"
    OVER_LIMIT_TRANSACTION = "OVER_LIMIT_TRANSACTION"


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    WAIVED = "WAIVED"


class HoldType(str, Enum):
    STANDARD = "STANDARD"
    LARGE_CHECK = "LARGE_CHECK"


class FilingStatus(str, Enum):
    FILED = "FILED"
    AMENDED = "AMENDED"


class TriggerDirection(str, Enum):
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    BOTH = "BOTH"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class AuditType(str, Enum):
    SCHEDULED = "SCHEDULED"
    SURPRISE = "SURPRISE"


class AuditStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApprovalAction(str, Enum):
    TELLER_REQUEST = "TELLER_REQUEST"
    OVER_SHORT_WAIVER = "OVER_SHORT_WAIVER"
    HOLD_WAIVER = "HOLD_WAIVER"
