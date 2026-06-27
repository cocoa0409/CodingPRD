"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Yearbook Production PRD. All entities in this domain are mutable
resources and carry the four common fields id, created_at, updated_at, version
(PRD §2.4: "every resource exposes all four of id, created_at, updated_at, and version").
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────────

class YearbookProductionPhase(str, Enum):
    LADDER_BUILD = "LADDER_BUILD"
    CONTENT = "CONTENT"
    PROOFING = "PROOFING"
    PLANT = "PLANT"
    PRINTING = "PRINTING"
    DELIVERED = "DELIVERED"


class LadderPageStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class SubmissionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class StaffAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class AdContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    PLACED = "PLACED"
    VOIDED = "VOIDED"


class ProofStatus(str, Enum):
    OPEN = "OPEN"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PLANT_SUBMITTED = "PLANT_SUBMITTED"
    PLANT_APPROVED = "PLANT_APPROVED"


class PreSaleOrderStatus(str, Enum):
    PLACED = "PLACED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PreSalePriceTier(str, Enum):
    EARLY = "EARLY"
    STANDARD = "STANDARD"


class PrintRunStatus(str, Enum):
    COMMITTED = "COMMITTED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class DistributionRecordStatus(str, Enum):
    HANDED_OUT = "HANDED_OUT"


class Section(str, Enum):
    STUDENT_LIFE = "STUDENT_LIFE"
    ACADEMICS = "ACADEMICS"
    SPORTS = "SPORTS"
    CLUBS = "CLUBS"
    ADS = "ADS"
    SIGNATURE = "SIGNATURE"


class AdSize(str, Enum):
    FULL = "FULL"
    HALF = "HALF"
    QUARTER = "QUARTER"


class StaffRoleTitle(str, Enum):
    EDITOR = "EDITOR"
    PHOTOGRAPHER = "PHOTOGRAPHER"
    SECTION_LEAD = "SECTION_LEAD"
    SIGNATURE_COORDINATOR = "SIGNATURE_COORDINATOR"


class SubmissionKind(str, Enum):
    PHOTO = "PHOTO"
    QUOTE = "QUOTE"


class UserRole(str, Enum):
    ADVISER = "Adviser"
    STAFF = "Staff"
    CONTRIBUTOR = "Contributor"
    SALESREP = "SalesRep"


# ─── Entity TypedDicts (all carry common fields) ──────────────────────────────

class Yearbook(TypedDict):
    id: str
    school_name: str
    academic_year: str
    target_page_count: int
    unit_cost_cents: int
    presale_open_iso: str
    presale_close_iso: str
    production_phase: str
    ladder_filled_count: int
    ladder_complete: bool
    ad_revenue_cents: int
    presale_revenue_cents: int
    production_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class LadderPage(TypedDict):
    id: str
    yearbook_id: str
    page_number: int
    section: str
    template_code: str
    spread_span: int
    assigned_staff_id: Optional[str]
    required_submission_count: int
    approved_submission_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    ladder_page_id: str
    kind: str
    contributor_id: str
    asset_ref: str
    review_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    yearbook_id: str
    staff_user_id: str
    role_title: str
    deadline_iso: str
    assigned_page_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdContract(TypedDict):
    id: str
    yearbook_id: str
    ladder_page_id: str
    sponsor_name: str
    size: str
    list_price_cents: int
    discount_pct: float
    net_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict):
    id: str
    yearbook_id: str
    round_number: int
    reviewer_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreSaleOrder(TypedDict):
    id: str
    yearbook_id: str
    buyer_name: str
    quantity: int
    personalize: bool
    stamp_name: str
    ordered_at_iso: str
    price_tier: str
    total_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintRun(TypedDict):
    id: str
    yearbook_id: str
    quantity: int
    delivery_address: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict):
    id: str
    yearbook_id: str
    presale_order_id: str
    recipient_name: str
    copies_handed: int
    status: str
    created_at: str
    updated_at: str
    version: int
