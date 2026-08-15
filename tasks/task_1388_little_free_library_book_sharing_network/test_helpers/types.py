"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    STEWARD = "Steward"
    SCHOOL_LIAISON = "SchoolLiaison"
    HUB_COORDINATOR = "HubCoordinator"
    MODERATOR = "Moderator"
    NETWORK_ADMIN = "NetworkAdmin"


class StewardStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BoxCharterStatus(str, Enum):
    DRAFT = "DRAFT"
    CHARTERED = "CHARTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ListingPosture(str, Enum):
    UNLISTED = "UNLISTED"
    LISTED = "LISTED"
    FLAGGED = "FLAGGED"
    DELISTED = "DELISTED"


class InspectionResult(str, Enum):
    CONFIRMED = "CONFIRMED"
    NOT_FOUND = "NOT_FOUND"
    FAILED_CONDITION = "FAILED_CONDITION"


class MaintenanceCategory(str, Enum):
    WEATHER_DAMAGE = "WEATHER_DAMAGE"
    VANDALISM = "VANDALISM"
    WEAR = "WEAR"
    INSTALLATION_DEFECT = "INSTALLATION_DEFECT"


class MaintenanceSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MaintenanceStatus(str, Enum):
    REPORTED = "REPORTED"
    SCHEDULED = "SCHEDULED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    WONT_FIX = "WONT_FIX"


class Season(str, Enum):
    WINTER = "WINTER"
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    FALL = "FALL"


class ComplaintCategory(str, Enum):
    INAPPROPRIATE_CONTENT = "INAPPROPRIATE_CONTENT"
    HATE_SPEECH = "HATE_SPEECH"
    COMMERCIAL_SPAM = "COMMERCIAL_SPAM"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    STEWARD_RESPONSE_PENDING = "STEWARD_RESPONSE_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"
    ESCALATED = "ESCALATED"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_DISMISSED = "ADJUDICATED_DISMISSED"


class BookCategory(str, Enum):
    FICTION = "FICTION"
    NONFICTION = "NONFICTION"
    CHILDREN = "CHILDREN"
    YOUNG_ADULT = "YOUNG_ADULT"
    REFERENCE = "REFERENCE"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class SchoolStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DriveStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    OPEN = "OPEN"
    COLLECTION_CLOSED = "COLLECTION_CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BatchSourceType(str, Enum):
    PUBLIC_DROP = "PUBLIC_DROP"
    STEWARD_TRANSFER = "STEWARD_TRANSFER"
    BOOK_DRIVE = "BOOK_DRIVE"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SORTED = "SORTED"
    CLOSED = "CLOSED"


class BookItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ALLOCATED = "ALLOCATED"
    DISPATCHED = "DISPATCHED"
    PLACED = "PLACED"
    QUARANTINED = "QUARANTINED"
    RECYCLED = "RECYCLED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    PLACED = "PLACED"
    CANCELLED = "CANCELLED"
    REMOVED = "REMOVED"


class RecognitionEventType(str, Enum):
    MAINTENANCE_RESOLVED = "MAINTENANCE_RESOLVED"
    ALLOCATION_PLACED = "ALLOCATION_PLACED"
    DRIVE_COMPLETED = "DRIVE_COMPLETED"
    COMPLAINT_UPHELD = "COMPLAINT_UPHELD"
    TRAINING_PASSED = "TRAINING_PASSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# common_fields entities carry id + created_at + updated_at + version.
# Lean record types (TrainingCompletion, InspectionRecord, RecognitionEvent)
# carry ONLY id + created_at — no updated_at, no version.
# ---------------------------------------------------------------------------


class Steward(TypedDict):
    id: str
    full_name: str
    email: str
    region_code: str
    status: str
    training_level: int
    lifetime_points: int
    rolling_points: int
    recognition_tier: str
    strike_count: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingModule(TypedDict):
    id: str
    code: str
    title: str
    level: int
    prerequisite_module_id: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class TrainingCompletion(TypedDict):
    # Lean record: id + created_at only, no updated_at / version.
    id: str
    steward_id: str
    module_id: str
    score: int
    result: str
    created_at: str


class LibraryBox(TypedDict):
    id: str
    steward_id: str
    name: str
    latitude: float
    longitude: float
    capacity_books: int
    region_code: str
    charter_number: Optional[str]
    charter_status: str
    listing_posture: str
    installed_at: Optional[str]
    suspended_at: Optional[str]
    last_activity_at: Optional[str]
    current_stock: int
    open_critical_maintenance_count: int
    open_high_maintenance_count: int
    upheld_complaints_90d: int
    days_since_activity: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict):
    # Lean record: id + created_at only, no updated_at / version.
    id: str
    box_id: str
    inspector_user_id: str
    result: str
    notes: Optional[str]
    created_at: str


class MaintenanceRequest(TypedDict):
    id: str
    box_id: str
    category: str
    description: str
    severity: Optional[str]
    status: str
    season_at_report: str
    season_multiplier: float
    sla_deadline_at: Optional[str]
    triaged_at: Optional[str]
    scheduled_date: Optional[str]
    resolved_at: Optional[str]
    resolution_count: int
    reimbursement_cents: Optional[int]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    box_id: str
    category: str
    target_category: Optional[str]
    description: str
    evidence_url: Optional[str]
    status: str
    triaged_by_user_id: Optional[str]
    response_due_at: Optional[str]
    response_text: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_notes: Optional[str]
    outcome: Optional[str]
    upheld_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    district_code: str
    contact_email: str
    region_code: str
    restricted_categories: List[str]
    status: str
    drives_completed_count: int
    created_at: str
    updated_at: str
    version: int


class BookDrive(TypedDict):
    id: str
    school_id: str
    coordinator_steward_id: str
    goal_books: int
    starts_at: str
    ends_at: str
    status: str
    school_approval_status: str
    network_approval_status: str
    collected_count: int
    accepted_count: int
    fulfillment_pct_gross: int
    fulfillment_pct_net: int
    qualifies_for_bonus: bool
    created_at: str
    updated_at: str
    version: int


class DonationBatch(TypedDict):
    id: str
    source_type: str
    drive_id: Optional[str]
    region_code: str
    status: str
    item_count: int
    graded_count: int
    created_at: str
    updated_at: str
    version: int


class BookItem(TypedDict):
    id: str
    batch_id: str
    title: str
    category: str
    condition_grade: Optional[str]
    status: str
    box_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanSnapshotEntry(TypedDict):
    box_id: str
    quantity: int
    need_score: int


class DistributionRun(TypedDict):
    id: str
    batch_id: str
    status: str
    plan_snapshot: List[PlanSnapshotEntry]
    planned_item_count: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    run_id: str
    book_item_id: str
    box_id: str
    status: str
    placed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecognitionEvent(TypedDict):
    # Lean record: id + created_at only, no updated_at / version.
    id: str
    steward_id: str
    event_type: str
    points_delta: int
    source_type: str
    source_id: str
    created_at: str
