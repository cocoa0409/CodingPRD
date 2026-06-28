"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the common fields id, created_at, updated_at
and version (see PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ACCOUNT_ADMIN = "AccountAdmin"
    IMPORTER_USER = "ImporterUser"
    LICENSED_BROKER = "LicensedBroker"
    CBP_OFFICER = "CBPOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class ImporterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BondStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SATURATED = "SATURATED"
    TERMINATED = "TERMINATED"


class BondType(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    SINGLE_ENTRY = "SINGLE_ENTRY"


class ISFStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    MATCHED = "MATCHED"
    CANCELLED = "CANCELLED"


class EntryStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    HOLD_EXAM = "HOLD_EXAM"
    RELEASED = "RELEASED"
    LIQUIDATED = "LIQUIDATED"
    CANCELLED = "CANCELLED"


class EntryType(str, Enum):
    CONSUMPTION_01 = "CONSUMPTION_01"
    WAREHOUSE_21 = "WAREHOUSE_21"
    FTZ_06 = "FTZ_06"


class PreferenceClaim(str, Enum):
    NONE = "NONE"
    USMCA = "USMCA"


class PGAFlag(str, Enum):
    NONE = "NONE"
    FDA = "FDA"
    USDA = "USDA"


class PGADecision(str, Enum):
    PENDING = "PENDING"
    MAY_PROCEED = "MAY_PROCEED"
    HOLD = "HOLD"
    REFUSED = "REFUSED"


class PGAAgency(str, Enum):
    FDA = "FDA"
    USDA = "USDA"


class ExamSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED_SLOT = "RELEASED_SLOT"
    CANCELLED_SLOT = "CANCELLED_SLOT"


class StationCode(str, Enum):
    CES_LAX = "CES_LAX"
    CES_JFK = "CES_JFK"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class PSCStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class FilingKind(str, Enum):
    PSC = "PSC"
    PROTEST = "PROTEST"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4)
# ---------------------------------------------------------------------------
class Importer(TypedDict):
    id: str
    name: str
    ior_number: str
    owner_user_id: str
    continuous_bond_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    importer_id: str
    bond_type: str
    limit_cents: int
    outstanding_liability_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ISFFiling(TypedDict):
    id: str
    importer_id: str
    bill_of_lading: str
    vessel_eta: str
    data_element_count: int
    filed_at: Optional[str]
    late_filing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomsEntry(TypedDict):
    id: str
    importer_id: str
    bond_id: str
    isf_filing_id: Optional[str]
    statement_id: Optional[str]
    entry_type: str
    country_of_origin: str
    entry_date: str
    provisional_total_cents: int
    final_total_cents: Optional[int]
    total_duties_owed_cents: int
    filed_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EntryLine(TypedDict):
    id: str
    entry_id: str
    hts_code: str
    customs_value_cents: int
    assists_cents: int
    quantity: int
    preference_claim: str
    pga_flag: str
    dutiable_value_cents: int
    line_duty_cents: int
    preference_verified: bool
    created_at: str
    updated_at: str
    version: int


class PGAReview(TypedDict):
    id: str
    entry_id: str
    agency: str
    decision: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamSlot(TypedDict):
    id: str
    station_code: str
    entry_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict):
    id: str
    importer_id: str
    period_month: str
    statement_total_cents: int
    entry_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PostSummaryCorrection(TypedDict):
    id: str
    entry_id: str
    filing_kind: str
    corrected_value_delta_cents: int
    adjustment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
