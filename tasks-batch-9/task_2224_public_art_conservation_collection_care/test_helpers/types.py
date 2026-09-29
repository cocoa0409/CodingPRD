"""Domain types for the Public Art Conservation API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every record in this system carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.5), so every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    COLLECTIONS_REGISTRAR = "CollectionsRegistrar"
    CONDITION_SURVEYOR = "ConditionSurveyor"
    CHIEF_CONSERVATOR = "ChiefConservator"
    CONSERVATOR_VENDOR = "ConservatorVendor"
    MAINTENANCE_CREW = "MaintenanceCrew"
    PUBLIC_ART_MANAGER = "PublicArtManager"
    FINANCE_OFFICER = "FinanceOfficer"
    ART_COMMISSION_MEMBER = "ArtCommissionMember"
    ARTIST_REPRESENTATIVE = "ArtistRepresentative"


# --------------------------------------------------------------------------
# Classification enums
# --------------------------------------------------------------------------
class MaterialClass(str, Enum):
    BRONZE = "BRONZE"
    PAINTED_STEEL = "PAINTED_STEEL"
    STONE = "STONE"
    MURAL_COATING = "MURAL_COATING"


class SignificanceTier(str, Enum):
    LANDMARK = "LANDMARK"
    SIGNIFICANT = "SIGNIFICANT"
    STANDARD = "STANDARD"


class ExposureClass(str, Enum):
    COASTAL = "COASTAL"
    URBAN = "URBAN"
    PARK = "PARK"
    INTERIOR = "INTERIOR"


class ProtocolMethod(str, Enum):
    WASH = "WASH"
    WAX = "WAX"
    GRAFFITI_REMOVAL = "GRAFFITI_REMOVAL"
    COATING_RENEWAL = "COATING_RENEWAL"
    INSPECTION = "INSPECTION"


class SolventClass(str, Enum):
    NONE = "NONE"
    MILD = "MILD"
    AGGRESSIVE = "AGGRESSIVE"


class Accreditation(str, Enum):
    AIC_PA = "AIC_PA"
    AIC_ASSOCIATE = "AIC_ASSOCIATE"
    NONE = "NONE"


class TreatmentScope(str, Enum):
    STABILIZATION = "STABILIZATION"
    SURFACE = "SURFACE"
    COATING = "COATING"
    STRUCTURAL = "STRUCTURAL"
    GRAFFITI = "GRAFFITI"


# `complexity_class` on a cost line draws from the same five members as
# `treatment_scope` (PRD §3.4).
ComplexityClass = TreatmentScope


class MoralRightsStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class PriorityBasis(str, Enum):
    NONE = "NONE"
    SINGLE_ASSESSMENT = "SINGLE_ASSESSMENT"
    CYCLE_COHORT = "CYCLE_COHORT"


# --------------------------------------------------------------------------
# Status enums (PRD §2.7 and §3.x state machines)
# --------------------------------------------------------------------------
class CustodyStatus(str, Enum):
    ON_VIEW = "ON_VIEW"
    IN_STORAGE = "IN_STORAGE"
    IN_TREATMENT = "IN_TREATMENT"
    DEACCESSIONED = "DEACCESSIONED"
    DESTROYED = "DESTROYED"


class ConservationStatus(str, Enum):
    MONITORED = "MONITORED"
    TREATMENT_REQUIRED = "TREATMENT_REQUIRED"
    TREATMENT_IN_PROGRESS = "TREATMENT_IN_PROGRESS"
    STABILIZED = "STABILIZED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class Recommendation(str, Enum):
    NONE = "NONE"
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AbortReason(str, Enum):
    NONE = "NONE"
    SUPERSEDED_BY_TREATMENT = "SUPERSEDED_BY_TREATMENT"
    ARTWORK_DEACCESSIONED = "ARTWORK_DEACCESSIONED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class WithdrawReason(str, Enum):
    NONE = "NONE"
    PROPOSAL_SUPERSEDED = "PROPOSAL_SUPERSEDED"
    ARTWORK_DEACCESSIONED = "ARTWORK_DEACCESSIONED"


class ConservatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConsultationSubject(str, Enum):
    TREATMENT = "TREATMENT"
    RELOCATION = "RELOCATION"
    REMOVAL = "REMOVAL"
    DEACCESSION = "DEACCESSION"


class ConsultationStatus(str, Enum):
    PENDING = "PENDING"
    CONCURRED = "CONCURRED"
    OBJECTED = "OBJECTED"
    LAPSED = "LAPSED"
    WAIVED = "WAIVED"


class NoticeActionType(str, Enum):
    ALTERATION = "ALTERATION"
    RELOCATION = "RELOCATION"
    REMOVAL = "REMOVAL"
    DESTRUCTION = "DESTRUCTION"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WAIT_ELAPSED = "WAIT_ELAPSED"
    CONSUMED = "CONSUMED"
    VOID = "VOID"


class CaseStatus(str, Enum):
    INITIATED = "INITIATED"
    PUBLIC_COMMENT = "PUBLIC_COMMENT"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"


class DeaccessionCriterion(str, Enum):
    DETERIORATION_BEYOND_REPAIR = "DETERIORATION_BEYOND_REPAIR"
    PUBLIC_SAFETY_HAZARD = "PUBLIC_SAFETY_HAZARD"
    SITE_REDEVELOPMENT = "SITE_REDEVELOPMENT"
    DUPLICATE_HOLDING = "DUPLICATE_HOLDING"
    LACK_OF_RELEVANCE = "LACK_OF_RELEVANCE"


class Disposition(str, Enum):
    SALE = "SALE"
    TRANSFER = "TRANSFER"
    DESTRUCTION = "DESTRUCTION"
    RETURN_TO_ARTIST = "RETURN_TO_ARTIST"


class Ballot(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ABSTAIN = "ABSTAIN"
    RECUSE = "RECUSE"


class PoolType(str, Enum):
    ENDOWMENT = "ENDOWMENT"
    PERCENT_FOR_ART = "PERCENT_FOR_ART"


class AllocationPurpose(str, Enum):
    TREATMENT = "TREATMENT"
    MAINTENANCE = "MAINTENANCE"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    NONE = "NONE"
    MANUAL_RELEASE = "MANUAL_RELEASE"
    VISIT_ABORTED = "VISIT_ABORTED"
    PROPOSAL_WITHDRAWN = "PROPOSAL_WITHDRAWN"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"


class IncidentType(str, Enum):
    GRAFFITI = "GRAFFITI"
    VANDALISM = "VANDALISM"
    VEHICLE_IMPACT = "VEHICLE_IMPACT"
    WEATHER = "WEATHER"
    THEFT = "THEFT"


class DamageStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    RESOLVED = "RESOLVED"


class ClaimStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class TriageClass(str, Enum):
    NONE = "NONE"
    ROUTINE_MAINTENANCE = "ROUTINE_MAINTENANCE"
    CONSERVATOR_TREATMENT = "CONSERVATOR_TREATMENT"
    TOTAL_LOSS = "TOTAL_LOSS"


class ClaimBasis(str, Enum):
    NONE = "NONE"
    ACV = "ACV"
    RESTORATION = "RESTORATION"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Artist(TypedDict):
    id: str
    full_name: str
    is_living: bool
    deceased_on: Optional[str]
    contact_email: str
    represented_by: Optional[str]
    moral_rights_waiver_on_file: bool
    notice_wait_days: int
    consultation_response_days: int
    artwork_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    site_code: str
    name: str
    address_ref: str
    exposure_class: str
    capacity_units: int
    concurrent_work_capacity: int
    installed_units_used: int
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    accession_number: str
    title: str
    artist_id: str
    site_id: str
    material_class: str
    significance_tier: str
    footprint_units: int
    insured_value_cents: int
    acquisition_date: str
    acquisition_document_ref: str
    recognized_stature: bool
    custody_status: str
    conservation_status: str
    moral_rights_status: str
    condition_index: Optional[float]
    treatment_priority_score: Optional[float]
    treatment_priority_rank: Optional[int]
    priority_basis: str
    open_notice_count: int
    maintenance_applications_ytd: int
    last_maintenance_completed_on: Optional[str]
    next_maintenance_due_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceProtocol(TypedDict):
    id: str
    protocol_code: str
    material_class: str
    method: str
    cycle_days: int
    max_annual_applications: int
    requires_conservator: bool
    solvent_class: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    artwork_id: str
    protocol_id: str
    window_start: str
    window_end: str
    crew_note: Optional[str]
    status: str
    abort_reason: str
    graffiti_reported_at: Optional[str]
    sla_deadline_at: Optional[str]
    sla_breached: bool
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConditionAssessment(TypedDict):
    id: str
    artwork_id: str
    cycle_year: int
    assessed_on: str
    surface_score: int
    structural_score: int
    coating_score: int
    mount_score: int
    graffiti_score: int
    status: str
    photo_count: int
    photo_view_codes: List[str]
    condition_index: Optional[float]
    recommendation: str
    revision_rounds: int
    submitted_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Conservator(TypedDict):
    id: str
    firm_name: str
    accreditation: str
    material_specialties: List[str]
    hourly_rate_cents: int
    insurance_expires_on: str
    status: str
    active_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class TreatmentProposal(TypedDict):
    id: str
    artwork_id: str
    conservator_id: str
    assessment_id: str
    treatment_scope: str
    engagement_start: str
    engagement_end: str
    alters_appearance: bool
    status: str
    line_items: List[dict]
    subtotal_cents: int
    overhead_cents: int
    contingency_cents: int
    mobilization_cents: int
    estimate_total_cents: int
    pinned_estimate_total_cents: Optional[int]
    withdraw_reason: str
    revision_rounds: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArtistConsultation(TypedDict):
    id: str
    artwork_id: str
    artist_id: str
    proposal_id: Optional[str]
    subject: str
    status: str
    sent_on: str
    due_at: str
    responded_at: Optional[str]
    response_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoralRightsNotice(TypedDict):
    id: str
    artwork_id: str
    artist_id: str
    action_type: str
    status: str
    sent_at: str
    earliest_action_at: str
    acknowledged_at: Optional[str]
    consumed_by_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeaccessionCase(TypedDict):
    id: str
    artwork_id: str
    criteria: List[str]
    disposition: str
    disposition_target_ref: Optional[str]
    comment_days: int
    status: str
    initiated_by_user_id: str
    public_comment_opens_on: Optional[str]
    public_comment_closes_at: Optional[str]
    vote_records: List[dict]
    approve_count: int
    deny_count: int
    abstain_count: int
    recuse_count: int
    decision_ratio: Optional[float]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingPool(TypedDict):
    id: str
    pool_code: str
    pool_type: str
    fiscal_year: int
    principal_cents: int
    draw_rate_bps: int
    set_aside_cents: int
    admin_fee_cents: int
    draw_authorized_cents: int
    recovery_credits_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    pool_id: str
    purpose: str
    amount_cents: int
    proposal_id: Optional[str]
    visit_id: Optional[str]
    status: str
    release_reason: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageIncident(TypedDict):
    id: str
    artwork_id: str
    incident_type: str
    damage_extent_pct: float
    narrative: str
    linked_proposal_id: Optional[str]
    credited_pool_id: Optional[str]
    damage_status: str
    claim_status: str
    triage_class: str
    claim_basis: str
    claimed_gross_cents: int
    settlement_cents: int
    reported_at: str
    created_at: str
    updated_at: str
    version: int
