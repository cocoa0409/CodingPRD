"""Domain types for the performing arts center season API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────

class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    PROGRAMMING_DIRECTOR = "ProgrammingDirector"
    RENTAL_MANAGER = "RentalManager"
    ARTIST_REPRESENTATIVE = "ArtistRepresentative"
    RENTAL_CLIENT_CONTACT = "RentalClientContact"
    TECHNICAL_DIRECTOR = "TechnicalDirector"
    BOX_OFFICE_MANAGER = "BoxOfficeManager"
    FINANCE_CONTROLLER = "FinanceController"


# ─── Enumerations on persisted fields ─────────────────

class SpaceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"


class CreditRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class UnionDepartmentName(str, Enum):
    STAGEHANDS = "STAGEHANDS"
    ELECTRICS = "ELECTRICS"
    AUDIO = "AUDIO"
    WARDROBE = "WARDROBE"


class EquipmentCategory(str, Enum):
    POWER_DISTRO = "POWER_DISTRO"
    DMX_NODE = "DMX_NODE"
    RIGGING_HARDWARE = "RIGGING_HARDWARE"
    AUDIO_PACKAGE = "AUDIO_PACKAGE"


class EngagementType(str, Enum):
    PRESENTED = "PRESENTED"
    RENTAL = "RENTAL"


class LifecycleStatus(str, Enum):
    """Booking dimension of the engagement (PRD §2.7)."""
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    PERFORMED = "PERFORMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class FinancialClearance(str, Enum):
    """Risk dimension of the engagement (PRD §2.7)."""
    UNASSESSED = "UNASSESSED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"
    ESCALATED_APPROVED = "ESCALATED_APPROVED"
    BLOCKED = "BLOCKED"


class TicketingStatus(str, Enum):
    """Box-office dimension of the engagement (PRD §2.7)."""
    TICKETING_UNSET = "TICKETING_UNSET"
    TIERS_DRAFT = "TIERS_DRAFT"
    ON_SALE = "ON_SALE"
    CLOSED = "CLOSED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    PROHIBITIVE = "PROHIBITIVE"


class NegotiationStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class RiderReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CAPABLE = "CAPABLE"
    GAP_IDENTIFIED = "GAP_IDENTIFIED"
    CLEARED = "CLEARED"
    REJECTED_INFEASIBLE = "REJECTED_INFEASIBLE"


class CapabilityGap(str, Enum):
    RIGGING_OVER_CAPACITY = "RIGGING_OVER_CAPACITY"
    RIGGING_NEAR_LIMIT = "RIGGING_NEAR_LIMIT"
    POWER_SHORTFALL = "POWER_SHORTFALL"
    DMX_SHORTFALL = "DMX_SHORTFALL"


class CoversGap(str, Enum):
    RIGGING_NEAR_LIMIT = "RIGGING_NEAR_LIMIT"
    POWER_SHORTFALL = "POWER_SHORTFALL"
    DMX_SHORTFALL = "DMX_SHORTFALL"
    NONE = "NONE"


class RentalLineStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class LaborCallStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    WORKED = "WORKED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class PriceTierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TicketSaleStatus(str, Enum):
    SOLD = "SOLD"
    REFUNDED = "REFUNDED"


class SalesChannel(str, Enum):
    WEB = "WEB"
    PHONE = "PHONE"
    WINDOW = "WINDOW"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXPENSES_RECONCILED = "EXPENSES_RECONCILED"
    FINALIZED = "FINALIZED"


class ProgramType(str, Enum):
    STUDENT_MATINEE = "STUDENT_MATINEE"
    MASTERCLASS = "MASTERCLASS"
    COMMUNITY_WORKSHOP = "COMMUNITY_WORKSHOP"


class EducationProgramStatus(str, Enum):
    FUNDED = "FUNDED"
    CANCELLED_WITH_ENGAGEMENT = "CANCELLED_WITH_ENGAGEMENT"


class ReserveEntryType(str, Enum):
    OPENING_BALANCE = "OPENING_BALANCE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    SETTLEMENT_CONTRIBUTION = "SETTLEMENT_CONTRIBUTION"
    EDUCATION_SUBSIDY_DRAW = "EDUCATION_SUBSIDY_DRAW"
    EDUCATION_SUBSIDY_REFUND = "EDUCATION_SUBSIDY_REFUND"


# ─── Entity TypedDicts ────────────────────────────────
# Every entity below carries id + created_at + updated_at + version
# (PRD §2.4) except ReserveLedgerEntry, which is append-only and carries
# only id + created_at.

class PerformanceSpace(TypedDict):
    id: str
    name: str
    seat_capacity: int
    base_facility_fee_cents: int
    load_in_day_fee_cents: int
    changeover_buffer_minutes: int
    rigging_capacity_kg: int
    house_power_amps: int
    dmx_universes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    legal_name: str
    agency_name: str
    guarantee_floor_cents: int
    historical_sell_through_pct: float
    routing_window_start_utc: str
    routing_window_end_utc: str
    min_days_between_engagements: int
    lifetime_guarantee_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class RentalClient(TypedDict):
    id: str
    org_name: str
    contact_email: str
    credit_rating: str
    is_nonprofit: bool
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class UnionDepartment(TypedDict):
    id: str
    department: str
    roster_size: int
    straight_hourly_rate_cents: int
    overtime_multiplier: float
    doubletime_multiplier: float
    call_minimum_hours: float
    meal_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    category: str
    model_name: str
    on_hand_qty: int
    reserved_qty: int
    daily_rate_cents: int
    replacement_value_cents: int
    reserve_funded: bool
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    engagement_type: str
    space_id: str
    artist_id: Optional[str]
    rental_client_id: Optional[str]
    title: str
    load_in_start_utc: str
    performance_start_utc: str
    performance_end_utc: str
    load_out_end_utc: str
    performance_day_count: int
    load_in_day_count: int
    lifecycle_status: str
    financial_clearance: str
    ticketing_status: str
    negotiated_fee_cents: int
    artist_share_pct: float
    facility_fee_cents: int
    labor_estimate_total_cents: int
    additional_equipment_cost_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    risk_score: int
    risk_tier: str
    projected_gross_cents: int
    projected_margin_cents: int
    realized_gross_cents: int
    realized_margin_cents: int
    negotiation_round_count: int
    fee_accepted_by_user_id: Optional[str]
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeNegotiation(TypedDict):
    id: str
    engagement_id: str
    round_index: int
    status: str
    offered_fee_cents: int
    offered_artist_share_pct: float
    counter_fee_cents: Optional[int]
    counter_artist_share_pct: Optional[float]
    revision_count: int
    accepted_fee_cents: Optional[int]
    accepted_share_pct: Optional[float]
    opened_by_user_id: str
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TechRider(TypedDict):
    id: str
    engagement_id: str
    submitted_rigging_kg: int
    requested_power_amps: int
    requested_dmx_universes: int
    requires_orchestra_pit: bool
    review_status: str
    capability_gaps: List[str]
    additional_equipment_cost_cents: int
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentRentalLine(TypedDict):
    id: str
    tech_rider_id: str
    equipment_item_id: str
    covers_gap: str
    qty: int
    rental_days: int
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborCall(TypedDict):
    id: str
    engagement_id: str
    union_department_id: str
    crew_size: int
    call_start_utc: str
    call_end_utc: str
    scheduled_hours: float
    estimated_cost_cents: int
    actual_hours: Optional[float]
    meal_break_taken: Optional[bool]
    actual_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceTier(TypedDict):
    id: str
    engagement_id: str
    tier_name: str
    seats_allocated: int
    base_price_cents: int
    price_ceiling_cents: int
    dynamic_pricing_enabled: bool
    subscription_eligible: bool
    sold_qty: int
    subscription_held_qty: int
    available_qty: int
    gross_cents: int
    subscription_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketSale(TypedDict):
    id: str
    price_tier_id: str
    qty: int
    channel: str
    sell_through_pct_at_sale: float
    dynamic_multiplier_applied: float
    unit_price_cents: int
    gross_cents: int
    restoration_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPackage(TypedDict):
    id: str
    name: str
    package_price_cents: int
    included_engagement_ids: List[str]
    subscription_tier_name: str
    seats_per_order: int
    sold_count: int
    allocation_map: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    engagement_id: str
    status: str
    box_office_gross_cents: int
    restoration_fees_cents: int
    adjusted_gross_cents: int
    guarantee_cents: int
    actual_labor_cents: int
    actual_equipment_cents: int
    actual_marketing_cents: int
    reimbursable_expense_cap_cents: int
    reimbursable_expenses_cents: int
    artist_share_cents: int
    net_to_center_cents: int
    reserve_contribution_cents: int
    amount_payable_to_artist_cents: int
    balance_due_from_client_cents: int
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EducationProgram(TypedDict):
    id: str
    engagement_id: str
    program_type: str
    participant_capacity: int
    subsidy_requested_cents: int
    subsidy_approved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReserveLedgerEntry(TypedDict):
    """Append-only and immutable once written: it carries only id and
    created_at — no updated_at and no version (PRD §2.4)."""
    id: str
    entry_type: str
    amount_cents: int
    engagement_id: Optional[str]
    memo: str
    balance_after_cents: int
    created_at: str


class BoxOfficeStatement(TypedDict):
    """Computed projection returned by the box-office statement endpoint."""
    engagement_id: str
    tier_count: int
    seats_allocated_total: int
    sold_qty_total: int
    subscription_held_qty_total: int
    single_ticket_gross_cents: int
    subscription_revenue_cents: int
    restoration_fees_cents: int
    box_office_gross_cents: int
    adjusted_gross_cents: int


__all__ = [
    "UserRole",
    "SpaceStatus",
    "CreditRating",
    "UnionDepartmentName",
    "EquipmentCategory",
    "EngagementType",
    "LifecycleStatus",
    "FinancialClearance",
    "TicketingStatus",
    "RiskTier",
    "NegotiationStatus",
    "RiderReviewStatus",
    "CapabilityGap",
    "CoversGap",
    "RentalLineStatus",
    "LaborCallStatus",
    "PriceTierStatus",
    "TicketSaleStatus",
    "SalesChannel",
    "SettlementStatus",
    "ProgramType",
    "EducationProgramStatus",
    "ReserveEntryType",
    "PerformanceSpace",
    "Artist",
    "RentalClient",
    "UnionDepartment",
    "EquipmentItem",
    "Engagement",
    "FeeNegotiation",
    "TechRider",
    "EquipmentRentalLine",
    "LaborCall",
    "PriceTier",
    "TicketSale",
    "SubscriptionPackage",
    "Settlement",
    "EducationProgram",
    "ReserveLedgerEntry",
    "BoxOfficeStatement",
]
