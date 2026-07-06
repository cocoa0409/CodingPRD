"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    Homeowner = "Homeowner"
    BoardMember = "BoardMember"
    ComplianceOfficer = "ComplianceOfficer"
    HOAManager = "HOAManager"
    Anonymous = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class HomeownerStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    MARGINAL = "MARGINAL"
    DELINQUENT = "DELINQUENT"


class HomeownerBookingPrivilege(str, Enum):
    ALLOWED = "ALLOWED"
    FROZEN = "FROZEN"


class PropertyComplianceFlag(str, Enum):
    OPEN = "OPEN"
    APPROVED_MOD = "APPROVED_MOD"
    SUSPENDED = "SUSPENDED"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DELINQUENT = "DELINQUENT"
    ON_LIEN = "ON_LIEN"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    MANUAL = "MANUAL"
    AUTOPAY = "AUTOPAY"


class AutopayMandateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ARCCategory(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


class ARCRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ARCReviewVerdict(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVISE = "REVISE"


class ViolationCategory(str, Enum):
    NUISANCE = "NUISANCE"
    LANDSCAPE = "LANDSCAPE"
    STRUCTURAL = "STRUCTURAL"
    SAFETY = "SAFETY"


class ViolationStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    CURED = "CURED"
    FINED = "FINED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class AmenityReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class MotionCategory(str, Enum):
    BUDGET = "BUDGET"
    POLICY = "POLICY"
    ELECTION = "ELECTION"


class MotionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PASSED = "CLOSED_PASSED"
    CLOSED_FAILED = "CLOSED_FAILED"
    QUORUM_FAILED = "QUORUM_FAILED"


class BallotChoice(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


class WorkOrderWorkStatus(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderPaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class WorkOrderSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_ARC = "AUTO_ARC"


class DocumentCategory(str, Enum):
    CCR = "CCR"
    POLICY = "POLICY"
    MINUTES = "MINUTES"
    BUDGET = "BUDGET"


class GracePolicy(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all except Document carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Homeowner(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    is_board_member: bool
    standing: str
    delinquency_score: int
    booking_privilege: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    homeowner_id: str
    address: str
    monthly_dues_cents: int
    compliance_flag: str
    total_outstanding_cents: int
    fine_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    property_id: str
    billing_period_start: str
    billing_period_end: str
    prorate_from: Optional[str]
    amount_due_cents: int
    amount_paid_cents: int
    late_fee_cents: int
    status: str
    due_date: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    assessment_id: str
    amount_cents: int
    method: str
    posted_at: str
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AutopayMandate(TypedDict, total=False):
    id: str
    homeowner_id: str
    max_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ARCRequest(TypedDict, total=False):
    id: str
    property_id: str
    submitter_homeowner_id: str
    category: str
    description: str
    revision_count: int
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ARCReview(TypedDict, total=False):
    id: str
    arc_request_id: str
    reviewer_homeowner_id: str
    weight: int
    verdict: str
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    property_id: str
    category: str
    reported_at: str
    fined_at: Optional[str]
    fine_amount_cents: int
    fine_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Amenity(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    reservation_window_start_hour: int
    reservation_window_end_hour: int
    blackout_dates: List[str]
    created_at: str
    updated_at: str
    version: int


class AmenityReservation(TypedDict, total=False):
    id: str
    amenity_id: str
    homeowner_id: str
    start_ts: str
    end_ts: str
    guest_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Motion(TypedDict, total=False):
    id: str
    title: str
    description: str
    category: str
    voting_window_start: str
    voting_window_end: str
    eligible_voter_count: int
    quorum_pct: int
    status: str
    yes_count: int
    no_count: int
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict, total=False):
    id: str
    motion_id: str
    homeowner_id: str
    choice: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    related_property_id: Optional[str]
    title: str
    cost_estimate_cents: int
    assigned_vendor_id: Optional[str]
    work_status: str
    payment_status: str
    source: str
    created_at: str
    updated_at: str
    version: int


# Document has common_fields=false — only id + created_at
class Document(TypedDict, total=False):
    id: str
    title: str
    category: str
    content_url: str
    created_at: str
