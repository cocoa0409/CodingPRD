"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries
id + created_at + updated_at + version, with one exception: the
ItemResponse record is an immutable measurement that carries only
id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class Subject(str, Enum):
    MATH = "MATH"
    ELA = "ELA"
    SCIENCE = "SCIENCE"
    SOCIAL_STUDIES = "SOCIAL_STUDIES"


class StandardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class ItemStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONTENT_REVIEW = "CONTENT_REVIEW"
    BIAS_REVIEW = "BIAS_REVIEW"
    FIELD_TEST_ELIGIBLE = "FIELD_TEST_ELIGIBLE"
    FIELD_TESTING = "FIELD_TESTING"
    STATS_REVIEW = "STATS_REVIEW"
    OPERATIONAL = "OPERATIONAL"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class SecurityPosture(str, Enum):
    UNSECURED = "UNSECURED"
    SECURED = "SECURED"
    EXPOSED = "EXPOSED"
    COMPROMISED = "COMPROMISED"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    REVISE = "REVISE"


class RetirementReason(str, Enum):
    STATISTICAL_FAIL = "STATISTICAL_FAIL"
    BIAS_CONFIRMED = "BIAS_CONFIRMED"
    OVER_EXPOSED = "OVER_EXPOSED"
    CONTENT_DEPRECATED = "CONTENT_DEPRECATED"
    MANUAL = "MANUAL"


class ItemType(str, Enum):
    MC = "MC"
    MS = "MS"
    EBSR = "EBSR"
    TE = "TE"
    CR = "CR"


class CommitteeKind(str, Enum):
    CONTENT = "CONTENT"
    BIAS_SENSITIVITY = "BIAS_SENSITIVITY"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    REVISE = "REVISE"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StatsKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PassFlag(str, Enum):
    PASS = "PASS"
    FAIL_BORDERLINE = "FAIL_BORDERLINE"
    FAIL_SEVERE = "FAIL_SEVERE"


class BlueprintStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class FormStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    ASSEMBLED = "ASSEMBLED"
    EQUATED = "EQUATED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class VariantKind(str, Enum):
    TRANSLATION = "TRANSLATION"
    ACCOMMODATION = "ACCOMMODATION"


class VariantStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GrantScope(str, Enum):
    ITEM_READ = "ITEM_READ"
    ITEM_WRITE = "ITEM_WRITE"
    STATS_READ = "STATS_READ"
    FORM_ASSEMBLE = "FORM_ASSEMBLE"
    GRANT_ADMIN = "GRANT_ADMIN"


class DossierKind(str, Enum):
    TECHNICAL_MANUAL = "TECHNICAL_MANUAL"
    VALIDITY_EVIDENCE = "VALIDITY_EVIDENCE"
    RELIABILITY_REPORT = "RELIABILITY_REPORT"


class DossierStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    ITEM_WRITER = "ItemWriter"
    CONTENT_REVIEWER = "ContentReviewer"
    BIAS_SENSITIVITY_REVIEWER = "BiasSensitivityReviewer"
    PSYCHOMETRICIAN = "Psychometrician"
    TEST_ASSEMBLER = "TestAssembler"
    SECURITY_OFFICER = "SecurityOfficer"
    TRANSLATION_SPECIALIST = "TranslationSpecialist"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class AssessmentProgram(TypedDict, total=False):
    id: str
    program_code: str
    subject: str
    grade_level: int
    admin_year: int
    current_period_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContentStandard(TypedDict, total=False):
    id: str
    program_id: str
    standard_code: str
    strand: str
    description: str
    depth_of_knowledge: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    program_id: str
    item_code: str
    primary_standard_id: str
    secondary_standard_ids: List[str]
    item_type: str
    stimulus_html: str
    options_json: dict
    max_score_points: int
    author_user_id: str
    status: str
    security_posture: str
    content_review_outcome: str
    bias_review_outcome: str
    revision_cycle_count: int
    field_test_attempt_count: int
    operational_exposure_count: int
    exposure_cap: int
    retired_at: Optional[str]
    retirement_reason: Optional[str]
    p_value_provisional: Optional[float]
    p_value_final: Optional[float]
    point_biserial_provisional: Optional[float]
    point_biserial_final: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ReviewCommittee(TypedDict, total=False):
    id: str
    program_id: str
    committee_kind: str
    name: str
    quorum_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewSession(TypedDict, total=False):
    id: str
    committee_id: str
    program_id: str
    scheduled_at: str
    started_at: Optional[str]
    closed_at: Optional[str]
    status: str
    agenda_item_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class ReviewVerdict(TypedDict, total=False):
    id: str
    session_id: str
    item_id: str
    reviewer_user_id: str
    verdict: str
    rationale: Optional[str]
    submitted_at: str
    soft_deleted: bool
    created_at: str
    updated_at: str
    version: int


class FieldTestWindow(TypedDict, total=False):
    id: str
    program_id: str
    window_label: str
    start_utc: str
    end_utc: str
    target_sample_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only measurement record: id + created_at only (no updated_at/version).
class ItemResponse(TypedDict, total=False):
    id: str
    created_at: str
    window_id: str
    item_id: str
    student_anon_id: str
    response_timestamp: str
    attempt_duration_seconds: int
    raw_score: int
    excluded: bool


class ItemStatistic(TypedDict, total=False):
    id: str
    item_id: str
    window_id: str
    n_responses: int
    p_value: float
    point_biserial: float
    stats_kind: str
    finalized_at: Optional[str]
    pass_flag: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestBlueprint(TypedDict, total=False):
    id: str
    program_id: str
    blueprint_code: str
    sections: List[dict]
    total_items_required: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestForm(TypedDict, total=False):
    id: str
    blueprint_id: str
    program_id: str
    form_code: str
    intended_admin_date: str
    status: str
    assembled_at: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormItemSlot(TypedDict, total=False):
    id: str
    form_id: str
    item_id: str
    section_index: int
    position_in_section: int
    is_anchor: bool
    points_possible: int
    created_at: str
    updated_at: str
    version: int


class EquatingLink(TypedDict, total=False):
    id: str
    program_id: str
    source_form_id: str
    target_form_id: str
    anchor_item_ids: List[str]
    scaling_slope: float
    scaling_intercept: float
    equated_at: str
    created_at: str
    updated_at: str
    version: int


class ItemVariant(TypedDict, total=False):
    id: str
    item_id: str
    variant_kind: str
    language_code: Optional[str]
    accommodation_code: Optional[str]
    stimulus_html: str
    options_json: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    program_id: str
    grantee_user_id: str
    grant_scope: str
    valid_from: str
    valid_until: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValidityDossier(TypedDict, total=False):
    id: str
    program_id: str
    form_id: str
    dossier_kind: str
    content_md: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
