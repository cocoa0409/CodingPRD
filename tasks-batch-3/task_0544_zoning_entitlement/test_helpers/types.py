"""Domain types: entity TypedDicts, status enums, role enum.

Everything here is derived from the Zoning Entitlement PRD (§1-§5). Append-only
evidentiary records (CompletenessReview, Finding) carry only id + created_at and
therefore omit updated_at / version, per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PLANNER = "Planner"
    CLERK = "Clerk"
    COMMISSIONER = "Commissioner"
    ADMIN = "Admin"


class ParcelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_APPLICATION = "UNDER_APPLICATION"
    ENTITLED = "ENTITLED"
    SUBDIVIDED = "SUBDIVIDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INCOMPLETE = "INCOMPLETE"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    DECIDED_APPROVED = "DECIDED_APPROVED"
    DECIDED_DENIED = "DECIDED_DENIED"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    RECORDED = "RECORDED"
    WITHDRAWN = "WITHDRAWN"
    DENIED_ON_APPEAL = "DENIED_ON_APPEAL"
    CLOSED = "CLOSED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class AgendaItemStatus(str, Enum):
    PLACED = "PLACED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CONTINUED = "CONTINUED"
    REMOVED = "REMOVED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PlatStatus(str, Enum):
    PENDING = "PENDING"
    RECORDED = "RECORDED"
    VACATED = "VACATED"
    REJECTED = "REJECTED"


class AssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ASSESSED = "ASSESSED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    VOIDED = "VOIDED"


class ApplicationType(str, Enum):
    VARIANCE = "VARIANCE"
    REZONE = "REZONE"
    CUP = "CUP"
    SUBDIVISION = "SUBDIVISION"


# --- Entities carrying the full id/created_at/updated_at/version set ---

class Parcel(TypedDict):
    id: str
    apn: str
    zoning_district: str
    area_acres: float
    neighbor_parcel_count: int
    expanded_neighbor_count: int
    sensitive_area: bool
    assessed_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    name: str
    park_fee_per_lot_cents: int
    road_fee_tier1_per_acre_cents: int
    road_fee_tier2_per_acre_cents: int
    road_fee_tier3_per_acre_cents: int
    admin_pct: float
    affordable_discount_pct: float
    credit_pct: float
    fee_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    organization: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EntitlementApplication(TypedDict):
    id: str
    application_type: str
    parcel_id: str
    applicant_id: str
    requested_use: str
    affordable_housing: bool
    status: str
    submitted_at: Optional[str]
    revision_count: int
    assigned_planner_user_id: Optional[str]
    decision: Optional[str]
    decision_at: Optional[str]
    appeal_deadline: Optional[str]
    provisional_expiration_date: Optional[str]
    effective_date: Optional[str]
    final_expiration_date: Optional[str]
    extension_count: int
    review_window_closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoticeMailing(TypedDict):
    id: str
    application_id: str
    notice_kind: str
    mailed_at: str
    recipient_count: int
    used_expanded_radius: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    body: str
    scheduled_date: str
    agenda_capacity: int
    agenda_slots_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingAgendaItem(TypedDict):
    id: str
    hearing_id: str
    application_id: str
    agenda_position: int
    decision: Optional[str]
    continued_to_hearing_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionOfApproval(TypedDict):
    id: str
    application_id: str
    condition_code: str
    condition_text: str
    satisfied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    application_id: str
    appellant_name: str
    grounds: str
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Plat(TypedDict):
    id: str
    application_id: str
    fee_schedule_id: str
    declared_lot_count: int
    declared_gross_acres: float
    prior_paid_fee_cents: int
    recorded_lot_count: Optional[int]
    recorded_gross_acres: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactFeeAssessment(TypedDict):
    id: str
    plat_id: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    total_fee_cents: int
    gross_fee_cents: int
    credit_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only evidentiary records: id + created_at only (PRD §2.4) ---

class CompletenessReview(TypedDict):
    id: str
    application_id: str
    cycle_number: int
    determination: str
    deficiency_notes: Optional[str]
    reviewed_by: str
    created_at: str


class Finding(TypedDict):
    id: str
    application_id: str
    finding_code: str
    finding_text: str
    supports_approval: bool
    created_at: str
