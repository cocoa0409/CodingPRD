"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the PRD. Mutable
entities carry id/created_at/updated_at/version; the three append-only audit
records (ShareIssuance, Form3921, WaterfallDistribution) carry only id +
created_at (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums (one per stateful entity) -------------------------------

class CapTableStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    DISSOLVED = "DISSOLVED"


class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class OptionPoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class OptionGrantStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXERCISED = "EXERCISED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ExerciseStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class Section83bElectionStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED_LATE = "REJECTED_LATE"


class SafeNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    OUTSTANDING = "OUTSTANDING"
    CONVERTED = "CONVERTED"
    REPAID = "REPAID"


class LiquidationEventStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    FINALIZED = "FINALIZED"


class BlackoutWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIFTED = "LIFTED"


# --- Value enums ----------------------------------------------------------

class SecurityClassType(str, Enum):
    COMMON = "COMMON"
    PREFERRED = "PREFERRED"


class HolderType(str, Enum):
    FOUNDER = "FOUNDER"
    EMPLOYEE = "EMPLOYEE"
    INVESTOR = "INVESTOR"
    ENTITY = "ENTITY"


class InstrumentType(str, Enum):
    SAFE = "SAFE"
    NOTE = "NOTE"


class VestingStyle(str, Enum):
    GRADED = "GRADED"
    CLIFF_ONLY = "CLIFF_ONLY"


class UserRole(str, Enum):
    ADMINISTRATOR = "Administrator"
    BOARD_APPROVER = "BoardApprover"
    STAKEHOLDER = "Stakeholder"
    AUDITOR = "Auditor"


# --- Entity TypedDicts (mutable — id/created_at/updated_at/version) --------

class CapTable(TypedDict):
    id: str
    company_name: str
    authorized_shares: int
    status: str
    issued_shares: int
    fully_diluted_shares: int
    locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityClass(TypedDict):
    id: str
    cap_table_id: str
    name: str
    class_type: str
    shares_outstanding: int
    original_issue_price_cents: int
    liquidation_pref_multiple: float
    participating: bool
    participation_cap_multiple: float
    seniority_below_class_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shareholder(TypedDict):
    id: str
    cap_table_id: str
    legal_name: str
    holder_type: str
    email: str
    is_us_taxpayer: bool
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    cap_table_id: str
    fmv_per_share_cents: int
    valuation_date: str
    expires_at: str
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OptionPool(TypedDict):
    id: str
    cap_table_id: str
    authorized_shares: int
    allocated_shares: int
    available_shares: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionGrant(TypedDict):
    id: str
    cap_table_id: str
    option_pool_id: str
    shareholder_id: str
    security_class_id: str
    valuation_id: str
    share_count: int
    strike_price_cents: int
    grant_date: str
    vesting_months: int
    cliff_months: int
    vesting_style: str
    early_exercise_allowed: bool
    vested_shares: int
    exercised_shares: int
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exercise(TypedDict):
    id: str
    cap_table_id: str
    option_grant_id: str
    share_count: int
    is_early_exercise: bool
    spread_cents: int
    filing_3921_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Section83bElection(TypedDict):
    id: str
    cap_table_id: str
    exercise_id: str
    filed_date: str
    exercise_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafeNote(TypedDict):
    id: str
    cap_table_id: str
    shareholder_id: str
    instrument_type: str
    principal_cents: int
    valuation_cap_cents: int
    discount_pct: float
    interest_rate_pct: float
    issue_date: str
    converted_share_count: int
    converted_into_class_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LiquidationEvent(TypedDict):
    id: str
    cap_table_id: str
    total_proceeds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict):
    id: str
    cap_table_id: str
    reason: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only audit records (id + created_at only) ---------------------

class ShareIssuance(TypedDict):
    id: str
    cap_table_id: str
    security_class_id: str
    shareholder_id: str
    share_count: int
    price_paid_cents: int
    issued_at: str
    created_at: str


class Form3921(TypedDict):
    id: str
    cap_table_id: str
    exercise_id: str
    shareholder_id: str
    tax_year: int
    exercise_fmv_cents: int
    strike_price_cents: int
    shares_transferred: int
    created_at: str


class WaterfallDistribution(TypedDict):
    id: str
    cap_table_id: str
    liquidation_event_id: str
    security_class_id: str
    preference_paid_cents: int
    participation_paid_cents: int
    total_paid_cents: int
    created_at: str
