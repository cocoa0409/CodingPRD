"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    MEMBER = "Member"
    VOLUNTEER = "Volunteer"
    PROGRAM_ADMIN = "ProgramAdmin"


class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SiteType(str, Enum):
    LIBRARY_BRANCH = "LIBRARY_BRANCH"
    GARDEN = "GARDEN"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class StandingTier(str, Enum):
    PROBATION = "PROBATION"
    STANDARD = "STANDARD"
    TRUSTED = "TRUSTED"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VarietyCategory(str, Enum):
    VEGETABLE = "VEGETABLE"
    HERB = "HERB"
    FLOWER = "FLOWER"
    NATIVE = "NATIVE"


class SeedVarietyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SeedLotStatus(str, Enum):
    DRAFT = "DRAFT"
    QUARANTINE = "QUARANTINE"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class GerminationTestStatus(str, Enum):
    RECORDED = "RECORDED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class SeedPacketStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    RECALLED = "RECALLED"
    VOIDED = "VOIDED"
    DISCARDED = "DISCARDED"


class CheckoutStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    DISPUTED = "DISPUTED"
    VERIFIED = "VERIFIED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SwapEventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    INTAKE_OPEN = "INTAKE_OPEN"
    INTAKE_CLOSED = "INTAKE_CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IntakeItemType(str, Enum):
    SEED_PACKET = "SEED_PACKET"
    PLANT_START = "PLANT_START"
    CUTTING = "CUTTING"


class IntakeItemCondition(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"


class SwapIntakeItemStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RETURNED_TO_OWNER = "RETURNED_TO_OWNER"
    SWAPPED = "SWAPPED"


class CreditEntryType(str, Enum):
    EARNED = "EARNED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PackingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PackingAssignmentStatus(str, Enum):
    SIGNUP = "SIGNUP"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Site(TypedDict, total=False):
    id: str
    name: str
    site_type: str
    region_zone: str
    label_stock_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    home_site_id: str
    status: str
    active_checkout_count: int
    overdue_checkout_count: int
    terminal_checkout_count: int
    verified_return_count: int
    simple_return_rate: float
    decay_weighted_return_score: float
    standing_tier: str
    effective_borrow_limit: int
    credits_earned_total: int
    credits_redeemed_total: int
    credits_expired_total: int
    credits_revoked_total: int
    credits_balance: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedVariety(TypedDict, total=False):
    id: str
    variety_name: str
    species: str
    category: str
    invasive_flag: bool
    rarity_flag: bool
    approved_zones: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedLot(TypedDict, total=False):
    id: str
    variety_id: str
    home_site_id: str
    lot_code: str
    harvest_year: int
    seeds_received: int
    provisional_viability_pct: float
    status: str
    final_viability_pct: Optional[float]
    seeds_remaining: int
    seeds_in_packets: int
    seeds_discarded: int
    packets_created_total: int
    viable_seed_count: int
    created_at: str
    updated_at: str
    version: int


class GerminationTest(TypedDict, total=False):
    id: str
    lot_id: str
    recorded_by_volunteer_id: str
    seeds_tested: int
    sprouted_count: int
    result_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedPacket(TypedDict, total=False):
    id: str
    lot_id: str
    packet_code: str
    seeds_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Checkout(TypedDict, total=False):
    id: str
    member_id: str
    packet_id: str
    checked_out_at: str
    due_at: str
    returned_at: Optional[str]
    recall_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SwapEvent(TypedDict, total=False):
    id: str
    site_id: str
    title: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SwapIntakeItem(TypedDict, total=False):
    id: str
    event_id: str
    member_id: str
    variety_id: str
    item_type: str
    condition: str
    credit_value: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditEntry(TypedDict, total=False):
    # Append-only ledger row: carries only id + created_at (PRD §2.4).
    id: str
    member_id: str
    event_id: str
    entry_type: str
    credits: int
    note: str
    created_at: str


class PackingSession(TypedDict, total=False):
    id: str
    site_id: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackingAssignment(TypedDict, total=False):
    id: str
    session_id: str
    volunteer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
