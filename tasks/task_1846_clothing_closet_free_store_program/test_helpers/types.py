"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
four system-managed fields (id, created_at, updated_at, version) described in
the PRD common-resource-properties section.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    VOLUNTEER_LEAD = "VolunteerLead"
    VOLUNTEER = "Volunteer"
    CLIENT = "Client"
    REFERRAL_PARTNER = "ReferralPartner"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EligibilityTier(str, Enum):
    STANDARD = "STANDARD"
    HARDSHIP = "HARDSHIP"


class VisitStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    VOIDED = "VOIDED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISTRIBUTED = "DISTRIBUTED"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_SORT = "IN_SORT"
    SORTED = "SORTED"
    CLOSED = "CLOSED"


class ItemStatus(str, Enum):
    PENDING_STOCK = "PENDING_STOCK"
    STOCKED = "STOCKED"
    RESERVED = "RESERVED"
    DISTRIBUTED = "DISTRIBUTED"
    OFF_SEASON = "OFF_SEASON"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    RECYCLED = "RECYCLED"


class ItemCategory(str, Enum):
    ADULT_TOPS = "ADULT_TOPS"
    ADULT_BOTTOMS = "ADULT_BOTTOMS"
    CHILDRENS = "CHILDRENS"
    COATS = "COATS"
    INTERVIEW_ATTIRE = "INTERVIEW_ATTIRE"
    ACCESSORIES = "ACCESSORIES"


class Season(str, Enum):
    WINTER = "WINTER"
    SUMMER = "SUMMER"
    ALL_SEASON = "ALL_SEASON"


class QualityGrade(str, Enum):
    NEW_WITH_TAGS = "NEW_WITH_TAGS"
    GOOD = "GOOD"
    FAIR = "FAIR"
    REJECT = "REJECT"


class ZonePosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    NEAR_FULL = "NEAR_FULL"
    FULL = "FULL"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ShiftRoleType(str, Enum):
    SORTING = "SORTING"
    INTAKE = "INTAKE"
    FLOOR = "FLOOR"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SignupStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DriveType(str, Enum):
    INTERVIEW_ATTIRE = "INTERVIEW_ATTIRE"
    WINTER_COATS = "WINTER_COATS"


class DriveStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RotationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RecyclingBatchStatus(str, Enum):
    ACCUMULATING = "ACCUMULATING"
    SEALED = "SEALED"
    PICKED_UP = "PICKED_UP"


class Client(TypedDict):
    id: str
    full_name: str
    household_size: int
    eligibility_tier: str
    status: str
    last_checkout_at: Optional[str]
    visits_in_30d: int
    items_in_30d: int
    created_at: str
    updated_at: str
    version: int


class ClientVisit(TypedDict):
    id: str
    client_id: str
    voucher_id: Optional[str]
    status: str
    checked_in_at: str
    checked_out_at: Optional[str]
    general_allowance: int
    voucher_bonus_applied: int
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict):
    id: str
    visit_id: str
    item_id: str
    category_snapshot: str
    is_drive_line: bool
    drive_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationBatch(TypedDict):
    id: str
    donor_name: str
    donor_email: Optional[str]
    item_count_declared: int
    items_created_count: int
    status: str
    sorted_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    donation_batch_id: str
    category: str
    season: str
    quality_grade: str
    drive_id: Optional[str]
    status: str
    storage_zone_id: Optional[str]
    reserved_visit_id: Optional[str]
    recycling_batch_id: Optional[str]
    graded_by_user_id: str
    stocked_at: Optional[str]
    distributed_at: Optional[str]
    distributed_from_zone_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageZone(TypedDict):
    id: str
    zone_code: str
    season_policy: str
    capacity_items: int
    current_stock: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    is_lead: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    start_at: str
    end_at: str
    role_type: str
    capacity_volunteers: int
    active_signup_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftSignup(TypedDict):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralPartner(TypedDict):
    id: str
    name: str
    base_voucher_quota: int
    status: str
    activated_month_key: str
    vouchers_issued_current_month: int
    current_month_quota: int
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    code: str
    partner_id: str
    client_id: str
    bonus_items: int
    waives_frequency: bool
    expires_at: str
    status: str
    issued_month_key: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialDrive(TypedDict):
    id: str
    drive_type: str
    target_category: str
    start_at: str
    end_at: str
    bonus_items_per_client: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalRotation(TypedDict):
    id: str
    target_season: str
    window_start: str
    window_end: str
    status: str
    executed_at: Optional[str]
    moved_out_count: int
    moved_in_count: int
    created_at: str
    updated_at: str
    version: int


class RecyclingBatch(TypedDict):
    id: str
    recycler_name: str
    capacity_kg: float
    status: str
    item_count: int
    est_weight_kg: float
    provisional_credit_cents: Optional[int]
    actual_weight_kg: Optional[float]
    final_credit_cents: Optional[int]
    sealed_by_user_id: Optional[str]
    picked_up_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
