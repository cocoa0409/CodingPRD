"""Typed shapes for the facilities capacity API resources.

Only `ClassSizePolicy`, `EnrollmentProjection` and `DisposalRecord` are
append-only ledgers: they carry `id` and `created_at` only, with no
`updated_at` and no `version`.
"""

from __future__ import annotations

from typing import List, Literal, Optional, TypedDict

UserRole = Literal[
    "DistrictAdmin",
    "FacilitiesPlanner",
    "CapacityCertifier",
    "PermitCoordinator",
    "BuildingOfficial",
    "OperationsScheduler",
    "AssetManager",
    "CrewLead",
]

GradeConfiguration = Literal["ELEMENTARY_K5", "MIDDLE_68", "HIGH_912", "K8_COMBINED"]
GradeBand = Literal["K_3", "G4_6", "G7_8", "G9_12"]
RoomType = Literal[
    "STANDARD_CLASSROOM",
    "SCIENCE_LAB",
    "SPED_RESOURCE",
    "ART_MUSIC",
    "GYM",
    "LIBRARY",
    "ADMIN",
]
RoomStatus = Literal["IN_SERVICE", "OUT_OF_SERVICE_RENOVATION", "DECOMMISSIONED"]
ProgramType = Literal[
    "SPED_SELF_CONTAINED", "DUAL_LANGUAGE", "TITLE_I_INTERVENTION", "CTE_LAB"
]
ProjectionSource = Literal["COHORT_SURVIVAL", "DEVELOPER_YIELD"]
ConfidenceTier = Literal["HIGH", "MEDIUM", "LOW"]

StudyMethod = Literal["STATE_LOADING_STANDARD", "DISTRICT_POLICY"]
StudyStatus = Literal["DRAFT", "SUBMITTED", "RETURNED", "CERTIFIED", "SUPERSEDED"]

SizeClass = Literal["SINGLE_24x40", "DOUBLE_28x64", "TRIPLE_36x64"]
ConditionGrade = Literal["A", "B", "C", "D"]
ConditionStatus = Literal["SERVICEABLE", "NEEDS_REHAB", "UNSAFE"]
AllocationStatus = Literal[
    "IN_STORAGE", "RESERVED", "SCHEDULED", "INSTALLED", "PENDING_REMOVAL", "DISPOSED"
]

FeasibilityStatus = Literal[
    "UNASSESSED", "FEASIBLE", "FEASIBLE_WITH_MITIGATION", "INFEASIBLE"
]
InfeasibleReason = Literal["PAD_TOO_SMALL", "FIRE_ACCESS"]
MitigationFlag = Literal["ELECTRICAL_UPGRADE", "SEWER_HOOKUP", "ADA_PATH_UPGRADE"]

RequestStatus = Literal[
    "DRAFT",
    "SITE_ASSESSED",
    "PERMIT_PENDING",
    "PERMITTED",
    "SCHEDULED",
    "INSTALLED",
    "DECOMMISSION_REQUESTED",
    "DECOMMISSIONED",
    "REJECTED",
    "WITHDRAWN",
]
CostRecommendation = Literal["RELOCATE", "BOUNDARY_CHANGE", "PERMANENT_ADDITION"]
CostBasis = Literal["LIFECYCLE_20YR", "IMMEDIATE_CAPITAL"]

PermitType = Literal[
    "DSA_STRUCTURAL", "FIRE_MARSHAL", "ELECTRICAL", "PLUMBING", "ADA_ACCESS"
]
PermitStatus = Literal["SUBMITTED", "CORRECTIONS_REQUIRED", "APPROVED", "DENIED"]
PermitDecision = Literal["APPROVED", "CORRECTIONS_REQUIRED", "DENIED"]

WorkType = Literal["SET", "RELOCATE"]
ScheduleStatus = Literal["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]

DisposalMethod = Literal["SALE", "SCRAP", "TRANSFER_TO_COUNTY"]
ValuationBasis = Literal["STRAIGHT_LINE", "CONDITION_ADJUSTED"]
RelianceFlag = Literal["NONE", "MONITOR", "LONG_TERM_RELIANCE"]


class _Versioned(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class _Ledger(TypedDict):
    id: str
    created_at: str


class School(_Versioned):
    name: str
    grade_configuration: GradeConfiguration
    site_acreage: float
    fire_lane_clear_width_ft: float
    electrical_spare_capacity_kw: float
    sewer_spare_connections: int
    consecutive_reliance_years: int
    hosted_portable_seats: int
    reliance_flag: RelianceFlag
    certified_study_id: Optional[str]


class ClassSizePolicy(_Ledger):
    grade_band: GradeBand
    effective_school_year: str
    max_class_size: int
    min_area_sqft_per_seat: float
    lab_area_premium_sqft: float


class Room(_Versioned):
    school_id: str
    room_number: str
    room_type: RoomType
    area_sqft: float
    status: RoomStatus


class ProgramSetAside(_Versioned):
    school_id: str
    program_type: ProgramType
    reserved_room_type: RoomType
    reserved_room_count: int
    seats_excluded_per_room: int


class EnrollmentProjection(_Ledger):
    school_id: str
    school_year: str
    grade_level: int
    projected_students: int
    source: ProjectionSource
    confidence_tier: ConfidenceTier


class CapacityStudy(_Versioned):
    school_id: str
    class_size_policy_id: str
    school_year: str
    method: StudyMethod
    status: StudyStatus
    revision_round: int
    authored_by_user_id: str
    certified_by_user_id: Optional[str]
    certified_on: Optional[str]
    submitted_on: Optional[str]
    gross_room_seats: int
    set_aside_deduction_seats: int
    program_capacity_seats: int
    projected_enrollment_total: int
    utilization_pct: float
    portable_trigger_met: bool
    seat_deficit: int
    required_portable_count: int


class PortableUnit(_Versioned):
    asset_tag: str
    size_class: SizeClass
    condition_grade: ConditionGrade
    condition_status: ConditionStatus
    allocation_status: AllocationStatus
    rated_seats: int
    acquisition_cost_cents: int
    in_service_year: int
    ada_ramp_installed: bool
    replaced_unit_id: Optional[str]
    lifetime_relocation_count: int
    accumulated_relocation_cost_cents: int
    current_school_id: Optional[str]


class PlacementSite(_Versioned):
    school_id: str
    pad_code: str
    pad_length_ft: float
    pad_width_ft: float
    distance_to_fire_lane_ft: float
    electrical_drop_available_kw: float
    sewer_connection_available: bool
    ada_path_of_travel_compliant: bool
    feasibility_status: FeasibilityStatus
    infeasible_reason: Optional[InfeasibleReason]
    mitigation_flags: List[MitigationFlag]
    assessed_for_size_class: Optional[SizeClass]
    occupied_by_unit_id: Optional[str]


class CapitalBudget(_Versioned):
    fiscal_year: str
    authorized_cents: int
    encumbered_cents: int
    expended_cents: int
    uncommitted_cents: int


class InstallationCrew(_Versioned):
    name: str
    max_concurrent_jobs: int
    certified_work_types: List[WorkType]


class PlacementRequest(_Versioned):
    capacity_study_id: str
    placement_site_id: str
    capital_budget_id: str
    portable_unit_id: Optional[str]
    school_id: str
    requested_window_start: str
    requested_window_end: str
    haul_miles: int
    status: RequestStatus
    required_permit_count: int
    encumbered_cost_cents: int
    estimated_relocation_cost_cents: int
    cost_recommendation: Optional[CostRecommendation]
    rejection_reason: Optional[str]


class Permit(_Versioned):
    placement_request_id: str
    permit_type: PermitType
    status: PermitStatus
    review_cycle_count: int
    submitted_on: Optional[str]
    approved_on: Optional[str]
    correction_note: Optional[str]


class InstallationSchedule(_Versioned):
    placement_request_id: str
    installation_crew_id: str
    work_type: WorkType
    window_start: str
    window_end: str
    status: ScheduleStatus
    off_summer_waiver: bool
    cancellation_reason: Optional[str]


class DisposalRecord(_Ledger):
    portable_unit_id: str
    method: DisposalMethod
    valuation_basis: ValuationBasis
    proceeds_cents: int
    salvage_value_cents: int
    net_disposal_result_cents: int
    disposed_on: str
