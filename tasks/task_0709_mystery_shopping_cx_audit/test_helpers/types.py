"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes defined in the PRD. Entities that carry the standard
system-managed fields (id, created_at, updated_at, version) are modeled with all
four; CertificationAttempt is the lone immutable record carrying only id and
created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    CLIENT_MANAGER = "ClientManager"
    SHOPPER = "Shopper"
    QA_VALIDATOR = "QaValidator"
    FINANCE_OFFICER = "FinanceOfficer"


# --- Shared enums ----------------------------------------------------------
class ScenarioFamily(str, Enum):
    RETAIL = "RETAIL"
    DINING = "DINING"
    BANKING = "BANKING"


# --- Status enums ----------------------------------------------------------
class ClientAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShopperStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class CertificationOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class LocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScenarioScriptStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ShopWaveStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_FIELD = "IN_FIELD"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EvidenceKind(str, Enum):
    PHOTO = "PHOTO"
    RECEIPT = "RECEIPT"


class EvidenceReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"


class ScoreCardAuditStatus(str, Enum):
    DRAFT = "DRAFT"
    AUDITED = "AUDITED"


class ScoreCardFraudStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    CLEARED = "CLEARED"
    FRAUD_HOLD = "FRAUD_HOLD"


class ReimbursementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    BATCHED = "BATCHED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class DisputeReason(str, Enum):
    REJECTION_APPEAL = "REJECTION_APPEAL"
    SCORE_CHALLENGE = "SCORE_CHALLENGE"
    REIMBURSE_SHORTFALL = "REIMBURSE_SHORTFALL"


class DisputeOpenedByRole(str, Enum):
    SHOPPER = "SHOPPER"
    CLIENT = "CLIENT"


class DisputeStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    COUNTERED = "COUNTERED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class PayoutBatchStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity TypedDicts -----------------------------------------------------
# Entities carrying the standard system-managed fields.
class ClientAccount(TypedDict):
    id: str
    company_name: str
    billing_email: str
    fee_per_completed_shop_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shopper(TypedDict):
    id: str
    full_name: str
    email: str
    home_lat: float
    home_lng: float
    tax_id_on_file: bool
    status: str
    certification_score: int
    reliability_score: float
    ytd_paid_cents: int
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


# Immutable append-only record: id + created_at only, no updated_at / version.
class CertificationAttempt(TypedDict):
    id: str
    shopper_id: str
    raw_score: int
    scenario_family: str
    outcome: str
    attempt_index: int
    created_at: str


class Location(TypedDict):
    id: str
    client_id: str
    label: str
    lat: float
    lng: float
    scenario_family: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScenarioScript(TypedDict):
    id: str
    client_id: str
    title: str
    scenario_family: str
    required_photo_count: int
    receipt_required: bool
    reimburse_cap_cents: int
    base_fee_cents: int
    weights_json: dict
    passing_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopWave(TypedDict):
    id: str
    client_id: str
    name: str
    field_window_start: str
    field_window_end: str
    rotation_cooldown_days: int
    status: str
    validated_shop_count: int
    client_billable_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    wave_id: str
    shopper_id: str
    location_id: str
    script_id: str
    due_at: str
    travel_distance_km: float
    claimed_out_of_pocket_cents: int
    reimbursable_cents: int
    shopper_fee_cents: int
    status: str
    submission_count: int
    validated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    id: str
    assignment_id: str
    kind: str
    object_uri: str
    section_key: Optional[str]
    receipt_amount_cents: int
    review_status: str
    created_at: str
    updated_at: str
    version: int


class ScoreCard(TypedDict):
    id: str
    assignment_id: str
    section_scores_json: dict
    estimated_score: int
    audited_score: Optional[int]
    audit_status: str
    fraud_status: str
    created_at: str
    updated_at: str
    version: int


class Reimbursement(TypedDict):
    id: str
    assignment_id: str
    shopper_id: str
    amount_cents: int
    status: str
    payout_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    assignment_id: str
    opened_by_role: str
    reason: str
    round_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict):
    id: str
    shopper_id: str
    tax_year: int
    gross_amount_cents: int
    requires_1099: bool
    status: str
    created_at: str
    updated_at: str
    version: int
