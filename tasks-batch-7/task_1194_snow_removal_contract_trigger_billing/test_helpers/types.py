"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPS_DISPATCHER = "OpsDispatcher"
    CREW_LEAD = "CrewLead"
    SUBCONTRACTOR = "Subcontractor"
    CLIENT_CONTACT = "ClientContact"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ContractType(str, Enum):
    PER_PUSH = "PER_PUSH"
    SEASONAL = "SEASONAL"
    HOURLY = "HOURLY"


class AmendmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class StormEventStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    CHALLENGED = "CHALLENGED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class VisitExecutionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_BACKUP = "AWAITING_BACKUP"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class VisitBillingStatus(str, Enum):
    PENDING = "PENDING"
    BILLABLE_CONFIRMED = "BILLABLE_CONFIRMED"
    NON_BILLABLE = "NON_BILLABLE"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MaterialType(str, Enum):
    ROCK_SALT = "ROCK_SALT"
    ICE_MELT_BLEND = "ICE_MELT_BLEND"
    LIQUID_BRINE = "LIQUID_BRINE"


class MaterialStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class PhotoPhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class PhotoReviewStatus(str, Enum):
    UPLOADED = "UPLOADED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceKind(str, Enum):
    EVENT = "EVENT"
    PERIOD = "PERIOD"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DisputeReason(str, Enum):
    TRIGGER_NOT_MET = "TRIGGER_NOT_MET"
    INCOMPLETE_SERVICE = "INCOMPLETE_SERVICE"
    PHOTO_INSUFFICIENT = "PHOTO_INSUFFICIENT"
    RATE_DISAGREEMENT = "RATE_DISAGREEMENT"
    MATERIAL_QUANTITY = "MATERIAL_QUANTITY"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    RESOLVED_REMOVED = "RESOLVED_REMOVED"


class ClaimSeverity(str, Enum):
    INJURY_REPORTED = "INJURY_REPORTED"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    NEAR_MISS = "NEAR_MISS"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    DOCUMENTATION_REVIEW = "DOCUMENTATION_REVIEW"
    DOCUMENTED = "DOCUMENTED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class SubcontractorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class CoverageStatus(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TrueUpStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    SUPERSEDED = "SUPERSEDED"


class Client(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    client_id: str
    name: str
    address: str
    region_code: str
    pavement_area_sqft: int
    requires_loader: bool
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    client_id: str
    contract_type: str
    season_start: str
    season_end: str
    trigger_depth_inches: float
    per_push_rate_cents: int
    hourly_rate_cents: int
    hourly_tier2_rate_cents: int
    hourly_tier_threshold_minutes: int
    night_premium_pct: float
    seasonal_fee_cents: int
    seasonal_push_cap: int
    seasonal_overage_rate_cents: int
    sla_miss_penalty_cents: int
    require_photo_verification: bool
    salt_rate_per_lb_cents: int
    blend_rate_per_lb_cents: int
    brine_rate_per_lb_cents: int
    status: str
    season_billable_push_count: int
    season_billable_minutes: int
    season_billed_cents: int
    unbilled_billable_cents: int
    season_sla_miss_count: int
    overage_active: bool
    prior_contract_id: Optional[str]
    renewed_to_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractSite(TypedDict, total=False):
    id: str
    contract_id: str
    site_id: str
    trigger_depth_inches: Optional[float]
    per_push_rate_cents: Optional[int]
    priority_sequence: int
    completion_target_minutes: int
    salt_included_lbs: float
    effective_trigger_depth_inches: float
    effective_per_push_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractAmendment(TypedDict, total=False):
    id: str
    contract_id: str
    effective_from: str
    trigger_depth_inches: Optional[float]
    per_push_rate_cents: Optional[int]
    sla_miss_penalty_cents: Optional[int]
    require_photo_verification: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class StormEvent(TypedDict, total=False):
    id: str
    region_code: str
    window_start: str
    window_end: str
    reported_accumulation_inches: float
    reported_source_name: str
    status: str
    verified_accumulation_inches: Optional[float]
    verified_at: Optional[str]
    verifying_observation_ids: List[str]
    challenged_at: Optional[str]
    challenged_by_client_id: Optional[str]
    challenge_reason: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only feed record: carries ONLY id + created_at (no updated_at, no version).
class WeatherObservation(TypedDict, total=False):
    id: str
    storm_event_id: str
    source_name: str
    observed_at: str
    accumulation_inches: float
    note: Optional[str]
    created_at: str


class ServiceVisit(TypedDict, total=False):
    id: str
    storm_event_id: str
    contract_site_id: str
    contract_id: str
    site_id: str
    assigned_subcontractor_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    actual_start_at: Optional[str]
    completed_at: Optional[str]
    execution_status: str
    billing_status: str
    sla_deadline_at: str
    grace_extended: bool
    sla_miss: Optional[bool]
    billable_minutes: int
    night_premium_applied: bool
    billable_amount_cents: int
    material_cost_cents: int
    applied_trigger_depth_inches: Optional[float]
    applied_per_push_rate_cents: Optional[int]
    completed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialApplication(TypedDict, total=False):
    id: str
    visit_id: str
    material_type: str
    quantity_lbs: float
    rate_per_lb_cents_snapshot: int
    line_cost_cents: int
    status: str
    logged_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ServicePhoto(TypedDict, total=False):
    id: str
    visit_id: str
    phase: str
    image_uri: str
    review_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    storm_event_id: Optional[str]
    kind: str
    period_start: Optional[str]
    period_end: Optional[str]
    status: str
    lines: List[dict]
    subtotal_cents: int
    credit_cents: int
    total_cents: int
    paid_cents: int
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    invoice_id: str
    visit_id: str
    reason: str
    status: str
    opened_by_client_id: str
    evidence_items: List[dict]
    resolved_by_user_id: Optional[str]
    resolution_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SlipFallClaim(TypedDict, total=False):
    id: str
    site_id: str
    incident_at: str
    severity: str
    description: str
    status: str
    storm_event_id: Optional[str]
    documentation_contract_id: Optional[str]
    score_standard: Optional[int]
    score_strict: Optional[int]
    documentation_completeness_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    has_loader: bool
    has_brine_truck: bool
    status: str
    assignments_released_count: int
    assignments_failed_count: int
    active_assignment_count: int
    reliability_score: int
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict, total=False):
    id: str
    storm_event_id: str
    contract_id: str
    subcontractor_id: str
    coverage_start: str
    coverage_end: str
    status: str
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeasonalTrueUp(TypedDict, total=False):
    id: str
    contract_id: str
    status: str
    billable_push_count: int
    overage_pushes: int
    overage_cents: int
    material_actual_cents: int
    material_normative_cents: int
    material_allowance_cents: int
    material_settlement_cents: int
    sla_miss_count: int
    performance_credit_cents: int
    balance_due_cents: int
    issued_at: Optional[str]
    settled_at: Optional[str]
    settled_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
