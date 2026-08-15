"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ENTRANT = "Entrant"
    JUDGE = "Judge"
    AUDITOR = "Auditor"
    FULFILLMENT_VENDOR = "FulfillmentVendor"
    ANONYMOUS = "Anonymous"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUBMISSION_CLOSED = "SUBMISSION_CLOSED"
    JUDGING = "JUDGING"
    FINALISTS_LOCKED = "FINALISTS_LOCKED"
    EMBARGOED = "EMBARGOED"
    CEREMONY_LIVE = "CEREMONY_LIVE"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class CategoryStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class EntrantStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    BARRED = "BARRED"


class EntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    IN_JUDGING = "IN_JUDGING"
    FINALIST = "FINALIST"
    NON_FINALIST = "NON_FINALIST"
    WINNER = "WINNER"
    NON_WINNER = "NON_WINNER"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    WAIVED = "WAIVED"


class MaterialType(str, Enum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    PDF = "PDF"
    IMAGE = "IMAGE"
    URL = "URL"


class MaterialStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class FeeTier(str, Enum):
    EARLY = "EARLY"
    STANDARD = "STANDARD"
    LATE = "LATE"


class JudgeStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ConflictType(str, Enum):
    FINANCIAL = "FINANCIAL"
    FAMILIAL = "FAMILIAL"
    PROFESSIONAL = "PROFESSIONAL"
    PERSONAL = "PERSONAL"
    OTHER = "OTHER"


class ConflictSeverity(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class ConflictStatus(str, Enum):
    DECLARED = "DECLARED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESCINDED = "RESCINDED"


class PanelRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    RECUSED = "RECUSED"
    REMOVED = "REMOVED"
    COMPLETED = "COMPLETED"


class RoundName(str, Enum):
    SCREENING = "SCREENING"
    SEMIFINAL = "SEMIFINAL"
    FINAL = "FINAL"


class RoundStatus(str, Enum):
    CONFIGURING = "CONFIGURING"
    PANEL_LOCKED = "PANEL_LOCKED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    NORMALIZED = "NORMALIZED"
    PUBLISHED = "PUBLISHED"
    VOIDED = "VOIDED"


class ScoringMode(str, Enum):
    RAW_RANK = "RAW_RANK"
    Z_SCORE = "Z_SCORE"


class ScoreStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class CeremonyStatus(str, Enum):
    PLANNING = "PLANNING"
    REHEARSAL = "REHEARSAL"
    LIVE = "LIVE"
    CONCLUDED = "CONCLUDED"
    ABORTED = "ABORTED"


class AnnouncementStatus(str, Enum):
    STAGED = "STAGED"
    ANNOUNCED = "ANNOUNCED"
    RETRACTED = "RETRACTED"
    RESTAGED = "RESTAGED"


class ItemType(str, Enum):
    TROPHY = "TROPHY"
    CERTIFICATE = "CERTIFICATE"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AppealGrounds(str, Enum):
    SCORING_ERROR = "SCORING_ERROR"
    CONFLICT_UNDECLARED = "CONFLICT_UNDECLARED"
    ELIGIBILITY_MISREAD = "ELIGIBILITY_MISREAD"
    PROCEDURAL_VIOLATION = "PROCEDURAL_VIOLATION"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class Remedy(str, Enum):
    RESCORE = "RESCORE"
    REINSTATE = "REINSTATE"
    NONE = "NONE"


class IntegrityFlag(str, Enum):
    CLEAN = "CLEAN"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPROMISED = "COMPROMISED"


class RefundPolicy(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    EARLY_BIRD_FREE = "EARLY_BIRD_FREE"


# --- Entity TypedDicts (PRD §2.4 common-field tracking) ---


class AwardSeason(TypedDict, total=False):
    id: str
    code: str
    title: str
    status: str
    submission_opens_at: str
    early_fee_ends_at: str
    submission_closes_at: str
    eligibility_window_start: str
    eligibility_window_end: str
    ceremony_scheduled_at: Optional[str]
    embargo_lifts_at: Optional[str]
    ack_window_hours: int
    go_live_lead_minutes: int
    max_appeals_per_entry: int
    refund_policy: str
    active_entries_count: int
    integrity_flag: str
    created_at: str
    updated_at: str
    version: int


class AwardCategory(TypedDict, total=False):
    id: str
    season_id: str
    code: str
    name: str
    description: Optional[str]
    eligibility_rules_text: Optional[str]
    min_materials: int
    max_entries_per_entrant: int
    early_fee_cents: int
    standard_fee_cents: int
    late_fee_cents: int
    panel_size: int
    finalist_slots: int
    scoring_rubric: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class Entrant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    country_code: str
    standing: str
    delinquent_since: Optional[str]
    lifetime_disqualifications: int
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict, total=False):
    id: str
    category_id: str
    entrant_id: str
    title: str
    work_completed_at: str
    status: str
    payment_status: str
    revision_count: int
    fee_tier_applied: Optional[str]
    fee_waived: bool
    final_composite_score: Optional[float]
    final_rank: Optional[int]
    disqualified_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# EntryMaterial is an evidence-style record: only id + created_at (PRD §2.4).
class EntryMaterial(TypedDict, total=False):
    id: str
    entry_id: str
    material_type: str
    uri: str
    file_size_bytes: int
    checksum_sha256: str
    status: str
    created_at: str


class FeeInvoice(TypedDict, total=False):
    id: str
    entry_id: str
    amount_cents: int
    tier: str
    status: str
    due_at: str
    paid_at: Optional[str]
    refund_cents: Optional[int]
    retained_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    expertise_tags: List[str]
    affiliated_entrant_ids: List[str]
    status: str
    reliability_score_bp: int
    created_at: str
    updated_at: str
    version: int


# ConflictDeclaration is an evidence-style record: only id + created_at (PRD §2.4).
class ConflictDeclaration(TypedDict, total=False):
    id: str
    judge_id: str
    season_id: str
    entrant_id: str
    category_id: Optional[str]
    conflict_type: str
    severity: str
    note: Optional[str]
    status: str
    created_at: str


class PanelAssignment(TypedDict, total=False):
    id: str
    judge_id: str
    category_id: str
    scoring_round_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoringRound(TypedDict, total=False):
    id: str
    category_id: str
    round_index: int
    name: str
    status: str
    advance_count: Optional[int]
    scoring_mode: str
    scheduled_window_start: str
    scheduled_window_end: str
    opened_at: Optional[str]
    closed_at: Optional[str]
    normalization_snapshot: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


# Score is an evidence-style record: only id + created_at (PRD §2.4).
class Score(TypedDict, total=False):
    id: str
    scoring_round_id: str
    entry_id: str
    judge_id: str
    criterion_scores: Dict[str, int]
    weighted_raw: Optional[float]
    z_intermediate: Optional[float]
    rank_among_judges_scores: Optional[float]
    normalized_score: Optional[float]
    status: str
    created_at: str


class FinalistRecord(TypedDict, total=False):
    id: str
    category_id: str
    entry_id: str
    announced_rank: int
    notification_status: str
    notified_at: Optional[str]
    embargo_visible: bool
    created_at: str
    updated_at: str
    version: int


class Ceremony(TypedDict, total=False):
    id: str
    season_id: str
    venue_name: str
    starts_at: str
    ends_at: str
    status: str
    rundown: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class WinnerAnnouncement(TypedDict, total=False):
    id: str
    category_id: str
    ceremony_id: str
    winner_entry_id: Optional[str]
    status: str
    announced_at: Optional[str]
    retraction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FulfillmentOrder(TypedDict, total=False):
    id: str
    season_id: str
    entry_id: str
    announcement_id: str
    item_type: str
    engraving_text: Optional[str]
    quantity: int
    status: str
    vendor_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    entry_id: str
    filed_by_entrant_id: str
    grounds: str
    narrative: str
    status: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    remedy: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditLog is an evidence-style record: only id + created_at (PRD §2.4).
class AuditLog(TypedDict, total=False):
    id: str
    season_id: str
    actor_role: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    detail: Dict[str, Any]
    hash_chain_prev: str
    hash_chain_self: str
    created_at: str
