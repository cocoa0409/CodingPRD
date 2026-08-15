"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2 and 3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    FIELD_REP = "FieldRep"
    CLIENT = "Client"
    PAYROLL_ADMIN = "PayrollAdmin"
    BILLING_CLERK = "BillingClerk"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BillingModel(str, Enum):
    PER_STORE = "PER_STORE"
    HOURLY = "HOURLY"


class ScopeType(str, Enum):
    RESET = "RESET"
    NEW_ITEM_CUTOVER = "NEW_ITEM_CUTOVER"
    AUDIT = "AUDIT"
    FIXTURE_INSTALL = "FIXTURE_INSTALL"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    IN_FIELD = "IN_FIELD"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"


class ProjectStoreStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    DROPPED = "DROPPED"


class EmploymentType(str, Enum):
    W2 = "W2"
    C1099 = "C1099"


class MileagePolicy(str, Enum):
    HOME_BASED = "HOME_BASED"
    FIRST_STOP = "FIRST_STOP"


class RepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class VerificationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PhotoType(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    POG_LABEL = "POG_LABEL"
    FIXTURE = "FIXTURE"
    VOID_AREA = "VOID_AREA"


class ExceptionType(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    VOID = "VOID"
    FIXTURE_MISSING = "FIXTURE_MISSING"
    POG_MISSING = "POG_MISSING"
    PRICE_MISMATCH = "PRICE_MISMATCH"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Resolution(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DELIVERY_EXCEPTION = "DELIVERY_EXCEPTION"
    LOST = "LOST"


class ScanResult(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"
    LOST = "LOST"


class ReworkAuthStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class MileageLogStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD 2.4).
# PhotoEvidence and ExceptionReport are immutable once filed and carry only
# id + created_at (PRD 2.4), so their TypedDicts omit updated_at and version.

class Client(TypedDict, total=False):
    id: str
    name: str
    billing_model: Optional[str]
    status: str
    hourly_rate_cents: Optional[int]
    per_store_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    scope_type: str
    status: str
    billing_model: Optional[str]
    effective_billing_model: Optional[str]
    rework_penalty_score: int
    posture: str
    completed_store_count: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_number: str
    name: str
    address: str
    timezone: str
    created_at: str
    updated_at: str
    version: int


class ProjectStore(TypedDict, total=False):
    id: str
    project_id: str
    store_id: str
    status: str
    due_date: str
    assigned_rep_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldRep(TypedDict, total=False):
    id: str
    full_name: str
    employment_type: str
    home_base_commute_miles: int
    mileage_rate_cents: int
    travel_minute_rate_cents: int
    mileage_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    project_id: str
    project_store_id: str
    rep_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    is_rework: bool
    created_at: str
    updated_at: str
    version: int


class StoreVisit(TypedDict, total=False):
    id: str
    assignment_id: str
    check_in_at: str
    check_out_at: Optional[str]
    on_site_minutes: int
    verification_status: str
    billable_amount_cents: Optional[int]
    is_rework: bool
    created_at: str
    updated_at: str
    version: int


class PhotoEvidence(TypedDict, total=False):
    # immutable evidence record: only id + created_at are system-managed
    id: str
    store_visit_id: str
    photo_type: str
    image_url: str
    captured_at: str
    created_at: str


class ExceptionReport(TypedDict, total=False):
    # immutable evidence record: only id + created_at are system-managed
    id: str
    store_visit_id: str
    exception_type: str
    sku_count: int
    severity: str
    resolution: str
    created_at: str


class FixtureShipment(TypedDict, total=False):
    id: str
    project_id: str
    project_store_id: str
    carrier: str
    tracking_number: str
    status: str
    promised_date: str
    created_at: str
    updated_at: str
    version: int


class ReworkAuthorization(TypedDict, total=False):
    id: str
    project_id: str
    project_store_id: str
    rejected_store_visit_id: str
    status: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MileageLog(TypedDict, total=False):
    id: str
    rep_id: str
    assignment_id: str
    round_trip_miles: int
    home_to_first_stop_miles: int
    drive_minutes: int
    mileage_pay_cents: int
    travel_time_pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    client_id: str
    project_id: str
    status: str
    line_total_cents: int
    adjustment_cents: int
    grand_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
