"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes defined in the Translation & Localization Services PRD.
Full-lifecycle resources carry id + created_at + updated_at + version; the two leaner
resources (RateCard, PayoutLedgerEntry) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    PROJECT_MANAGER = "ProjectManager"
    ACCOUNTS_RECEIVABLE = "AccountsReceivable"
    CLIENT = "Client"
    TRANSLATOR = "Translator"
    REVIEWER = "Reviewer"


# ─── Status enums ─────────────────────────────────────
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LinguistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class ProjectJobStatus(str, Enum):
    PENDING = "PENDING"
    TRANSLATING = "TRANSLATING"
    IN_QA = "IN_QA"
    REVISION = "REVISION"
    QA_PASSED = "QA_PASSED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AssignmentRole(str, Enum):
    TRANSLATOR = "TRANSLATOR"
    REVIEWER = "REVIEWER"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    DELIVERED = "DELIVERED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class QAOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RushTier(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    SAME_DAY = "SAME_DAY"


class CertificationMode(str, Enum):
    NONE = "NONE"
    CERTIFIED = "CERTIFIED"
    NOTARIZED = "NOTARIZED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PayoutEntryType(str, Enum):
    COMMIT = "COMMIT"
    REVERSAL = "REVERSAL"
    FINAL_ADJUST = "FINAL_ADJUST"


# ─── Entity TypedDicts ────────────────────────────────
# Full-lifecycle resources: id + created_at + updated_at + version

class Client(TypedDict):
    id: str
    name: str
    billing_email: str
    ar_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Linguist(TypedDict):
    id: str
    full_name: str
    native_locale: str
    qualified_pairs: List[dict]
    can_review: bool
    daily_throughput_words: int
    committed_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    rate_card_id: str
    name: str
    rush_tier: str
    certification_mode: str
    pinned_base_rate_cents_per_word: int
    pinned_linguist_rate_cents_per_word: int
    quoted_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectJob(TypedDict):
    id: str
    project_id: str
    filename: str
    quoted_no_match_words: int
    quoted_fuzzy_words: int
    quoted_reps_words: int
    quoted_context_words: int
    actual_no_match_words: Optional[int]
    actual_fuzzy_words: Optional[int]
    actual_reps_words: Optional[int]
    actual_context_words: Optional[int]
    weighted_source_words: float
    revision_rounds: int
    latest_qa_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    job_id: str
    linguist_id: str
    role: str
    window_start: str
    window_end: str
    payout_cents: int
    payout_finalized: bool
    expected_job_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QAReport(TypedDict):
    id: str
    job_id: str
    reviewer_assignment_id: str
    critical_count: int
    major_count: int
    minor_count: int
    scored_word_count: int
    score: float
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    project_id: str
    client_id: str
    translation_subtotal_cents: int
    volume_discount_cents: int
    rush_surcharge_cents: int
    revision_surcharge_cents: int
    certification_cents: int
    total_cents: int
    expected_project_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryCertificate(TypedDict):
    id: str
    job_id: str
    certification_mode: str
    page_count: int
    certificate_number: int
    created_at: str
    updated_at: str
    version: int


# Lean resources: id + created_at only (no updated_at, no version)

class RateCard(TypedDict):
    id: str
    source_locale: str
    target_locale: str
    base_rate_cents_per_word: int
    linguist_rate_cents_per_word: int
    active: bool
    created_at: str


class PayoutLedgerEntry(TypedDict):
    id: str
    linguist_id: str
    assignment_id: str
    entry_type: str
    amount_cents: int
    reason: str
    created_at: str
