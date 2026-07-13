"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PERMIT_REVIEWER = "PermitReviewer"
    INSPECTOR = "Inspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    CLOSED_OUT = "CLOSED_OUT"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TrafficControlPlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RestorationBondStatus(str, Enum):
    POSTED = "POSTED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class LaneClosureStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    RESTORATION_PENDING = "RESTORATION_PENDING"
    RESTORED = "RESTORED"
    RESTORATION_REJECTED = "RESTORATION_REJECTED"
    VOIDED = "VOIDED"


class SidewalkObstructionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTORED = "RESTORED"
    VOIDED = "VOIDED"


class EncroachmentAgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"


class ZoneClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    ARTERIAL = "ARTERIAL"


class ObstructionType(str, Enum):
    LANE = "LANE"
    FULL_ROAD = "FULL_ROAD"
    SIDEWALK = "SIDEWALK"


class ViolationType(str, Enum):
    UNPERMITTED_WORK = "UNPERMITTED_WORK"
    TCP_VIOLATION = "TCP_VIOLATION"
    OVERSTAY = "OVERSTAY"
    RESTORATION_FAILURE = "RESTORATION_FAILURE"


# --- Entities carrying common fields (id, created_at, updated_at, version) ---


class Applicant(TypedDict):
    id: str
    company_name: str
    license_number: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class StreetSegment(TypedDict):
    id: str
    block_label: str
    zone_class: str
    last_repaved_date: str
    roadway_lane_count: int
    moratorium_waived: bool
    moratorium_end_date: str
    active_lane_closure_count: int
    created_at: str
    updated_at: str
    version: int


class SidewalkSpan(TypedDict):
    id: str
    block_label: str
    side: str
    width_ft: float
    ada_min_clearance_ft: float
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    applicant_id: str
    street_segment_id: str
    primary_obstruction_type: str
    requested_start_date: str
    requested_end_date: str
    requires_utility_cut: bool
    status: str
    assigned_reviewer_user_id: Optional[str]
    actual_start_date: Optional[str]
    actual_end_date: Optional[str]
    estimated_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    surcharge_cents: Optional[int]
    total_charge_cents: Optional[int]
    cumulative_penalty_cents: int
    valid_until: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrafficControlPlan(TypedDict):
    id: str
    permit_id: str
    device_list: List[str]
    requires_flaggers: bool
    flagger_count: int
    setback_ft: float
    status: str
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestorationBond(TypedDict):
    id: str
    permit_id: str
    posted_cents: int
    required_cents: int
    held_cents: int
    refunded_cents: int
    forfeited_cents: int
    provisional_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaneClosure(TypedDict):
    id: str
    permit_id: str
    street_segment_id: str
    obstruction_type: str
    start_date: str
    end_date: str
    requires_utility_cut: bool
    estimated_deficiency_cents: int
    assessed_deficiency_cents: int
    inspector_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SidewalkObstruction(TypedDict):
    id: str
    permit_id: str
    sidewalk_span_id: str
    start_date: str
    end_date: str
    maintained_clearance_ft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EncroachmentAgreement(TypedDict):
    id: str
    permit_id: str
    term_months: int
    proposed_fee_cents: int
    agreed_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields: false) — only id + created_at ---


class ViolationNotice(TypedDict):
    id: str
    permit_id: str
    violation_type: str
    penalty_cents: int
    note: Optional[str]
    created_at: str
