"""Domain types: entity TypedDicts, status enums, role enum (Sign & Billboard Zoning Permit)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PLANNER = "Planner"
    ZONING_BOARD = "ZoningBoard"
    INSPECTOR = "Inspector"


# --- Status / axis enums ------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PERMITTED = "PERMITTED"


class DimensionalReview(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class OverlayReview(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    VARIANCE_REQUIRED = "VARIANCE_REQUIRED"
    VARIANCE_GRANTED = "VARIANCE_GRANTED"


class VarianceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class PermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class NonConformingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AMORTIZED = "AMORTIZED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class BillboardRegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


# --- Entity TypedDicts --------------------------------------------------------
# common_fields: false -> only id + created_at (no updated_at, no version)
class Parcel(TypedDict):
    id: str
    created_at: str
    zoning_district: str
    historic_overlay: bool
    corridor_overlay: bool
    max_sign_area_sqft: float
    max_height_ft: float
    min_setback_ft: float
    allowed_illumination: str
    max_signs: int
    active_permit_count: int
    available_sign_slots: int


class Applicant(TypedDict):
    id: str
    created_at: str
    name: str
    contact_email: str


class Inspector(TypedDict):
    id: str
    created_at: str
    name: str


class RemovalOrder(TypedDict):
    id: str
    created_at: str
    violation_id: str
    issued_at: str
    compliance_deadline: str
    status: str


# common_fields: true -> id + created_at + updated_at + version
class SignApplication(TypedDict):
    id: str
    parcel_id: str
    applicant_id: str
    sign_type: str
    requested_area_sqft: float
    requested_height_ft: float
    requested_setback_ft: float
    requested_illumination: str
    provisional_fee_cents: int
    approved_area_sqft: Optional[float]
    approved_type: Optional[str]
    approved_illumination: Optional[str]
    status: str
    dimensional_review: str
    overlay_review: str
    created_at: str
    updated_at: str
    version: int


class Variance(TypedDict):
    id: str
    application_id: str
    kind: str
    requested_value: float
    justification: str
    recommendation: Optional[str]
    recommended_by_user_id: Optional[str]
    decision: Optional[str]
    decided_by_user_id: Optional[str]
    granted_value: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    application_id: str
    fee_charged_cents: int
    fee_paid: bool
    fee_refunded_cents: int
    issued_at: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    permit_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NonConformingRegistration(TypedDict):
    id: str
    parcel_id: str
    description: str
    original_value_cents: int
    amortization_period_years: int
    registered_at: str
    straight_line_value_cents: int
    declining_balance_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    parcel_id: str
    permit_id: Optional[str]
    kind: str
    issued_at: str
    cure_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Billboard(TypedDict):
    id: str
    parcel_id: str
    operator_id: str
    face_count: int
    is_digital: bool
    structure_height_ft: float
    registration_status: str
    registration_expires_at: Optional[str]
    registration_fee_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class BillboardLease(TypedDict):
    id: str
    billboard_id: str
    lessee_name: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
