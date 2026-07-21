"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the PRD's vocabulary for the vehicle-donation charity program.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DONOR = "Donor"
    CHARITY_ADMIN = "CharityAdmin"
    INTAKE_AGENT = "IntakeAgent"
    TITLE_CLERK = "TitleClerk"
    AUCTION_MANAGER = "AuctionManager"
    FINANCE_OFFICER = "FinanceOfficer"
    PROGRAM_ADMIN = "ProgramAdmin"


class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class CharityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DonationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    PICKUP_BLOCKED = "PICKUP_BLOCKED"
    IN_CUSTODY = "IN_CUSTODY"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    ACCRUED = "ACCRUED"
    REMITTED = "REMITTED"
    WITHHELD = "WITHHELD"


class IntakeChannel(str, Enum):
    WEB = "WEB"
    PHONE = "PHONE"
    PARTNER = "PARTNER"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    SALVAGE = "SALVAGE"


class ExceptionType(str, Enum):
    NONE = "NONE"
    MATERIAL_IMPROVEMENT = "MATERIAL_IMPROVEMENT"
    GIFT_TO_NEEDY = "GIFT_TO_NEEDY"
    SIGNIFICANT_USE = "SIGNIFICANT_USE"


class FmvVariant(str, Enum):
    BASE_CONDITION = "BASE_CONDITION"
    POST_INSPECTION = "POST_INSPECTION"


class TitleState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class PickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VenueType(str, Enum):
    AUCTION = "AUCTION"
    SALVAGE = "SALVAGE"
    DIRECT_SALE = "DIRECT_SALE"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LotStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    NO_SALE = "NO_SALE"
    VOIDED = "VOIDED"
    WITHDRAWN = "WITHDRAWN"


class LedgerEntryType(str, Enum):
    PROCEEDS_CREDIT = "PROCEEDS_CREDIT"
    PROGRAM_FEE_DEBIT = "PROGRAM_FEE_DEBIT"
    TOW_COST_DEBIT = "TOW_COST_DEBIT"
    ADMIN_FEE_DEBIT = "ADMIN_FEE_DEBIT"
    REVERSAL = "REVERSAL"
    REMITTANCE_SETTLEMENT = "REMITTANCE_SETTLEMENT"
    CHARITY_FEE_DEBIT = "CHARITY_FEE_DEBIT"


class LedgerDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class ReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class FormType(str, Enum):
    FORM_1098C_BOX_4A = "FORM_1098C_BOX_4A"
    FORM_1098C_BOX_4B = "FORM_1098C_BOX_4B"
    ACKNOWLEDGMENT_ONLY = "ACKNOWLEDGMENT_ONLY"


class ValuationVariant(str, Enum):
    GROSS_PROCEEDS = "GROSS_PROCEEDS"
    FMV_FULL = "FMV_FULL"
    FMV_SAFE_HARBOR = "FMV_SAFE_HARBOR"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class TaskType(str, Enum):
    RECEIPT_DELIVERY = "RECEIPT_DELIVERY"
    PICKUP_ESCALATION = "PICKUP_ESCALATION"
    TITLE_STALE = "TITLE_STALE"
    REMITTANCE_PENDING = "REMITTANCE_PENDING"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    DONE = "DONE"


# --- Entity shapes -----------------------------------------------------------
# Records carrying id + created_at + updated_at + version.

class Donor(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    status: str
    donation_count: int
    created_at: str
    updated_at: str
    version: int


class CharityAffiliate(TypedDict):
    id: str
    name: str
    ein: str
    state_code: str
    remittance_fee_pct: float
    status: str
    pledged_balance_cents: int
    remitted_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    donor_id: str
    charity_id: str
    intake_channel: str
    declared_condition: str
    pickup_required: bool
    status: str
    payout_status: str
    pickup_attempts: int
    exception_type: str
    fmv_estimate_cents: Optional[int]
    gross_proceeds_cents: int
    program_fee_cents: int
    tow_allowance_cents: int
    net_to_charity_cents: int
    deduction_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    donation_id: str
    vin: str
    year: int
    make: str
    model: str
    base_book_value_cents: int
    odometer_miles: Optional[int]
    condition_grade: Optional[str]
    salvage_flag: bool
    keys_present: bool
    inspected: bool
    fmv_estimate_cents: int
    fmv_variant: str
    created_at: str
    updated_at: str
    version: int


class TitleRecord(TypedDict):
    id: str
    donation_id: str
    title_number: str
    owner_name: str
    lien_holder: Optional[str]
    state: str
    rejection_count: int
    rejection_reason: Optional[str]
    dmv_filing_reference: Optional[str]
    submitted_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TowVendor(TypedDict):
    id: str
    name: str
    service_state_code: str
    hourly_rate_cents: int
    daily_capacity_slots: int
    status: str
    booked_slots_count: int
    created_at: str
    updated_at: str
    version: int


class PickupOrder(TypedDict):
    id: str
    donation_id: str
    tow_vendor_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    attempt_number: int
    actual_pickup_utc: Optional[str]
    actual_tow_cost_cents: int
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesVenue(TypedDict):
    id: str
    name: str
    venue_type: str
    commission_pct: float
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict):
    id: str
    donation_id: str
    venue_id: str
    lot_number: str
    reserve_price_cents: int
    status: str
    listed_at_utc: str
    sale_price_cents: Optional[int]
    sold_at_utc: Optional[str]
    relist_count: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReceipt(TypedDict):
    id: str
    donation_id: str
    form_type: str
    valuation_variant: str
    claimed_amount_cents: int
    status: str
    control_number: Optional[str]
    issued_at_utc: Optional[str]
    issued_by_user_id: Optional[str]
    void_reason: Optional[str]
    reissue_count: int
    created_at: str
    updated_at: str
    version: int


class RemittanceBatch(TypedDict):
    id: str
    charity_id: str
    period_start_utc: str
    period_end_utc: str
    status: str
    donation_count: int
    gross_cents: int
    provisional_fee_cents: int
    fee_cents: int
    net_cents: int
    closed_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    payment_reference: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUpTask(TypedDict):
    id: str
    donation_id: str
    task_type: str
    status: str
    due_utc: str
    assigned_role: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Proceeds ledger entries are immutable journal lines: they carry id and
# created_at only -- no updated_at and no version.
class ProceedsLedgerEntry(TypedDict):
    id: str
    donation_id: Optional[str]
    remittance_batch_id: Optional[str]
    entry_type: str
    direction: str
    amount_cents: int
    memo: str
    created_at: str
