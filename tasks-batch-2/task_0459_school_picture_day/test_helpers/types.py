"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in the School Picture Day API is a full lifecycle record and carries
the four common properties id / created_at / updated_at / version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    STUDIO_PHOTOGRAPHER = "StudioPhotographer"
    FULFILLMENT_CLERK = "FulfillmentClerk"
    GUARDIAN = "Guardian"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class SessionStatus(str, Enum):
    DRAFT = "DRAFT"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    CAPTURE_OPEN = "CAPTURE_OPEN"
    GALLERY_OPEN = "GALLERY_OPEN"
    ORDERING_CLOSED = "ORDERING_CLOSED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PHOTOGRAPHED = "PHOTOGRAPHED"
    ABSENT = "ABSENT"


class PhotoStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    RETAKE_REQUESTED = "RETAKE_REQUESTED"
    RETAKEN = "RETAKEN"
    APPROVED = "APPROVED"


class PackageTier(str, Enum):
    BASIC = "BASIC"
    DELUXE = "DELUXE"
    PREMIUM = "PREMIUM"


class PhotoOrderStatus(str, Enum):
    CART = "CART"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RetouchKind(str, Enum):
    RETOUCH = "RETOUCH"
    RETAKE = "RETAKE"


class RetouchOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DONE = "DONE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DistributionMethod(str, Enum):
    SCHOOL_PICKUP = "SCHOOL_PICKUP"
    HOME_DELIVERY = "HOME_DELIVERY"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class CaptureSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class PictureDaySession(TypedDict, total=False):
    id: str
    school_name: str
    scheduled_date: str
    gallery_access_code: Optional[str]
    gallery_opens_at: Optional[str]
    gallery_closes_at: str
    retouch_budget_cents: int
    retouch_credit_balance_cents: int
    school_commission_balance_cents: int
    total_merchandise_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    guardian_user_id: str
    full_name: str
    grade: str
    homeroom: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Photo(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    matched_student_id: Optional[str]
    retake_of_photo_id: Optional[str]
    candidate_grade: str
    candidate_homeroom: str
    candidate_name: str
    match_confidence_score: int
    yearbook_exported: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageItem(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    sku: str
    name: str
    tier: str
    base_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class PhotoOrder(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    student_id: str
    subtotal_cents: int
    discount_pct: float
    discount_cents: int
    merchandise_cents: int
    shipping_cents: int
    total_cents: int
    has_premium_line: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    photo_order_id: str
    package_item_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class RetouchOrder(TypedDict, total=False):
    id: str
    photo_id: str
    kind: str
    adjustment_count: int
    premium_linked: bool
    gross_cost_cents: int
    comp_discount_cents: int
    net_cost_cents: int
    replacement_photo_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    photo_order_id: str
    carrier: str
    distribution_method: str
    tracking_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Backdrop(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    label: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Photographer(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class CaptureSlot(TypedDict, total=False):
    id: str
    picture_day_session_id: str
    backdrop_id: str
    photographer_id: str
    homeroom: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int
