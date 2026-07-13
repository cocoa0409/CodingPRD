"""Domain types: entity TypedDicts, status enums, and the role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CONTRIBUTOR = "Contributor"
    REVIEWER = "Reviewer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_ADMIN = "FinanceAdmin"


class OnboardingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TaxFormStatus(str, Enum):
    MISSING = "MISSING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Exclusivity(str, Enum):
    NON_EXCLUSIVE = "NON_EXCLUSIVE"
    EXCLUSIVE = "EXCLUSIVE"


class RoyaltyLevel(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class TaxFormRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ModelReleaseStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AssetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    TAKEN_DOWN = "TAKEN_DOWN"


class DownloadEarningStatus(str, Enum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    REVERSED = "REVERSED"


class PayoutStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"


class ExclusivityWindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class TakedownStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# --- Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version) ---

class Contributor(TypedDict):
    id: str
    display_name: str
    country_code: str
    onboarding_status: str
    tax_form_status: str
    exclusivity: str
    royalty_level: str
    lifetime_earnings_cents: int
    available_balance_cents: int
    accepted_asset_count: int
    strike_count: int
    created_at: str
    updated_at: str
    version: int


class TaxForm(TypedDict):
    id: str
    contributor_id: str
    form_type: str
    tax_id: str
    treaty_rate_pct: Optional[float]
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModelRelease(TypedDict):
    id: str
    contributor_id: str
    release_type: str
    releaser_name: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    contributor_id: str
    model_release_id: Optional[str]
    title: str
    media_type: str
    content_category: str
    keywords: List[str]
    perceptual_hash: str
    requires_release: bool
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — AssetReview is an immutable audit record (id + created_at only).
class AssetReview(TypedDict):
    id: str
    asset_id: str
    decision: str
    reject_reason: Optional[str]
    similar_to_asset_id: Optional[str]
    reviewer_id: str
    created_at: str


class LicenseTier(TypedDict):
    id: str
    code: str
    base_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Download(TypedDict):
    id: str
    asset_id: str
    license_tier_code: str
    buyer_reference: str
    sale_price_cents: int
    royalty_rate_snapshot_pct: float
    royalty_amount_cents: int
    earning_status: str
    available_at: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    contributor_id: str
    gross_amount_cents: int
    withholding_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusivityWindow(TypedDict):
    id: str
    contributor_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EarningAdjustment(TypedDict):
    id: str
    contributor_id: str
    amount_cents: int
    reason: str
    created_at: str
    updated_at: str
    version: int


class TakedownRequest(TypedDict):
    id: str
    asset_id: str
    claim_type: str
    claimant_name: str
    hold_start: str
    hold_end: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
