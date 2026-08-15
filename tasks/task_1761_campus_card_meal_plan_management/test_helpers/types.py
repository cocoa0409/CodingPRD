"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class HolderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class HolderType(str, Enum):
    STUDENT_RESIDENT = "STUDENT_RESIDENT"
    STUDENT_COMMUTER = "STUDENT_COMMUTER"
    FACULTY = "FACULTY"
    STAFF = "STAFF"
    AFFILIATE = "AFFILIATE"


class HousingStatus(str, Enum):
    ON_CAMPUS = "ON_CAMPUS"
    COMMUTER = "COMMUTER"
    OFF_CAMPUS = "OFF_CAMPUS"


class CardLifecycleStatus(str, Enum):
    PENDING_PHOTO = "PENDING_PHOTO"
    ACTIVE = "ACTIVE"
    LOST_FROZEN = "LOST_FROZEN"
    STOLEN_FROZEN = "STOLEN_FROZEN"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    DEACTIVATED = "DEACTIVATED"


class PhotoStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TermStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class ProrationMode(str, Enum):
    WEEKLY = "WEEKLY"
    DAILY = "DAILY"


class MealPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class ChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class VoidReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    ENROLLMENT_CANCELLED = "ENROLLMENT_CANCELLED"


class AccountType(str, Enum):
    DINING_DOLLARS = "DINING_DOLLARS"
    CAMPUS_CASH = "CAMPUS_CASH"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSE_PENDING = "CLOSE_PENDING"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class FrozenReason(str, Enum):
    CARD_STOLEN = "CARD_STOLEN"
    HOLDER_SUSPENDED = "HOLDER_SUSPENDED"


class LedgerEntryType(str, Enum):
    FUND = "FUND"
    ALLOCATION_GRANT = "ALLOCATION_GRANT"
    PURCHASE = "PURCHASE"
    PURCHASE_REVERSAL = "PURCHASE_REVERSAL"
    FEE = "FEE"
    PRORATION_CREDIT = "PRORATION_CREDIT"
    PRORATION_DEBIT = "PRORATION_DEBIT"
    PROVISIONAL_CREDIT = "PROVISIONAL_CREDIT"
    PROVISIONAL_CLAWBACK = "PROVISIONAL_CLAWBACK"
    ADJUSTMENT_CREDIT = "ADJUSTMENT_CREDIT"
    ADJUSTMENT_DEBIT = "ADJUSTMENT_DEBIT"
    REFUND_PAYOUT = "REFUND_PAYOUT"
    FORFEIT = "FORFEIT"


class TenderType(str, Enum):
    MEAL_SWIPE = "MEAL_SWIPE"
    DINING_DOLLARS = "DINING_DOLLARS"
    CAMPUS_CASH = "CAMPUS_CASH"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DisputeReasonCode(str, Enum):
    UNAUTHORIZED_USE = "UNAUTHORIZED_USE"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    SERVICE_NOT_RECEIVED = "SERVICE_NOT_RECEIVED"


class DisputeStatus(str, Enum):
    OPENED = "OPENED"
    PROVISIONAL_CREDIT_GRANTED = "PROVISIONAL_CREDIT_GRANTED"
    RESOLVED_FOR_CARDHOLDER = "RESOLVED_FOR_CARDHOLDER"
    RESOLVED_FOR_MERCHANT = "RESOLVED_FOR_MERCHANT"
    WITHDRAWN = "WITHDRAWN"


class RefundVariant(str, Enum):
    AUTO_EXCLUDING_PROVISIONAL = "AUTO_EXCLUDING_PROVISIONAL"
    FULL_BALANCE = "FULL_BALANCE"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class SecurityLevel(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class SuspendedReason(str, Enum):
    CARD_FROZEN = "CARD_FROZEN"
    MANUAL = "MANUAL"


class AccessDecision(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DenyReason(str, Enum):
    ZONE_DECOMMISSIONED = "ZONE_DECOMMISSIONED"
    CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"
    CARD_PROVISIONAL = "CARD_PROVISIONAL"
    NO_ACTIVE_GRANT = "NO_ACTIVE_GRANT"
    INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
    OUTSIDE_SCHEDULE = "OUTSIDE_SCHEDULE"


class MerchantCategory(str, Enum):
    RESTAURANT = "RESTAURANT"
    GROCERY = "GROCERY"
    COFFEE = "COFFEE"
    BOOKSTORE = "BOOKSTORE"
    OTHER = "OTHER"


class CommissionMode(str, Enum):
    PER_TRANSACTION = "PER_TRANSACTION"
    AGGREGATE = "AGGREGATE"


class MerchantStatus(str, Enum):
    PENDING_CONTRACT = "PENDING_CONTRACT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CARD_OFFICE_ADMIN = "CardOfficeAdmin"
    CARD_HOLDER = "CardHolder"
    DINING_SERVICES_MANAGER = "DiningServicesManager"
    BURSAR_OFFICE = "BursarOffice"
    FRAUD_ANALYST = "FraudAnalyst"
    SECURITY_OFFICER = "SecurityOfficer"
    MERCHANT_USER = "MerchantUser"
    POINT_OF_SALE = "PointOfSale"
    DOOR_CONTROLLER = "DoorController"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class CardHolder(TypedDict, total=False):
    id: str
    university_id: str
    full_name: str
    email: str
    holder_type: str
    housing_status: str
    status: str
    fraud_strike_count: int
    fraud_flag: bool
    created_at: str
    updated_at: str
    version: int


class CampusCard(TypedDict, total=False):
    id: str
    holder_id: str
    card_number: str
    lifecycle_status: str
    photo_status: str
    is_provisional: bool
    replaced_by_card_id: Optional[str]
    replacement_fee_cents: int
    stolen_police_report_number: Optional[str]
    expires_at: str
    lost_or_stolen_report_count: int
    created_at: str
    updated_at: str
    version: int


class PhotoSubmission(TypedDict, total=False):
    id: str
    card_id: str
    image_ref: str
    review_status: str
    rejection_reason: Optional[str]
    reviewed_by: Optional[str]
    submission_sequence: int
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict, total=False):
    id: str
    term_code: str
    name: str
    start_date: str
    end_date: str
    add_drop_deadline: str
    total_weeks: int
    proration_mode: str
    current_week_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealPlan(TypedDict, total=False):
    id: str
    plan_code: str
    name: str
    weekly_swipe_allowance: int
    is_unlimited_swipes: bool
    dining_dollar_allocation_cents: int
    price_cents: int
    requires_on_campus_housing: bool
    eligible_holder_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MealPlanEnrollment(TypedDict, total=False):
    id: str
    holder_id: str
    plan_id: str
    term_id: str
    supersedes_enrollment_id: Optional[str]
    status: str
    charge_cents: Optional[int]
    credit_cents: int
    weekly_swipe_allowance: int
    is_unlimited_swipes: bool
    swipes_used_this_week: int
    enrolled_week_index: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanChangeRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    new_plan_id: str
    requested_by: str
    status: str
    effective_week_index: int
    charge_delta_cents: Optional[int]
    funding_delta_cents: Optional[int]
    void_reason: Optional[str]
    decided_by: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DecliningBalanceAccount(TypedDict, total=False):
    id: str
    holder_id: str
    account_type: str
    term_id: Optional[str]
    balance_cents: int
    status: str
    frozen_reason: Optional[str]
    last_adjusted_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    account_id: str
    entry_type: str
    amount_cents: int
    description: str
    reference_transaction_id: Optional[str]
    reference_dispute_id: Optional[str]
    entry_sequence: int
    running_balance_cents: int
    created_at: str


class CardTransaction(TypedDict, total=False):
    id: str
    card_id: str
    account_id: Optional[str]
    enrollment_id: Optional[str]
    merchant_id: Optional[str]
    tender_type: str
    amount_cents: int
    idempotency_key: str
    location_description: Optional[str]
    status: str
    pre_dispute_status: Optional[str]
    settled_in_settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    transaction_id: str
    filed_by_holder_id: str
    reason_code: str
    status: str
    provisional_credit_cents: int
    granter_analyst_id: Optional[str]
    resolver_analyst_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    account_id: str
    requested_by_holder_id: str
    refund_variant: str
    amount_cents: int
    status: str
    denial_reason: Optional[str]
    approved_by: Optional[str]
    paid_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DoorZone(TypedDict, total=False):
    id: str
    zone_code: str
    building: str
    security_level: str
    access_windows: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    card_id: str
    zone_id: str
    clearance: str
    valid_from: str
    valid_until: str
    status: str
    suspended_reason: Optional[str]
    granted_by: str
    created_at: str
    updated_at: str
    version: int


class AccessEvent(TypedDict, total=False):
    # Immutable event record: only id + created_at, no updated_at / version.
    id: str
    card_id: str
    zone_id: str
    grant_id: Optional[str]
    decision: str
    deny_reason: Optional[str]
    attempted_at: str
    created_at: str


class Merchant(TypedDict, total=False):
    id: str
    merchant_code: str
    legal_name: str
    category: str
    commission_bps: int
    commission_mode: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MerchantSettlement(TypedDict, total=False):
    id: str
    merchant_id: str
    term_id: str
    period_start: str
    period_end: str
    status: str
    gross_cents: Optional[int]
    commission_cents: Optional[int]
    net_cents: Optional[int]
    transaction_count: Optional[int]
    carried_from_settlement_id: Optional[str]
    submitted_by: Optional[str]
    approved_by: Optional[str]
    paid_by: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
