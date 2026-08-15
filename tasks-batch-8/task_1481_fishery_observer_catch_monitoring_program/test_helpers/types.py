"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    OBSERVER = "Observer"
    DEBRIEFER = "Debriefer"
    VESSEL_OPERATOR = "VesselOperator"
    EM_REVIEWER = "EMReviewer"


class FisheryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VesselOperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PaymentStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"


class VesselStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MonitoringMode(str, Enum):
    HUMAN_OBSERVER = "HUMAN_OBSERVER"
    ELECTRONIC_MONITORING = "ELECTRONIC_MONITORING"


class GearType(str, Enum):
    TRAWL = "TRAWL"
    LONGLINE = "LONGLINE"
    POT = "POT"
    GILLNET = "GILLNET"


class CertificationLevel(str, Enum):
    TRAINEE = "TRAINEE"
    CERTIFIED = "CERTIFIED"
    LEAD = "LEAD"


class ObserverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECERTIFIED = "DECERTIFIED"


class DebrieferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EMReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CoveragePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SELECTION_COMPLETED = "SELECTION_COMPLETED"
    CLOSED = "CLOSED"


class SelectionNoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    VOIDED = "VOIDED"


class DeploymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SAFETY_HOLD = "SAFETY_HOLD"
    READY_TO_DEPLOY = "READY_TO_DEPLOY"
    AT_SEA = "AT_SEA"
    RETURNED = "RETURNED"
    EARLY_TERMINATED = "EARLY_TERMINATED"
    DEBRIEFING = "DEBRIEFING"
    DATA_REJECTED = "DATA_REJECTED"
    DATA_VALIDATED = "DATA_VALIDATED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SafetyResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class HaulSampleStatus(str, Enum):
    RECORDED = "RECORDED"
    FLAGGED = "FLAGGED"
    VERIFIED = "VERIFIED"
    DISCARDED = "DISCARDED"


class HarassmentReportStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    APPEALED = "APPEALED"
    DISMISSED = "DISMISSED"
    RESOLVED = "RESOLVED"


class EMEnrollmentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EMTripStatus(str, Enum):
    DECLARED = "DECLARED"
    FOOTAGE_SUBMITTED = "FOOTAGE_SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    REVIEWED = "REVIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class FeeVariant(str, Enum):
    STANDARD = "STANDARD"
    SMALL_VESSEL = "SMALL_VESSEL"


class Fishery(TypedDict, total=False):
    id: str
    code: str
    name: str
    region: str
    coverage_target_pct: float
    priority_gear: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VesselOperator(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    contact_person_ref: str
    payment_standing: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    operator_id: str
    fishery_id: str
    vessel_name: str
    permit_number: str
    home_port: str
    length_ft: float
    gear_type: str
    declared_annual_revenue_cents: Optional[int]
    monitoring_mode: str
    selection_penalty_points: int
    substantiated_harassment_count: int
    last_observed_end_date: Optional[str]
    sea_days_observed_ytd: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Observer(TypedDict, total=False):
    id: str
    person_ref: str
    full_name: str
    home_port: str
    certification_level: str
    max_consecutive_sea_days: int
    sea_days_used_ytd: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Debriefer(TypedDict, total=False):
    id: str
    person_ref: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EMReviewer(TypedDict, total=False):
    id: str
    person_ref: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoveragePlan(TypedDict, total=False):
    id: str
    fishery_id: str
    period_start: str
    period_end: str
    projected_fleet_effort_days: int
    projected_em_effort_days: int
    required_observer_sea_days: Optional[int]
    actual_fleet_effort_days: Optional[int]
    final_required_observer_sea_days: Optional[int]
    actual_observer_sea_days: int
    actual_em_sea_days: int
    coverage_attainment_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SelectionRun(TypedDict, total=False):
    id: str
    coverage_plan_id: str
    run_index: int
    notice_response_deadline: str
    vessels_evaluated: int
    vessels_selected: int
    selection_deficit_sea_days: int
    created_at: str
    updated_at: str
    version: int


class SelectionNotice(TypedDict, total=False):
    id: str
    selection_run_id: str
    coverage_plan_id: str
    vessel_id: str
    allocated_sea_days: int
    reserved_sea_days: int
    consumed_sea_days: int
    remaining_sea_days: int
    selection_score: float
    rank: int
    response_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict, total=False):
    id: str
    selection_notice_id: str
    coverage_plan_id: str
    vessel_id: str
    observer_id: str
    assigned_debriefer_id: Optional[str]
    scheduled_departure_date: str
    scheduled_return_date: str
    planned_sea_days: int
    actual_return_date: Optional[str]
    actual_sea_days: Optional[int]
    latest_safety_result: Optional[str]
    early_termination_reason: Optional[str]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict, total=False):
    # Append-only record (PRD §2.4): carries only id + created_at, never
    # updated_at / version.
    id: str
    deployment_id: str
    vessel_id: str
    observer_id: str
    life_raft_certified: bool
    epirb_registered: bool
    immersion_suits_adequate: bool
    fire_suppression_ok: bool
    comms_equipment_ok: bool
    deficiency_notes: Optional[str]
    supersedes_inspection_id: Optional[str]
    result: str
    created_at: str


class HaulSample(TypedDict, total=False):
    id: str
    deployment_id: str
    haul_date: str
    haul_number: int
    species_code: str
    sampled_weight_kg: float
    total_haul_weight_kg: float
    sampling_ratio: float
    flagged_reason: Optional[str]
    verified_by_debriefer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HarassmentReport(TypedDict, total=False):
    id: str
    deployment_id: str
    observer_id: str
    vessel_id: str
    report_type: str
    narrative: str
    incident_date: str
    penalty_applied: bool
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EMEnrollment(TypedDict, total=False):
    id: str
    vessel_id: str
    equipment_vendor: str
    equipment_install_date: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EMTrip(TypedDict, total=False):
    id: str
    vessel_id: str
    em_enrollment_id: str
    assigned_reviewer_id: Optional[str]
    departure_date: str
    return_date: str
    trip_sea_days: int
    video_hours: Optional[float]
    reviewed_hours: float
    reviewed_pct: Optional[float]
    sampled_catch_kg: float
    estimated_total_catch_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    coverage_plan_id: str
    vessel_id: str
    operator_id: str
    fee_variant: str
    sea_days_billed: int
    line_items: list
    amount_due_cents: int
    fee_cap_applied: bool
    amount_paid_cents: int
    amount_adjusted_cents: int
    amount_outstanding_cents: int
    issued_by_user_id: Optional[str]
    issue_date: Optional[str]
    due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
