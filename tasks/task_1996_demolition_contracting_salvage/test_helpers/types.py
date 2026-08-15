"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.7, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SURVEY_PHASE = "SURVEY_PHASE"
    PRECONDITIONS_PENDING = "PRECONDITIONS_PENDING"
    RELEASED = "RELEASED"
    DEMOLITION_ACTIVE = "DEMOLITION_ACTIVE"
    DEBRIS_CLEARANCE = "DEBRIS_CLEARANCE"
    BACKFILL_PHASE = "BACKFILL_PHASE"
    FINAL_REVIEW = "FINAL_REVIEW"
    CLOSED = "CLOSED"


class WorkPosture(str, Enum):
    WORKABLE = "WORKABLE"
    STOPPED = "STOPPED"


class DiversionTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class StructureSurveyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class SurveyType(str, Enum):
    INITIAL = "INITIAL"
    ADDENDUM = "ADDENDUM"


class AbatementStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ABATEMENT_ACTIVE = "ABATEMENT_ACTIVE"
    CLEARANCE_PENDING = "CLEARANCE_PENDING"
    CLEARANCE_CERTIFIED = "CLEARANCE_CERTIFIED"
    CLEARANCE_FAILED = "CLEARANCE_FAILED"


class MaterialType(str, Enum):
    ASBESTOS = "ASBESTOS"
    LEAD_PAINT = "LEAD_PAINT"
    PCB = "PCB"
    MERCURY = "MERCURY"
    OTHER = "OTHER"


class DisconnectStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORTED_DISCONNECTED = "REPORTED_DISCONNECTED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    FIELD_VERIFIED = "FIELD_VERIFIED"
    VERIFICATION_REJECTED = "VERIFICATION_REJECTED"
    CONFIRMED = "CONFIRMED"


class UtilityType(str, Enum):
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"
    WATER = "WATER"
    SEWER = "SEWER"
    TELECOM = "TELECOM"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EngineeringSurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"


class DemolitionMethod(str, Enum):
    IMPLOSION = "IMPLOSION"
    HIGH_REACH_ARM = "HIGH_REACH_ARM"
    MECHANICAL = "MECHANICAL"
    SELECTIVE_DECONSTRUCTION = "SELECTIVE_DECONSTRUCTION"


class StabilityRating(str, Enum):
    STABLE = "STABLE"
    CONDITIONALLY_STABLE = "CONDITIONALLY_STABLE"
    UNSTABLE = "UNSTABLE"


class SalvageManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class ValuationPolicy(str, Enum):
    OPTIMISTIC = "OPTIMISTIC"
    CONSERVATIVE = "CONSERVATIVE"


class SalvageMaterial(str, Enum):
    STEEL = "STEEL"
    COPPER = "COPPER"
    BRICK = "BRICK"
    TIMBER = "TIMBER"
    CONCRETE = "CONCRETE"
    FIXTURES = "FIXTURES"


class SalvageUnit(str, Enum):
    TON = "TON"
    LB = "LB"
    EACH = "EACH"
    CU_YD = "CU_YD"


class NotificationStatus(str, Enum):
    PENDING_DELIVERY = "PENDING_DELIVERY"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class NoticeMethod(str, Enum):
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    DOOR_HANGER = "DOOR_HANGER"
    POSTING = "POSTING"


class ReadingType(str, Enum):
    PM25 = "PM25"
    PM10 = "PM10"
    NOISE_DB = "NOISE_DB"


class DebrisTicketStatus(str, Enum):
    MANIFESTED = "MANIFESTED"
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class FacilityType(str, Enum):
    LANDFILL = "LANDFILL"
    RECYCLING = "RECYCLING"
    TRANSFER = "TRANSFER"


class MaterialClass(str, Enum):
    CONCRETE = "CONCRETE"
    METAL = "METAL"
    WOOD = "WOOD"
    MIXED_CD = "MIXED_CD"


class BackfillPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    COMPACTION_VERIFIED = "COMPACTION_VERIFIED"
    EROSION_VERIFIED = "EROSION_VERIFIED"
    COMPLETE = "COMPLETE"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    FINAL_LOT = "FINAL_LOT"
    EROSION_CLOSEOUT = "EROSION_CLOSEOUT"


class UserRole(str, Enum):
    CONTRACTOR_ADMIN = "ContractorAdmin"
    SITE_SUPERVISOR = "SiteSupervisor"
    SURVEYOR = "Surveyor"
    ABATEMENT_SUPERVISOR = "AbatementSupervisor"
    CLEARANCE_OFFICER = "ClearanceOfficer"
    UTILITY_COORDINATOR = "UtilityCoordinator"
    PERMIT_COORDINATOR = "PermitCoordinator"
    AUTHORITY_REVIEWER = "AuthorityReviewer"
    STRUCTURAL_ENGINEER = "StructuralEngineer"
    PEER_REVIEW_ENGINEER = "PeerReviewEngineer"
    SALVAGE_ESTIMATOR = "SalvageEstimator"
    ENVIRONMENTAL_MONITOR = "EnvironmentalMonitor"
    HAULING_DISPATCHER = "HaulingDispatcher"
    MUNICIPAL_INSPECTOR = "MunicipalInspector"


class Project(TypedDict, total=False):
    id: str
    name: str
    address: str
    lot_area_sqft: int
    required_diversion_rate: float
    blackout_dates: List[str]
    status: str
    work_posture: str
    pinned_engineering_survey_id: Optional[str]
    pinned_engineering_revision: Optional[int]
    cumulative_exposure_score: float
    in_transit_tons: float
    landfill_tons: float
    diverted_tons: float
    removed_tons: float
    diversion_rate: float
    diversion_tier: str
    created_at: str
    updated_at: str
    version: int


class StructureSurvey(TypedDict, total=False):
    id: str
    project_id: str
    structure_label: str
    survey_type: str
    status: str
    hazmat_found: bool
    findings_summary: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazmatAbatement(TypedDict, total=False):
    id: str
    structure_survey_id: str
    material_type: str
    description: str
    containment_method: str
    status: str
    started_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilityDisconnect(TypedDict, total=False):
    id: str
    project_id: str
    utility_type: str
    provider_name: str
    disconnect_window_start: str
    disconnect_window_end: str
    disconnect_status: str
    verification_status: str
    reported_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemolitionPermit(TypedDict, total=False):
    id: str
    project_id: str
    permit_number: str
    gross_floor_area_sqft: int
    fee_cents: int
    status: str
    revision_count: int
    renewal_count: int
    activated_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngineeringSurvey(TypedDict, total=False):
    id: str
    project_id: str
    revision_number: int
    demolition_method: str
    structural_stability_rating: str
    max_structure_height_ft: int
    adjacent_structure_distance_ft: int
    author_user_id: str
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SalvageManifest(TypedDict, total=False):
    id: str
    project_id: str
    valuation_policy: str
    processing_fee_cents: int
    status: str
    optimistic_total_cents: int
    conservative_total_cents: int
    net_credit_cents: int
    amendment_count: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvageItem(TypedDict, total=False):
    id: str
    salvage_manifest_id: str
    material: str
    description: str
    quantity: int
    unit: str
    low_unit_value_cents: int
    high_unit_value_cents: int
    is_amendment_line: bool
    extended_value_cents: int
    created_at: str
    updated_at: str
    version: int


class NeighborNotification(TypedDict, total=False):
    id: str
    project_id: str
    address: str
    notice_method: str
    scheduled_delivery_date: str
    status: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DustNoiseLog(TypedDict, total=False):
    # Append-only event: carries id + created_at only — NO updated_at, NO version.
    id: str
    project_id: str
    reading_type: str
    measured_value: float
    wind_speed_mph: float
    duration_hours: float
    exposure_score: float
    is_exceedance: bool
    recorded_at: str
    created_at: str


class DebrisTicket(TypedDict, total=False):
    id: str
    project_id: str
    ticket_number: str
    facility_type: str
    material_class: str
    gross_tons: float
    diverted_tons: float
    disposed_tons: float
    status: str
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackfillPlan(TypedDict, total=False):
    id: str
    project_id: str
    design_disturbed_area_sqft: int
    planned_protected_area_sqft: int
    fill_volume_cu_yd: int
    required_compaction_pct: float
    status: str
    provisional_coverage_ratio: float
    compaction_pct_achieved: Optional[float]
    measured_disturbed_area_sqft: Optional[int]
    measured_protected_area_sqft: Optional[int]
    final_coverage_ratio: float
    created_at: str
    updated_at: str
    version: int


class FinalInspection(TypedDict, total=False):
    id: str
    project_id: str
    inspection_type: str
    scheduled_date: str
    status: str
    attempt_count: int
    inspector_note: str
    passed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
