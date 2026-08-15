"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities with the standard four
system-managed properties carry id + created_at + updated_at + version;
LedgerEntry and ClockEvent are append-only and expose only id + created_at
(PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class PortfolioPosture(str, Enum):
    LADDER_OK = "LADDER_OK"
    LADDER_STRESSED = "LADDER_STRESSED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    HOLDOVER = "HOLDOVER"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class ContactKind(str, Enum):
    ASSET_MANAGER = "ASSET_MANAGER"
    BROKER = "BROKER"
    LANDLORD_COUNSEL = "LANDLORD_COUNSEL"


class OptionType(str, Enum):
    RENEWAL = "RENEWAL"
    EXPANSION = "EXPANSION"
    TERMINATION = "TERMINATION"
    ROFR = "ROFR"


class RateDetermination(str, Enum):
    FIXED = "FIXED"
    FAIR_MARKET = "FAIR_MARKET"


class OptionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    WINDOW_OPEN = "WINDOW_OPEN"
    NOTICE_SENT = "NOTICE_SENT"
    EXERCISED = "EXERCISED"
    IN_ARBITRATION = "IN_ARBITRATION"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class AssessmentMethod(str, Enum):
    COMPARABLE_AVERAGE = "COMPARABLE_AVERAGE"
    PSF_REGRESSION = "PSF_REGRESSION"


class AssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class ArbitrationStatus(str, Enum):
    OPEN = "OPEN"
    SUBMISSIONS_FROZEN = "SUBMISSIONS_FROZEN"
    DECIDED = "DECIDED"


class DeliveryMethod(str, Enum):
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    COURIER = "COURIER"
    PERSONAL_DELIVERY = "PERSONAL_DELIVERY"
    EMAIL_IF_PERMITTED = "EMAIL_IF_PERMITTED"


class ExerciseNoticeStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ReminderTier(str, Enum):
    T90 = "T90"
    T60 = "T60"
    T30 = "T30"
    T7 = "T7"
    T0 = "T0"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    CANCELED = "CANCELED"


class AmendmentKind(str, Enum):
    RENEWAL_TERM = "RENEWAL_TERM"
    EXPANSION_TERM = "EXPANSION_TERM"
    CONTRACTION = "CONTRACTION"
    HOLDOVER_SETTLEMENT = "HOLDOVER_SETTLEMENT"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    EXECUTED = "EXECUTED"
    ABANDONED = "ABANDONED"


class LedgerEntryKind(str, Enum):
    OPTION_FEE = "OPTION_FEE"
    MISSED_OPTION_PENALTY = "MISSED_OPTION_PENALTY"
    ARBITRATION_AWARD_ADJUSTMENT = "ARBITRATION_AWARD_ADJUSTMENT"
    AMENDMENT_SETTLEMENT = "AMENDMENT_SETTLEMENT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ASSET_MANAGER = "AssetManager"
    BROKER = "Broker"
    LANDLORD_COUNSEL = "LandlordCounsel"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common fields: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Portfolio(TypedDict, total=False):
    id: str
    name: str
    region: str
    laddering_max_pct_per_year: int
    total_active_square_feet: int
    posture: str
    posture_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    portfolio_id: str
    premises_label: str
    rentable_square_feet: int
    base_rent_cents_per_rsf_year: int
    commencement_date: str
    expiration_date: str
    holdover_tier1_pct: int
    holdover_tier2_pct: int
    holdover_tier1_days: int
    status: str
    holdover_entered_at: Optional[str]
    accrued_holdover_rent_cents: int
    active_amendment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contact(TypedDict, total=False):
    id: str
    portfolio_id: str
    full_name: str
    email: str
    contact_kind: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Option(TypedDict, total=False):
    id: str
    lease_id: str
    option_type: str
    notice_window_open_date: str
    notice_window_close_date: str
    target_commencement_date: str
    extension_years: Optional[int]
    rate_determination: str
    fixed_rent_cents_per_rsf_year: Optional[int]
    exercise_fee_cents: int
    missed_option_penalty_cents: int
    status: str
    exercised_at: Optional[str]
    lapsed_at: Optional[str]
    determined_rent_cents_per_rsf_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MarketRateAssessment(TypedDict, total=False):
    id: str
    option_id: str
    method: str
    comparable_rents_cents: Optional[List[int]]
    regression_base_cents: Optional[int]
    regression_adjustments: Optional[List[int]]
    status: str
    provisional_rent_cents: int
    determined_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ArbitrationCase(TypedDict, total=False):
    id: str
    assessment_id: str
    landlord_rent_cents: int
    tenant_rent_cents: int
    submission_close_date: str
    status: str
    award_rent_cents: Optional[int]
    panel_guidance_rent_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ExerciseNotice(TypedDict, total=False):
    id: str
    option_id: str
    delivery_method: str
    sent_at: str
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict, total=False):
    id: str
    option_id: str
    contact_id: str
    tier: str
    scheduled_for: str
    status: str
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict, total=False):
    id: str
    lease_id: str
    supersedes_amendment_id: Optional[str]
    kind: str
    new_expiration_date: str
    new_base_rent_cents_per_rsf_year: int
    status: str
    negotiation_opened_at: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only records: id + created_at ONLY (no updated_at, no version).

class LedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    lease_id: str
    entry_kind: str
    amount_cents: int
    effective_date: str
    source_option_id: Optional[str]
    source_assessment_id: Optional[str]


class ClockEvent(TypedDict, total=False):
    id: str
    created_at: str
    set_to: str
    fired_reminder_ids: List[str]
    lapsed_option_ids: List[str]
    holdover_lease_ids: List[str]
