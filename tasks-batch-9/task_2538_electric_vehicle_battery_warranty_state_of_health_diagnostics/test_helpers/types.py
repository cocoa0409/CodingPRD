"""Entity shapes, status vocabularies and the role vocabulary.

The TypedDicts mirror the field rosters the PRD publishes for each resource, so a
test that indexes a response dictionary is indexing a name the contract names.
Every enum below is closed: the PRD lists exactly these members.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ════════════════════════════════ roles ════════════════════════════════


class Role(str, Enum):
    """The seven roles of the PRD's access-control section."""

    PROGRAM_ADMIN = "ProgramAdmin"
    WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    TELEMATICS_GATEWAY = "TelematicsGateway"
    VEHICLE_OWNER = "VehicleOwner"
    INDEPENDENT_LAB = "IndependentLab"
    REGULATORY_LIAISON = "RegulatoryLiaison"


ALL_ROLES: List[str] = [r.value for r in Role]

# Every retrieval operation is available to every role, with the single exception
# that TelematicsGateway may read only telematics snapshots and thermal events.
BROAD_READ_ROLES: List[str] = [
    Role.PROGRAM_ADMIN.value,
    Role.WARRANTY_ADJUDICATOR.value,
    Role.SERVICE_TECHNICIAN.value,
    Role.VEHICLE_OWNER.value,
    Role.INDEPENDENT_LAB.value,
    Role.REGULATORY_LIAISON.value,
]


# ═══════════════════════════ status vocabularies ═══════════════════════════


class RemanStockState(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IMMOBILIZED = "IMMOBILIZED"


class PackType(str, Enum):
    NEW = "NEW"
    REMANUFACTURED = "REMANUFACTURED"


class PackStatus(str, Enum):
    STOCK = "STOCK"
    RESERVED = "RESERVED"
    IN_SERVICE = "IN_SERVICE"
    REMOVED = "REMOVED"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class HazmatClassification(str, Enum):
    UN3480 = "UN3480"
    UN3481 = "UN3481"
    UN3536 = "UN3536"


class PackagingSpec(str, Enum):
    STANDARD_UN_4G = "STANDARD_UN_4G"
    SP376_STRONG_OUTER = "SP376_STRONG_OUTER"


class ModuleStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAULTED = "FAULTED"
    REPLACED = "REPLACED"


class SnapshotValidity(str, Enum):
    VALID = "VALID"
    INVALID_FUTURE_CAPTURE = "INVALID_FUTURE_CAPTURE"
    INVALID_CAPACITY_RANGE = "INVALID_CAPACITY_RANGE"
    INVALID_ODOMETER_REGRESSION = "INVALID_ODOMETER_REGRESSION"


class AssessmentVariant(str, Enum):
    TELEMATICS_FLEET = "TELEMATICS_FLEET"
    BENCH_CAPACITY_TEST = "BENCH_CAPACITY_TEST"


class DiagnosticValidity(str, Enum):
    VALID = "VALID"
    STALE_TELEMETRY = "STALE_TELEMETRY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    BENCH_OUT_OF_RANGE = "BENCH_OUT_OF_RANGE"


class CoveragePosition(str, Enum):
    IN_COVERAGE = "IN_COVERAGE"
    GOODWILL_BAND = "GOODWILL_BAND"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"


class CertLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class CenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHIPPING_SUSPENDED = "SHIPPING_SUSPENDED"
    DECERTIFIED = "DECERTIFIED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CERT_LAPSED = "CERT_LAPSED"


class AdjudicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED_MODULE = "APPROVED_MODULE"
    APPROVED_PACK = "APPROVED_PACK"
    APPROVED_SOFTWARE = "APPROVED_SOFTWARE"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"


class Remedy(str, Enum):
    MODULE_REPLACEMENT = "MODULE_REPLACEMENT"
    PACK_REPLACEMENT = "PACK_REPLACEMENT"
    SOFTWARE_REMEDIATION = "SOFTWARE_REMEDIATION"


class ApprovedRemedy(str, Enum):
    MODULE_REPLACEMENT = "MODULE_REPLACEMENT"
    PACK_REPLACEMENT = "PACK_REPLACEMENT"
    SOFTWARE_REMEDIATION = "SOFTWARE_REMEDIATION"
    DENIED = "DENIED"


class RecommendationBasis(str, Enum):
    THERMAL_HISTORY = "THERMAL_HISTORY"
    CELL_DELTA = "CELL_DELTA"
    RETENTION_FLOOR = "RETENTION_FLOOR"
    MODULE_ALLOWANCE = "MODULE_ALLOWANCE"
    MODULE_FAULT = "MODULE_FAULT"
    NO_MODULE_FAULT = "NO_MODULE_FAULT"


class SettlementVariant(str, Enum):
    FULL_COVERAGE = "FULL_COVERAGE"
    GOODWILL_PRORATED = "GOODWILL_PRORATED"


class DenialReason(str, Enum):
    ADJUDICATOR_DECISION = "ADJUDICATOR_DECISION"
    DISPUTE_DOWNGRADE = "DISPUTE_DOWNGRADE"
    CONSENT_DECLINED = "CONSENT_DECLINED"


class Severity(str, Enum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class EventSource(str, Enum):
    TELEMATICS = "TELEMATICS"
    SERVICE_CENTER = "SERVICE_CENTER"


class ContainmentStatus(str, Enum):
    DETECTED = "DETECTED"
    ISOLATED = "ISOLATED"
    PACK_QUARANTINED = "PACK_QUARANTINED"
    CONTAINMENT_CLOSED = "CONTAINMENT_CLOSED"


class NotificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    FILED = "FILED"
    LATE_FILED = "LATE_FILED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"


class TargetDefect(str, Enum):
    CHARGING = "CHARGING"
    THERMAL_MANAGEMENT = "THERMAL_MANAGEMENT"


class AppliesToPackType(str, Enum):
    NEW = "NEW"
    REMANUFACTURED = "REMANUFACTURED"
    ANY = "ANY"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LIMITED_RELEASE = "LIMITED_RELEASE"
    FIELD_RELEASE = "FIELD_RELEASE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReleaseScope(str, Enum):
    LIMITED = "LIMITED"
    FIELD = "FIELD"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    APPLIED = "APPLIED"


class DisputeStatus(str, Enum):
    LAB_ASSIGNED = "LAB_ASSIGNED"
    LAB_RESULT_RECEIVED = "LAB_RESULT_RECEIVED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"
    RESOLVED_DOWNGRADED = "RESOLVED_DOWNGRADED"


class ShipmentContents(str, Enum):
    FULL_PACK = "FULL_PACK"
    MODULES_ONLY = "MODULES_ONLY"


class TransportMode(str, Enum):
    GROUND = "GROUND"
    AIR = "AIR"


class ShipmentDestination(str, Enum):
    REMAN_CENTER = "REMAN_CENTER"
    RECYCLER = "RECYCLER"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class Disposition(str, Enum):
    REMANUFACTURE = "REMANUFACTURE"
    SCRAP = "SCRAP"


class RejectionReason(str, Enum):
    PACKAGING_NONCONFORMANT = "PACKAGING_NONCONFORMANT"
    SOC_OUT_OF_LIMIT = "SOC_OUT_OF_LIMIT"
    DOCUMENTATION_MISSING = "DOCUMENTATION_MISSING"


# ═══════════════════════════ entity shapes ═══════════════════════════
# Common fields: every resource below carries `id`, `created_at`, `updated_at`
# and `version`, with the single exception of TelematicsSnapshot — an immutable
# event row that carries `id` and `created_at` only.


class RetentionTier(TypedDict):
    through_months: int
    through_miles: int
    min_retention_pct: float


class WarrantyProgram(TypedDict, total=False):
    id: str
    name: str
    coverage_months: int
    coverage_miles: int
    retention_schedule: List[RetentionTier]
    pack_replacement_retention_pct: float
    module_replacement_cap: int
    goodwill_months: int
    goodwill_miles: int
    diagnostic_fee_cents: int
    module_unit_price_cents: int
    pack_price_new_cents: int
    pack_price_reman_cents: int
    labor_hours_module: float
    labor_hours_pack: float
    surcharge_un3480_cents: int
    surcharge_un3481_cents: int
    surcharge_un3536_cents: int
    snapshot_min_count: int
    snapshot_window_size: int
    snapshot_freshness_days: int
    cell_delta_pack_threshold_mv: int
    info_request_limit: int
    reman_min_soh_pct: float
    allow_new_pack_substitution: bool
    liability_cap_cents: int
    lab_tolerance_pct: float
    dispute_window_days: int
    accrued_liability_cents: int
    reman_available_count: int
    reman_stock_state: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    model_code: str
    region_code: str
    warranty_program_id: str
    in_service_date: str
    owner_contact_email: str
    odometer_miles: int
    installed_pack_id: Optional[str]
    warranty_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BatteryPack(TypedDict, total=False):
    id: str
    serial_number: str
    pack_type: str
    nominal_capacity_kwh: float
    module_count: int
    gross_weight_kg: float
    stock_region_code: str
    refurb_soh_pct: Optional[float]
    remanufacture_count: int
    installed_vehicle_id: Optional[str]
    superseded_pack_id: Optional[str]
    status: str
    hazmat_classification: Optional[str]
    damaged_defective: bool
    module_replacements_to_date: int
    faulted_module_count: int
    created_at: str
    updated_at: str
    version: int


class BatteryModule(TypedDict, total=False):
    id: str
    pack_id: str
    position_index: int
    module_capacity_kwh: float
    status: str
    cell_delta_mv: Optional[int]
    thermal_runaway_flag: bool
    replaced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TelematicsSnapshot(TypedDict, total=False):
    """The one append-only event row: `id` and `created_at`, no version, no update path."""

    id: str
    vehicle_id: str
    captured_at: str
    odometer_miles: int
    reported_capacity_kwh: float
    charge_cycles: int
    max_cell_delta_mv: int
    coolant_temp_c: float
    dcfc_session_count: int
    validity_flag: str
    corrected_capacity_kwh: float
    created_at: str


class SoHAssessment(TypedDict, total=False):
    id: str
    vehicle_id: str
    pack_id: str
    technician_id: str
    variant: str
    bench_measured_capacity_kwh: Optional[float]
    module_fault_positions: List[int]
    module_degraded_positions: List[int]
    window_snapshot_count: int
    nominal_basis_kwh: Optional[float]
    estimated_capacity_kwh: Optional[float]
    retention_pct: Optional[float]
    diagnostic_validity: str
    elapsed_months: int
    assessed_odometer_miles: int
    coverage_position: str
    applicable_min_retention_pct: Optional[float]
    max_cell_delta_mv: int
    qualifies_for_claim: bool
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    hv_certification_level: str
    has_pack_lift: bool
    insulation_tester_cal_due_at: str
    hv_bay_count: int
    labor_rate_cents_per_hour: int
    status: str
    open_hazmat_holds: int
    rejected_shipment_count: int
    late_notification_count: int
    compliance_score: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    service_center_id: str
    full_name: str
    hv_cert_level: str
    cert_expires_at: str
    status: str
    last_hv_window_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    vehicle_id: str
    service_center_id: str
    assessment_id: str
    diagnosing_technician_id: str
    replacement_pack_id: Optional[str]
    fulfilment_technician_id: Optional[str]
    linked_campaign_id: Optional[str]
    adjudication_status: str
    recommended_remedy: str
    approved_remedy: Optional[str]
    recommendation_basis: str
    info_request_round: int
    settlement_variant: Optional[str]
    remedy_cost_cents: Optional[int]
    proration_factor: Optional[float]
    owner_share_cents: Optional[int]
    oem_share_cents: Optional[int]
    admin_fee_cents: Optional[int]
    oem_total_cents: Optional[int]
    adjudicated_by_user_id: Optional[str]
    fulfilment_blocked: bool
    hv_bay_window_start: Optional[str]
    hv_bay_window_end: Optional[str]
    denial_reason: Optional[str]
    reopened_count: int
    pack_shipment_required: bool
    created_at: str
    updated_at: str
    version: int


class ThermalEvent(TypedDict, total=False):
    id: str
    vehicle_id: str
    pack_id: str
    severity: str
    detected_at: str
    affected_module_positions: List[int]
    source: str
    containment_status: str
    notification_status: str
    notification_deadline_at: Optional[str]
    notification_filed_at: Optional[str]
    regulator_reference: Optional[str]
    reporting_service_center_id: Optional[str]
    containment_steps_completed: int
    event_status: str
    created_at: str
    updated_at: str
    version: int


class RemediationCampaign(TypedDict, total=False):
    id: str
    campaign_code: str
    target_defect: str
    software_version: str
    applies_to_pack_type: str
    applies_to_model_code: Optional[str]
    consent_required: bool
    pilot_region_codes: List[str]
    status: str
    release_scope: Optional[str]
    solicited_consent_count: int
    open_consent_count: int
    applied_count: int
    created_at: str
    updated_at: str
    version: int


class RemediationConsent(TypedDict, total=False):
    id: str
    campaign_id: str
    vehicle_id: str
    superseded_consent_id: Optional[str]
    solicitation_round: int
    consent_status: str
    expires_at: str
    decision_at: Optional[str]
    applied_at: Optional[str]
    applied_software_version: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityDispute(TypedDict, total=False):
    id: str
    claim_id: str
    lab_name: str
    owner_statement: str
    nominal_basis_kwh: float
    oem_retention_pct: float
    lab_measured_capacity_kwh: Optional[float]
    lab_retention_pct: Optional[float]
    deviation_pct: Optional[float]
    retest_count: int
    dispute_status: str
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackShipment(TypedDict, total=False):
    id: str
    pack_id: str
    origin_service_center_id: str
    certifying_technician_id: str
    shipment_contents: str
    packaging_spec: str
    transport_mode: str
    destination: str
    state_of_charge_pct: float
    hazmat_classification: str
    required_packaging_spec: str
    gross_weight_kg: float
    hazmat_fee_cents: int
    soc_limit_pct: float
    status: str
    tendered_at: Optional[str]
    received_at: Optional[str]
    disposition: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Resources carrying the full common-field quartet.
VERSIONED_ENTITIES = [
    "WarrantyProgram",
    "Vehicle",
    "BatteryPack",
    "BatteryModule",
    "SoHAssessment",
    "ServiceCenter",
    "Technician",
    "WarrantyClaim",
    "ThermalEvent",
    "RemediationCampaign",
    "RemediationConsent",
    "CapacityDispute",
    "PackShipment",
]

# The single append-only event resource.
EVENT_ENTITIES = ["TelematicsSnapshot"]
