"""Domain types for the Electric Outage Management & Storm Restoration API.

Entity field sets mirror the resource projections declared in PRD sections
2.5, 2.10, and 3. TroubleSignal, EtrRevision, and CostLedgerEntry are
append-style records (PRD 2.5) and deliberately omit `updated_at`/`version`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EMERGENCY_DIRECTOR = "EmergencyDirector"
    DISPATCHER = "Dispatcher"
    TELEMETRY_GATEWAY = "TelemetryGateway"
    FIELD_CREW_LEAD = "FieldCrewLead"
    SYSTEM_OPERATOR = "SystemOperator"
    MUTUAL_AID_COORDINATOR = "MutualAidCoordinator"
    MATERIALS_MANAGER = "MaterialsManager"
    CLAIMS_OFFICER = "ClaimsOfficer"
    REGULATOR = "Regulator"


class EventType(str, Enum):
    THUNDERSTORM = "THUNDERSTORM"
    HURRICANE = "HURRICANE"
    ICE_STORM = "ICE_STORM"
    WILDFIRE_PSPS = "WILDFIRE_PSPS"
    TORNADO = "TORNADO"


class EventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    CLOSED = "CLOSED"


class PriorityClass(str, Enum):
    LIFE_SUPPORT = "LIFE_SUPPORT"
    CRITICAL_FACILITY = "CRITICAL_FACILITY"


class CertificationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    DECERTIFIED = "DECERTIFIED"


class SignalType(str, Enum):
    METER_LAST_GASP = "METER_LAST_GASP"
    CUSTOMER_CALL = "CUSTOMER_CALL"
    SCADA_TRIP = "SCADA_TRIP"
    METER_RESTORE_PING = "METER_RESTORE_PING"


class SignalDisposition(str, Enum):
    UNCLUSTERED = "UNCLUSTERED"
    CLUSTERED = "CLUSTERED"
    DISMISSED = "DISMISSED"


class OutageStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    ASSESSED = "ASSESSED"
    WORKING = "WORKING"
    RESTORED = "RESTORED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class CauseCode(str, Enum):
    TREE = "TREE"
    LIGHTNING = "LIGHTNING"
    EQUIPMENT = "EQUIPMENT"
    VEHICLE = "VEHICLE"
    UNKNOWN = "UNKNOWN"


class RevisionReason(str, Enum):
    INITIAL = "INITIAL"
    DAMAGE_FOUND = "DAMAGE_FOUND"
    CREW_DELAYED = "CREW_DELAYED"
    NESTED_DISCOVERED = "NESTED_DISCOVERED"
    WEATHER_DELAY = "WEATHER_DELAY"
    CORRECTION = "CORRECTION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class DamageClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CATASTROPHIC = "CATASTROPHIC"


class CrewType(str, Enum):
    LINE = "LINE"
    TREE = "TREE"
    DAMAGE_ASSESSOR = "DAMAGE_ASSESSOR"
    SUBSTATION = "SUBSTATION"


class CrewStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    AVAILABLE = "AVAILABLE"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"


class MutualAidStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AVAILABLE = "AVAILABLE"
    DEMOBILIZING = "DEMOBILIZING"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class DepartureReason(str, Enum):
    COMPLETED = "COMPLETED"
    EARLY_RELEASE = "EARLY_RELEASE"


class BlockStatus(str, Enum):
    OPEN = "OPEN"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class WorkType(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    REPAIR = "REPAIR"
    REPLACE_POLE = "REPLACE_POLE"
    REPLACE_TRANSFORMER = "REPLACE_TRANSFORMER"
    SWITCHING = "SWITCHING"


class ExecutionStatus(str, Enum):
    CREATED = "CREATED"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VerificationStatus(str, Enum):
    PENDING_VERIFY = "PENDING_VERIFY"
    VERIFY_PASSED = "VERIFY_PASSED"
    VERIFY_FAILED = "VERIFY_FAILED"


class SwitchingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    ABORTED = "ABORTED"


class RequisitionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    STAGED = "STAGED"
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class LedgerEntryType(str, Enum):
    LABOR_INTERNAL = "LABOR_INTERNAL"
    LABOR_MUTUAL_AID = "LABOR_MUTUAL_AID"
    MATERIAL = "MATERIAL"
    LODGING = "LODGING"
    MUTUAL_AID_PENALTY = "MUTUAL_AID_PENALTY"


class CostClass(str, Enum):
    CAPITAL = "CAPITAL"
    O_AND_M = "O_AND_M"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    OBLIGATED = "OBLIGATED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


# --- Entity projections (common_fields: true — id/created_at/updated_at/version) ---


class StormEvent(TypedDict, total=False):
    id: str
    event_name: str
    event_type: str
    event_status: str
    activated_at: Optional[str]
    open_outage_count: int
    total_labor_cents: int
    total_material_cents: int
    total_mutual_aid_cents: int
    total_lodging_cents: int
    total_event_cost_cents: int
    capital_cost_cents: int
    om_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Feeder(TypedDict, total=False):
    id: str
    feeder_code: str
    county_code: str
    service_customer_count: int
    cluster_signal_threshold: int
    cluster_call_threshold: int
    certified_priority_count: int
    created_at: str
    updated_at: str
    version: int


class PriorityCustomer(TypedDict, total=False):
    id: str
    account_ref: str
    priority_class: str
    feeder_id: str
    certification_status: str
    certified_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TroubleSignal(TypedDict, total=False):
    # append-only record: id + created_at only (no updated_at, no version)
    id: str
    signal_type: str
    feeder_id: str
    outage_id: Optional[str]
    occurred_at: str
    disposition: str
    created_at: str


class Outage(TypedDict, total=False):
    id: str
    storm_event_id: str
    feeder_id: str
    parent_outage_id: Optional[str]
    outage_status: str
    cause_code: Optional[str]
    customers_affected: Optional[int]
    confirmed_at: Optional[str]
    current_etr: Optional[str]
    etr_missed: bool
    has_priority_customers: bool
    priority_score: int
    restoration_reported_at: Optional[str]
    merged_into_outage_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EtrRevision(TypedDict, total=False):
    # append-only record: id + created_at only (no updated_at, no version)
    id: str
    outage_id: str
    revision_seq: int
    revision_reason: str
    published_etr: str
    previous_etr: Optional[str]
    issued_by: str
    created_at: str


class DamageAssessment(TypedDict, total=False):
    id: str
    outage_id: str
    assessor_crew_id: str
    assessment_status: str
    damage_class: str
    estimated_repair_minutes: int
    requires_switching: bool
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_code: str
    crew_type: str
    home_base: str
    hourly_rate_cents: int
    crew_status: str
    shift_started_at: Optional[str]
    worked_minutes_this_shift: int
    created_at: str
    updated_at: str
    version: int


class MutualAidCrew(TypedDict, total=False):
    id: str
    storm_event_id: str
    company_name: str
    crew_type: str
    roster_size: int
    service_county_code: str
    daily_rate_cents: int
    per_diem_cents: int
    committed_window_start: str
    committed_window_end: str
    ma_status: str
    arrived_at: Optional[str]
    departed_at: Optional[str]
    lodging_block_id: Optional[str]
    engagement_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LodgingBlock(TypedDict, total=False):
    id: str
    storm_event_id: str
    hotel_name: str
    county_code: str
    room_count: int
    nightly_rate_cents: int
    window_start: str
    window_end: str
    block_status: str
    rooms_allocated: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    outage_id: str
    work_type: str
    required_crew_type: str
    requires_switching_order: bool
    execution_status: str
    verification_status: str
    assigned_crew_id: Optional[str]
    assigned_mutual_aid_crew_id: Optional[str]
    switching_order_id: Optional[str]
    arrived_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SwitchingOrder(TypedDict, total=False):
    id: str
    work_order_id: str
    switching_steps: List[str]
    so_status: str
    issuer_user_id: str
    approver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialStock(TypedDict, total=False):
    id: str
    warehouse_code: str
    material_sku: str
    quantity_on_hand: int
    unit_cost_cents: int
    quantity_reserved: int
    quantity_available: int
    created_at: str
    updated_at: str
    version: int


class MaterialRequisition(TypedDict, total=False):
    id: str
    work_order_id: str
    material_stock_id: str
    quantity: int
    requisition_status: str
    created_at: str
    updated_at: str
    version: int


class CostLedgerEntry(TypedDict, total=False):
    # append-only record: id + created_at only (no updated_at, no version)
    id: str
    storm_event_id: str
    work_order_id: Optional[str]
    entry_type: str
    cost_class: str
    county_code: str
    amount_cents: int
    posted_at: str
    reversed_entry_id: Optional[str]
    created_at: str


class FemaClaim(TypedDict, total=False):
    id: str
    storm_event_id: str
    county_code: str
    threshold_cents: int
    claim_status: str
    eligible_cost_cents: int
    eligible_snapshot_cents: Optional[int]
    variance_cents: Optional[int]
    preparer_user_id: Optional[str]
    certifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
