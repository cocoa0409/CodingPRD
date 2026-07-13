"""Domain types: entity TypedDicts, status enums, role enum.

All names use PRD terminology (PRD §1–§3). Two resource types — the campaign
Update/thank-you note and the Refund record — are immutable journal entries
carrying ONLY ``id`` and ``created_at`` (PRD §2.4); their TypedDicts omit
``updated_at`` and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    GUEST = "Guest"
    ORGANIZER = "Organizer"
    BENEFICIARY = "Beneficiary"
    DONOR = "Donor"
    TRUST_SAFETY_AGENT = "TrustSafetyAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


# ------------------------------------------------------------------------- statuses
class CampaignLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PayoutPosture(str, Enum):
    OPEN = "OPEN"
    HOLD = "HOLD"
    FROZEN = "FROZEN"


class BeneficiaryVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TeamRole(str, Enum):
    OWNER = "OWNER"
    CO_ORGANIZER = "CO_ORGANIZER"
    WITHDRAWAL_MANAGER = "WITHDRAWAL_MANAGER"


class TeamMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class DonationStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class TaxReceiptStatus(str, Enum):
    DEDUCTIBLE = "DEDUCTIBLE"
    NON_DEDUCTIBLE = "NON_DEDUCTIBLE"


class UpdateType(str, Enum):
    UPDATE = "UPDATE"
    THANK_YOU = "THANK_YOU"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    ON_HOLD = "ON_HOLD"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class DisputeReason(str, Enum):
    FRAUD = "FRAUD"
    UNAUTHORIZED = "UNAUTHORIZED"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    OTHER = "OTHER"


class RefundReason(str, Enum):
    REQUESTED_BY_DONOR = "REQUESTED_BY_DONOR"
    DISPUTE_UPHELD = "DISPUTE_UPHELD"


class HoldSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CampaignCategory(str, Enum):
    MEDICAL = "MEDICAL"
    MEMORIAL = "MEMORIAL"
    EMERGENCY = "EMERGENCY"
    OTHER = "OTHER"


class PlacementCategory(str, Enum):
    HOMEPAGE = "HOMEPAGE"
    MEDICAL = "MEDICAL"
    EMERGENCY = "EMERGENCY"


class PlacementStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# ------------------------------------------------------------------------- entities
# common_fields: true — id + created_at + updated_at + version
class Organizer(TypedDict):
    id: str
    display_name: str
    email: str
    total_dispute_count: int
    upheld_dispute_count: int
    refunded_amount_cents: int
    raised_cents: int
    has_unverified_beneficiary: bool
    strict_risk_score: int
    lenient_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    legal_name: str
    email: str
    stripe_account_ref: Optional[str]
    verification_status: str
    withdrawal_ready: bool
    total_paid_out_cents: int
    last_payout_settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    display_name: str
    email: str
    is_anonymous_default: bool
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    organizer_id: str
    beneficiary_id: str
    title: str
    story: str
    goal_cents: int
    category: str
    is_charity: bool
    lifecycle_status: str
    payout_posture: str
    raised_cents: int
    reserve_total_cents: int
    committed_cents: int
    paid_out_cents: int
    disputed_locked_cents: int
    hold_locked_cents: int
    provisional_available_cents: int
    settled_available_cents: int
    tax_disclosure: str
    created_at: str
    updated_at: str
    version: int


class TeamMember(TypedDict):
    id: str
    campaign_id: str
    organizer_id: str
    team_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    campaign_id: str
    donor_id: str
    amount_cents: int
    tip_cents: int
    is_anonymous: bool
    processing_fee_cents: int
    total_charged_cents: int
    net_to_campaign_cents: int
    reserve_cents: int
    status: str
    tax_receipt_status: str
    thanked: bool
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    campaign_id: str
    beneficiary_id: str
    amount_cents: int
    scheduled_at: Optional[str]
    status: str
    stripe_payout_ref: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    donation_id: str
    reason: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    campaign_id: str
    reason: str
    severity: str
    locked_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeaturePlacement(TypedDict):
    id: str
    campaign_id: str
    category: str
    slot_index: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable journal entries, ONLY id + created_at (PRD §2.4)
class Update(TypedDict):
    id: str
    campaign_id: str
    update_type: str
    body: str
    donation_id: Optional[str]
    created_at: str


class Refund(TypedDict):
    id: str
    donation_id: str
    dispute_id: Optional[str]
    amount_cents: int
    reason: str
    created_at: str
