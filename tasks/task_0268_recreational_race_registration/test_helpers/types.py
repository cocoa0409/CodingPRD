"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly (integer cents, snake_case identifiers).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PARTICIPANT = "Participant"
    RACE_DIRECTOR = "RaceDirector"
    PACKET_STAFF = "PacketStaff"
    TIMING_OFFICIAL = "TimingOfficial"


# --- Status enums (PRD §3) ---
class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RESULTS_POSTED = "RESULTS_POSTED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    BIB_ASSIGNED = "BIB_ASSIGNED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    DEFERRED = "DEFERRED"
    TRANSFERRED = "TRANSFERRED"
    FINISHED = "FINISHED"


class WaitlistEntryStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class TransferRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ResultRecordStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"
    DQ = "DQ"


class FundraisingPledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PacketPickupStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class DistanceLabel(str, Enum):
    FIVE_K = "FIVE_K"
    TEN_K = "TEN_K"
    HALF_MARATHON = "HALF_MARATHON"
    MARATHON = "MARATHON"


class EntryType(str, Enum):
    STANDARD = "STANDARD"
    CHARITY = "CHARITY"


class TierName(str, Enum):
    EARLY_BIRD = "EARLY_BIRD"
    REGULAR = "REGULAR"
    LATE = "LATE"


# --- Entity TypedDicts ---
# Resources carrying common fields (id, created_at, updated_at, version).

class Participant(TypedDict):
    id: str
    email: str
    full_name: str
    birthdate: str
    gender: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    name: str
    race_date_utc: str
    registration_opens_utc: str
    registration_closes_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Distance(TypedDict):
    id: str
    event_id: str
    label: str
    distance_km: float
    capacity_total: int
    charity_capacity: int
    charity_fundraising_minimum_cents: int
    confirmed_count: int
    charity_confirmed_count: int
    waitlist_open: bool
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict):
    id: str
    distance_id: str
    name: str
    start_offset_seconds: int
    wave_capacity: int
    corral_capacity: int
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    event_id: str
    distance_id: str
    wave_id: str
    participant_id: str
    entry_type: str
    party_size: int
    promo_code: Optional[str]
    qualifying_time_seconds: Optional[int]
    fundraising_minimum_cents: int
    status: str
    amount_due_cents: int
    amount_paid_cents: int
    processing_fee_cents: int
    refund_cents: int
    deferred_to_registration_id: Optional[str]
    deferral_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    distance_id: str
    registration_id: str
    participant_id: str
    queue_position: int
    status: str
    offer_expires_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundraisingPledge(TypedDict):
    id: str
    registration_id: str
    donor_name: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    registration_id: str
    from_participant_id: str
    to_participant_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BibAssignment(TypedDict):
    id: str
    registration_id: str
    distance_id: str
    wave_id: str
    bib_number: int
    corral: str
    created_at: str
    updated_at: str
    version: int


class PacketPickup(TypedDict):
    id: str
    registration_id: str
    picked_up_by_name: str
    id_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ResultRecord(TypedDict):
    id: str
    registration_id: str
    distance_id: str
    gun_start_clock_seconds: int
    mat_cross_clock_seconds: int
    finish_clock_seconds: int
    gun_time_seconds: int
    chip_time_seconds: int
    pace_seconds_per_km: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PricingTier is immutable (PRD §2.4): it carries ONLY id and created_at —
# no updated_at, no version.
class PricingTier(TypedDict):
    id: str
    distance_id: str
    tier_name: str
    effective_from_utc: str
    base_price_cents: int
    created_at: str
