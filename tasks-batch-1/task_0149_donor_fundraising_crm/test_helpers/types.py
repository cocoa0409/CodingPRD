"""Domain types: entity TypedDicts, status enums, and the role enum.

All field names mirror the PRD's Donor & Fundraising CRM contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    GIFT_ADMIN = "GiftAdmin"
    CAMPAIGN_MANAGER = "CampaignManager"
    DONOR_RELATIONS = "DonorRelations"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GiftStatus(str, Enum):
    RECORDED = "RECORDED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECEIPTED = "RECEIPTED"
    REFUNDED = "REFUNDED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    WAIVED = "WAIVED"


class MatchClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class PlannedGiftStatus(str, Enum):
    INTENT = "INTENT"
    CONFIRMED = "CONFIRMED"
    REALIZED = "REALIZED"
    LAPSED = "LAPSED"


class DonorLifecycleStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REACTIVATED = "REACTIVATED"
    ARCHIVED = "ARCHIVED"


class GivingStatus(str, Enum):
    NONE = "NONE"
    ENTRY = "ENTRY"
    MID = "MID"
    MAJOR = "MAJOR"


class SoftCreditPolicy(str, Enum):
    FULL_TO_ALL = "FULL_TO_ALL"
    SPLIT_EVEN = "SPLIT_EVEN"
    PRIMARY_ONLY = "PRIMARY_ONLY"


class AppealChannel(str, Enum):
    EMAIL = "EMAIL"
    DIRECT_MAIL = "DIRECT_MAIL"
    EVENT = "EVENT"
    PHONE = "PHONE"
    WEB = "WEB"


class Frequency(str, Enum):
    ONE_TIME = "ONE_TIME"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class ScheduleBasis(str, Enum):
    FRONT_LOADED = "FRONT_LOADED"
    BACK_LOADED = "BACK_LOADED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    ACH = "ACH"
    CASH = "CASH"
    STOCK = "STOCK"


class PlannedVehicle(str, Enum):
    BEQUEST = "BEQUEST"
    CHARITABLE_TRUST = "CHARITABLE_TRUST"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    IRA_ROLLOVER = "IRA_ROLLOVER"


class AcknowledgementKind(str, Enum):
    ACKNOWLEDGEMENT = "ACKNOWLEDGEMENT"
    RECEIPT = "RECEIPT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Standard resources carry id + created_at + updated_at + version.
class Household(TypedDict):
    id: str
    name: str
    primary_donor_id: Optional[str]
    soft_credit_policy: str
    total_soft_credit_cents: int
    member_count: int
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict):
    id: str
    full_name: str
    email: str
    household_id: Optional[str]
    employer_id: Optional[str]
    lifecycle_status: str
    giving_status: str
    lifetime_hard_credit_cents: int
    last_gift_at: Optional[str]
    lapse_threshold_days: int
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    name: str
    match_ratio: float
    min_gift_cents: int
    max_match_cents: int
    annual_match_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    name: str
    goal_cents: int
    starts_on: str
    ends_on: str
    status: str
    raised_hard_cents: int
    raised_with_match_cents: int
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    campaign_id: str
    channel: str
    code: str
    expected_response_rate: float
    attributed_gift_count: int
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    donor_id: str
    campaign_id: str
    total_amount_cents: int
    installment_count: int
    frequency: str
    schedule_basis: str
    status: str
    paid_cents: int
    balance_cents: int
    installments_due_count: int
    created_at: str
    updated_at: str
    version: int


class PledgeInstallment(TypedDict):
    id: str
    pledge_id: str
    sequence_no: int
    amount_cents: int
    due_on: str
    status: str
    paid_by_gift_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Gift(TypedDict):
    id: str
    donor_id: str
    campaign_id: str
    appeal_id: Optional[str]
    pledge_id: Optional[str]
    amount_cents: int
    payment_method: str
    status: str
    deductible_amount_cents: int
    benefit_value_cents: int
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchClaim(TypedDict):
    id: str
    gift_id: str
    employer_id: str
    requested_amount_cents: int
    matched_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlannedGift(TypedDict):
    id: str
    donor_id: str
    vehicle: str
    expected_amount_cents: int
    status: str
    realized_gift_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Acknowledgement(TypedDict):
    id: str
    gift_id: str
    donor_id: str
    template_code: str
    kind: str
    receipt_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Segment(TypedDict):
    id: str
    name: str
    min_lifetime_cents: int
    giving_status_in: List[str]
    lifecycle_status_in: List[str]
    member_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields:false — append-only, immutable; carries ONLY id + created_at
# (no updated_at, no version) plus its own fields.
class SoftCredit(TypedDict):
    id: str
    gift_id: str
    household_id: str
    beneficiary_donor_id: str
    soft_credit_cents: int
    reversed: bool
    created_at: str
