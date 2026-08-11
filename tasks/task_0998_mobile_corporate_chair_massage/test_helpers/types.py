"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORGANIZER = "Organizer"
    THERAPIST = "Therapist"


class CorporateAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class WellnessProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class Cadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class TherapistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class TherapistLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULING = "SCHEDULING"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class BookingKind(str, Enum):
    EVENT = "EVENT"
    RECURRING_OCCURRENCE = "RECURRING_OCCURRENCE"


class ChairSlotStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    RELEASED = "RELEASED"


class SlotClaimStatus(str, Enum):
    CLAIMED = "CLAIMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TravelLegStatus(str, Enum):
    PLANNED = "PLANNED"
    REIMBURSED = "REIMBURSED"
    WAIVED = "WAIVED"


class TravelFeeVariant(str, Enum):
    QUOTED = "QUOTED"
    SETTLED = "SETTLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class EntryKind(str, Enum):
    EARNING = "EARNING"
    TRAVEL_REIMBURSEMENT = "TRAVEL_REIMBURSEMENT"
    ADJUSTMENT = "ADJUSTMENT"


# --- Entity TypedDicts (common fields: id, created_at, updated_at, version) ---

class Region(TypedDict):
    id: str
    code: str
    name: str
    base_mileage_rate_cents: int
    travel_included_miles: int
    setup_buffer_minutes: int
    teardown_buffer_minutes: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class CorporateAccount(TypedDict):
    id: str
    company_name: str
    billing_email: str
    region_id: str
    status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    lifetime_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class WellnessProgram(TypedDict):
    id: str
    corporate_account_id: str
    name: str
    cadence: str
    chair_count: int
    slot_minutes: int
    window_start_time: str
    window_duration_minutes: int
    recurrence_discount_pct: float
    status: str
    next_occurrence_date: Optional[str]
    occurrences_materialized: int
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict):
    id: str
    full_name: str
    email: str
    home_region_id: str
    per_hour_rate_cents: int
    status: str
    max_minutes_per_day: int
    rating_avg_x100: int
    created_at: str
    updated_at: str
    version: int


class TherapistLicense(TypedDict):
    id: str
    therapist_id: str
    region_id: str
    license_number: str
    issued_on: str
    expires_on: str
    status: str
    suspension_reason: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    corporate_account_id: str
    wellness_program_id: Optional[str]
    booking_kind: str
    region_id: str
    site_address: str
    event_date: str
    window_start_minutes: int
    window_duration_minutes: int
    chair_count: int
    slot_minutes: int
    per_minute_rate_cents: int
    status: str
    billing_status: str
    booked_chair_minutes: int
    delivered_chair_minutes: int
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ChairSlot(TypedDict):
    id: str
    booking_id: str
    therapist_id: Optional[str]
    chair_index: int
    status: str
    assigned_at: Optional[str]
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SlotClaim(TypedDict):
    id: str
    chair_slot_id: str
    booking_id: str
    recipient_name: str
    recipient_email: str
    slot_ordinal: int
    start_offset_minutes: int
    status: str
    waiver_id: Optional[str]
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TravelLeg(TypedDict):
    id: str
    booking_id: str
    therapist_id: str
    origin_address: str
    distance_miles: int
    travel_fee_cents: int
    travel_fee_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    booking_id: str
    slot_claim_id: str
    signer_email: str
    signed_at: str
    signature_payload: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    booking_id: str
    corporate_account_id: str
    status: str
    chair_minutes_billed: int
    subtotal_cents: int
    recurrence_discount_cents: int
    travel_fees_cents: int
    cancellation_fee_cents: int
    satisfaction_credit_cents: int
    total_cents: int
    pricing_variant: str
    issued_at: Optional[str]
    dispute_reason: str
    created_at: str
    updated_at: str
    version: int


# Immutable ledger-style records (PRD §2.5): carry ONLY id + created_at,
# no updated_at, no version.

class SatisfactionSurvey(TypedDict):
    id: str
    created_at: str
    slot_claim_id: str
    rating: int
    comment: str
    submitted_at: str


class PayoutLedgerEntry(TypedDict):
    id: str
    created_at: str
    therapist_id: str
    booking_id: str
    entry_kind: str
    amount_cents: int
    posted_at: str
    memo: str
