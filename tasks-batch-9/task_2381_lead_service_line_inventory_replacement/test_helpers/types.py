"""Typed shapes and enumerations for the lead service line domain."""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role:
    """The six declared actor roles."""

    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    INVENTORY_ANALYST = "InventoryAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FIELD_TECHNICIAN = "FieldTechnician"
    CUSTOMER_REPRESENTATIVE = "CustomerRepresentative"
    REPLACEMENT_CONTRACTOR = "ReplacementContractor"


ALL_ROLES = (
    Role.PROGRAM_ADMINISTRATOR,
    Role.INVENTORY_ANALYST,
    Role.COMPLIANCE_OFFICER,
    Role.FIELD_TECHNICIAN,
    Role.CUSTOMER_REPRESENTATIVE,
    Role.REPLACEMENT_CONTRACTOR,
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class InventoryStatus:
    DRAFT = "DRAFT"
    VALIDATION_PENDING = "VALIDATION_PENDING"
    PUBLISHED = "PUBLISHED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"


class ProgramPosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class FundingMode:
    WATERFALL = "WATERFALL"
    PRO_RATA = "PRO_RATA"


class CctOptimizationStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    OPTIMIZED = "OPTIMIZED"
    PENDING_REOPTIMIZATION = "PENDING_REOPTIMIZATION"


class Material:
    LEAD = "LEAD"
    GRR = "GRR"
    COPPER = "COPPER"
    PLASTIC = "PLASTIC"
    UNKNOWN = "UNKNOWN"


class Classification:
    LEAD = "LEAD"
    GRR = "GRR"
    NON_LEAD = "NON_LEAD"
    UNKNOWN = "UNKNOWN"


class CertaintyBasis:
    RECORDS_BASIS = "RECORDS_BASIS"
    FIELD_BASIS = "FIELD_BASIS"


class InventoryState:
    UNCLASSIFIED = "UNCLASSIFIED"
    CLASSIFIED_PROVISIONAL = "CLASSIFIED_PROVISIONAL"
    CLASSIFIED_VERIFIED = "CLASSIFIED_VERIFIED"


class ReplacementState:
    NOT_REQUIRED = "NOT_REQUIRED"
    ELIGIBLE = "ELIGIBLE"
    IN_PROGRAM = "IN_PROGRAM"
    REPLACED_PARTIAL = "REPLACED_PARTIAL"
    REPLACED_FULL = "REPLACED_FULL"


class SourceType:
    HISTORIC_RECORD = "HISTORIC_RECORD"
    PREDICTIVE_MODEL = "PREDICTIVE_MODEL"
    WATER_SAMPLING = "WATER_SAMPLING"
    VISUAL_INSPECTION = "VISUAL_INSPECTION"
    POTHOLE = "POTHOLE"


class Side:
    UTILITY = "UTILITY"
    CUSTOMER = "CUSTOMER"


class EvidenceOrigin:
    MANUAL = "MANUAL"
    APPOINTMENT_CASCADE = "APPOINTMENT_CASCADE"
    REPLACEMENT_CASCADE = "REPLACEMENT_CASCADE"


class CrewStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class VerificationMethod:
    VISUAL_INSPECTION = "VISUAL_INSPECTION"
    POTHOLE = "POTHOLE"
    WATER_SAMPLING = "WATER_SAMPLING"


class AppointmentState:
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    ABANDONED = "ABANDONED"


class BarrierReason:
    LOCKED_PREMISE = "LOCKED_PREMISE"
    OCCUPANT_REFUSED = "OCCUPANT_REFUSED"
    UTILITY_CONFLICT = "UTILITY_CONFLICT"
    WEATHER = "WEATHER"


class BatchState:
    OPEN = "OPEN"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class RejectionReason:
    CONFIDENCE_BELOW_FLOOR = "CONFIDENCE_BELOW_FLOOR"


class SampleType:
    FIRST_DRAW = "FIRST_DRAW"
    FIFTH_LITER = "FIFTH_LITER"


class PublicationBasis:
    RECORDS = "RECORDS"
    FIELD_VERIFIED = "FIELD_VERIFIED"


class PublicationState:
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class SupersedeReason:
    AMENDED_BY_NEWER_PUBLICATION = "AMENDED_BY_NEWER_PUBLICATION"


class NotificationState:
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETURNED = "RETURNED"


class DeliveryChannel:
    MAIL = "MAIL"
    EMAIL = "EMAIL"
    DOOR_HANGER = "DOOR_HANGER"


class ReturnReason:
    ADDRESS_INVALID = "ADDRESS_INVALID"
    REFUSED = "REFUSED"
    VACANT = "VACANT"


class FulfillmentState:
    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    FUNDED = "FUNDED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConsentState:
    NOT_REQUESTED = "NOT_REQUESTED"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    NO_RESPONSE = "NO_RESPONSE"


class ConsentOutcome:
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    NO_RESPONSE = "NO_RESPONSE"


class OrderScope:
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class ConsentBarrierReason:
    COST = "COST"
    REFUSED = "REFUSED"
    NO_CONTACT = "NO_CONTACT"
    ACCESS_DENIED = "ACCESS_DENIED"


class AllocationState:
    COMMITTED = "COMMITTED"
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"


class SourceKind:
    STATE_REVOLVING_FUND = "STATE_REVOLVING_FUND"
    FEDERAL_GRANT = "FEDERAL_GRANT"
    RATE_REVENUE = "RATE_REVENUE"


class FundingSourceStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class EquityTier:
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"


class ComplianceStatus:
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class WaterSystem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    pwsid: str
    system_name: str
    compliance_deadline_date: str
    baseline_lead_and_grr_count: int
    disadvantaged_tract_codes: List[str]
    funding_mode: str
    cct_optimization_status: str
    cct_orthophosphate_mg_l: Optional[float]
    cct_target_ph: Optional[float]
    total_service_line_count: int
    lead_count: int
    grr_count: int
    non_lead_count: int
    unknown_count: int
    unknown_share_pct: float
    outstanding_notification_count: int
    inventory_status: str
    program_posture: str


class ServiceLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    street_project_id: Optional[str]
    address_label: str
    census_tract_code: str
    serves_sensitive_population: bool
    interior_diameter_mm: float
    total_length_m: float
    disadvantaged_status: bool
    utility_side_material: str
    customer_side_material: str
    classification: str
    certainty_basis: str
    certainty_score: float
    replacement_priority_score: float
    consent_barrier_flag: bool
    inventory_state: str
    replacement_state: str


class EvidenceItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_line_id: str
    source_type: str
    side: str
    observed_material: str
    observed_at: str
    notes: Optional[str]
    tier_rank: int
    confidence_weight: float
    origin: str
    retracted: bool
    retraction_reason: Optional[str]


class VerificationCrew(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    crew_name: str
    shift_start_utc_time: str
    shift_end_utc_time: str
    daily_appointment_capacity: int
    certified_methods: List[str]
    status: str
    scheduled_appointment_count: int


class VerificationAppointment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_line_id: str
    crew_id: str
    method: str
    window_start_utc: str
    window_end_utc: str
    state: str
    attempt_count: int
    barrier_reason: Optional[str]
    observed_material: Optional[str]
    observed_side: Optional[str]
    emitted_evidence_item_id: Optional[str]


class Sample(TypedDict, total=False):
    sample_seq: int
    service_line_id: str
    lead_ppb: float
    collected_at: str
    sample_type: str
    invalidated: bool
    invalidation_reason: Optional[str]


class SamplingBatch(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    stratum_code: str
    stratum_line_count: int
    samples: List[Sample]
    required_sample_count: int
    valid_sample_count: int
    percentile_90_ppb: Optional[float]
    exceedance_count: int
    exceedance: bool
    classification_confidence: Optional[float]
    state: str
    reopen_count: int
    rejection_reason: Optional[str]


class InventoryPublication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    basis: str
    reporting_period_label: str
    drafted_by_user_id: str
    certified_by_user_id: Optional[str]
    state: str
    pinned_lead_count: Optional[int]
    pinned_grr_count: Optional[int]
    pinned_unknown_count: Optional[int]
    pinned_non_lead_count: Optional[int]
    notifiable_line_count: Optional[int]
    published_at: Optional[str]
    notification_due_at: Optional[str]
    supersede_reason: Optional[str]


class CustomerNotification(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_line_id: str
    inventory_publication_id: str
    notified_classification: str
    state: str
    delivery_channel: Optional[str]
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    return_reason: Optional[str]
    delivery_attempt_count: int
    due_at: str
    overdue: bool


class FundingAllocation(TypedDict, total=False):
    funding_source_id: str
    allocated_cents: int
    priority_rank: int
    state: str


class ReplacementOrder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_line_id: str
    street_project_id: Optional[str]
    estimated_cost_cents: int
    excavation_start_date: str
    excavation_end_date: str
    fulfillment_state: str
    consent_state: str
    scope: Optional[str]
    consent_barrier_reason: Optional[str]
    funding_allocations: List[FundingAllocation]
    funding_mode_applied: Optional[str]
    allocated_total_cents: int
    flushing_duration_minutes: Optional[int]
    replaced_sides: List[str]
    completed_at: Optional[str]
    cancellation_reason: Optional[str]


class StreetProject(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    project_name: str
    moratorium_start_date: str
    moratorium_end_date: str
    paving_start_date: str
    max_concurrent_excavations: int
    active_excavation_order_count: int


class FundingSource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    water_system_id: str
    source_kind: str
    authorized_cents: int
    priority_rank: int
    max_share_pct: float
    equity_required_pct: float
    available_cents: int
    committed_cents: int
    drawn_cents: int
    disadvantaged_committed_cents: int
    disadvantaged_share_pct: float
    equity_shortfall_cents: int
    status: str


class ProgressReport(TypedDict, total=False):
    id: str
    created_at: str
    water_system_id: str
    period_start_date: str
    period_end_date: str
    full_replacement_count: int
    partial_replacement_count: int
    disadvantaged_full_count: int
    base_credit: float
    disadvantaged_share_pct: float
    equity_tier: str
    equity_multiplier: float
    total_credit: float
    mandated_annual_credit: int
    deferral_allowance: int
    shortfall_credit: float
    compliance_status: str
    replaced_count: int
    baseline_denominator: int
    replacement_progress_pct: float


#: Entities that carry the full common-field set.
VERSIONED_ENTITIES = (
    "WaterSystem",
    "ServiceLine",
    "EvidenceItem",
    "VerificationCrew",
    "VerificationAppointment",
    "SamplingBatch",
    "InventoryPublication",
    "CustomerNotification",
    "ReplacementOrder",
    "StreetProject",
    "FundingSource",
)

JsonDict = Dict[str, Any]
