"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full common field set (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    FACILITY_OPERATOR = "FacilityOperator"
    PERMIT_REVIEWER = "PermitReviewer"
    INSPECTOR = "Inspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    ANONYMOUS = "Anonymous"


class FacilityPermitTrack(str, Enum):
    UNPERMITTED = "UNPERMITTED"
    PERMIT_BY_RULE = "PERMIT_BY_RULE"
    TITLE_V = "TITLE_V"


class FacilityComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEVIATION = "DEVIATION"
    ENFORCEMENT = "ENFORCEMENT"
    SUSPENDED = "SUSPENDED"


class SourceLifecycleStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PERMITTED = "PERMITTED"
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    SHUTDOWN = "SHUTDOWN"


class SourceMonitoringStatus(str, Enum):
    UNMONITORED = "UNMONITORED"
    STACK_TESTED = "STACK_TESTED"
    CEM_ACTIVE = "CEM_ACTIVE"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLIC_NOTICE = "PUBLIC_NOTICE"
    ISSUED = "ISSUED"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    REVOKED = "REVOKED"


class PublicNoticeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InventoryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    AMENDED = "AMENDED"


class StackTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ExceedanceStatus(str, Enum):
    OPEN = "OPEN"
    REPORTED = "REPORTED"
    REPORTED_LATE = "REPORTED_LATE"
    RESOLVED = "RESOLVED"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class EnforcementStatus(str, Enum):
    INITIATED = "INITIATED"
    PENALTY_ASSESSED = "PENALTY_ASSESSED"
    VARIANCE_GRANTED = "VARIANCE_GRANTED"
    DISMISSED = "DISMISSED"
    PAID = "PAID"
    CLOSED = "CLOSED"


class Facility(TypedDict):
    id: str
    name: str
    operator_name: str
    county: str
    permit_track: str
    potential_to_emit_tpy: float
    compliance_status: str
    open_exceedance_count: int
    fee_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EmissionSource(TypedDict):
    id: str
    facility_id: str
    source_type: str
    pollutant: str
    max_hourly_rate_lbs: float
    operating_hours_per_year: int
    control_efficiency: float
    permit_limit_ppm: float
    uncontrolled_pte_tpy: float
    controlled_pte_tpy: float
    lifecycle_status: str
    monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    facility_id: str
    permit_type: str
    status: str
    issued_at: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class PublicNotice(TypedDict):
    id: str
    permit_id: str
    comment_open_at: str
    comment_close_at: str
    comment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionsInventory(TypedDict):
    id: str
    facility_id: str
    reporting_year: int
    status: str
    total_emissions_tons: float
    estimated_fee_cents: int
    assessed_fee_cents: int
    certified_at: Optional[str]
    due_at: str
    created_at: str
    updated_at: str
    version: int


class InventoryLineItem(TypedDict):
    id: str
    inventory_id: str
    source_id: str
    method: str
    reported_tons: float
    created_at: str
    updated_at: str
    version: int


class StackTest(TypedDict):
    id: str
    source_id: str
    scheduled_start: str
    scheduled_end: str
    measured_rate_lbs: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CEMDataBlock(TypedDict):
    id: str
    source_id: str
    period_start: str
    period_end: str
    avg_concentration_ppm: float
    is_exceedance: bool
    created_at: str
    updated_at: str
    version: int


class ExceedanceEvent(TypedDict):
    id: str
    source_id: str
    event_type: str
    detected_at: str
    magnitude_pct: float
    reported_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    facility_id: str
    description: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    facility_id: str
    complaint_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    facility_id: str
    action_type: str
    origin: str
    penalty_cents: int
    variance_start: Optional[str]
    variance_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
