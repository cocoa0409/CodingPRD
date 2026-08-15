"""Domain types: entity TypedDicts, status enums, role enum for the rental house API."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    HOUSE_ADMIN = "HouseAdmin"
    WARDROBE_STAFF = "WardrobeStaff"
    RENTER_CONTACT = "RenterContact"
    ACCOUNTANT = "Accountant"


class RenterType(str, Enum):
    THEATRE = "THEATRE"
    FILM = "FILM"
    EVENT = "EVENT"
    INDIVIDUAL = "INDIVIDUAL"


class RenterStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RateCardStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class Period(str, Enum):
    ANCIENT = "ANCIENT"
    MEDIEVAL = "MEDIEVAL"
    RENAISSANCE = "RENAISSANCE"
    REGENCY = "REGENCY"
    VICTORIAN = "VICTORIAN"
    EDWARDIAN = "EDWARDIAN"
    TWENTIES = "TWENTIES"
    FIFTIES = "FIFTIES"
    EIGHTIES = "EIGHTIES"
    CONTEMPORARY = "CONTEMPORARY"
    FANTASY = "FANTASY"


class Category(str, Enum):
    COSTUME = "COSTUME"
    PROP = "PROP"
    SET_DRESSING = "SET_DRESSING"
    WEAPONRY = "WEAPONRY"
    ACCESSORY = "ACCESSORY"


class SizeClass(str, Enum):
    NONE = "NONE"
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    PLUS = "PLUS"


class AlterationPolicy(str, Enum):
    PROHIBITED = "PROHIBITED"
    REVERSIBLE_ONLY = "REVERSIBLE_ONLY"
    TAILORING_ALLOWED = "TAILORING_ALLOWED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACCESSION_PENDING = "DEACCESSION_PENDING"
    DEACCESSIONED = "DEACCESSIONED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT = "OUT"
    CLEANING = "CLEANING"
    REPAIR = "REPAIR"
    AWAITING_DISPOSAL = "AWAITING_DISPOSAL"
    DISPOSED = "DISPOSED"


class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_RUN = "IN_RUN"
    WRAP = "WRAP"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"


class RateVariant(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    LONG_RUN = "LONG_RUN"


class PullListStatus(str, Enum):
    DRAFT = "DRAFT"
    PICKING = "PICKING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    PICKED = "PICKED"
    OUT = "OUT"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class AlterationType(str, Enum):
    HEM = "HEM"
    TAKE_IN = "TAKE_IN"
    LET_OUT = "LET_OUT"
    DYE = "DYE"
    DISTRESS = "DISTRESS"
    TRIM = "TRIM"


class FittingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESTORED = "RESTORED"


class DamageSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    REPAIRABLE = "REPAIRABLE"
    DESTROYED = "DESTROYED"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


class ValuationMethod(str, Enum):
    AGREED_VALUE = "AGREED_VALUE"
    DEPRECIATED_REPLACEMENT = "DEPRECIATED_REPLACEMENT"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_CLEANING = "IN_CLEANING"
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"
    READY = "READY"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CREDITED = "CREDITED"
    VOID = "VOID"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version) ---


class Renter(TypedDict):
    id: str
    name: str
    renter_type: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    renter_id: str
    insurer_name: str
    policy_number: str
    coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    name: str
    long_run_threshold_weeks: int
    long_run_discount_pct: float
    deep_run_threshold_weeks: int
    deep_run_discount_pct: float
    late_fee_daily_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    name: str
    period: str
    category: str
    size_class: str
    alteration_policy: str
    replacement_value_cents: int
    base_daily_rate_cents: int
    base_weekly_rate_cents: int
    status: str
    serviceable_unit_count: int
    created_at: str
    updated_at: str
    version: int


class ItemUnit(TypedDict):
    id: str
    item_id: str
    barcode: str
    condition_grade: str
    acquisition_date: str
    acquisition_cost_cents: int
    status: str
    last_returned_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict):
    id: str
    renter_id: str
    title: str
    rehearsal_start_date: str
    performance_start_date: str
    closing_date: str
    return_by_date: str
    run_weeks: int
    long_run: bool
    rate_card_id: Optional[str]
    rate_card_version: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    production_id: str
    item_id: str
    quantity: int
    window_start_date: str
    window_end_date: str
    rate_variant: str
    quoted_charge_cents: int
    hold_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PullList(TypedDict):
    id: str
    production_id: str
    status: str
    submitted_at: Optional[str]
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PullListLine(TypedDict):
    id: str
    pull_list_id: str
    reservation_id: str
    item_unit_id: str
    status: str
    due_back_date: Optional[str]
    returned_at: Optional[str]
    rental_charge_cents: int
    late_fee_cents: int
    rental_invoiced: bool
    late_fee_invoiced: bool
    created_at: str
    updated_at: str
    version: int


class FittingAuthorization(TypedDict):
    id: str
    pull_list_line_id: str
    alteration_type: str
    notes: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnAssessment(TypedDict):
    id: str
    pull_list_line_id: str
    condition_grade_before: str
    condition_grade_after: str
    damage_severity: str
    restoration_complete: bool
    late_days: int
    assessed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    pull_list_line_id: str
    return_assessment_id: Optional[str]
    claim_type: str
    valuation_method: str
    assessed_value_cents: int
    status: str
    created_by_user_id: str
    posted_by_user_id: Optional[str]
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningTicket(TypedDict):
    id: str
    item_unit_id: str
    status: str
    requires_repair: bool
    repair_done: bool
    queue_depth_at_creation: int
    cleaning_fee_cents: int
    invoiced: bool
    queued_at: str
    ready_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    production_id: str
    status: str
    rental_charges_cents: int
    late_fee_cents: int
    cleaning_charges_cents: int
    damage_charges_cents: int
    total_cents: int
    credited_cents: int
    amount_paid_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int
