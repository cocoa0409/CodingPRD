"""Domain types for the Juried Exhibition Administration API.

Status enums, role enum and entity TypedDicts. Field names are exactly the
names the PRD uses in its resource descriptions.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    CALL_MANAGER = "CallManager"
    JURY_CHAIR = "JuryChair"
    JUROR = "Juror"
    ARTIST = "Artist"
    REGISTRAR = "Registrar"
    FINANCE_OFFICER = "FinanceOfficer"


# ─── Status enums ─────────────────────────────────────

class ExhibitionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_ENTRIES = "OPEN_FOR_ENTRIES"
    JURYING = "JURYING"
    RESULTS_PUBLISHED = "RESULTS_PUBLISHED"
    INSTALLATION = "INSTALLATION"
    ON_VIEW = "ON_VIEW"
    CLOSED = "CLOSED"


class SettlementStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECONCILING = "RECONCILING"
    PAYOUTS_RELEASED = "PAYOUTS_RELEASED"
    BOOKS_CLOSED = "BOOKS_CLOSED"


class EntryStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FEE = "PENDING_FEE"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"


class ArtworkStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    DELIVERED = "DELIVERED"
    ON_VIEW = "ON_VIEW"
    SOLD = "SOLD"
    RETURN_PENDING = "RETURN_PENDING"
    RETURN_SCHEDULED = "RETURN_SCHEDULED"
    RETURNED = "RETURNED"
    UNCLAIMED_FORFEIT = "UNCLAIMED_FORFEIT"
    WITHDRAWN = "WITHDRAWN"


class PlacementStatus(str, Enum):
    UNPLACED = "UNPLACED"
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    DEINSTALLED = "DEINSTALLED"


class JurorStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    RESIGNED = "RESIGNED"


class JuryRoundStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    SCORING_COMPLETE = "SCORING_COMPLETE"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AwardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RESCINDED = "RESCINDED"


class SaleStatus(str, Enum):
    RECORDED = "RECORDED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    PAYOUT_RELEASED = "PAYOUT_RELEASED"
    VOIDED = "VOIDED"


# ─── Value enums ──────────────────────────────────────

class MediumCategory(str, Enum):
    PAINTING = "PAINTING"
    SCULPTURE = "SCULPTURE"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    PRINTMAKING = "PRINTMAKING"
    TEXTILE = "TEXTILE"
    NEW_MEDIA = "NEW_MEDIA"


class MemberStatus(str, Enum):
    MEMBER = "MEMBER"
    NON_MEMBER = "NON_MEMBER"


class PayoutMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"


class ImageRole(str, Enum):
    PRIMARY = "PRIMARY"
    DETAIL = "DETAIL"


class ImageFormat(str, Enum):
    JPEG = "JPEG"
    PNG = "PNG"
    TIFF = "TIFF"


class ColorProfile(str, Enum):
    SRGB = "SRGB"
    ADOBE_RGB = "ADOBE_RGB"
    CMYK = "CMYK"


class RelationType(str, Enum):
    FAMILY = "FAMILY"
    TEACHER_STUDENT = "TEACHER_STUDENT"
    SAME_GALLERY = "SAME_GALLERY"
    COLLABORATOR = "COLLABORATOR"
    FINANCIAL_INTEREST = "FINANCIAL_INTEREST"


class RoundType(str, Enum):
    BLIND_SCORING = "BLIND_SCORING"
    DELIBERATION = "DELIBERATION"


class LightingClass(str, Enum):
    STANDARD = "STANDARD"
    MUSEUM = "MUSEUM"


class ConditionStage(str, Enum):
    INTAKE = "INTAKE"
    DEINSTALL = "DEINSTALL"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    DAMAGED = "DAMAGED"


class AwardCategory(str, Enum):
    BEST_IN_SHOW = "BEST_IN_SHOW"
    JURORS_CHOICE = "JURORS_CHOICE"
    MEDIUM_MERIT = "MEDIUM_MERIT"
    PURCHASE_AWARD = "PURCHASE_AWARD"


class SaleType(str, Enum):
    GALLERY_SALE = "GALLERY_SALE"
    PURCHASE_AWARD = "PURCHASE_AWARD"


class ReturnMethod(str, Enum):
    ARTIST_PICKUP = "ARTIST_PICKUP"
    COURIER = "COURIER"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PRESENTING = "PRESENTING"


# ─── Versioned resources (id + created_at + updated_at + version) ───

class Exhibition(TypedDict):
    id: str
    title: str
    season_year: int
    status: str
    settlement_status: str
    call_opens_at: str
    call_closes_at: str
    notification_at: str
    delivery_window_start_at: str
    delivery_window_end_at: str
    opening_at: str
    closing_at: str
    claim_deadline_days: int
    entry_fee_base_cents: int
    works_included_in_base: int
    entry_fee_additional_cents: int
    member_discount_pct: float
    max_works_per_entry: int
    max_entries_per_artist: int
    max_dimension_cm: float
    max_weight_kg: float
    per_work_insurance_cap_cents: int
    allowed_media_categories: List[str]
    eligible_state_codes: List[str]
    acceptance_capacity: int
    waitlist_capacity: int
    jury_quorum: int
    advance_score_threshold: float
    score_weight_technique: float
    score_weight_originality: float
    score_weight_relevance: float
    commission_pct: float
    sales_tax_pct: float
    award_budget_cents: int
    shortlisted_count: int
    accepted_count: int
    waitlisted_count: int
    insured_value_total_cents: int
    insurance_premium_cents: int
    award_committed_cents: int
    jury_cost_committed_cents: int
    sales_gross_cents: int
    commission_total_cents: int
    sales_tax_total_cents: int
    artist_payable_total_cents: int
    payouts_released_cents: int
    council_retention_cents: int
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    legal_name: str
    email: str
    residency_state_code: str
    member_status: str
    tax_form_on_file: bool
    payout_method: str
    payout_hold: bool
    unclaimed_forfeit_count: int
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict):
    id: str
    exhibition_id: str
    artist_id: str
    status: str
    works_count: int
    entry_fee_cents: Optional[int]
    fee_paid_cents: int
    fee_waived: bool
    submitted_at: Optional[str]
    shortlisted_count: int
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    entry_id: Optional[str]
    wall_segment_id: Optional[str]
    title: str
    medium_category: str
    width_cm: float
    height_cm: float
    depth_cm: float
    weight_kg: float
    year_created: int
    declared_value_cents: int
    for_sale: bool
    list_price_cents: Optional[int]
    status: str
    placement_status: str
    span_start_cm: Optional[float]
    span_end_cm: Optional[float]
    longest_edge_cm: float
    blind_label: str
    primary_image_count: int
    provisional_mean_score: Optional[float]
    certified_mean_score: Optional[float]
    valid_score_count: int
    intake_condition_grade: Optional[str]
    claim_deadline_at: Optional[str]
    return_method: Optional[str]
    return_carrier: Optional[str]
    return_tracking_number: Optional[str]
    storage_fee_cents: int
    sold_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Juror(TypedDict):
    id: str
    display_name: str
    email: str
    expertise_categories: List[str]
    honorarium_cents: int
    status: str
    honorarium_committed_cents: int
    honorarium_paid_cents: int
    conflict_count: int
    assignment_count: int
    created_at: str
    updated_at: str
    version: int


class JuryRound(TypedDict):
    id: str
    exhibition_id: str
    round_number: int
    round_type: str
    opens_at: str
    closes_at: str
    quorum_required: int
    status: str
    reopen_count: int
    scored_artwork_count: int
    quorum_shortfall_count: int
    created_at: str
    updated_at: str
    version: int


class JurorAssignment(TypedDict):
    id: str
    juror_id: str
    jury_round_id: str
    session_start_at: str
    session_end_at: str
    status: str
    session_minutes: int
    honorarium_share_cents: int
    scores_submitted_count: int
    created_at: str
    updated_at: str
    version: int


class WallSegment(TypedDict):
    id: str
    exhibition_id: str
    label: str
    length_cm: float
    max_weight_kg: float
    lighting_class: str
    occupied_cm: float
    available_cm: float
    loaded_weight_kg: float
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    exhibition_id: str
    name: str
    contribution_cents: int
    purchase_award_budget_cents: int
    recognition_tier: str
    purchase_award_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    exhibition_id: str
    artwork_id: str
    sponsor_id: Optional[str]
    category: str
    prize_cents: int
    status: str
    proposed_by_user_id: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    artwork_id: str
    source_award_id: Optional[str]
    sale_type: str
    buyer_name: str
    buyer_region_code: str
    tax_exempt: bool
    sale_price_cents: int
    taxable_base_cents: int
    sales_tax_cents: int
    commission_cents: int
    artist_payable_cents: int
    buyer_total_cents: int
    status: str
    recorded_by_user_id: str
    payout_released_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only evidence records (id + created_at only) ───
# The PRD states these four carry only id and created_at; updated_at and
# version are absent from the resource entirely.

class ArtworkImage(TypedDict):
    id: str
    artwork_id: str
    role: str
    format: str
    pixel_long_edge: int
    pixel_short_edge: int
    file_bytes: int
    color_profile: str
    capture_date: str
    credit_line: str
    checksum_sha256: str
    standard_ok: bool
    created_at: str


class ConflictDeclaration(TypedDict):
    id: str
    juror_id: str
    artist_id: str
    relation_type: str
    voided_score_count: int
    created_at: str


class Score(TypedDict):
    id: str
    jury_round_id: str
    artwork_id: str
    juror_id: str
    technique: int
    originality: int
    relevance: int
    expertise_match: bool
    composite_score: float
    voided_by_conflict: bool
    submitted_at: str
    created_at: str


class ConditionReport(TypedDict):
    id: str
    artwork_id: str
    stage: str
    condition_grade: str
    photo_count: int
    damage_notes: Optional[str]
    reported_by_user_id: str
    created_at: str
