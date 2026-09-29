"""Domain types for the CAFO Nutrient Management API: status enums, role enum,
entity TypedDicts.

Field names mirror the PRD exactly. Two record kinds — the soil test and the
storage inspection — are immutable registers that carry only ``id`` and
``created_at``; their TypedDicts deliberately omit ``updated_at`` and
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    CERTIFIED_PLANNER = "CertifiedPlanner"
    STATE_REVIEWER = "StateReviewer"
    HAULER = "Hauler"
    COMPLIANCE_ADMIN = "ComplianceAdmin"


# --------------------------------------------------------------------------
# Input enumerations
# --------------------------------------------------------------------------
class AnimalType(str, Enum):
    DAIRY_COW = "DAIRY_COW"
    BEEF_FEEDER = "BEEF_FEEDER"
    SWINE_FINISHING = "SWINE_FINISHING"
    LAYER_HEN = "LAYER_HEN"


class ManureHandling(str, Enum):
    LIQUID = "LIQUID"
    DRY = "DRY"


class DischargePotential(str, Enum):
    NONE = "NONE"
    STORMWATER_ONLY = "STORMWATER_ONLY"
    CONTINUOUS = "CONTINUOUS"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class PermitType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GENERAL = "GENERAL"


class CoverageStatus(str, Enum):
    DRAFT_APPLICATION = "DRAFT_APPLICATION"
    SUBMITTED = "SUBMITTED"
    COVERED = "COVERED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"


class PermitComplianceStatus(str, Enum):
    IN_GOOD_STANDING = "IN_GOOD_STANDING"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"


class HaulerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class ApplicationMethod(str, Enum):
    SURFACE_BROADCAST = "SURFACE_BROADCAST"
    INCORPORATED_24H = "INCORPORATED_24H"
    INJECTION = "INJECTION"
    IRRIGATION = "IRRIGATION"


class Crop(str, Enum):
    CORN_GRAIN = "CORN_GRAIN"
    SOYBEAN = "SOYBEAN"
    ALFALFA = "ALFALFA"
    GRASS_HAY = "GRASS_HAY"


class PreviousCrop(str, Enum):
    CORN_GRAIN = "CORN_GRAIN"
    SOYBEAN = "SOYBEAN"
    ALFALFA = "ALFALFA"
    GRASS_HAY = "GRASS_HAY"
    NONE = "NONE"


class PIndexCategory(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class BindingBasis(str, Enum):
    NITROGEN = "NITROGEN"
    PHOSPHORUS = "PHOSPHORUS"


class BudgetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class StructureType(str, Enum):
    EARTHEN_LAGOON = "EARTHEN_LAGOON"
    CONCRETE_TANK = "CONCRETE_TANK"
    STACKING_PAD = "STACKING_PAD"


class StorageStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FREEBOARD_ALERT = "FREEBOARD_ALERT"
    OVERFLOW_IMMINENT = "OVERFLOW_IMMINENT"


class VisualCondition(str, Enum):
    NORMAL = "NORMAL"
    SEEPAGE = "SEEPAGE"
    EROSION = "EROSION"
    CRACKING = "CRACKING"


class SoilCondition(str, Enum):
    DRY = "DRY"
    MOIST = "MOIST"
    SATURATED = "SATURATED"
    FROZEN = "FROZEN"
    SNOW_COVERED = "SNOW_COVERED"


class EventStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class IncidentType(str, Enum):
    MORTALITY = "MORTALITY"
    DISCHARGE = "DISCHARGE"
    SPILL = "SPILL"


class DisposalMethod(str, Enum):
    COMPOSTING = "COMPOSTING"
    BURIAL = "BURIAL"
    INCINERATION = "INCINERATION"
    RENDERING = "RENDERING"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    NOTIFIED = "NOTIFIED"
    WRITTEN_SUBMITTED = "WRITTEN_SUBMITTED"
    CLOSED = "CLOSED"


class InspectionKind(str, Enum):
    ROUTINE = "ROUTINE"
    COMPLAINT = "COMPLAINT"
    FOLLOW_UP = "FOLLOW_UP"


class DeficiencyCategory(str, Enum):
    RECORDKEEPING = "RECORDKEEPING"
    FREEBOARD = "FREEBOARD"
    SETBACK = "SETBACK"
    TRANSFER_DOCUMENTATION = "TRANSFER_DOCUMENTATION"
    MORTALITY = "MORTALITY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    NOV_ISSUED = "NOV_ISSUED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLOSED = "CLOSED"


class VarianceClassification(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    EXCEEDS_TOLERANCE = "EXCEEDS_TOLERANCE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class NutrientSummaryBasis(str, Enum):
    DESIGN_BASIS = "DESIGN_BASIS"
    RECORDS_BASIS = "RECORDS_BASIS"


class CapacityProjectionBasis(str, Enum):
    AVAILABLE_BASIS = "AVAILABLE_BASIS"
    DESIGN_BASIS = "DESIGN_BASIS"


# --------------------------------------------------------------------------
# Entity shapes — records carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class Operation(TypedDict):
    id: str
    name: str
    county: str
    animal_type: str
    head_count: int
    manure_handling: str
    open_lot_area_sqft: float
    discharge_potential: str
    has_conservation_plan: bool
    animal_units: float
    size_class: str
    permit_required: bool
    design_annual_manure_gallons: float
    daily_production_gallons: float
    recorded_annual_manure_gallons: float
    design_storage_days: int
    compliance_posture: str
    open_finding_count: int
    open_discharge_incident_count: int
    created_at: str
    updated_at: str
    version: int


class Hauler(TypedDict):
    id: str
    business_name: str
    license_number: str
    license_expires_on: str
    certified_applicator: bool
    hauler_status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    operation_id: str
    permit_type: str
    effective_on: str
    expiration_on: Optional[str]
    renewal_window_opens_on: Optional[str]
    renewal_due_on: Optional[str]
    coverage_status: str
    compliance_status: str
    renewal_submitted_at: Optional[str]
    is_late_renewal: bool
    gross_fee: float
    conservation_discount_pct: float
    conservation_discount_amount: float
    net_fee: float
    late_surcharge_amount: float
    total_due: float
    created_at: str
    updated_at: str
    version: int


class NutrientManagementPlan(TypedDict):
    id: str
    operation_id: str
    permit_id: str
    plan_year: int
    supersedes_plan_id: Optional[str]
    allowed_application_methods: List[str]
    winter_application_allowed: bool
    plan_status: str
    certifying_planner_user_id: Optional[str]
    certified_at: Optional[str]
    approved_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict):
    id: str
    operation_id: str
    field_name: str
    total_acres: float
    distance_to_water_ft: float
    has_tile_inlet: bool
    slope_pct: float
    water_frontage_ft: float
    required_setback_ft: float
    excluded_acres: float
    net_applicable_acres: float
    last_application_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldNutrientBudget(TypedDict):
    id: str
    plan_id: str
    field_id: str
    soil_test_id: str
    crop: str
    yield_goal: float
    previous_crop: str
    planned_application_method: str
    crop_n_need_lbs: float
    legume_credit_lbs: float
    adjusted_n_need_lbs: float
    crop_p_removal_lbs: float
    p_allowance_lbs: float
    allowable_n_rate_gal_per_acre: float
    allowable_p_rate_gal_per_acre: float
    binding_basis: str
    allowable_rate_gal_per_acre: float
    allowable_total_gallons: float
    applied_gallons_to_date: float
    remaining_gallons: float
    budget_status: str
    created_at: str
    updated_at: str
    version: int


class ManureStorage(TypedDict):
    id: str
    operation_id: str
    structure_name: str
    structure_type: str
    surface_area_sqft: float
    total_depth_in: float
    required_freeboard_in: float
    design_capacity_gallons: float
    freeboard_reserve_gallons: float
    operating_capacity_gallons: float
    cumulative_intake_gallons: float
    precipitation_adjustment_gallons: float
    cumulative_outflow_gallons: float
    current_volume_gallons: float
    committed_outflow_gallons: float
    available_capacity_gallons: float
    days_of_storage_available: int
    storage_status: str
    last_inspected_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LandApplicationEvent(TypedDict):
    id: str
    plan_id: str
    budget_id: str
    storage_id: str
    applied_on: str
    gallons_applied: float
    acres_treated: float
    application_method: str
    setback_maintained_ft: float
    soil_condition: str
    precipitation_forecast_in_24h: float
    applicator_name: str
    rate_gal_per_acre: float
    n_applied_lbs: float
    p2o5_applied_lbs: float
    event_status: str
    created_at: str
    updated_at: str
    version: int


class ManureTransfer(TypedDict):
    id: str
    operation_id: str
    storage_id: str
    hauler_id: str
    recipient_name: str
    recipient_address: str
    transferred_on: str
    gallons_transferred: float
    nutrient_analysis_provided: bool
    recipient_n_lbs: float
    recipient_p2o5_lbs: float
    recipient_ack_signed_at: Optional[str]
    transfer_status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    operation_id: str
    incident_type: str
    subject_storage_id: Optional[str]
    subject_field_id: Optional[str]
    discovered_at: str
    description: str
    mortality_head_count: int
    disposal_method: Optional[str]
    released_gallons: float
    reached_water: bool
    requires_oral_notification: bool
    oral_notification_deadline_at: Optional[str]
    written_report_deadline_at: Optional[str]
    oral_notified_at: Optional[str]
    notification_late: Optional[bool]
    incident_status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    operation_id: str
    permit_id: str
    scheduled_on: str
    inspection_kind: str
    inspector_user_id: Optional[str]
    conducted_on: Optional[str]
    findings_count: int
    deficiency_categories: Optional[List[str]]
    response_due_on: Optional[str]
    corrective_action_summary: Optional[str]
    closed_by_user_id: Optional[str]
    inspection_status: str
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict):
    id: str
    operation_id: str
    plan_id: str
    report_year: int
    beginning_storage_gallons: float
    ending_storage_gallons: float
    variance_explanation: Optional[str]
    recorded_land_applied_gallons: float
    recorded_transferred_gallons: float
    recorded_total_gallons: float
    mass_balance_expected_gallons: float
    variance_pct: float
    variance_classification: str
    total_n_applied_lbs: float
    total_p2o5_applied_lbs: float
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    return_reason: Optional[str]
    report_status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Immutable registers — written once, carry ONLY id + created_at
# --------------------------------------------------------------------------
class SoilTest(TypedDict):
    id: str
    field_id: str
    sampled_on: str
    lab_name: str
    soil_test_p_ppm: float
    soil_test_k_ppm: float
    organic_matter_pct: float
    p_index: float
    p_index_category: str
    is_valid: bool
    created_at: str


class StorageInspection(TypedDict):
    id: str
    storage_id: str
    inspected_on: str
    inspector_name: str
    measured_freeboard_in: float
    visual_condition: str
    measured_volume_gallons: float
    freeboard_deficit_in: float
    alert_raised: bool
    created_at: str


IMMUTABLE_REGISTER_ENTITIES = ("SoilTest", "StorageInspection")
