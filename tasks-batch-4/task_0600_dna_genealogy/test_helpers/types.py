"""Domain types for the Consumer DNA Genealogy API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import TypedDict, List, Optional


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    LAB_TECHNICIAN = "LabTechnician"
    PRIVACY_OFFICER = "PrivacyOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ────────────────────────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGED = "PURGED"


class DnaStatus(str, Enum):
    NO_SAMPLE = "NO_SAMPLE"
    PROCESSING = "PROCESSING"
    DNA_READY = "DNA_READY"
    PURGED = "PURGED"


class SubscriptionTier(str, Enum):
    FREE = "FREE"
    PLUS = "PLUS"
    PRO = "PRO"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    CLOSED = "CLOSED"


class AccessStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class BillingEventType(str, Enum):
    PAYMENT_FAILED = "PAYMENT_FAILED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    CANCEL = "CANCEL"


class ChipVersion(str, Enum):
    V4 = "V4"
    V5 = "V5"


class KitStatus(str, Enum):
    ORDERED = "ORDERED"
    ACTIVATED = "ACTIVATED"
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    VOID = "VOID"


class SampleStatus(str, Enum):
    RECEIVED = "RECEIVED"
    EXTRACTED = "EXTRACTED"
    QC_FAILED = "QC_FAILED"
    QUEUED = "QUEUED"
    GENOTYPING = "GENOTYPING"
    GENOTYPED = "GENOTYPED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class InstrumentStatus(str, Enum):
    ONLINE = "ONLINE"
    MAINTENANCE = "MAINTENANCE"


class LabBatchStatus(str, Enum):
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    FINALIZED = "FINALIZED"
    ABORTED = "ABORTED"


class ConsentScope(str, Enum):
    HEALTH_TRAITS = "HEALTH_TRAITS"
    RELATIVE_MATCHING = "RELATIVE_MATCHING"
    RESEARCH = "RESEARCH"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ReportType(str, Enum):
    ETHNICITY = "ETHNICITY"
    HEALTH_TRAIT = "HEALTH_TRAIT"


class ReportVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class MatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPPRESSED = "SUPPRESSED"
    PURGED = "PURGED"


class PredictedRelationship(str, Enum):
    PARENT_CHILD = "PARENT_CHILD"
    SIBLING = "SIBLING"
    CLOSE_COUSIN = "CLOSE_COUSIN"
    DISTANT_COUSIN = "DISTANT_COUSIN"


class FamilyTreeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TreePersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class HintType(str, Enum):
    DNA_TREE = "DNA_TREE"
    CENSUS = "CENSUS"


class HintStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"


class RequestType(str, Enum):
    EXPORT = "EXPORT"
    DELETE = "DELETE"


class DataRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# ─── Entity shapes (PRD §2.4: every resource carries id/created_at/updated_at/version) ───

class Customer(TypedDict):
    id: str
    email: str
    display_name: str
    account_status: str
    dna_status: str
    wallet_credit_cents: int
    matching_opt_in: bool
    research_opt_in: bool
    health_opt_in: bool
    visible_match_count: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    tier: str
    pending_tier: Optional[str]
    billing_status: str
    access_status: str
    current_period_start: str
    current_period_end: str
    grace_until: Optional[str]
    lifetime_charged_cents: int
    last_change_charge_cents: Optional[int]
    last_change_from_tier: Optional[str]
    published_report_count: int
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict):
    id: str
    customer_id: str
    barcode: str
    chip_version: str
    price_cents: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    kit_id: str
    batch_id: Optional[str]
    status: str
    extraction_attempts: int
    dna_yield_ng: Optional[float]
    call_rate: Optional[float]
    population_scores: List[dict]
    genotype_markers: List[int]
    created_at: str
    updated_at: str
    version: int


class LabInstrument(TypedDict):
    id: str
    name: str
    chip_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LabBatch(TypedDict):
    id: str
    instrument_id: str
    run_start_at: str
    run_end_at: str
    status: str
    member_count: int
    pass_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ConsentGrant(TypedDict):
    id: str
    customer_id: str
    scope: str
    effective_from: str
    effective_until: str
    status: str
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    customer_id: str
    sample_id: str
    report_type: str
    variant: str
    status: str
    composition: List[dict]
    residual_population: Optional[str]
    trait_count: int
    generated_at: str
    created_at: str
    updated_at: str
    version: int


class RelativeMatch(TypedDict):
    id: str
    customer_a_id: str
    customer_b_id: str
    shared_cm: float
    segment_count: int
    predicted_relationship: str
    confidence_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FamilyTree(TypedDict):
    id: str
    customer_id: str
    name: str
    status: str
    person_count: int
    created_at: str
    updated_at: str
    version: int


class TreePerson(TypedDict):
    id: str
    tree_id: str
    father_id: Optional[str]
    mother_id: Optional[str]
    linked_customer_id: Optional[str]
    given_name: str
    surname: str
    birth_year: Optional[int]
    status: str
    hint_count: int
    created_at: str
    updated_at: str
    version: int


class RecordHint(TypedDict):
    id: str
    person_id: str
    source_match_id: Optional[str]
    hint_type: str
    status: str
    confidence: float
    created_at: str
    updated_at: str
    version: int


class DataRequest(TypedDict):
    id: str
    customer_id: str
    request_type: str
    status: str
    reviewed_by: Optional[str]
    scheduled_purge_at: Optional[str]
    export_url: Optional[str]
    created_at: str
    updated_at: str
    version: int
