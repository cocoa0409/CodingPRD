"""Typed shapes for the twelve resources of PRD §2.4.

"Every resource in this system — projects, budget lines, deliverables, cuts,
change orders, talent engagements, locations, shoot days, compliance
certificates, crew members, crew bookings and equipment reservations — carries
the same four system-managed properties, with no exceptions and no entity
omitting any of them" — so every shape below inherits :class:`CommonFields`.

These are documentation and editor aids: ``TypedDict`` is not enforced at
runtime, and the assertions module is what actually checks a response body.
"""

from typing import Any, Literal, Optional, TypedDict

# ─── The four system-managed properties (PRD §2.4) ─────────────────────────


class CommonFields(TypedDict):
    """`id`, `created_at`, `updated_at` and `version`, on every resource."""

    id: str
    created_at: str
    updated_at: str
    version: int


COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")

ProjectStatus = Literal["DRAFT", "SCOPED", "IN_PRODUCTION", "IN_POST", "DELIVERED", "ARCHIVED"]
ReviewGate = Literal["OPEN", "CHANGE_ORDER_PENDING"]
ArchiveStatus = Literal["NOT_PACKAGED", "HANDED_OVER", "RETENTION_EXPIRED"]
Channel = Literal["BROADCAST", "OLV", "SOCIAL", "INTERNAL", "OOH"]
AspectRatio = Literal["16:9", "9:16", "1:1", "4:5", "2.39:1"]
CaptionRequirement = Literal["NONE", "CLOSED_SRT", "BURNED_IN_SUBTITLES", "OPEN_CAPTIONS"]
BudgetCategory = Literal["CREW", "EQUIPMENT", "LOCATION", "TALENT", "POST"]
BudgetLineStatus = Literal["PLANNED", "COMMITTED"]
DeliverableStatus = Literal[
    "PENDING", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "HANDED_OVER"
]
ReviewStatus = Literal["DRAFT", "SUBMITTED", "APPROVED", "CHANGES_REQUESTED", "SUPERSEDED"]
TechnicalStatus = Literal["PENDING_QC", "QC_PASSED", "QC_FAILED"]
ChangeOrderStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "VOIDED"]
ChangeOrderTrigger = Literal["REVISION_ROUND_EXCEEDED", "DELIVERABLE_ADDED_AFTER_SCOPE_LOCK"]
UnionAffiliation = Literal["UNION", "NON_UNION"]
CompensationModel = Literal["USAGE_BUYOUT", "UNION_SESSION_REUSE"]
CompBasis = Literal["PROVISIONAL", "FINAL"]
EngagementStatus = Literal["DRAFT", "CONFIRMED", "COMPLETED"]
ScoutingStatus = Literal["SCOUTED", "HOLD", "CONFIRMED"]
ShootDayStatus = Literal["PLANNED", "CONFIRMED", "WRAPPED", "CANCELLED"]
CallSheetStatus = Literal["DRAFT", "PUBLISHED"]
CertType = Literal["FILM_PERMIT", "LIABILITY_COI"]
CertStatus = Literal["SUBMITTED", "ISSUED", "DENIED"]
EffectiveStatus = Literal["SUBMITTED", "ISSUED", "DENIED", "EXPIRED"]
CompliancePosture = Literal["BLOCKED", "RESTRICTED", "OPEN"]
Department = Literal["CAMERA", "GRIP_ELECTRIC", "SOUND", "ART", "PRODUCTION", "POST"]
BookingStatus = Literal["HELD", "CONFIRMED", "COMPLETED", "RELEASED"]
ReservationStatus = Literal["RESERVED", "RETURNED", "RELEASED"]


# ─── Project (PRD §3.1, §2.7, §3.10) ───────────────────────────────────────


class Project(CommonFields, total=False):
    client_name: str
    campaign_title: str
    creative_brief_summary: str
    channel_scope: list[Channel]
    usage_term_months: int
    budget_ceiling_cents: int
    contracted_revision_rounds: int
    raw_footage_retention_months: int
    raw_footage_terabytes: float
    status: ProjectStatus
    provisional_cost_cents: int
    committed_cost_cents: int
    approved_budget_cents: Optional[int]
    budget_variance_cents: int
    round_entitlement_balance: int
    review_gate: ReviewGate
    archive_status: ArchiveStatus
    handover_at: Optional[str]
    handover_recipient: Optional[str]
    retention_expires_at: Optional[str]


# ─── Budget line (PRD §3.2) ────────────────────────────────────────────────


class BudgetLine(CommonFields, total=False):
    project_id: str
    category: BudgetCategory
    description: str
    quantity: float
    unit_rate_cents: int
    markup_pct: float
    extended_cents: int
    status: BudgetLineStatus


# ─── Deliverable (PRD §3.1, §3.8) ──────────────────────────────────────────


class Deliverable(CommonFields, total=False):
    project_id: str
    title: str
    channel: Channel
    aspect_ratio: AspectRatio
    target_duration_seconds: int
    caption_requirement: CaptionRequirement
    usage_rights_months: int
    air_date: str
    status: DeliverableStatus
    consumed_review_rounds: int
    granted_extra_rounds: int
    round_entitlement: int
    version_count: int


# ─── Cut / deliverable version (PRD §3.8) ──────────────────────────────────


class DeliverableVersion(CommonFields, total=False):
    deliverable_id: str
    cut_label: str
    aspect_ratio: AspectRatio
    duration_seconds: int
    has_captions: bool
    caption_format: CaptionRequirement
    file_size_gb: float
    supersedes_version_id: Optional[str]
    round_index: int
    review_status: ReviewStatus
    technical_status: TechnicalStatus
    qc_failure_reasons: list[str]
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    review_note: Optional[str]


# ─── Change order (PRD §3.9) ───────────────────────────────────────────────


class ChangeOrder(CommonFields, total=False):
    deliverable_id: str
    trigger_reason: ChangeOrderTrigger
    additional_rounds_granted: int
    labor_cents: int
    rush_pct: float
    rush_cents: int
    subtotal_cents: int
    producer_fee_pct: float
    producer_fee_cents: int
    amount_cents: int
    status: ChangeOrderStatus
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    decision_note: Optional[str]


# ─── Talent engagement (PRD §3.3) ──────────────────────────────────────────


class TalentEngagement(CommonFields, total=False):
    project_id: str
    talent_name: str
    union_affiliation: UnionAffiliation
    compensation_model: CompensationModel
    session_fee_cents: int
    session_days: int
    status: EngagementStatus
    comp_basis: CompBasis
    channel_basis_count: int
    term_basis_months: int
    base_fee_cents: int
    usage_load_cents: int
    reuse_cycles: int
    reuse_fee_cents: int
    pension_health_cents: int
    agent_fee_cents: int
    total_comp_cents: int


# ─── Location (PRD §3.4) ───────────────────────────────────────────────────


class Location(CommonFields, total=False):
    name: str
    address: str
    stage_count: int
    daily_fee_cents: int
    insurance_minimum_cents: int
    permit_authority: str
    scouting_status: ScoutingStatus
    scheduled_shoot_day_count: int


# ─── Shoot day (PRD §3.4, §3.5, §3.6, §3.7) ────────────────────────────────


class ShootDay(CommonFields, total=False):
    project_id: str
    location_id: str
    shoot_date: str
    call_time: str
    wrap_time: str
    status: ShootDayStatus
    call_sheet_status: CallSheetStatus
    call_sheet_published_at: Optional[str]
    cancellation_reason: Optional[str]
    compliance_posture: CompliancePosture
    confirmed_crew_count: int
    day_cost_cents: int


# ─── Compliance certificate (PRD §3.5) ─────────────────────────────────────


class ComplianceCert(CommonFields, total=False):
    project_id: str
    shoot_day_id: Optional[str]
    cert_type: CertType
    carrier_or_authority: str
    reference_code: str
    effective_from: str
    effective_to: str
    coverage_amount_cents: int
    fee_cents: int
    status: CertStatus
    effective_status: EffectiveStatus
    decision_note: Optional[str]
    decided_at: Optional[str]


# ─── Crew member (PRD §3.6) ────────────────────────────────────────────────


class CrewMember(CommonFields, total=False):
    full_name: str
    department: Department
    hourly_rate_cents: int
    union_local: Optional[str]
    min_turnaround_hours: int


# ─── Crew booking (PRD §3.6) ───────────────────────────────────────────────


class CrewBooking(CommonFields, total=False):
    shoot_day_id: str
    crew_member_id: str
    department_role: str
    call_time: str
    wrap_time: str
    scheduled_hours: float
    straight_time_cents: int
    overtime_tier1_cents: int
    overtime_tier2_cents: int
    cost_cents: int
    status: BookingStatus
    release_reason: Optional[str]


# ─── Equipment reservation (PRD §3.6) ──────────────────────────────────────


class EquipmentReservation(CommonFields, total=False):
    shoot_day_id: str
    vendor_name: str
    kit_label: str
    unit_count: int
    daily_rate_cents: int
    pickup_at: str
    return_at: str
    rental_days: int
    total_cost_cents: int
    status: ReservationStatus


# Every resource the PRD §2.4 sentence enumerates, for the common-field sweep.
ALL_RESOURCE_SHAPES: tuple[Any, ...] = (
    Project,
    BudgetLine,
    Deliverable,
    DeliverableVersion,
    ChangeOrder,
    TalentEngagement,
    Location,
    ShootDay,
    ComplianceCert,
    CrewMember,
    CrewBooking,
    EquipmentReservation,
)
