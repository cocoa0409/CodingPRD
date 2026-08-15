"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    STADIUM_ADMIN = "StadiumAdmin"
    PREMIUM_SALES_REP = "PremiumSalesRep"
    FINANCE_CONTROLLER = "FinanceController"
    EVENT_SERVICES_MANAGER = "EventServicesManager"
    ACCOUNT_HOLDER = "AccountHolder"


class SuiteTier(str, Enum):
    FOUNDERS = "FOUNDERS"
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    SILVER = "SILVER"


class SuiteStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LICENSED = "LICENSED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SETTLED = "SETTLED"


class EventType(str, Enum):
    REGULAR = "REGULAR"
    RIVALRY = "RIVALRY"
    PLAYOFF = "PLAYOFF"
    CONCERT = "CONCERT"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AccountType(str, Enum):
    CORPORATE = "CORPORATE"
    INDIVIDUAL = "INDIVIDUAL"
    BROKER = "BROKER"


class AccountStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_EXECUTION = "PENDING_EXECUTION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRING = "EXPIRING"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    TRANSFERRED = "TRANSFERRED"
    WITHDRAWN = "WITHDRAWN"


class SuspensionReason(str, Enum):
    ACCOUNT_DEFAULT = "ACCOUNT_DEFAULT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class InvoiceType(str, Enum):
    LICENSE_FEE = "LICENSE_FEE"
    F_B_SHORTFALL = "F_B_SHORTFALL"
    TRANSFER_FEE = "TRANSFER_FEE"
    TERMINATION_FEE = "TERMINATION_FEE"
    RENTAL = "RENTAL"
    ASSESSMENT = "ASSESSMENT"
    MANUAL = "MANUAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CARD = "CARD"
    WIRE = "WIRE"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PackageTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LUXE = "LUXE"


class CateringOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    CANCELLED_LATE = "CANCELLED_LATE"


class CredentialType(str, Enum):
    HOLDER = "HOLDER"
    GUEST = "GUEST"
    VIP = "VIP"


class CredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVATED = "ACTIVATED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RentalStatus(str, Enum):
    QUOTED = "QUOTED"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TransferType(str, Enum):
    SALE_TRANSFER = "SALE_TRANSFER"
    SUBLEASE = "SUBLEASE"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class RenewalOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    REVISED = "REVISED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class AllocationMethod(str, Enum):
    PER_SUITE_EQUAL = "PER_SUITE_EQUAL"
    BY_SEAT = "BY_SEAT"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    LEVIED = "LEVIED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


# --- Entity payloads (all carry the common system fields of PRD §2.5) ---

class Venue(TypedDict, total=False):
    id: str
    name: str
    address: str
    default_catering_cutoff_hours: int
    created_at: str
    updated_at: str
    version: int


class Suite(TypedDict, total=False):
    id: str
    venue_id: str
    suite_code: str
    tier: str
    capacity_seats: int
    base_annual_fee_cents: int
    f_b_minimum_cents: int
    status: str
    current_agreement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict, total=False):
    id: str
    venue_id: str
    label: str
    starts_on: str
    ends_on: str
    renewal_window_opens_on: str
    renewal_window_closes_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    event_type: str
    starts_at: str
    duration_hours: int
    rental_base_price_cents: int
    catering_cutoff_hours: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    legal_name: str
    account_type: str
    tax_id: str
    billing_email: str
    status: str
    credit_standing: str
    balance_due_cents: int
    lifetime_spend_cents: int
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    suite_id: str
    account_id: str
    start_season_id: str
    term_seasons: int
    base_annual_fee_cents: int
    escalator_bp: int
    f_b_minimum_cents: int
    executed_on: Optional[str]
    fee_schedule_cents: Optional[List[int]]
    current_season_index: int
    f_b_accrued_cents_current_season: int
    suspension_reason: Optional[str]
    suspension_count: int
    renewal_agreement_id: Optional[str]
    active_sublease_account_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    description: str
    quantity: int
    unit_price_cents: int


class Invoice(TypedDict, total=False):
    id: str
    account_id: str
    agreement_id: Optional[str]
    rental_id: Optional[str]
    assessment_id: Optional[str]
    season_id: Optional[str]
    invoice_type: str
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    late_fee_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    due_on: str
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    method: str
    allocations: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict, total=False):
    id: str
    event_id: str
    suite_id: str
    agreement_id: Optional[str]
    rental_id: Optional[str]
    package_tier: str
    guest_count: int
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    service_fee_cents: int
    total_cents: int
    accrual_cents: int
    cancel_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessCredential(TypedDict, total=False):
    id: str
    event_id: str
    suite_id: str
    agreement_id: Optional[str]
    rental_id: Optional[str]
    guest_name: str
    guest_email: str
    credential_type: str
    barcode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SingleEventRental(TypedDict, total=False):
    id: str
    event_id: str
    suite_id: str
    account_id: str
    guest_count: int
    quoted_price_cents: int
    deposit_cents: int
    hold_expires_at: Optional[str]
    cancel_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    agreement_id: str
    from_account_id: str
    to_account_id: str
    transfer_type: str
    asking_price_cents: int
    transfer_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict, total=False):
    id: str
    agreement_id: str
    season_id: str
    proposed_fee_cents: int
    proposed_escalator_bp: int
    proposed_term_seasons: int
    response_due_on: str
    round_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    account_id: str
    desired_tier: str
    target_season_id: Optional[str]
    priority_score: float
    offered_suite_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    total_cost_cents: int
    allocation_method: str
    levied_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
