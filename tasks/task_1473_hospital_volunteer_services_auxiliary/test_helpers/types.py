"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DIRECTOR = "VolunteerServicesDirector"
    COORDINATOR = "VolunteerCoordinator"
    SCREENER = "Screener"
    DEPARTMENT_HEAD = "DepartmentHead"
    TREASURER = "AuxiliaryTreasurer"
    VOLUNTEER = "Volunteer"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ServiceStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SEPARATED = "SEPARATED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PRESIDENT = "PRESIDENT"


class ClearanceType(str, Enum):
    BACKGROUND = "BACKGROUND"
    HEALTH_TB = "HEALTH_TB"
    HEALTH_FLU = "HEALTH_FLU"


class ClearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RoleCategory(str, Enum):
    PATIENT_FACING = "PATIENT_FACING"
    GIFT_SHOP = "GIFT_SHOP"
    CLERICAL = "CLERICAL"
    FUNDRAISING = "FUNDRAISING"
    COMMUNITY = "COMMUNITY"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PlacementStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"


class TrainingRecurrence(str, Enum):
    ONE_TIME = "ONE_TIME"
    ANNUAL = "ANNUAL"


class TrainingStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    SIGNED_UP = "SIGNED_UP"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class HourEntryStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class BadgeStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class SaleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class RecognitionEventType(str, Enum):
    TIER_INCREASED = "TIER_INCREASED"
    TIER_DECREASED = "TIER_DECREASED"


class VolunteerApplication(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    phone: str
    notes: Optional[str]
    status: str
    volunteer_id: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    rejection_reason: Optional[str]
    info_request_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    phone: str
    notes: Optional[str]
    service_status: str
    compliance_posture: str
    total_service_hours: float
    recognition_points: float
    recognition_tier: str
    joined_at: str
    current_service_year_start: str
    separated_at: Optional[str]
    separation_reason: Optional[str]
    suspension_reason: Optional[str]
    is_junior_today: bool
    created_at: str
    updated_at: str
    version: int


class Clearance(TypedDict, total=False):
    id: str
    volunteer_id: str
    clearance_type: str
    document_ref: str
    status: str
    submitted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    expires_at: Optional[str]
    adjudication_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    name: str
    head_user_id: str
    junior_allowed: bool
    created_at: str
    updated_at: str
    version: int


class VolunteerRole(TypedDict, total=False):
    id: str
    name: str
    category: str
    minimum_age: int
    can_supervise_juniors: bool
    required_training_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class DepartmentRequest(TypedDict, total=False):
    id: str
    department_id: str
    role_id: str
    slots_needed: int
    slots_filled: int
    notes: Optional[str]
    status: str
    filled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict, total=False):
    id: str
    request_id: str
    volunteer_id: str
    offer_note: Optional[str]
    counter_note: Optional[str]
    counter_rounds: int
    status: str
    accepted_at: Optional[str]
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    volunteer_id: str
    training_code: str
    recurrence: str
    status: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    department_id: str
    role_id: str
    start_at: str
    end_at: str
    capacity: int
    allow_waitlist: bool
    filled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    supervisor_assignment_id: Optional[str]
    signed_up_at: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourEntry(TypedDict, total=False):
    id: str
    volunteer_id: str
    shift_assignment_id: Optional[str]
    service_date: str
    minutes: int
    service_category: str
    notes: Optional[str]
    status: str
    approved_at: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Badge(TypedDict, total=False):
    id: str
    volunteer_id: str
    badge_number: str
    status: str
    issued_at: Optional[str]
    revoked_at: Optional[str]
    revoke_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundraisingCampaign(TypedDict, total=False):
    id: str
    name: str
    goal_cents: int
    start_at: str
    end_at: str
    promo_discount_pct: int
    status: str
    created_by_user_id: str
    closed_at: Optional[str]
    gross_receipts_cents: int
    raised_cents: int
    net_proceeds_cents: int
    disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class GiftShopItem(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit_price_cents: int
    unit_cost_cents: int
    stock_on_hand: int
    reorder_level: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class GiftShopSale(TypedDict, total=False):
    id: str
    cashier_volunteer_id: str
    buyer_volunteer_id: Optional[str]
    campaign_id: Optional[str]
    lines: list
    total_cents: int
    discount_pct_applied: int
    tendered_cents: int
    change_cents: int
    status: str
    voided_at: Optional[str]
    void_reason: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecognitionEvent(TypedDict, total=False):
    # Append-only event log: id + created_at only; NO updated_at, NO version
    id: str
    volunteer_id: str
    event_type: str
    tier: str
    points_snapshot: float
    created_at: str
