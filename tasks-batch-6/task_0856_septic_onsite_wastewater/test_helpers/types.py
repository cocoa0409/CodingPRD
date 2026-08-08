"""Domain types for the on-site wastewater register: status enums, role enum, entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    DESIGN_PROFESSIONAL = "DesignProfessional"
    INSTALLER = "Installer"
    PUMPER = "Pumper"
    ENVIRONMENTAL_HEALTH_SPECIALIST = "EnvironmentalHealthSpecialist"
    HEALTH_OFFICER = "HealthOfficer"
    RECORDS_CLERK = "RecordsClerk"


ALL_ROLES = [r.value for r in UserRole]


class WaterSourceType(str, Enum):
    PUBLIC_WATER = "PUBLIC_WATER"
    PRIVATE_WELL = "PRIVATE_WELL"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class WellType(str, Enum):
    DOMESTIC = "DOMESTIC"
    IRRIGATION = "IRRIGATION"
    MONITORING = "MONITORING"


class AdvisoryStatus(str, Enum):
    CLEAR = "CLEAR"
    ADVISORY = "ADVISORY"
    CONDEMNED = "CONDEMNED"


class WaterSampleResult(str, Enum):
    PASS = "PASS"
    EXCEEDANCE = "EXCEEDANCE"
    UNSAFE = "UNSAFE"


class ExceedanceReason(str, Enum):
    COLIFORM_DETECTED = "COLIFORM_DETECTED"
    NITRATE_MCL_EXCEEDED = "NITRATE_MCL_EXCEEDED"


class SoilGroup(str, Enum):
    SANDY = "SANDY"
    LOAMY = "LOAMY"
    CLAY_LOAM = "CLAY_LOAM"
    CLAY = "CLAY"


class SiteEvaluationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SystemType(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    MOUND = "MOUND"
    ATU = "ATU"
    DRIP = "DRIP"


class SetbackStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    COMPLIANT = "COMPLIANT"
    VARIANCE_REQUIRED = "VARIANCE_REQUIRED"
    VARIANCE_GRANTED = "VARIANCE_GRANTED"
    VARIANCE_DENIED = "VARIANCE_DENIED"


class SystemDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISIONS_REQUIRED = "REVISIONS_REQUIRED"
    APPROVED = "APPROVED"
    PERMITTED = "PERMITTED"
    SUPERSEDED = "SUPERSEDED"


class LicenseClass(str, Enum):
    INSTALLER = "INSTALLER"
    PUMPER = "PUMPER"
    DUAL = "DUAL"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ContractorEffectiveStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConstructionPermitStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    COVER_PASSED = "COVER_PASSED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class InspectionType(str, Enum):
    COVER = "COVER"
    FINAL = "FINAL"
    COMPLAINT = "COMPLAINT"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OperatingPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DUE_SOON = "DUE_SOON"
    DELINQUENT = "DELINQUENT"


class FailureType(str, Enum):
    SURFACING_EFFLUENT = "SURFACING_EFFLUENT"
    BACKUP = "BACKUP"
    STRUCTURAL = "STRUCTURAL"
    GROUNDWATER_CONTAMINATION = "GROUNDWATER_CONTAMINATION"


class RepairSeverity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    IMMINENT_HAZARD = "IMMINENT_HAZARD"


class RepairOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXTENDED = "EXTENDED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class InspectionMode(str, Enum):
    DESK_REVIEW = "DESK_REVIEW"
    FIELD_VERIFIED = "FIELD_VERIFIED"


class FieldCondition(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class CertificateGrade(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class TransferInspectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BLOCKED = "BLOCKED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"


# ── Entity shapes ─────────────────────────────────────────────────────────────
# Records carrying id + created_at + updated_at + version.


class Parcel(TypedDict):
    id: str
    apn: str
    county_code: str
    owner_user_id: str
    site_address: str
    lot_size_sqft: int
    water_source: str
    max_design_flow_gpd: int
    permitted_design_flow_gpd: int
    fees_assessed_cents: int
    fees_paid_cents: int
    fees_credited_cents: int
    fee_balance_cents: int
    open_repair_order_count: int
    water_quality_flag: bool
    risk_tier: str
    transfer_hold: bool
    created_at: str
    updated_at: str
    version: int


class Well(TypedDict):
    id: str
    parcel_id: str
    well_type: str
    location_x_ft: float
    location_y_ft: float
    depth_ft: int
    advisory_status: str
    last_sample_collected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SiteEvaluation(TypedDict):
    id: str
    parcel_id: str
    evaluator_user_id: str
    evaluated_on: str
    soil_group: str
    depth_to_limiting_layer_in: int
    perc_holes: List[dict]
    preliminary_perc_rate_min_per_in: Optional[float]
    certified_perc_rate_min_per_in: Optional[float]
    soil_loading_rate_gpd_per_sqft: Optional[float]
    valid_until: str
    status: str
    review_note: Optional[str]
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class SystemDesign(TypedDict):
    id: str
    site_evaluation_id: str
    designer_user_id: str
    system_type: str
    bedrooms: int
    tank_capacity_gal: int
    drainfield_x_ft: float
    drainfield_y_ft: float
    design_flow_gpd: int
    required_drainfield_sqft: int
    nearest_well_distance_ft: Optional[float]
    required_setback_ft: float
    setback_status: str
    status: str
    review_ehs_user_id: Optional[str]
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    business_name: str
    license_number: str
    license_class: str
    license_expires_on: str
    bond_amount_cents: int
    status: str
    effective_status: str
    created_at: str
    updated_at: str
    version: int


class ConstructionPermit(TypedDict):
    id: str
    system_design_id: str
    parcel_id: str
    contractor_id: str
    permit_number: str
    valid_from: str
    valid_until: str
    design_flow_gpd: int
    fee_cents: int
    status: str
    cover_inspection_passed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    construction_permit_id: str
    contractor_id: str
    inspection_type: str
    inspector_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    result_recorded_at: Optional[str]
    deficiency_codes: List[str]
    reinspection_round: int
    created_at: str
    updated_at: str
    version: int


class OperatingPermit(TypedDict):
    id: str
    parcel_id: str
    construction_permit_id: str
    household_size: int
    tank_capacity_gal: int
    issued_on: str
    expires_on: str
    last_pumped_on: Optional[str]
    pumping_interval_months: int
    next_pumping_due_on: str
    monitoring_required: bool
    status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    parcel_id: str
    operating_permit_id: str
    failure_type: str
    reported_on: str
    severity: Optional[str]
    compliance_deadline: Optional[str]
    issued_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    extension_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferInspection(TypedDict):
    id: str
    parcel_id: str
    operating_permit_id: str
    requested_on: str
    buyer_name: str
    seller_name: str
    inspection_mode: str
    expedited: bool
    subtotal_cents: int
    expedite_fee_cents: int
    total_due_cents: int
    certificate_grade: Optional[str]
    certified_at: Optional[str]
    certificate_valid_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable evidence records: id + created_at only, no updated_at and no version.


class WaterSample(TypedDict):
    id: str
    well_id: str
    collected_at: str
    nitrate_mg_l: float
    coliform_present: bool
    result: str
    exceedance_reasons: List[str]
    created_at: str


class PumpingRecord(TypedDict):
    id: str
    operating_permit_id: str
    contractor_id: str
    pumped_on: str
    gallons_removed: int
    sludge_depth_in: float
    scum_depth_in: float
    accepted: bool
    created_at: str
