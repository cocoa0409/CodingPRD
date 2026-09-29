"""Domain types for the Senior Living Dining Therapeutic Diets API.

Entity TypedDicts, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    CLINICAL_STAFF = "ClinicalStaff"
    REGISTERED_DIETITIAN = "RegisteredDietitian"
    DINING_SERVICES_MANAGER = "DiningServicesManager"
    SATELLITE_KITCHEN_LEAD = "SatelliteKitchenLead"
    BILLING_SPECIALIST = "BillingSpecialist"
    RESIDENT_REPRESENTATIVE = "ResidentRepresentative"


# --------------------------------------------------------------------------
# Shared enumerations
# --------------------------------------------------------------------------
class CareLevel(str, Enum):
    INDEPENDENT_LIVING = "INDEPENDENT_LIVING"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    MEMORY_CARE = "MEMORY_CARE"
    SKILLED_NURSING = "SKILLED_NURSING"


class MealPeriod(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"


class TextureLevel(str, Enum):
    REGULAR = "REGULAR"
    BITE_SIZED = "BITE_SIZED"
    MINCED_MOIST = "MINCED_MOIST"
    PUREED = "PUREED"


class LiquidConsistency(str, Enum):
    THIN = "THIN"
    SLIGHTLY_THICK = "SLIGHTLY_THICK"
    MILDLY_THICK = "MILDLY_THICK"
    MODERATELY_THICK = "MODERATELY_THICK"
    EXTREMELY_THICK = "EXTREMELY_THICK"


class TherapeuticCode(str, Enum):
    CARB_CONTROLLED = "CARB_CONTROLLED"
    RENAL = "RENAL"
    LOW_SODIUM = "LOW_SODIUM"
    HIGH_PROTEIN = "HIGH_PROTEIN"
    GLUTEN_FREE = "GLUTEN_FREE"


# --------------------------------------------------------------------------
# Community / venue / resident
# --------------------------------------------------------------------------
class VenueKind(str, Enum):
    MAIN_DINING = "MAIN_DINING"
    BISTRO = "BISTRO"
    SATELLITE = "SATELLITE"


class VenueStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TempCompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class DiningStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    DISCHARGED = "DISCHARGED"


class TrayCardState(str, Enum):
    CLEAR = "CLEAR"
    HOLD_PENDING_REVIEW = "HOLD_PENDING_REVIEW"
    BLOCKED = "BLOCKED"


class PreferenceStrictness(str, Enum):
    STRICT = "STRICT"
    FLEXIBLE = "FLEXIBLE"


# --------------------------------------------------------------------------
# Diet order — two independent status dimensions (PRD §3.2)
# --------------------------------------------------------------------------
class DietOrderClinicalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISCONTINUED = "DISCONTINUED"


class DietOrderReviewStatus(str, Enum):
    AWAITING_DIETITIAN = "AWAITING_DIETITIAN"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REREVIEW_REQUIRED = "REREVIEW_REQUIRED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"


# --------------------------------------------------------------------------
# Substitution rules / tray card
# --------------------------------------------------------------------------
class SubstitutionTriggerType(str, Enum):
    ALLERGEN = "ALLERGEN"
    TEXTURE = "TEXTURE"
    DISLIKE = "DISLIKE"


class SubstitutionRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TrayLineReason(str, Enum):
    ALLERGEN_UNRESOLVED = "ALLERGEN_UNRESOLVED"
    EXTENSION_PENDING = "EXTENSION_PENDING"
    NONE = "NONE"
    ALLERGEN_SUBSTITUTION = "ALLERGEN_SUBSTITUTION"
    TEXTURE_SUBSTITUTION = "TEXTURE_SUBSTITUTION"
    DISLIKE_SUBSTITUTION = "DISLIKE_SUBSTITUTION"


# --------------------------------------------------------------------------
# Menu cycle / items / extensions / ballots
# --------------------------------------------------------------------------
class MenuCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DIETITIAN_SIGNOFF = "PENDING_DIETITIAN_SIGNOFF"
    PUBLISHED = "PUBLISHED"
    REFRESH_PENDING = "REFRESH_PENDING"
    ARCHIVED = "ARCHIVED"


class ExtensionCoverageStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"


class ExtensionReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class RefreshTier(str, Enum):
    QUORUM = "QUORUM"
    ADVISORY = "ADVISORY"


class BallotSentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class BallotStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --------------------------------------------------------------------------
# Reservations / tickets
# --------------------------------------------------------------------------
class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    SEATED = "SEATED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class TicketType(str, Enum):
    RESIDENT = "RESIDENT"
    GUEST = "GUEST"
    TAKEOUT = "TAKEOUT"


class TicketStatus(str, Enum):
    ISSUED = "ISSUED"
    SERVED = "SERVED"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------
# Temperature logs
# --------------------------------------------------------------------------
class ProbePoint(str, Enum):
    HOT_HOLDING = "HOT_HOLDING"
    COLD_HOLDING = "COLD_HOLDING"
    REHEAT = "REHEAT"


# --------------------------------------------------------------------------
# Monitoring / reconciliation
# --------------------------------------------------------------------------
class PlanOfCareReviewStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class PlanOfCareTriggerReason(str, Enum):
    WEIGHT_LOSS_30D = "WEIGHT_LOSS_30D"
    LOW_INTAKE_AVG = "LOW_INTAKE_AVG"
    COMBINED = "COMBINED"


class PlanOfCareOutcome(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    DIET_ORDER_REREVIEW = "DIET_ORDER_REREVIEW"
    ESCALATED = "ESCALATED"


class ReconciliationStatus(str, Enum):
    RECONCILED = "RECONCILED"
    FINALIZED = "FINALIZED"


# ==========================================================================
# Entity TypedDicts
#
# Most resources carry id + created_at + updated_at + version (PRD §2.4).
# IntakeObservation, TemperatureLog and CommitteeFeedback are append-only
# and carry ONLY id and created_at.
# ==========================================================================
class Community(TypedDict):
    id: str
    name: str
    care_levels_offered: List[str]
    guest_meal_sponsor_cap_cents: int
    variance_tolerance_cents: int
    pending_dietitian_review_count: int
    active_menu_cycle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiningVenue(TypedDict):
    id: str
    community_id: str
    name: str
    venue_kind: str
    seat_capacity: int
    care_levels_served: List[str]
    seating_turn_minutes: int
    turnover_buffer_minutes: int
    temp_compliance_posture: str
    consecutive_temp_violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    community_id: str
    full_name: str
    care_level: str
    baseline_weight_kg: float
    allergens: List[str]
    dislikes: List[str]
    preference_strictness: str
    dining_status: str
    tray_card_state: str
    current_weight_kg: float
    guest_meal_charge_balance_cents: int
    rolling_30d_weight_change_pct: float
    baseline_weight_change_pct: float
    intake_risk_score: float
    avg_intake_pct_7d: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DietOrder(TypedDict):
    id: str
    resident_id: str
    texture_level: str
    liquid_consistency: str
    therapeutic_codes: List[str]
    supersedes_order_id: Optional[str]
    clinical_status: str
    review_status: str
    review_round: int
    ordered_by_user_id: str
    reviewed_by_user_id: Optional[str]
    reviewer_note: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRule(TypedDict):
    id: str
    resident_id: str
    trigger_type: str
    match_value: str
    replacement_item_code: str
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeatingReservation(TypedDict):
    id: str
    resident_id: str
    venue_id: str
    service_date: str
    meal_period: str
    seat_start_utc: str
    seat_end_utc: str
    party_size: int
    status: str
    allow_waitlist: bool
    suspension_hold: bool
    seated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuCycle(TypedDict):
    id: str
    community_id: str
    cycle_number: int
    week_count: int
    effective_start_date: str
    effective_end_date: str
    status: str
    refresh_round: int
    refresh_index: float
    refresh_tier: str
    refresh_reason: Optional[str]
    signed_off_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    menu_cycle_id: str
    item_code: str
    name: str
    day_index: int
    meal_period: str
    base_texture: str
    allergen_tags: List[str]
    required_therapeutic_codes: List[str]
    extension_coverage_status: str
    created_at: str
    updated_at: str
    version: int


class TherapeuticExtension(TypedDict):
    id: str
    menu_item_id: str
    diet_code: str
    nutrient_overrides: Optional[Dict[str, Any]]
    review_status: str
    review_round: int
    authored_by_user_id: str
    reviewed_by_user_id: Optional[str]
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MealServiceTicket(TypedDict):
    id: str
    venue_id: str
    resident_id: Optional[str]
    reservation_id: Optional[str]
    ticket_type: str
    service_date: str
    meal_period: str
    status: str
    billed_amount_cents: int
    voided_amount_cents: int
    billed_reconciliation_id: Optional[str]
    issued_by_user_id: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingReconciliation(TypedDict):
    id: str
    community_id: str
    period_start_date: str
    period_end_date: str
    status: str
    ticket_ledger_total_cents: int
    census_projection_total_cents: int
    variance_cents: int
    ledger_meal_counts: Dict[str, int]
    census_meal_counts: Dict[str, int]
    void_credit_cents: int
    pre_fee_base_cents: int
    administrative_fee_cents: int
    net_billable_total_cents: int
    variance_note: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanOfCareReview(TypedDict):
    id: str
    resident_id: str
    trigger_observation_id: str
    trigger_reason: str
    risk_score_at_open: float
    status: str
    outcome: Optional[str]
    note: Optional[str]
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: ONLY id and created_at (PRD §2.4) ---------------
class IntakeObservation(TypedDict):
    id: str
    resident_id: str
    observation_date: str
    meal_period: str
    intake_pct: float
    weight_kg: Optional[float]
    recorded_by_user_id: str
    created_at: str


class TemperatureLog(TypedDict):
    id: str
    venue_id: str
    probe_point: str
    temperature_f: float
    in_range: bool
    corrective_action_code: Optional[str]
    violation_sequence_index: int
    logged_at_utc: str
    logged_by_user_id: str
    created_at: str


class CommitteeFeedback(TypedDict):
    id: str
    menu_cycle_id: str
    resident_id: str
    menu_item_code: str
    sentiment: str
    vote_weight: int
    status: str
    created_at: str


# --------------------------------------------------------------------------
# Computed reads (PRD §3.3 tray card, §3.5 seat availability)
# --------------------------------------------------------------------------
class TrayCardLine(TypedDict):
    item_code: str
    served_item_code: str
    substitution_rule_id: Optional[str]
    reason: str


class TrayCard(TypedDict):
    resident_id: str
    menu_cycle_id: str
    service_date: str
    meal_period: str
    day_index: int
    lines: List[TrayCardLine]
    blocked_item_codes: List[str]
    tray_status: str


class SeatAvailability(TypedDict):
    venue_id: str
    service_date: str
    meal_period: str
    seat_capacity: int
    committed_seats: int
    open_seats: int
    blocking_reservation_ids: List[str]
