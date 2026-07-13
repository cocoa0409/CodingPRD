"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Rental Registration & Habitability Inspection PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---------------------------------------------------------------

class UserRole(str, Enum):
    LANDLORD = "Landlord"
    INSPECTOR = "Inspector"
    REGISTRAR = "Registrar"
    TENANT = "Tenant"


# --- Status enums --------------------------------------------------------

class PropertyStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"
    CONDEMNED = "CONDEMNED"


class LicenseStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    RESOLVED = "RESOLVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    ESCALATED = "ESCALATED"
    VERIFIED_RESOLVED = "VERIFIED_RESOLVED"
    CONDEMNED_BASIS = "CONDEMNED_BASIS"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"


class CondemnationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"


# --- Value enums ---------------------------------------------------------

class CertificationLevel(str, Enum):
    STANDARD = "STANDARD"
    SENIOR = "SENIOR"
    LEAD_CERTIFIED = "LEAD_CERTIFIED"


class Category(str, Enum):
    LIFE_SAFETY = "LIFE_SAFETY"
    HABITABILITY = "HABITABILITY"
    LEAD_PAINT = "LEAD_PAINT"
    STRUCTURAL = "STRUCTURAL"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ChecklistResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class InspectionType(str, Enum):
    PERIODIC = "PERIODIC"
    COMPLAINT = "COMPLAINT"
    REINSPECTION = "REINSPECTION"


class NoticeType(str, Enum):
    LEAD_PAINT_DISCLOSURE = "LEAD_PAINT_DISCLOSURE"
    INSPECTION_NOTICE = "INSPECTION_NOTICE"
    VIOLATION_NOTICE = "VIOLATION_NOTICE"
    CONDEMNATION_NOTICE = "CONDEMNATION_NOTICE"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)

class Landlord(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    mailing_address: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    email: str
    certification_level: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    landlord_id: str
    street_address: str
    unit_count: int
    year_built: int
    registration_status: str
    current_license_id: Optional[str]
    has_lead_risk: bool
    open_violation_count: int
    open_critical_violation_count: int
    total_penalty_cents: int
    total_fees_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class RentalLicense(TypedDict):
    id: str
    property_id: str
    license_number: str
    term_years: int
    status: str
    fee_cents: int
    lead_surcharge_applied: bool
    issued_at: Optional[str]
    expires_at: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    property_id: str
    tenant_email: str
    tenant_unit: str
    category: str
    description: str
    severity_alleged: str
    status: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    property_id: str
    inspector_id: str
    inspection_type: str
    complaint_id: Optional[str]
    prior_inspection_id: Optional[str]
    scheduled_date: str
    duration_minutes: int
    status: str
    conducted_at: Optional[str]
    result_score: float
    overdue: bool
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    property_id: str
    checklist_item_id: Optional[str]
    code: str
    category: str
    severity: str
    status: str
    cure_deadline: str
    penalty_cents: int
    remediation_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenantNotice(TypedDict):
    id: str
    property_id: str
    recipient_email: str
    recipient_unit: str
    notice_type: str
    status: str
    sent_at: str
    ack_deadline: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CondemnationOrder(TypedDict):
    id: str
    property_id: str
    triggering_violation_id: Optional[str]
    basis: str
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields: false → only id + created_at) -----

class ChecklistItem(TypedDict):
    id: str
    inspection_id: str
    category: str
    code: str
    result: str
    severity: str
    notes: Optional[str]
    created_at: str
