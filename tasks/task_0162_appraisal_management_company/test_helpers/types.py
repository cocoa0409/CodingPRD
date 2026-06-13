"""Domain types for the Appraisal Management Company (AMC) API.

Entity TypedDicts, status enums, and the role enum, derived from the PRD.
Mutable entities carry the full common property set (id, created_at, updated_at,
version, PRD §2.6). FirewallEvent is the sole audit-only entity: it carries only
id + created_at (PRD §2.4), so its TypedDict omits updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    AMC_COORDINATOR = "AMCCoordinator"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    APPRAISER = "Appraiser"
    LENDER_USER = "LenderUser"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums ──────────────────────────────────────────────────────
class AppraiserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    IN_QC = "IN_QC"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REVISION = "REVISION"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ComplianceOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class RevisionReasonCategory(str, Enum):
    USPAP_DEFICIENCY = "USPAP_DEFICIENCY"
    UAD_DEFICIENCY = "UAD_DEFICIENCY"
    DATA_CORRECTION = "DATA_CORRECTION"
    VALUE_DISPUTE = "VALUE_DISPUTE"


class RevisionOrigin(str, Enum):
    COMPLIANCE = "COMPLIANCE"
    MANUAL = "MANUAL"


class RevisionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RovResolution(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VALUE_CHANGED = "VALUE_CHANGED"
    VALUE_UPHELD = "VALUE_UPHELD"


class FeeSplitVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ProductType(str, Enum):
    URAR_1004 = "URAR_1004"
    CONDO_1073 = "CONDO_1073"
    EXTERIOR_2055 = "EXTERIOR_2055"


# ─── Entity TypedDicts (mutable: full common property set) ──────────────
class Lender(TypedDict):
    id: str
    name: str
    approved_panel_appraiser_ids: List[str]
    monthly_fee_budget_cents: int
    committed_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict):
    id: str
    full_name: str
    license_state: str
    status: str
    base_fee_share_pct: float
    active_assignment_count: int
    completed_count: int
    on_time_count: int
    last_assigned_at: Optional[str]
    panel_score: float
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    street_address: str
    state_code: str
    prior_appraised_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    lender_id: str
    property_id: str
    order_fee_cents: int
    product_type: str
    rush: bool
    sla_hours: int
    placed_at: Optional[str]
    status: str
    appraised_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    order_id: str
    appraiser_id: str
    sla_hours: int
    accepted_at: Optional[str]
    inspection_start: Optional[str]
    inspection_end: Optional[str]
    revision_round: int
    actual_turnaround_hours: Optional[float]
    status: str
    supersedes_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict):
    id: str
    assignment_id: str
    opinion_of_value_cents: int
    uad_condition_rating: str
    uad_quality_rating: str
    comparable_count: int
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict):
    id: str
    report_id: str
    uspap_comp_minimum_met: bool
    uad_ratings_valid: bool
    outcome: str
    finding_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict):
    id: str
    report_id: str
    reason_category: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconsiderationOfValue(TypedDict):
    id: str
    order_id: str
    requested_value_cents: int
    value_delta_pct: float
    requires_second_review: bool
    resolution: str
    new_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FeeSplit(TypedDict):
    id: str
    order_id: str
    variant: str
    appraiser_fee_cents: int
    amc_fee_cents: int
    revision_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


# Audit-only entity (PRD §2.4): id + created_at ONLY, no updated_at/version.
class FirewallEvent(TypedDict):
    id: str
    order_id: str
    actor_role: str
    blocked_operation: str
    error_id: str
    created_at: str
