"""Domain types for the Public Aquarium Collection & Animal Care API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Two record types (water-quality readings and husbandry records) are
append-only observations and carry only `id` and `created_at` (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CURATOR_OF_COLLECTIONS = "CuratorOfCollections"
    COMPLIANCE_DIRECTOR = "ComplianceDirector"
    VETERINARY_OFFICER = "VeterinaryOfficer"
    AQUARIST_TECHNICIAN = "AquaristTechnician"
    PERMIT_OFFICER = "PermitOfficer"
    PARTNER_INSTITUTION_LIAISON = "PartnerInstitutionLiaison"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class SystemType(str, Enum):
    RECIRCULATING_MARINE = "RECIRCULATING_MARINE"
    FLOW_THROUGH = "FLOW_THROUGH"
    CLOSED_FRESHWATER = "CLOSED_FRESHWATER"


class DesignHabitat(str, Enum):
    COLD_MARINE = "COLD_MARINE"
    TROPICAL_MARINE = "TROPICAL_MARINE"
    FRESHWATER = "FRESHWATER"
    TOUCH_POOL = "TOUCH_POOL"


class RedundancyClass(str, Enum):
    N = "N"
    N_PLUS_1 = "N_PLUS_1"
    TWO_N = "TWO_N"


class AlarmState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class ReadingSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class RedundancyTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ExhibitPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class PostureReason(str, Enum):
    LSS_CRITICAL = "LSS_CRITICAL"
    LSS_OFFLINE = "LSS_OFFLINE"
    LSS_WARNING = "LSS_WARNING"
    REDUNDANCY_OVERDUE = "REDUNDANCY_OVERDUE"
    BIOLOAD_PRESSURE = "BIOLOAD_PRESSURE"


class TaxonGroup(str, Enum):
    ELASMOBRANCH = "ELASMOBRANCH"
    TELEOST = "TELEOST"
    INVERTEBRATE = "INVERTEBRATE"
    MARINE_MAMMAL = "MARINE_MAMMAL"
    REPTILE = "REPTILE"
    BIRD = "BIRD"


class ProtectionStatus(str, Enum):
    UNLISTED = "UNLISTED"
    CITES_APPENDIX_II = "CITES_APPENDIX_II"
    CITES_APPENDIX_I = "CITES_APPENDIX_I"
    ESA_LISTED = "ESA_LISTED"


class SustainabilityRating(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class AccreditationStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    PROVISIONAL = "PROVISIONAL"
    NON_ACCREDITED = "NON_ACCREDITED"
    SUSPENDED = "SUSPENDED"


class PlanEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class PlanEntryAction(str, Enum):
    APPROVE = "APPROVE"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    RETIRE = "RETIRE"


class SustainabilityRequirement(str, Enum):
    GREEN_ONLY = "GREEN_ONLY"
    GREEN_OR_YELLOW = "GREEN_OR_YELLOW"
    ANY_WITH_JUSTIFICATION = "ANY_WITH_JUSTIFICATION"


class SourceType(str, Enum):
    CAPTIVE_BRED = "CAPTIVE_BRED"
    RESCUE_STRANDING = "RESCUE_STRANDING"
    INSTITUTIONAL_TRANSFER = "INSTITUTIONAL_TRANSFER"
    WILD_COLLECTION = "WILD_COLLECTION"


class AcquisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PERMIT = "PENDING_PERMIT"
    READY_FOR_CLEARANCE = "READY_FOR_CLEARANCE"
    CLEARED = "CLEARED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ScoreVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ClosureReason(str, Enum):
    CURATOR_CANCELLED = "CURATOR_CANCELLED"
    PLAN_SUSPENDED = "PLAN_SUSPENDED"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"


class SuspensionReason(str, Enum):
    DIRECTOR_ACTION = "DIRECTOR_ACTION"
    LAST_SPECIMEN_LOST = "LAST_SPECIMEN_LOST"
    EXHIBIT_CLOSED = "EXHIBIT_CLOSED"


class PermitType(str, Enum):
    IMPORT = "IMPORT"
    TRANSPORT = "TRANSPORT"
    POSSESSION = "POSSESSION"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PermitDecision(str, Enum):
    ISSUE = "ISSUE"
    DENY = "DENY"
    REQUEST_INFO = "REQUEST_INFO"
    REVOKE = "REVOKE"


class DocumentCode(str, Enum):
    HEALTH_CERTIFICATE = "HEALTH_CERTIFICATE"
    ORIGIN_DECLARATION = "ORIGIN_DECLARATION"
    IMPORT_LICENSE = "IMPORT_LICENSE"
    TRANSPORT_PLAN = "TRANSPORT_PLAN"
    POSSESSION_AFFIDAVIT = "POSSESSION_AFFIDAVIT"
    CITES_PERMIT = "CITES_PERMIT"
    ESA_AUTHORIZATION = "ESA_AUTHORIZATION"
    ACQUISITION_PROVENANCE = "ACQUISITION_PROVENANCE"
    CAPTIVE_BRED_CERT = "CAPTIVE_BRED_CERT"


class DispositionStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    CLEARED = "CLEARED"
    ON_EXHIBIT = "ON_EXHIBIT"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TRANSFERRED = "TRANSFERRED"
    DECEASED = "DECEASED"


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    UNDER_TREATMENT = "UNDER_TREATMENT"
    CRITICAL_CARE = "CRITICAL_CARE"
    DECEASED_PENDING_NECROPSY = "DECEASED_PENDING_NECROPSY"
    NECROPSY_COMPLETE = "NECROPSY_COMPLETE"


class QuarantineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


class QuarantineOutcome(str, Enum):
    EXTEND = "EXTEND"
    RESUME = "RESUME"
    CLEAR = "CLEAR"
    FAIL = "FAIL"


class LogType(str, Enum):
    FEEDING = "FEEDING"
    BEHAVIOR = "BEHAVIOR"
    TREATMENT = "TREATMENT"
    WEIGHT = "WEIGHT"


class BehaviorCode(str, Enum):
    NORMAL = "NORMAL"
    LETHARGIC = "LETHARGIC"
    AGGRESSIVE = "AGGRESSIVE"
    ABNORMAL_SWIM = "ABNORMAL_SWIM"


class CaseType(str, Enum):
    PREVENTIVE_EXAM = "PREVENTIVE_EXAM"
    TREATMENT = "TREATMENT"
    NECROPSY = "NECROPSY"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CaseOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    CHRONIC_MANAGED = "CHRONIC_MANAGED"
    MORTALITY_REFERRED = "MORTALITY_REFERRED"
    NECROPSY_FINALIZED = "NECROPSY_FINALIZED"


class FindingsSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class WelfareVariant(str, Enum):
    ROLLING = "ROLLING"
    AUDIT_SNAPSHOT = "AUDIT_SNAPSHOT"


class TransferStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class TransferDecision(str, Enum):
    APPROVE = "APPROVE"
    COUNTER = "COUNTER"
    DECLINE = "DECLINE"


class DeclineReason(str, Enum):
    LIAISON_DECLINED = "LIAISON_DECLINED"
    RECEIVER_INELIGIBLE = "RECEIVER_INELIGIBLE"
    TRANSPORT_PERMIT_EXPIRED = "TRANSPORT_PERMIT_EXPIRED"


class WelfareCondition(str, Enum):
    WATER_CHEMISTRY_MATCH = "WATER_CHEMISTRY_MATCH"
    TRANSPORT_OXYGEN_PLAN = "TRANSPORT_OXYGEN_PLAN"
    QUARANTINE_ON_ARRIVAL = "QUARANTINE_ON_ARRIVAL"
    CITES_TRANSPORT_CLEARANCE = "CITES_TRANSPORT_CLEARANCE"
    DIET_TRANSITION_PLAN = "DIET_TRANSITION_PLAN"
    NECROPSY_POLICY = "NECROPSY_POLICY"
    NO_COMMERCIAL_RESALE = "NO_COMMERCIAL_RESALE"
    BREEDING_LOAN_TERMS = "BREEDING_LOAN_TERMS"


class ProgramType(str, Enum):
    TOUCH_POOL_CONTACT = "TOUCH_POOL_CONTACT"
    FEEDING_ENCOUNTER = "FEEDING_ENCOUNTER"
    DIVE_ENCOUNTER = "DIVE_ENCOUNTER"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SessionAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class AuditScope(str, Enum):
    FULL = "FULL"
    ANIMAL_CARE_ONLY = "ANIMAL_CARE_ONLY"
    LIFE_SUPPORT_ONLY = "LIFE_SUPPORT_ONLY"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AuditAction(str, Enum):
    START = "START"
    CLOSE = "CLOSE"
    REOPEN = "REOPEN"
    CANCEL = "CANCEL"


# --------------------------------------------------------------------------
# Entity shapes — resources carrying id/created_at/updated_at/version
# --------------------------------------------------------------------------
class LifeSupportSystem(TypedDict):
    id: str
    system_code: str
    system_type: str
    design_habitat: str
    redundancy_class: str
    redundancy_test_interval_days: int
    last_redundancy_test_at: Optional[str]
    last_redundancy_test_result: Optional[str]
    redundancy_overdue: bool
    alarm_state: str
    consecutive_normal_readings: int
    consecutive_breach_readings: int
    water_quality_index: float
    created_at: str
    updated_at: str
    version: int


class Exhibit(TypedDict):
    id: str
    exhibit_code: str
    name: str
    habitat_type: str
    life_support_system_id: str
    display_volume_liters: float
    bioload_capacity_units: float
    occupied_bioload_units: float
    bioload_utilization_pct: float
    posture: str
    last_posture_reason: Optional[str]
    interaction_program_enabled: bool
    suspended_session_count: int
    created_at: str
    updated_at: str
    version: int


class Species(TypedDict):
    id: str
    scientific_name: str
    common_name: str
    taxon_group: str
    protection_status: str
    sustainability_rating: str
    bioload_units_per_specimen: float
    base_quarantine_days: int
    wild_take_quota_annual: int
    wild_take_quota_reserved: int
    permit_required: bool
    created_at: str
    updated_at: str
    version: int


class Institution(TypedDict):
    id: str
    name: str
    institution_code: str
    accreditation_status: str
    welfare_audit_score: float
    last_audit_at: Optional[str]
    is_receiving_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CollectionPlanEntry(TypedDict):
    id: str
    exhibit_id: str
    species_id: str
    planned_count: int
    sustainability_requirement: str
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    superseded_by_entry_id: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcquisitionRequest(TypedDict):
    id: str
    collection_plan_entry_id: str
    source_type: str
    source_institution_id: Optional[str]
    requested_count: int
    justification: Optional[str]
    status: str
    permit_required: bool
    permit_deadline_at: Optional[str]
    sustainability_score: float
    sustainability_score_variant: str
    quota_units_reserved: int
    fulfilled_count: int
    cleared_by_user_id: Optional[str]
    cleared_at: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    acquisition_request_id: str
    permit_type: str
    authority_reference: str
    document_codes: List[str]
    status: str
    submission_round: int
    missing_document_codes: List[str]
    valid_from: Optional[str]
    valid_until: Optional[str]
    issued_at: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    accession_code: str
    species_id: str
    acquisition_request_id: Optional[str]
    exhibit_id: Optional[str]
    holding_area: Optional[str]
    arrival_at: str
    disposition_status: str
    health_status: str
    pre_transfer_disposition: Optional[str]
    bioload_units: float
    quarantine_required_days: int
    welfare_score: Optional[float]
    welfare_score_variant: Optional[str]
    sire_specimen_id: Optional[str]
    dam_specimen_id: Optional[str]
    captive_bred: bool
    treatment_withdrawal_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarantineCase(TypedDict):
    id: str
    specimen_id: str
    protocol_days: int
    started_at: str
    projected_release_at: str
    status: str
    extension_count: int
    total_extension_days: int
    clearance_exam_count: int
    cleared_by_user_id: Optional[str]
    cleared_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VeterinaryCase(TypedDict):
    id: str
    specimen_id: str
    case_type: str
    opened_at: str
    treatment_start_at: Optional[str]
    withdrawal_days: Optional[int]
    diagnosis_code: Optional[str]
    status: str
    outcome: Optional[str]
    findings_severity: Optional[str]
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    specimen_id: str
    receiving_institution_id: str
    transport_permit_id: Optional[str]
    proposed_transfer_at: str
    welfare_conditions: List[str]
    counter_conditions: List[str]
    status: str
    negotiation_round: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    completed_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InteractionSession(TypedDict):
    id: str
    exhibit_id: str
    program_type: str
    starts_at: str
    ends_at: str
    max_guests: int
    guest_count: int
    safety_briefing_confirmed: bool
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccreditationAudit(TypedDict):
    id: str
    audit_code: str
    scope: str
    scheduled_for: str
    status: str
    readiness_score: Optional[float]
    domain_subscores: Optional[dict]
    blocking_finding_count: int
    opened_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    started_at: Optional[str]
    closed_at: Optional[str]
    determination_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observations — carry ONLY id and created_at (PRD §2.4)
# --------------------------------------------------------------------------
class WaterQualityReading(TypedDict):
    id: str
    life_support_system_id: str
    taken_at: str
    temperature_c: float
    salinity_ppt: float
    ph: float
    dissolved_oxygen_mg_l: float
    ammonia_mg_l: float
    nitrite_mg_l: float
    severity: str
    breach_parameters: List[str]
    water_quality_index_snapshot: float
    created_at: str


class HusbandryLog(TypedDict):
    id: str
    specimen_id: str
    log_type: str
    logged_at: str
    appetite_score: Optional[int]
    behavior_code: Optional[str]
    feed_grams: Optional[float]
    weight_grams: Optional[float]
    note: Optional[str]
    recorded_by_user_id: str
    created_at: str
