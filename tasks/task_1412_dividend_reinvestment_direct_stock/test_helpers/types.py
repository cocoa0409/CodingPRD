"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    PARTICIPANT = "Participant"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PricingBasis(str, Enum):
    MARKET_CLOSE = "MARKET_CLOSE"
    FIVE_DAY_AVERAGE = "FIVE_DAY_AVERAGE"


class BasisMethod(str, Enum):
    FIFO = "FIFO"
    AVERAGE_COST = "AVERAGE_COST"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class Election(str, Enum):
    FULL_REINVEST = "FULL_REINVEST"
    PARTIAL_REINVEST = "PARTIAL_REINVEST"
    CASH_ONLY = "CASH_ONLY"


class DividendEventStatus(str, Enum):
    DECLARED = "DECLARED"
    PRICED = "PRICED"
    REINVESTED = "REINVESTED"
    SETTLED = "SETTLED"


class PurchaseWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class PurchaseOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class LedgerEntryType(str, Enum):
    INITIAL = "INITIAL"
    REINVEST = "REINVEST"
    CASH_PAYOUT = "CASH_PAYOUT"
    OCP_PURCHASE = "OCP_PURCHASE"
    FRACTIONAL_SALE = "FRACTIONAL_SALE"
    WHOLE_SHARE_WITHDRAWAL = "WHOLE_SHARE_WITHDRAWAL"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"


class AcquisitionType(str, Enum):
    INITIAL = "INITIAL"
    REINVEST = "REINVEST"
    OCP = "OCP"
    TRANSFER_IN = "TRANSFER_IN"


class FeeType(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    OCP = "OCP"
    SALE = "SALE"
    TRANSFER = "TRANSFER"


class NoticeType(str, Enum):
    MODIFICATION = "MODIFICATION"
    SUSPENSION = "SUSPENSION"
    TERMINATION = "TERMINATION"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    EFFECTIVE = "EFFECTIVE"


class TransferType(str, Enum):
    TRANSFER = "TRANSFER"
    GIFT = "GIFT"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# All entities except ShareLedgerEntry carry id + created_at + updated_at +
# version (PRD common resource properties). ShareLedgerEntry is immutable and
# carries only id + created_at.


class Plan(TypedDict, total=False):
    id: str
    issuer_name: str
    ticker: str
    name: str
    status: str
    discount_pct: float
    pricing_basis: str
    basis_method: str
    ocp_min_cents: int
    ocp_max_cents: int
    ocp_fee_pct: float
    ocp_fee_min_cents: int
    sale_fee_cents: int
    transfer_fee_cents: int
    enrollment_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    fee_waiver_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    participant_id: str
    plan_id: str
    status: str
    election: str
    reinvest_pct: Optional[float]
    share_balance: float
    total_cost_basis_cents: int
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DividendEvent(TypedDict, total=False):
    id: str
    plan_id: str
    amount_per_share_cents: int
    record_date: str
    payable_date: str
    status: str
    closing_price_cents: Optional[int]
    avg5_price_cents: Optional[int]
    reinvestment_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PurchaseWindow(TypedDict, total=False):
    id: str
    plan_id: str
    opens_at: str
    closes_at: str
    price_cents: int
    status: str
    submitted_total_cents: int
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    window_id: str
    enrollment_id: str
    amount_cents: int
    status: str
    settled_shares: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ShareLedgerEntry(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at; no updated_at, no version.
    id: str
    enrollment_id: str
    entry_type: str
    quantity: float
    price_cents: Optional[int]
    cash_cents: Optional[int]
    source_type: str
    source_id: str
    created_at: str


class TaxLot(TypedDict, total=False):
    id: str
    enrollment_id: str
    acquired_at: str
    quantity: float
    remaining_quantity: float
    cost_per_share_cents: int
    total_basis_cents: int
    acquisition_type: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    enrollment_id: str
    fee_type: str
    computed_cents: int
    waived: bool
    waived_reason: Optional[str]
    charged_cents: int
    source_type: str
    source_id: str
    created_at: str
    updated_at: str
    version: int


class PlanNotice(TypedDict, total=False):
    id: str
    plan_id: str
    notice_type: str
    message: str
    effective_at: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferInstruction(TypedDict, total=False):
    id: str
    source_enrollment_id: str
    recipient_enrollment_id: Optional[str]
    transfer_type: str
    quantity: float
    recipient_name: Optional[str]
    recipient_address: Optional[str]
    status: str
    fmv_per_share_cents: Optional[int]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
