"""Domain types: entity TypedDicts, status enums, role enum for the Hazmat Tier II API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    REGULATOR = "Regulator"
    FACILITY_OPERATOR = "FacilityOperator"
    LEPC_COORDINATOR = "LEPCCoordinator"


class ErpStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    ENFORCEMENT = "ENFORCEMENT"


class PhysicalState(str, Enum):
    SOLID = "SOLID"
    LIQUID = "LIQUID"
    GAS = "GAS"


class InventoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StorageType(str, Enum):
    TANK = "TANK"
    CYLINDER = "CYLINDER"
    DRUM = "DRUM"
    BULK = "BULK"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"


class SdsStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ReportingStatus(str, Enum):
    PENDING_VERBAL = "PENDING_VERBAL"
    VERBAL_GIVEN = "VERBAL_GIVEN"
    WRITTEN_FILED = "WRITTEN_FILED"


class RemediationStatus(str, Enum):
    ONGOING = "ONGOING"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


class ReleaseMedium(str, Enum):
    AIR = "AIR"
    WATER = "WATER"
    SOIL = "SOIL"


class NoticeType(str, Enum):
    VERBAL = "VERBAL"
    WRITTEN = "WRITTEN"


class NoticeRecipient(str, Enum):
    LEPC = "LEPC"
    SERC = "SERC"
    NRC = "NRC"


class PermitType(str, Enum):
    OPERATING = "OPERATING"
    STORAGE = "STORAGE"
    AIR = "AIR"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CaseOrigin(str, Enum):
    RELEASE_RQ_EXCEEDED = "RELEASE_RQ_EXCEEDED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    LATE_FILING = "LATE_FILING"
    MANUAL = "MANUAL"


class CaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"


class RmpStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


# All entities in this API carry the mutation-tracking contract
# (id, created_at, updated_at, version).

class Facility(TypedDict):
    id: str
    name: str
    epa_facility_id: str
    state_code: str
    county: str
    operator_name: str
    erp_contact_name: Optional[str]
    erp_contact_phone: Optional[str]
    erp_plan_ref: Optional[str]
    erp_linked_lepc_district: Optional[str]
    erp_status: str
    compliance_posture: str
    open_case_count: int
    hazard_index: float
    total_outstanding_fee_cents: int
    is_rmp_required: bool
    created_at: str
    updated_at: str
    version: int


class Chemical(TypedDict):
    id: str
    cas_number: str
    name: str
    is_ehs: bool
    tpq_lbs: Optional[int]
    rq_lbs: int
    hazard_weight: float
    physical_state: str
    created_at: str
    updated_at: str
    version: int


class ChemicalInventory(TypedDict):
    id: str
    facility_id: str
    chemical_id: str
    reporting_year: int
    max_daily_amount_lbs: float
    average_daily_amount_lbs: float
    days_on_site: int
    storage_type: str
    reportable_amount_lbs: float
    average_onsite_lbs: float
    applicable_threshold_lbs: int
    is_reportable: bool
    exceeds_tpq: bool
    weighted_hazard_contribution: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TierIIFiling(TypedDict):
    id: str
    facility_id: str
    reporting_year: int
    status: str
    provisional_fee_cents: int
    assessed_fee_cents: int
    fee_paid_cents: int
    reportable_chemical_count: int
    ehs_reportable_count: int
    is_late: bool
    submitted_at: Optional[str]
    deadline: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class SDS(TypedDict):
    id: str
    facility_id: str
    chemical_id: str
    document_ref: str
    revision_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseNotification(TypedDict):
    id: str
    facility_id: str
    chemical_id: str
    release_datetime: str
    quantity_released_lbs: float
    medium: str
    reporting_status: str
    remediation_status: str
    exceeds_rq: bool
    requires_lepc: bool
    origin_case_opened: bool
    created_at: str
    updated_at: str
    version: int


class LEPCNotice(TypedDict):
    id: str
    release_id: str
    notice_type: str
    recipient: str
    sent_at: str
    acknowledged: bool
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    facility_id: str
    permit_type: str
    issued_date: str
    expiry_date: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    facility_id: str
    inspector_id: str
    scheduled_date: str
    status: str
    result: Optional[str]
    findings_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCase(TypedDict):
    id: str
    facility_id: str
    origin: str
    origin_ref: Optional[str]
    severity: str
    status: str
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class RiskManagementPlan(TypedDict):
    id: str
    facility_id: str
    program_level: int
    submitted_date: str
    next_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
