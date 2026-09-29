"""Entity shapes, enumerations and role names for the turf management API.

The TypedDicts mirror the response representations described in the PRD; they are
`total=False` because tests routinely inspect a subset of the payload.
"""

from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class Role:
    FIELD_OPERATIONS_COORDINATOR = "FieldOperationsCoordinator"
    TURF_AGRONOMIST = "TurfAgronomist"
    SAFETY_INSPECTOR = "SafetyInspector"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    FACILITIES_DIRECTOR = "FacilitiesDirector"


ALL_ROLES = (
    Role.FIELD_OPERATIONS_COORDINATOR,
    Role.TURF_AGRONOMIST,
    Role.SAFETY_INSPECTOR,
    Role.CERTIFICATION_OFFICER,
    Role.FACILITIES_DIRECTOR,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SurfaceType:
    NATURAL_GRASS = "NATURAL_GRASS"
    SYNTHETIC_TURF = "SYNTHETIC_TURF"


class SanctionedLevel:
    NONE = "NONE"
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    STATE = "STATE"


class PlayStatus:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED_ADMIN = "CLOSED_ADMIN"
    CLOSED_UNSAFE = "CLOSED_UNSAFE"
    RETIRED = "RETIRED"


class CertificationStatus:
    NOT_CERTIFIED = "NOT_CERTIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    CERTIFIED = "CERTIFIED"
    EXPIRED = "EXPIRED"


class WarrantyStatus:
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ClosureAction:
    CLOSE_ADMIN = "CLOSE_ADMIN"
    REOPEN_ADMIN = "REOPEN_ADMIN"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TaskType:
    AERATION = "AERATION"
    OVERSEEDING = "OVERSEEDING"
    FERTILITY = "FERTILITY"
    IRRIGATION = "IRRIGATION"
    GROOMING = "GROOMING"
    INFILL_REDISTRIBUTION = "INFILL_REDISTRIBUTION"
    SEAM_INSPECTION = "SEAM_INSPECTION"


class TaskStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskAction:
    START = "START"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"


class AssessmentType:
    IMPACT_ATTENUATION = "IMPACT_ATTENUATION"
    GOAL_ANCHORING = "GOAL_ANCHORING"
    STRIPING_LAYOUT = "STRIPING_LAYOUT"


class AssessmentStatus:
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class AssessmentResult:
    PASS = "PASS"
    ADVISORY = "ADVISORY"
    FAIL = "FAIL"


class OrderSeverity:
    MANDATORY = "MANDATORY"
    ADVISORY = "ADVISORY"


class OrderStatus:
    OPEN = "OPEN"
    VERIFICATION_SUBMITTED = "VERIFICATION_SUBMITTED"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    CANCELLED = "CANCELLED"


class VerificationDecision:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ActivityType:
    PRACTICE = "PRACTICE"
    GAME = "GAME"
    TOURNAMENT = "TOURNAMENT"
    COMMUNITY = "COMMUNITY"


class BookingStatus:
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    PLAYED = "PLAYED"
    RAINED_OUT = "RAINED_OUT"
    CANCELLED_LATE = "CANCELLED_LATE"
    CANCELLED_UNSAFE = "CANCELLED_UNSAFE"


class BookingOutcome:
    PLAYED = "PLAYED"
    RAINED_OUT = "RAINED_OUT"
    CANCELLED_LATE = "CANCELLED_LATE"


class WeatherCondition:
    DRY = "DRY"
    WET = "WET"


class LedgerEntryType:
    PLAY_WEAR = "PLAY_WEAR"
    LATE_CANCEL_WEAR = "LATE_CANCEL_WEAR"
    RAIN_OUT_RELIEF = "RAIN_OUT_RELIEF"
    RECOVERY_CREDIT = "RECOVERY_CREDIT"
    UNSAFE_CANCELLATION = "UNSAFE_CANCELLATION"


class PacketStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class PacketDecision:
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class BudgetStatus:
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class PriorityBasis:
    REMAINING_LIFE = "REMAINING_LIFE"
    CONDITION_RISK = "CONDITION_RISK"


class FundingStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class DisposalStatus:
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    MANIFESTED = "MANIFESTED"
    COMPLETED = "COMPLETED"


class PlanDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RESCIND = "RESCIND"


# ---------------------------------------------------------------------------
# Entity representations
# ---------------------------------------------------------------------------


class Field(TypedDict, total=False):
    id: str
    name: str
    surface_type: str
    installed_on_date: str
    expected_life_years: int
    area_sq_ft: int
    sanctioned_level: str
    warranty_expires_on: Optional[str]
    infill_depth_mm: Optional[float]
    predecessor_field_id: Optional[str]
    age_years: float
    warranty_status: str
    play_status: str
    certification_status: str
    certified_until_utc: Optional[str]
    admin_closure_active: bool
    admin_closure_reason_code: Optional[str]
    retired_at: Optional[str]
    open_mandatory_remediation_count: int
    open_advisory_remediation_count: int
    open_certification_packet_count: int
    open_replacement_plan_count: int
    unsafe_cancellation_count: int
    cumulative_wear_units: float
    usage_hours_ytd: float
    rest_debt_hours: float
    nitrogen_applied_ytd_lb_per_1000_sq_ft: float
    latest_gmax_mean_value: Optional[float]
    condition_index_agronomic: float
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    roles: List[str]
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceTask(TypedDict, total=False):
    id: str
    field_id: str
    assigned_staff_member_id: str
    task_type: str
    surface_class: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    nitrogen_lb_per_1000_sq_ft: Optional[float]
    planned_for_certification_window: bool
    recovery_credit_hours: float
    status: str
    started_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyAssessment(TypedDict, total=False):
    id: str
    field_id: str
    inspector_staff_member_id: str
    assessment_type: str
    assessed_at_utc: str
    gmax_readings: Optional[List[float]]
    gmax_mean_value: Optional[float]
    declared_result: Optional[str]
    result: str
    status: str
    superseded_at_utc: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationOrder(TypedDict, total=False):
    id: str
    field_id: str
    source_assessment_id: str
    severity: str
    status: str
    opened_at_utc: str
    closed_at_utc: Optional[str]
    rejection_count: int
    verification_assessment_id: Optional[str]
    submitted_by_staff_member_id: Optional[str]
    remediation_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageBooking(TypedDict, total=False):
    id: str
    field_id: str
    requested_by_staff_member_id: str
    activity_type: str
    window_start_utc: str
    window_end_utc: str
    expected_participant_count: int
    status: str
    outcome: Optional[str]
    actual_duration_hours: Optional[float]
    actual_participant_count: Optional[int]
    weather_condition: Optional[str]
    wear_load_units: Optional[float]
    rest_requirement_hours: Optional[float]
    started_with_rest_debt: Optional[bool]
    confirmed_at_utc: Optional[str]
    closed_out_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageLedgerEntry(TypedDict, total=False):
    """A ledger entry carries only `id` and `created_at` from the common set."""

    id: str
    field_id: str
    booking_id: Optional[str]
    maintenance_task_id: Optional[str]
    entry_type: str
    wear_units_delta: float
    rest_requirement_hours: Optional[float]
    rest_credit_hours: Optional[float]
    rest_window_end_utc: Optional[str]
    running_balance_after: float
    effective_at_utc: str
    note: str
    created_at: str


class CertificationPacket(TypedDict, total=False):
    id: str
    field_id: str
    governing_assessment_id: str
    competition_season_label: str
    status: str
    documentation_completeness_score: Optional[float]
    condition_index_certification: Optional[float]
    submitted_by_staff_member_id: Optional[str]
    decided_by_staff_member_id: Optional[str]
    submitted_at_utc: Optional[str]
    decided_at_utc: Optional[str]
    certified_until_utc: Optional[str]
    decision_notes: Optional[str]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class CapitalBudget(TypedDict, total=False):
    id: str
    fiscal_year: int
    total_authorized_amount_cents: int
    committed_amount_cents: int
    available_amount_cents: int
    lock_threshold_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementPlan(TypedDict, total=False):
    id: str
    field_id: str
    capital_budget_id: str
    target_surface_type: str
    area_sq_ft: int
    priority_basis: str
    planned_install_year: int
    base_construction_cents: int
    disposal_cents: int
    pre_contingency_subtotal_cents: int
    contingency_rate: float
    contingency_cents: int
    plan_funding_amount_cents: int
    replacement_priority_score: float
    funding_status: str
    disposal_status: str
    manifest_reference: Optional[str]
    disposal_facility_name: Optional[str]
    diverted_tonnage: Optional[float]
    total_tonnage: Optional[float]
    diversion_ratio: Optional[float]
    submitted_by_staff_member_id: Optional[str]
    decided_by_staff_member_id: Optional[str]
    submitted_at_utc: Optional[str]
    decided_at_utc: Optional[str]
    completed_at_utc: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict, total=False):
    current_utc: str
    fields_recomputed: int
