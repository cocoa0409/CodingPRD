"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable, versioned resources, so every entity
TypedDict carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    LICENSED_INSPECTOR = "LicensedInspector"
    SAFETY_ADMINISTRATOR = "SafetyAdministrator"
    BUILDING_OWNER = "BuildingOwner"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class DeviceCategory(str, Enum):
    PASSENGER_ELEVATOR = "PASSENGER_ELEVATOR"
    FREIGHT_ELEVATOR = "FREIGHT_ELEVATOR"
    ESCALATOR = "ESCALATOR"
    MOVING_WALK = "MOVING_WALK"
    DUMBWAITER = "DUMBWAITER"


class RiskClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DeviceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class InspectionType(str, Enum):
    ANNUAL = "ANNUAL"
    PERIODIC = "PERIODIC"
    REINSPECTION = "REINSPECTION"
    ACCIDENT_FOLLOWUP = "ACCIDENT_FOLLOWUP"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL = "CONDITIONAL"
    CANCELLED = "CANCELLED"


class DeficiencySeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    CITED = "CITED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    PAID = "PAID"
    DISMISSED = "DISMISSED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    POSTED = "POSTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class OosOrderReason(str, Enum):
    CRITICAL_DEFICIENCY = "CRITICAL_DEFICIENCY"
    ACCIDENT = "ACCIDENT"
    NONPAYMENT = "NONPAYMENT"
    EXPIRED_CERTIFICATE = "EXPIRED_CERTIFICATE"


class OosOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class FeeInvoiceType(str, Enum):
    REGISTRATION = "REGISTRATION"
    ANNUAL_RENEWAL = "ANNUAL_RENEWAL"
    REINSPECTION = "REINSPECTION"
    LATE_PENALTY = "LATE_PENALTY"


class FeeInvoiceStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    PAID = "PAID"


class AccidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    FATAL = "FATAL"


class AccidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CONDITIONAL = "CONDITIONAL"


class ContestOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class AccidentFinding(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all versioned resources)
# --------------------------------------------------------------------------
class Owner(TypedDict):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    name: str
    license_number: str
    license_expiry_period: int
    certified_categories: List[str]
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    owner_id: str
    category: str
    location_description: str
    install_period: int
    risk_class: str
    status: str
    next_inspection_due_period: Optional[int]
    outstanding_balance_cents: int
    accident_risk_score: int
    current_certificate_id: Optional[str]
    active_oos_count: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    device_id: str
    assigned_inspector_id: Optional[str]
    type: str
    scheduled_start_period: int
    scheduled_end_period: int
    performed_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict):
    id: str
    inspection_id: str
    device_id: str
    code: str
    severity: str
    description: str
    resolution_due_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    deficiency_id: str
    device_id: str
    fine_amount_cents: int
    surcharged_amount_cents: int
    issued_period: int
    due_period: int
    contest_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    device_id: str
    source_inspection_id: str
    certificate_number: str
    issue_period: int
    expiry_period: int
    posted_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutOfServiceOrder(TypedDict):
    id: str
    device_id: str
    citation_id: Optional[str]
    reason: str
    effective_start_period: int
    effective_end_period: int
    lifted_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    device_id: str
    type: str
    amount_cents: int
    due_period: int
    paid_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccidentReport(TypedDict):
    id: str
    device_id: str
    lead_investigator_id: Optional[str]
    severity: str
    occurred_period: int
    description: str
    provisional_risk_score: int
    final_risk_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
