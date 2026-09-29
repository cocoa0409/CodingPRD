"""Domain types for the Arena Changeover Operations API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    VENUE_OPERATIONS_DIRECTOR = "VenueOperationsDirector"
    BOOKING_MANAGER = "BookingManager"
    CHANGEOVER_SUPERVISOR = "ChangeoverSupervisor"
    LABOR_COORDINATOR = "LaborCoordinator"
    ANCHOR_TENANT_REP = "AnchorTenantRep"


# --------------------------------------------------------------------------
# Enumerated vocabularies
# --------------------------------------------------------------------------
class IceDeckStatus(str, Enum):
    NONE = "NONE"
    BUILDING = "BUILDING"
    IN_SERVICE = "IN_SERVICE"
    COVERED = "COVERED"
    MELTING = "MELTING"


class ProfileCode(str, Enum):
    ICE_HOCKEY = "ICE_HOCKEY"
    COURT_BASKETBALL = "COURT_BASKETBALL"
    CONCERT_END_STAGE = "CONCERT_END_STAGE"
    CONCERT_IN_ROUND = "CONCERT_IN_ROUND"
    FAMILY_SHOW = "FAMILY_SHOW"


class SeatingMode(str, Enum):
    FULL_BOWL = "FULL_BOWL"
    RETRACTABLE_IN = "RETRACTABLE_IN"
    CURTAINED_HALF = "CURTAINED_HALF"


class HoldPriorityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class HoldTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    OPEN = "OPEN"


class EventBookingStatus(str, Enum):
    DRAFT = "DRAFT"
    HELD = "HELD"
    CHALLENGED = "CHALLENGED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    DISPLACED = "DISPLACED"


class HoldChallengeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ChallengeDecision(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class ChangeoverOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    REWORK = "REWORK"
    READY_FOR_SIGNOFF = "READY_FOR_SIGNOFF"
    SIGNED_OFF = "SIGNED_OFF"
    ABANDONED = "ABANDONED"


class FloorStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    STRIKING = "STRIKING"
    LAYING = "LAYING"
    FLOOR_COMPLETE = "FLOOR_COMPLETE"


class SeatingStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RETRACTING = "RETRACTING"
    CURTAINING = "CURTAINING"
    SEATING_COMPLETE = "SEATING_COMPLETE"


class InfraStage(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    UTILITY_SET = "UTILITY_SET"
    NETWORK_SET = "NETWORK_SET"
    BROADCAST_READY = "BROADCAST_READY"


class ChangeoverDimension(str, Enum):
    FLOOR = "FLOOR"
    SEATING = "SEATING"
    INFRA = "INFRA"


class AbandonReason(str, Enum):
    FROM_BOOKING_GONE = "FROM_BOOKING_GONE"
    TO_BOOKING_GONE = "TO_BOOKING_GONE"


class BlockingReason(str, Enum):
    INCOMING_BOOKING_NOT_CONFIRMED = "INCOMING_BOOKING_NOT_CONFIRMED"
    FLOOR_PROTECTION_SHORTFALL = "FLOOR_PROTECTION_SHORTFALL"
    FLOOR_INCOMPLETE = "FLOOR_INCOMPLETE"
    SEATING_INCOMPLETE = "SEATING_INCOMPLETE"
    INFRA_INCOMPLETE = "INFRA_INCOMPLETE"
    CHANGEOVER_DEBT_FREEZE = "CHANGEOVER_DEBT_FREEZE"


class IceSheetStatus(str, Enum):
    BUILDING = "BUILDING"
    IN_SERVICE = "IN_SERVICE"
    COVERED = "COVERED"
    MELTING = "MELTING"
    REMOVED = "REMOVED"


class DockPurpose(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"


class DockSlotReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class DockReleaseReason(str, Enum):
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    BOOKING_GONE = "BOOKING_GONE"


class Craft(str, Enum):
    STAGEHAND = "STAGEHAND"
    RIGGER = "RIGGER"
    ICE_TECH = "ICE_TECH"
    ELECTRICIAN = "ELECTRICIAN"
    CONVERSION_CREW = "CONVERSION_CREW"


class LaborCallStatus(str, Enum):
    CALLED = "CALLED"
    WORKED = "WORKED"
    CANCELLED = "CANCELLED"


class AssetClass(str, Enum):
    STAGE_DECK = "STAGE_DECK"
    DASHER_BOARD_SET = "DASHER_BOARD_SET"
    FLOOR_PANEL_SET = "FLOOR_PANEL_SET"
    CURTAIN_SYSTEM = "CURTAIN_SYSTEM"
    ICE_COVER_PANEL_SET = "ICE_COVER_PANEL_SET"
    BASKETBALL_FLOOR = "BASKETBALL_FLOOR"


class EquipmentAssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MaintenanceAction(str, Enum):
    START = "START"
    COMPLETE = "COMPLETE"


class EquipmentIssueStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"


class EquipmentReturnReason(str, Enum):
    OPERATOR_RETURN = "OPERATOR_RETURN"
    ORDER_ABANDONED = "ORDER_ABANDONED"


# --------------------------------------------------------------------------
# Entity shapes.  Every persisted resource carries id/created_at/updated_at/
# version except the house configuration profile, which carries only id and
# created_at (PRD §2.4).
# --------------------------------------------------------------------------
class Venue(TypedDict):
    id: str
    name: str
    rigging_capacity_kg: float
    dock_count: int
    max_bowl_seats: int
    crew_headcount_cap: int
    min_turnaround_buffer_minutes: int
    dock_buffer_minutes: int
    overnight_shift_start_local_hour: int
    ice_deck_status: str
    rigging_committed_load_kg: float
    open_hold_count: int
    changeover_debt_minutes: int
    created_at: str
    updated_at: str
    version: int


class ConfigurationProfile(TypedDict):
    """Immutable once declared: only id and created_at, no updated_at, no version."""

    id: str
    venue_id: str
    code: str
    requires_ice: bool
    ice_cover_required: bool
    seating_mode: str
    nominal_seats: int
    base_changeover_minutes: int
    crew_size_required: int
    floor_protection_panels_required: int
    dehumidification_required_lph: float
    rigging_points_required: int
    created_at: str


class AnchorTenant(TypedDict):
    id: str
    venue_id: str
    name: str
    hold_priority_tier: str
    guaranteed_holds_per_season: int
    holds_consumed: int
    challenge_credits: int
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict):
    id: str
    venue_id: str
    tenant_id: Optional[str]
    config_profile_id: str
    title: str
    promoter_name: Optional[str]
    event_start_utc: str
    event_end_utc: str
    expected_attendance: int
    rigging_load_kg: float
    status: str
    hold_tier: Optional[str]
    hold_placed_at: Optional[str]
    hold_expires_at: Optional[str]
    release_reason: Optional[str]
    displaced_by_booking_id: Optional[str]
    displacement_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class HoldChallenge(TypedDict):
    id: str
    booking_id: str
    challenger_tenant_id: str
    challenger_booking_id: str
    status: str
    priority_delta: int
    ruled_at: Optional[str]
    ruling_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeoverOrder(TypedDict):
    id: str
    venue_id: str
    from_booking_id: str
    to_booking_id: str
    crew_headcount: int
    window_start_utc: str
    window_end_utc: str
    window_minutes: int
    overnight_shift: bool
    planned_turnaround_minutes: int
    actual_turnaround_minutes: Optional[int]
    overrun_minutes: int
    status: str
    floor_stage: str
    seating_stage: str
    infra_stage: str
    rework_count: int
    started_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    opened_by_user_id: str
    signed_off_by_user_id: Optional[str]
    abandon_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IceSheet(TypedDict):
    id: str
    venue_id: str
    config_profile_id: str
    status: str
    dehumidification_lph_applied: float
    required_dehumidification_lph: float
    sheet_thickness_mm: float
    cover_cycles: int
    cover_hours_accumulated: float
    cover_installed_at_utc: Optional[str]
    condensation_risk_score: float
    created_at: str
    updated_at: str
    version: int


class DockSlotReservation(TypedDict):
    id: str
    venue_id: str
    booking_id: str
    dock_number: int
    purpose: str
    window_start_utc: str
    window_end_utc: str
    truck_count: int
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaborCall(TypedDict):
    id: str
    venue_id: str
    changeover_order_id: Optional[str]
    booking_id: Optional[str]
    craft: str
    headcount: int
    call_start_utc: str
    call_end_utc: str
    guaranteed_hours: float
    overnight: bool
    status: str
    estimated_cost_cents: int
    actual_hours: Optional[float]
    settled_cost_cents: Optional[int]
    cancellation_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    venue_id: str
    asset_class: str
    units_total: int
    units_available: int
    units_out_of_service: int
    service_interval_cycles: int
    cycles_since_service: int
    service_due: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentIssue(TypedDict):
    id: str
    asset_id: str
    changeover_order_id: str
    units_issued: int
    damaged_units: int
    status: str
    return_reason: Optional[str]
    returned_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReadinessProjection(TypedDict):
    order_id: str
    status: str
    floor_stage: str
    seating_stage: str
    infra_stage: str
    window_minutes: int
    planned_turnaround_minutes: int
    slack_minutes: int
    blocking_reasons: List[str]


class SweepResult(TypedDict):
    swept_count: int
    released_booking_ids: List[str]
    venue_version: int
