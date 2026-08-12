"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.7, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    INTAKE_VOLUNTEER = "IntakeVolunteer"
    FIXER = "Fixer"
    SAFETY_OFFICER = "SafetyOfficer"


class RepairCategory(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    TEXTILE = "TEXTILE"
    BIKE = "BIKE"


class PartCategory(str, Enum):
    ELECTRONICS = "ELECTRONICS"
    TEXTILE = "TEXTILE"
    BIKE = "BIKE"
    GENERIC = "GENERIC"


class RepairEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    INTAKE_OPEN = "INTAKE_OPEN"
    REPAIR_ACTIVE = "REPAIR_ACTIVE"
    CLOSED = "CLOSED"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class EventPosture(str, Enum):
    ACCEPTING = "ACCEPTING"
    RESTRICTED = "RESTRICTED"


class StationStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class FixerProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class FixerShiftStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    LEFT_EARLY = "LEFT_EARLY"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RepairItemStatus(str, Enum):
    REGISTERED = "REGISTERED"
    TRIAGED = "TRIAGED"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_REPAIR = "IN_REPAIR"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    VERIFIED = "VERIFIED"
    WITHDRAWN = "WITHDRAWN"


class PartReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class OutcomeType(str, Enum):
    FIXED = "FIXED"
    PARTIALLY_FIXED = "PARTIALLY_FIXED"
    NOT_REPAIRABLE = "NOT_REPAIRABLE"


class VerificationStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ResolutionAction(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"


class DonationType(str, Enum):
    MONETARY = "MONETARY"
    IN_KIND = "IN_KIND"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    RECEIPTED = "RECEIPTED"
    REFUNDED = "REFUNDED"


# --- Entity TypedDicts ---
# Entities with the full common-field set carry id, created_at, updated_at, version.
# FixerSkill, TriageRecord and EventReport carry only id and created_at (PRD §2.7).


class RepairEvent(TypedDict):
    id: str
    name: str
    starts_at: str
    ends_at: str
    intake_item_cap: int
    status: str
    posture: str
    active_item_count: int
    diversion_kg_verified: float
    diversion_kg_projected: float
    parts_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    event_id: str
    category: str
    label: str
    capacity: int
    status: str
    checked_in_fixer_count: int
    created_at: str
    updated_at: str
    version: int


class FixerProfile(TypedDict):
    id: str
    display_name: str
    email: str
    status: str
    safety_induction_completed_at: str
    reliability_score: int
    created_at: str
    updated_at: str
    version: int


class FixerSkill(TypedDict):
    id: str
    fixer_id: str
    category: str
    level: int
    certified: bool
    created_at: str


class FixerShift(TypedDict):
    id: str
    fixer_id: str
    station_id: str
    event_id: str
    start_time: str
    end_time: str
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visitor(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    visitor_id: str
    signed_at: str
    safety_clause_accepted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairItem(TypedDict):
    id: str
    event_id: str
    visitor_id: str
    category: str
    description: str
    hazard_flag: bool
    weight_kg_estimated: float
    status: str
    assigned_station_id: Optional[str]
    assigned_fixer_id: Optional[str]
    priority_score: int
    required_skill_level: int
    created_at: str
    updated_at: str
    version: int


class TriageRecord(TypedDict):
    id: str
    item_id: str
    assessor_fixer_id: str
    severity: int
    estimated_difficulty: int
    diagnosis: str
    superseded_by_id: Optional[str]
    is_current: bool
    created_at: str


class PartStock(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    part_stock_id: str
    repair_item_id: str
    quantity: int
    unit_cost_cents: int
    cost_cents: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class RepairOutcome(TypedDict):
    id: str
    item_id: str
    fixer_id: str
    outcome: str
    weight_kg_actual: Optional[float]
    parts_cost_cents: int
    suggested_donation_cents: int
    verification_status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict):
    id: str
    event_id: str
    item_id: Optional[str]
    fixer_id: Optional[str]
    reported_by_user_id: str
    severity: str
    description: str
    status: str
    resolution_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InKindLine(TypedDict):
    description: str
    category: str
    declared_value_cents: int
    age_years: int


class Donation(TypedDict):
    id: str
    event_id: Optional[str]
    visitor_id: Optional[str]
    donation_type: str
    amount_cents: Optional[int]
    in_kind_lines: Optional[List[InKindLine]]
    status: str
    received_at: Optional[str]
    receipt_value_cents: Optional[int]
    campaign_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EventReport(TypedDict):
    id: str
    event_id: str
    generated_at: str
    items_total: int
    items_fixed: int
    items_partially_fixed: int
    items_not_repairable: int
    success_rate_strict: float
    success_rate_lenient: float
    diversion_kg_verified: float
    diversion_kg_projected: float
    parts_cost_total_cents: int
    donations_receipt_total_cents: int
    donations_campaign_total_cents: int
    created_at: str
