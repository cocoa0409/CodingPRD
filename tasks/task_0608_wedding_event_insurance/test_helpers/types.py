"""Domain types: entity TypedDicts, status enums, role enum.

All names track the Wedding & Event Insurance PRD terminology.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    UNDERWRITING_AGENT = "UnderwritingAgent"
    POLICYHOLDER = "Policyholder"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CoverageProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VendorStatus(str, Enum):
    SOLVENT = "SOLVENT"
    FLAGGED = "FLAGGED"
    DEFAULTED = "DEFAULTED"


class PerilStatus(str, Enum):
    WATCH = "WATCH"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PolicyLifecycleStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    IN_FORCE = "IN_FORCE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    CLAIMED_OUT = "CLAIMED_OUT"


class PolicyBillingStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    EARNED = "EARNED"


class CoverageStatus(str, Enum):
    SELECTED = "SELECTED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    VOIDED = "VOIDED"


class RiderStatus(str, Enum):
    SELECTED = "SELECTED"
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class CertificateStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class EndorsementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Entities carrying the full common-field set (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class CoverageProduct(TypedDict):
    id: str
    coverage_type: str
    tier: str
    base_premium_cents: int
    per_guest_premium_cents: int
    coverage_limit_cents: int
    deposit_sublimit_pct: float
    liquor_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    category: str
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForceMajeureEvent(TypedDict):
    id: str
    peril_name: str
    peril_type: str
    cutoff_at: str
    landfall_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    policyholder_id: str
    policy_form: str
    serves_alcohol: bool
    free_look_days: int
    bind_at: Optional[str]
    base_premium_cents: int
    rider_premium_cents: int
    total_premium_cents: int
    premium_earned_cents: int
    refund_due_cents: int
    lifecycle_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class EventProfile(TypedDict):
    id: str
    policy_id: str
    event_name: str
    venue_vendor_id: str
    expected_attendance: int
    event_start_at: str
    event_end_at: str
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    policy_id: str
    coverage_product_id: str
    protected_vendor_id: Optional[str]
    rated_premium_cents: int
    consumed_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    policy_id: str
    rider_type: str
    scheduled_value_cents: int
    rider_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    policy_id: str
    vendor_id: str
    additional_insured_name: str
    certificate_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    policy_id: str
    endorsement_type: str
    premium_delta_cents: int
    payload_json: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    coverage_id: str
    claim_type: str
    vendor_id: Optional[str]
    force_majeure_event_id: Optional[str]
    claimed_amount_cents: int
    approved_amount_cents: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — carry ONLY id + created_at (no updated_at, no version)
# ---------------------------------------------------------------------------
class ClaimDocument(TypedDict):
    id: str
    claim_id: str
    doc_type: str
    subject_kind: Optional[str]
    subject_ref: Optional[str]
    file_uri: str
    created_at: str


class PremiumLedgerEntry(TypedDict):
    id: str
    policy_id: str
    entry_kind: str
    amount_cents: int
    memo: Optional[str]
    created_at: str
