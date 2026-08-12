"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class ProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED_OUT = "CLOSED_OUT"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class MeasurementBasis(str, Enum):
    IN_PLACE = "IN_PLACE"
    SCOW = "SCOW"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"


class ReachStatus(str, Enum):
    PENDING = "PENDING"
    PRE_SURVEYED = "PRE_SURVEYED"
    DREDGING = "DREDGING"
    POST_SURVEY_SUBMITTED = "POST_SURVEY_SUBMITTED"
    ACCEPTED = "ACCEPTED"


class PlantType(str, Enum):
    CUTTER_SUCTION = "CUTTER_SUCTION"
    HOPPER = "HOPPER"
    CLAMSHELL = "CLAMSHELL"
    BACKHOE = "BACKHOE"


class PlantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class MaterialClass(str, Enum):
    SAND = "SAND"
    SILT = "SILT"
    CLAY = "CLAY"
    GRAVEL = "GRAVEL"
    ROCK = "ROCK"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class SurveyKind(str, Enum):
    PRE_DREDGE = "PRE_DREDGE"
    POST_DREDGE = "POST_DREDGE"


class SurveyStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class EventStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHUTDOWN = "SHUTDOWN"
    COMPLETED = "COMPLETED"


class ShutdownReason(str, Enum):
    SPECIES = "SPECIES"
    TURBIDITY = "TURBIDITY"
    EQUIPMENT = "EQUIPMENT"
    WINDOW = "WINDOW"


class SiteType(str, Enum):
    UPLAND_CONFINED = "UPLAND_CONFINED"
    OPEN_WATER = "OPEN_WATER"
    BEACH_NOURISHMENT = "BEACH_NOURISHMENT"


class SiteStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class TicketStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ClaimReason(str, Enum):
    WEATHER = "WEATHER"
    SPECIES_SHUTDOWN = "SPECIES_SHUTDOWN"
    OWNER_DIRECTED = "OWNER_DIRECTED"
    EQUIPMENT_BREAKDOWN = "EQUIPMENT_BREAKDOWN"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class SpeciesClass(str, Enum):
    FISH = "FISH"
    MAMMAL = "MAMMAL"
    REPTILE = "REPTILE"
    BIRD = "BIRD"


class SightingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class CertificateType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AUDIT_HOLD = "AUDIT_HOLD"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    OWNER_ENGINEER = "OwnerEngineer"
    CONTRACTOR_OPS = "ContractorOps"
    SURVEY_PARTY = "SurveyParty"
    ENVIRONMENTAL_MONITOR = "EnvironmentalMonitor"
    SITE_OPERATOR = "SiteOperator"


# --- Entity TypedDicts -------------------------------------------------------
# Every resource except TurbidityReading carries id + created_at + updated_at +
# version (PRD §2.5). TurbidityReading is append-only: id + created_at only.


class Project(TypedDict, total=False):
    id: str
    name: str
    measurement_basis: str
    base_rate_cents_per_cy: int
    standby_rate_cents_per_hour: int
    liquidated_damages_cents_per_day: int
    status: str
    compliance_posture: str
    allowed_days_frozen: Optional[int]
    total_certified_cents: int
    total_paid_cents: int
    outstanding_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    project_id: str
    permit_number: str
    window_start_utc: str
    window_end_utc: str
    turbidity_limit_ntu: int
    turbidity_ceiling_ntu: int
    turbidity_averaging_hours: int
    species_standdown_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reach(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    design_quantity_cy: int
    required_depth_ft: float
    allowable_overdepth_ft: float
    overdepth_allowance_cy: int
    status: str
    removed_in_place_cy: float
    cumulative_certified_quantity_cy: float
    created_at: str
    updated_at: str
    version: int


class DredgePlant(TypedDict, total=False):
    id: str
    contractor_ref: str
    plant_type: str
    rated_daily_production_cy: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DredgePlan(TypedDict, total=False):
    id: str
    project_id: str
    plant_id: str
    material_class: str
    planned_start_utc: str
    planned_end_utc: str
    revision: int
    nominal_daily_production_cy: float
    risk_adjusted_daily_production_cy: float
    nominal_duration_days: int
    risk_adjusted_duration_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    reach_id: str
    kind: str
    measured_volume_cy: int
    min_sounding_depth_ft: float
    supersedes_survey_id: Optional[str]
    submitted_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DredgeEvent(TypedDict, total=False):
    id: str
    reach_id: str
    plant_id: str
    started_utc: str
    reduced_rate: bool
    ended_utc: Optional[str]
    status: str
    shutdown_reason: Optional[str]
    last_shutdown_at: Optional[str]
    shutdown_accumulated_hours: float
    created_at: str
    updated_at: str
    version: int


class DisposalSite(TypedDict, total=False):
    id: str
    name: str
    site_type: str
    capacity_cy: int
    bulking_factor: float
    used_cy: float
    remaining_cy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PlacementTicket(TypedDict, total=False):
    id: str
    dredge_event_id: str
    disposal_site_id: str
    placed_utc: str
    declared_volume_cy: int
    witnessed_volume_cy: int
    reported_by_user_id: str
    in_situ_volume_cy: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StandbyClaim(TypedDict, total=False):
    id: str
    project_id: str
    plant_id: str
    period_start_utc: str
    period_end_utc: str
    claimed_hours: float
    reason: str
    payable_hours: float
    payable_amount_cents: int
    claimed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpeciesSighting(TypedDict, total=False):
    id: str
    project_id: str
    species_class: str
    observed_utc: str
    reported_by_user_id: str
    cleared_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TurbidityReading(TypedDict, total=False):
    # Append-only (PRD §2.5): carries ONLY id + created_at — no updated_at,
    # no version.
    id: str
    project_id: str
    value_ntu: int
    taken_utc: str
    recorded_by_user_id: str
    created_at: str


class PaymentCertificate(TypedDict, total=False):
    id: str
    project_id: str
    certificate_type: str
    period_start_utc: str
    period_end_utc: str
    reach_ids: List[str]
    standby_claim_ids: List[str]
    quantity_cy: float
    quantity_amount_cents: int
    standby_amount_cents: int
    liquidated_damages_cents: int
    reconciliation_delta_pct: float
    survey_derived_total_cy: float
    scow_derived_total_cy: float
    total_amount_cents: int
    submitted_by_user_id: str
    override_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
