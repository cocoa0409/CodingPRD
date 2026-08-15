"""Domain types: entity TypedDicts, status enums, role enum for the Holiday Toy Drive API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AGENCY_COORDINATOR = "AgencyCoordinator"
    CASE_WORKER = "CaseWorker"
    DONOR = "Donor"
    DISTRIBUTION_VOLUNTEER = "DistributionVolunteer"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    INTAKE_OPEN = "INTAKE_OPEN"
    MATCHING = "MATCHING"
    DISTRIBUTION_PREP = "DISTRIBUTION_PREP"
    DISTRIBUTION = "DISTRIBUTION"
    RECONCILIATION = "RECONCILIATION"
    CLOSED = "CLOSED"


class PrivacyMode(str, Enum):
    STRICT = "STRICT"
    STANDARD = "STANDARD"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FamilyStatus(str, Enum):
    REFERRED = "REFERRED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    MATCHED = "MATCHED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    BACKFILLED = "BACKFILLED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ChildStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WISH_LOCKED = "WISH_LOCKED"
    ADOPTED = "ADOPTED"
    GIFT_RECEIVED = "GIFT_RECEIVED"
    DELIVERED = "DELIVERED"
    BACKFILL_ELIGIBLE = "BACKFILL_ELIGIBLE"
    BACKFILL_PURCHASED = "BACKFILL_PURCHASED"
    CLOSED = "CLOSED"


class AgeBand(str, Enum):
    INFANT = "INFANT"
    TODDLER = "TODDLER"
    PRESCHOOL = "PRESCHOOL"
    SCHOOL_AGE = "SCHOOL_AGE"
    PRETEEN = "PRETEEN"
    TEEN = "TEEN"


class Gender(str, Enum):
    F = "F"
    M = "M"
    X = "X"


class WishItemStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMMITTED = "COMMITTED"
    RECEIVED = "RECEIVED"
    DELIVERED = "DELIVERED"
    BACKFILL_SOURCED = "BACKFILL_SOURCED"


class WishCategory(str, Enum):
    TOY = "TOY"
    CLOTHING = "CLOTHING"
    BOOK = "BOOK"
    SPORTS = "SPORTS"
    ELECTRONICS = "ELECTRONICS"
    ART = "ART"
    OTHER = "OTHER"


class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AdoptionScope(str, Enum):
    WHOLE_FAMILY = "WHOLE_FAMILY"
    CHILD_LIST = "CHILD_LIST"


class AdoptionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULFILLED = "FULFILLED"
    LATE_CANCELLED = "LATE_CANCELLED"
    DONOR_CANCELLED = "DONOR_CANCELLED"
    ADMIN_CANCELLED = "ADMIN_CANCELLED"
    EXPIRED = "EXPIRED"


class GiftStatus(str, Enum):
    COMMITTED = "COMMITTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    SORTED = "SORTED"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    RETURNED_TO_DONOR = "RETURNED_TO_DONOR"
    BACKFILL_REPLACED = "BACKFILL_REPLACED"


class BackfillPurchaseStatus(str, Enum):
    ORDERED = "ORDERED"
    PURCHASED = "PURCHASED"
    SORTED = "SORTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DistributionEventStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN_FOR_SLOTS = "OPEN_FOR_SLOTS"
    SORTING = "SORTING"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DistributionSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Lane(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class DuplicateFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"
    DISMISSED = "DISMISSED"


class DuplicateFlagDetector(str, Enum):
    AUTO_HASH = "AUTO_HASH"
    MANUAL_REPORT = "MANUAL_REPORT"


class ThankYouNoteStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    BOUNCED = "BOUNCED"
    CANCELLED = "CANCELLED"


class ThankYouTemplate(str, Enum):
    STANDARD = "STANDARD"
    MAJOR_DONOR = "MAJOR_DONOR"
    FIRST_TIME = "FIRST_TIME"
    LAPSED_RETURNING = "LAPSED_RETURNING"


class AuditEventType(str, Enum):
    PII_VIEW = "PII_VIEW"
    PII_EXPORT = "PII_EXPORT"
    STATUS_CHANGE = "STATUS_CHANGE"
    DUPLICATE_FLAGGED = "DUPLICATE_FLAGGED"
    DUPLICATE_RESOLVED = "DUPLICATE_RESOLVED"
    CONSENT_CHANGE = "CONSENT_CHANGE"


class Campaign(TypedDict, total=False):
    id: str
    season_year: int
    status: str
    intake_open_at: str
    intake_close_at: str
    gift_return_deadline: str
    distribution_date: str
    max_children_per_family: int
    max_gift_value_cents: int
    min_gift_value_cents: int
    backfill_budget_cents: int
    backfill_spent_cents: int
    privacy_mode: str
    created_at: str
    updated_at: str
    version: int


class PartnerAgency(TypedDict, total=False):
    id: str
    agency_code: str
    legal_name: str
    status: str
    referral_quota: int
    referral_used_count: int
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict, total=False):
    id: str
    agency_id: str
    campaign_id: str
    primary_caregiver_name: str
    caregiver_dob: str
    household_size: int
    address_text: str
    phone_last4: str
    duplicate_hash: str
    status: str
    verification_note: str
    verified_at: Optional[str]
    fulfilled_children_count: int
    total_children_count: int
    duplicate_of_family_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict, total=False):
    id: str
    family_id: str
    first_name: str
    dob: str
    gender: str
    age_band: str
    clothing_size: str
    interest_tags: List[str]
    status: str
    gift_estimate_cents: int
    created_at: str
    updated_at: str
    version: int


class WishItem(TypedDict, total=False):
    id: str
    child_id: str
    description: str
    category: str
    estimated_price_cents: int
    priority_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict, total=False):
    id: str
    email: str
    display_name: str
    status: str
    max_adoptions_per_season: int
    preferred_age_bands: List[str]
    giving_history_cents: int
    thank_you_opt_in: bool
    created_at: str
    updated_at: str
    version: int


class Adoption(TypedDict, total=False):
    id: str
    campaign_id: str
    donor_id: str
    family_id: str
    scope: str
    child_ids: List[str]
    commitment_cents: int
    status: str
    pledged_at: str
    confirmed_at: Optional[str]
    return_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Gift(TypedDict, total=False):
    id: str
    adoption_id: str
    child_id: str
    wish_item_id: Optional[str]
    description: str
    declared_value_cents: int
    status: str
    received_at: Optional[str]
    sorted_at: Optional[str]
    slot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackfillPurchase(TypedDict, total=False):
    id: str
    campaign_id: str
    child_id: str
    wish_item_id: str
    quoted_cost_cents: int
    final_cost_cents: Optional[int]
    status: str
    purchased_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict, total=False):
    id: str
    campaign_id: str
    site_name: str
    start_at: str
    end_at: str
    status: str
    capacity_slots: int
    created_at: str
    updated_at: str
    version: int


class DistributionSlot(TypedDict, total=False):
    id: str
    event_id: str
    family_id: str
    window_start: str
    window_end: str
    lane: str
    status: str
    gifts_staged_count: int
    created_at: str
    updated_at: str
    version: int


class DuplicateFlag(TypedDict, total=False):
    id: str
    family_id: str
    other_family_id: str
    detected_by: str
    status: str
    resolution_note: str
    created_at: str
    updated_at: str
    version: int


class ThankYouNote(TypedDict, total=False):
    id: str
    campaign_id: str
    donor_id: str
    template: str
    status: str
    sent_at: Optional[str]
    personalization_token: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit log: carries ONLY id + created_at as common fields
# (no updated_at, no version).
class FamilyAuditEvent(TypedDict, total=False):
    id: str
    family_id: str
    actor_role: str
    actor_id: str
    event_type: str
    payload_json: dict
    occurred_at: str
    created_at: str


class SeasonSettings(TypedDict, total=False):
    id: str
    singleton_key: str
    duplicate_auto_detect_enabled: bool
    duplicate_hash_salt: str
    late_donor_grace_hours: int
    major_donor_threshold_cents: int
    created_at: str
    updated_at: str
    version: int
