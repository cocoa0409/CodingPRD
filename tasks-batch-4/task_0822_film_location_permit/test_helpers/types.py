"""Domain types: entity TypedDicts, status enums, role enum for the Film Location Permit API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PRODUCTION_COMPANY = "ProductionCompany"
    DEPARTMENT_REVIEWER = "DepartmentReviewer"
    FIELD_OFFICER = "FieldOfficer"
    FILM_OFFICE_COORDINATOR = "FilmOfficeCoordinator"


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    ISSUED = "ISSUED"
    WRAP_REQUESTED = "WRAP_REQUESTED"
    WRAPPED = "WRAPPED"
    WITHDRAWN = "WITHDRAWN"


class DepartmentReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


class InsuranceCertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RoadClosureBookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"


class OfficerAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RiderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class OfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# ---- Entities with the full common-field complement (id/created_at/updated_at/version) ----
class ProductionCompany(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    primary_contact: str
    late_wrap_count: int
    damage_incident_count: int
    missed_notification_count: int
    compliance_score: int
    created_at: str
    updated_at: str
    version: int


class Officer(TypedDict, total=False):
    id: str
    full_name: str
    badge_number: str
    rank: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    production_company_id: str
    title: str
    synopsis: str
    shoot_start_at: str
    shoot_end_at: str
    crew_size: int
    requires_road_closure: bool
    requires_parking: bool
    status: str
    shoot_days: int
    estimated_fee_cents: int
    final_fee_cents: int
    municipal_surcharge_cents: int
    total_fee_cents: int
    deposit_cents: int
    amount_paid_cents: int
    deposit_held_cents: int
    issued_at: Optional[str]
    permitted_end_at: Optional[str]
    actual_end_at: Optional[str]
    damage_cost_cents: int
    late_wrap_penalty_cents: int
    deposit_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class DepartmentReview(TypedDict, total=False):
    id: str
    application_id: str
    department_id: str
    status: str
    decision_notes: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    application_id: str
    policy_number: str
    coverage_amount_cents: int
    aviation_coverage: bool
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoadClosureBooking(TypedDict, total=False):
    id: str
    application_id: str
    street_segment_id: str
    closure_start_at: str
    closure_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficerAssignment(TypedDict, total=False):
    id: str
    application_id: str
    officer_id: str
    shift_start_at: str
    shift_end_at: str
    status: str
    billed_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict, total=False):
    id: str
    application_id: str
    rider_type: str
    faa_waiver_number: Optional[str]
    max_altitude_ft: Optional[int]
    flight_start_at: Optional[str]
    flight_end_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- Immutable-by-design records: only id + created_at, NO updated_at / NO version ----
class Department(TypedDict, total=False):
    id: str
    code: str
    name: str
    trigger_condition: str
    created_at: str


class StreetSegment(TypedDict, total=False):
    id: str
    segment_code: str
    name: str
    length_m: float
    created_at: str


class LocationDetail(TypedDict, total=False):
    id: str
    application_id: str
    address: str
    geo_zone: str
    activity_type: str
    requested_start_at: str
    requested_end_at: str
    uses_road_closure: bool
    created_at: str


class NeighborhoodNotification(TypedDict, total=False):
    id: str
    application_id: str
    geo_zone: str
    notice_method: str
    sent_at: str
    lead_days: int
    created_at: str


class LedgerEntry(TypedDict, total=False):
    id: str
    application_id: str
    entry_type: str
    direction: str
    amount_cents: int
    memo: Optional[str]
    created_at: str
