"""Domain types: entity TypedDicts, status enums, role enum.

All nine resource types carry the common system-managed fields (id, created_at,
updated_at, version) per the PRD's "Common Resource Properties" section.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────────

class PatronStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    BARRED = "BARRED"


class Residency(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class FacilityType(str, Enum):
    FIELD = "FIELD"
    COURT = "COURT"
    POOL = "POOL"
    PAVILION = "PAVILION"


class FacilityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CoiStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LeagueStatus(str, Enum):
    PENDING = "PENDING"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    GRANTED = "GRANTED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    GRANTED = "GRANTED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    CREDIT = "CREDIT"


class LotteryRoundStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"
    CANCELLED = "CANCELLED"


class LotteryEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    REC_COORDINATOR = "RecCoordinator"
    PATRON = "Patron"
    FINANCE_CLERK = "FinanceClerk"


# ─── Entity TypedDicts (all carry common_fields: true) ────────────────────────

class Patron(TypedDict):
    id: str
    full_name: str
    email: str
    residency: str
    residency_verified: bool
    standing: str
    no_show_strikes: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    facility_type: str
    status: str
    hourly_rate_cents: int
    resident_discount_pct: float
    prime_multiplier: float
    prime_start_hour: int
    prime_end_hour: int
    buffer_minutes: int
    deposit_cents: int
    requires_coi: bool
    min_coi_coverage_cents: int
    granted_permit_count: int
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    patron_id: str
    coverage_amount_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeagueSeries(TypedDict):
    id: str
    facility_id: str
    patron_id: str
    coi_id: Optional[str]
    weekday: int
    start_hour: int
    duration_minutes: int
    first_date: str
    occurrences: int
    status: str
    granted_occurrence_count: int
    conflicted_occurrence_count: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    facility_id: str
    patron_id: str
    coi_id: Optional[str]
    league_id: Optional[str]
    lottery_round_id: Optional[str]
    start_at: str
    end_at: str
    is_prime_requested: bool
    status: str
    pricing_residency: str
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    deposit_held_cents: int
    refunded_cents: int
    cancelled_lead_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    permit_id: str
    fee_component_cents: int
    deposit_component_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    permit_id: str
    payment_id: Optional[str]
    refund_destination: str
    fee_refund_cents: int
    deposit_refund_cents: int
    total_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class LotteryRound(TypedDict):
    id: str
    facility_id: str
    slot_start_at: str
    slot_end_at: str
    opens_at: str
    closes_at: str
    status: str
    entry_count: int
    winning_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryEntry(TypedDict):
    id: str
    lottery_round_id: str
    patron_id: str
    priority_weight: int
    entry_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int
