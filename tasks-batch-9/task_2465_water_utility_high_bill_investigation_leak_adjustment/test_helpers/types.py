"""Typed vocabulary for the water-utility high-bill service.

String enums mirror the enumerations declared in the PRD so tests can refer to
domain values by name instead of by bare literal, and TypedDicts describe the
shapes that the composite fixtures hand back to tests.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE_REP = "CustomerServiceRep"
    METER_TECHNICIAN = "MeterTechnician"
    BILLING_SUPERVISOR = "BillingSupervisor"
    UTILITY_BOARD_CLERK = "UtilityBoardClerk"
    SYSTEM_ADMIN = "SystemAdmin"


class OpenedByRole(str, Enum):
    CUSTOMER = "CUSTOMER"
    CUSTOMER_SERVICE_REP = "CUSTOMER_SERVICE_REP"


# ---------------------------------------------------------------------------
# Reference data (PRD §2.10, §3.1)
# ---------------------------------------------------------------------------
class Season(str, Enum):
    SUMMER = "SUMMER"
    WINTER = "WINTER"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LOCKED = "LOCKED"


class MeterType(str, Enum):
    POTABLE_MASTER = "POTABLE_MASTER"
    IRRIGATION_SUBMETER = "IRRIGATION_SUBMETER"
    BACKFLOW_FIRE_LINE = "BACKFLOW_FIRE_LINE"


class AccuracyStatus(str, Enum):
    UNTESTED = "UNTESTED"
    VERIFIED_ACCURATE = "VERIFIED_ACCURATE"
    FAILED_FAST = "FAILED_FAST"
    FAILED_SLOW = "FAILED_SLOW"


class ReadType(str, Enum):
    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"
    CORRECTED = "CORRECTED"


# ---------------------------------------------------------------------------
# Billing (PRD §3.2, §3.5)
# ---------------------------------------------------------------------------
class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ADJUSTED = "ADJUSTED"
    UPHELD_AS_BILLED = "UPHELD_AS_BILLED"
    REBILL_PENDING = "REBILL_PENDING"
    REBILLED = "REBILLED"


# ---------------------------------------------------------------------------
# Investigation (PRD §3.3, §3.6)
# ---------------------------------------------------------------------------
class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    EVIDENCE_UNDER_REVIEW = "EVIDENCE_UNDER_REVIEW"
    EVIDENCE_EXHAUSTED = "EVIDENCE_EXHAUSTED"
    DETERMINED = "DETERMINED"
    ADJUSTMENT_PENDING = "ADJUSTMENT_PENDING"
    APPEALED = "APPEALED"
    RESOLVED = "RESOLVED"
    CLOSED_NO_ADJUSTMENT = "CLOSED_NO_ADJUSTMENT"


class LeakDetermination(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    CUSTOMER_SIDE_LEAK = "CUSTOMER_SIDE_LEAK"
    UTILITY_SIDE_LEAK = "UTILITY_SIDE_LEAK"
    METER_ERROR = "METER_ERROR"
    NO_LEAK = "NO_LEAK"
    IRRIGATION_USE = "IRRIGATION_USE"


class LeakType(str, Enum):
    SERVICE_LINE = "SERVICE_LINE"
    UNDERGROUND = "UNDERGROUND"
    TOILET = "TOILET"
    IRRIGATION = "IRRIGATION"
    POOL = "POOL"


class ProofStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Meter testing (PRD §3.4)
# ---------------------------------------------------------------------------
class TestRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FIELD_TEST_SCHEDULED = "FIELD_TEST_SCHEDULED"
    BENCH_TEST_PENDING = "BENCH_TEST_PENDING"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAST = "CLOSED_FAST"
    CLOSED_SLOW = "CLOSED_SLOW"


class TestType(str, Enum):
    FIELD = "FIELD"
    BENCH = "BENCH"


class RequestedByKind(str, Enum):
    CUSTOMER = "CUSTOMER"
    UTILITY = "UTILITY"


class FieldResult(str, Enum):
    PASS = "PASS"
    SUSPECT = "SUSPECT"


class BenchResult(str, Enum):
    PASS = "PASS"
    FAST = "FAST"
    SLOW = "SLOW"


class AccuracyMethod(str, Enum):
    AWWA_WEIGHTED = "AWWA_WEIGHTED"
    SIMPLE_MEAN = "SIMPLE_MEAN"


# ---------------------------------------------------------------------------
# Leak adjustment (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
class AdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class Variant(str, Enum):
    EXCESS_REPRICE = "EXCESS_REPRICE"
    BASELINE_REBILL = "BASELINE_REBILL"


# ---------------------------------------------------------------------------
# Collections (PRD §2.9, §3.8)
# ---------------------------------------------------------------------------
class ArrangementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHUTOFF_SCHEDULED = "SHUTOFF_SCHEDULED"
    SHUTOFF_HELD = "SHUTOFF_HELD"
    SHUTOFF_EXECUTED = "SHUTOFF_EXECUTED"


class CreditStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    IN_ARRANGEMENT = "IN_ARRANGEMENT"
    ARRANGEMENT_DEFAULTED = "ARRANGEMENT_DEFAULTED"


class EntryType(str, Enum):
    CHARGE = "CHARGE"
    CREDIT = "CREDIT"
    PAYMENT = "PAYMENT"
    REVERSAL = "REVERSAL"


class SourceKind(str, Enum):
    BILL_CHARGE = "BILL_CHARGE"
    REBILL_REVERSAL = "REBILL_REVERSAL"
    REBILL_CHARGE = "REBILL_CHARGE"
    LEAK_ADJUSTMENT_CREDIT = "LEAK_ADJUSTMENT_CREDIT"
    LEAK_ADJUSTMENT_ADMIN_FEE = "LEAK_ADJUSTMENT_ADMIN_FEE"
    LEAK_ADJUSTMENT_REVERSAL = "LEAK_ADJUSTMENT_REVERSAL"
    METER_TEST_DEPOSIT = "METER_TEST_DEPOSIT"
    METER_TEST_DEPOSIT_REFUND = "METER_TEST_DEPOSIT_REFUND"
    CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"
    ARRANGEMENT_DOWN_PAYMENT = "ARRANGEMENT_DOWN_PAYMENT"
    ARRANGEMENT_INSTALLMENT = "ARRANGEMENT_INSTALLMENT"


# ---------------------------------------------------------------------------
# Appeals (PRD §3.9)
# ---------------------------------------------------------------------------
class AppealStatus(str, Enum):
    FILED = "FILED"
    SCHEDULED = "SCHEDULED"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"


class AppealDecision(str, Enum):
    UPHOLD = "UPHOLD"
    REVERSE = "REVERSE"
    REMAND = "REMAND"


# ---------------------------------------------------------------------------
# Fixture return shapes
# ---------------------------------------------------------------------------
Json = Dict[str, Any]


class PeriodCalendar(TypedDict):
    """The four SUMMER periods every billing chain is built on."""

    periods: List[Json]
    ids: List[str]
    history_ids: List[str]
    target_id: str
    target: Json


class MeteredAccount(TypedDict):
    """A rate schedule, a period calendar, an account and its master meter."""

    rate_schedule: Json
    rate_schedule_id: str
    calendar: PeriodCalendar
    account: Json
    account_id: str
    account_version: int
    meter: Json
    meter_id: str
    customer_headers: Dict[str, str]


class BaselinedBill(MeteredAccount):
    """A metered account plus three settled history bills and one target bill."""

    history_bills: List[Json]
    history_bill_ids: List[str]
    bill: Json
    bill_id: str
    target_gallons: int
    target_read: Json
    target_read_id: str


class InvestigationCase(BaselinedBill):
    """A baselined bill carrying an open high-bill investigation."""

    investigation: Json
    investigation_id: str
    investigation_version: int
    rep_user_id: str
    rep_headers: Dict[str, str]


class ProofCase(InvestigationCase):
    """An investigation whose repair proof has been verified."""

    proof: Json
    proof_id: str
    proof_leak_type: str


class DeterminedCase(ProofCase):
    """An investigation sitting in DETERMINED with a determination stamp."""

    determination: str
    determination_by_user_id: str


class AdjustmentCase(DeterminedCase):
    """A drafted (and optionally submitted or posted) leak adjustment."""

    adjustment: Json
    adjustment_id: str
    adjustment_status: str


class ArrangementCase(TypedDict):
    """A payment arrangement together with the account and bill it finances."""

    account_id: str
    bill_id: str
    arrangement: Json
    arrangement_id: str
    customer_headers: Dict[str, str]


class AppealCase(DeterminedCase):
    """A board appeal filed against a determined investigation."""

    appeal: Json
    appeal_id: str
    filed_by_user_id: str
    hearing_date: Optional[str]
