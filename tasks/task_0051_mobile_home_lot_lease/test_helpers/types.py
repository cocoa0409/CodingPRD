"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes mirror the PRD's resource definitions. Entities carrying the
standard system-managed set (id, created_at, updated_at, version) are modeled
fully; the four append-only/immutable records (UtilityReading, UtilityCharge,
ConversionBallot, LotLedgerEntry) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────

class CommunityOwnershipModel(str, Enum):
    PARK_OWNED = "PARK_OWNED"
    RESIDENT_OWNED = "RESIDENT_OWNED"


class UtilityApportionmentMethod(str, Enum):
    PER_CAPITA = "PER_CAPITA"
    SUB_METER = "SUB_METER"


class StateCode(str, Enum):
    CA = "CA"
    OR = "OR"
    FL = "FL"
    TX = "TX"


class LotStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    EVICTING = "EVICTING"
    FROZEN = "FROZEN"


class ResidentStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    EVICTED = "EVICTED"


class LotLeaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    TRANSFERRED = "TRANSFERRED"


class RentScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    CONTESTED = "CONTESTED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class UtilityBillStatus(str, Enum):
    DRAFT = "DRAFT"
    APPORTIONED = "APPORTIONED"


class UtilityType(str, Enum):
    WATER = "WATER"
    ELECTRIC = "ELECTRIC"
    SEWER = "SEWER"


class EvictionReason(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    LEASE_VIOLATION = "LEASE_VIOLATION"


class EvictionCaseStatus(str, Enum):
    NOTICE_SERVED = "NOTICE_SERVED"
    CURED = "CURED"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"


class ConversionVoteStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"


class BallotChoice(str, Enum):
    YES = "YES"
    NO = "NO"


class LedgerEntryType(str, Enum):
    RENT_CHARGE = "RENT_CHARGE"
    UTILITY_CHARGE = "UTILITY_CHARGE"
    PAYMENT = "PAYMENT"


class UserRole(str, Enum):
    PARK_MANAGER = "ParkManager"
    RESIDENT = "Resident"
    HOUSING_AUTHORITY = "HousingAuthority"


# ─── Entity TypedDicts ─────────────────────────────────────────
# common_fields: true — carry id + created_at + updated_at + version.

class Community(TypedDict):
    id: str
    name: str
    state_code: str
    ownership_model: str
    utility_apportionment_method: str
    occupied_lot_count: int
    total_metered_units: float
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    community_id: str
    lot_number: str
    base_rent_cents: int
    status: str
    current_lease_id: Optional[str]
    current_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    community_id: str
    full_name: str
    household_size: int
    standing: str
    arrears_cents: int
    created_at: str
    updated_at: str
    version: int


class LotLease(TypedDict):
    id: str
    lot_id: str
    resident_id: str
    supersedes_lease_id: Optional[str]
    start_date: str
    rent_cents_at_signing: int
    status: str
    expected_lot_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RentSchedule(TypedDict):
    id: str
    lot_id: str
    prior_rent_cents: int
    proposed_rent_cents: int
    new_rent_cents: int
    effective_date: str
    cap_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityBill(TypedDict):
    id: str
    community_id: str
    utility_type: str
    period_start: str
    period_end: str
    master_charge_cents: int
    apportioned_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EvictionCase(TypedDict):
    id: str
    lease_id: str
    reason: str
    cure_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionVote(TypedDict):
    id: str
    community_id: str
    quorum_threshold_pct: float
    yes_count: int
    eligible_lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only/immutable, carry ONLY id + created_at.

class UtilityReading(TypedDict):
    id: str
    utility_bill_id: str
    lot_id: str
    metered_units: float
    created_at: str


class UtilityCharge(TypedDict):
    id: str
    utility_bill_id: str
    lot_id: str
    resident_id: str
    amount_cents: int
    created_at: str


class ConversionBallot(TypedDict):
    id: str
    conversion_vote_id: str
    lot_id: str
    choice: str
    created_at: str


class LotLedgerEntry(TypedDict):
    id: str
    lease_id: str
    resident_id: str
    entry_type: str
    amount_cents: int
    created_at: str
