"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: most resources carry id + created_at + updated_at + version.
PhotoEvidence, QCRevisionRequest, and VolumeForecast are append-only and
carry only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_ADMIN = "ClientAdmin"
    OPERATIONS_MANAGER = "OperationsManager"
    DISPATCH_COORDINATOR = "DispatchCoordinator"
    BROKER = "Broker"
    QC_REVIEWER = "QCReviewer"
    BILLING_CLERK = "BillingClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Status / kind enums
# ---------------------------------------------------------------------------

class ClientAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BrokerStatus(str, Enum):
    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LicenseKind(str, Enum):
    BPO = "BPO"
    APPRAISAL = "APPRAISAL"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RegulationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PropertyStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ARCHIVED = "ARCHIVED"


class PropertyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    CONDO = "CONDO"
    TOWNHOME = "TOWNHOME"
    MULTI_FAMILY = "MULTI_FAMILY"
    MANUFACTURED = "MANUFACTURED"


class OrderKind(str, Enum):
    BPO = "BPO"
    APPRAISAL = "APPRAISAL"


class InspectionLevel(str, Enum):
    DRIVE_BY = "DRIVE_BY"
    INTERIOR = "INTERIOR"


class Priority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"


class FulfillmentStatus(str, Enum):
    INTAKE = "INTAKE"
    READY_FOR_DISPATCH = "READY_FOR_DISPATCH"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    QC_REVIEW = "QC_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    WAIVED = "WAIVED"


class ComparableStatus(str, Enum):
    DRAFT = "DRAFT"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class PhotoKind(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    STREET = "STREET"
    INTERIOR_LIVING = "INTERIOR_LIVING"
    INTERIOR_KITCHEN = "INTERIOR_KITCHEN"
    INTERIOR_BATH = "INTERIOR_BATH"
    DEFECT = "DEFECT"
    OTHER = "OTHER"


class FeeKind(str, Enum):
    BASE = "BASE"
    RUSH_SURCHARGE = "RUSH_SURCHARGE"
    INTERIOR_SURCHARGE = "INTERIOR_SURCHARGE"
    APPRAISAL_SURCHARGE = "APPRAISAL_SURCHARGE"
    TRAVEL = "TRAVEL"
    MISC = "MISC"


class FeeLineStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class QCVerdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class RevisionOutcome(str, Enum):
    OPEN = "OPEN"
    RESOLVED_ON_TIME = "RESOLVED_ON_TIME"
    RESOLVED_LATE = "RESOLVED_LATE"
    EXPIRED = "EXPIRED"


class PayoutBatchStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# common_fields: true — id + created_at + updated_at + version
class ClientAccount(TypedDict):
    id: str
    client_code: str
    display_name: str
    sla_hours_standard: int
    sla_hours_rush: int
    late_penalty_bps_per_day: int
    scorecard_weight_turnaround: float
    scorecard_weight_quality: float
    scorecard_weight_revision: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict):
    id: str
    broker_code: str
    full_name: str
    email: str
    max_concurrent_orders: int
    status: str
    composite_score: float
    created_at: str
    updated_at: str
    version: int


class BrokerLicense(TypedDict):
    id: str
    broker_id: str
    state_code: str
    license_kind: str
    license_number: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StateRegulation(TypedDict):
    id: str
    state_code: str
    bpo_permitted: bool
    appraisal_required_for_interior: bool
    min_driveby_radius_miles: float
    min_interior_radius_miles: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    street_address: str
    city: str
    state_code: str
    postal_code: str
    living_area_sqft: int
    lot_area_sqft: int
    year_built: int
    property_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationOrder(TypedDict):
    id: str
    client_id: str
    property_id: str
    assigned_broker_id: Optional[str]
    order_kind: str
    inspection_level: str
    priority: str
    agreed_fee_cents: int
    sla_due_at: Optional[str]
    completed_at: Optional[str]
    days_late: Optional[int]
    late_penalty_cents: Optional[int]
    net_payable_cents: Optional[int]
    fulfillment_status: str
    payment_status: str
    revision_count: int
    is_rush_breach: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class Comparable(TypedDict):
    id: str
    order_id: str
    source_property_id: str
    sale_price_cents: int
    sale_date: str
    distance_miles: float
    adjustment_cents: int
    adjusted_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeLine(TypedDict):
    id: str
    order_id: str
    fee_kind: str
    description: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QCReview(TypedDict):
    id: str
    order_id: str
    reviewer_id: str
    cycle_index: int
    verdict: Optional[str]
    defects_found: Optional[int]
    notes: Optional[str]
    reviewed_at: Optional[str]
    is_segregation_violation: bool
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict):
    id: str
    broker_id: str
    period_start: str
    period_end: str
    total_payable_cents: int
    order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carry ONLY id + created_at
class PhotoEvidence(TypedDict):
    id: str
    order_id: str
    photo_kind: str
    file_url: str
    captured_at: str
    uploaded_by_broker_id: str
    created_at: str


class QCRevisionRequest(TypedDict):
    id: str
    order_id: str
    qc_review_id: str
    cycle_index: int
    reason: Optional[str]
    due_at: str
    resolved_at: Optional[str]
    outcome: str
    created_at: str


class VolumeForecast(TypedDict):
    id: str
    state_code: str
    forecast_month: str
    predicted_order_count: int
    model_version: str
    generated_at: str
    created_at: str
