"""Domain types: entity TypedDicts, status enums, role enum.

All eleven resources carry the common system-managed fields
(id, created_at, updated_at, version) described in PRD §2.5.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_CARE_MANAGER = "CustomerCareManager"
    CUSTOMER_CARE_REP = "CustomerCareRep"
    HOMEBUYER = "Homebuyer"


class HomeStatus(str, Enum):
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    PRE_CLOSE_READY = "PRE_CLOSE_READY"
    ORIENTATION_SCHEDULED = "ORIENTATION_SCHEDULED"
    ORIENTED = "ORIENTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    CLOSED = "CLOSED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelReason(str, Enum):
    BUYER_NO_SHOW = "BUYER_NO_SHOW"
    BUYER_REQUEST = "BUYER_REQUEST"
    BUILDER_DELAY = "BUILDER_DELAY"


class AttendeeType(str, Enum):
    BUYER = "BUYER"
    CO_BUYER = "CO_BUYER"
    POA_PROXY = "POA_PROXY"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DeficiencyStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    CLASSIFIED = "CLASSIFIED"
    DECIDED = "DECIDED"
    IN_REPAIR = "IN_REPAIR"
    READY_FOR_REINSPECTION = "READY_FOR_REINSPECTION"
    VERIFIED = "VERIFIED"
    SIGNED_OFF = "SIGNED_OFF"
    WITHDRAWN = "WITHDRAWN"


class Classification(str, Enum):
    WARRANTABLE = "WARRANTABLE"
    COSMETIC = "COSMETIC"


class Resolution(str, Enum):
    COMPLETE_BEFORE_CLOSING = "COMPLETE_BEFORE_CLOSING"
    COMPLETE_AFTER_CLOSING = "COMPLETE_AFTER_CLOSING"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class EscrowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    FULLY_RELEASED = "FULLY_RELEASED"
    VOIDED = "VOIDED"


class SignatureStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    STALE = "STALE"


class SurveyStatus(str, Enum):
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"


class SystemKey(str, Enum):
    HVAC = "HVAC"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    APPLIANCES = "APPLIANCES"
    EXTERIOR = "EXTERIOR"
    SAFETY = "SAFETY"
    OTHER = "OTHER"


class ChecklistOutcome(str, Enum):
    DEMONSTRATED = "DEMONSTRATED"
    SKIPPED = "SKIPPED"
    PENDING = "PENDING"


# --------------------------------------------------------------------------
# Entity records. Every resource carries id / created_at / updated_at /
# version per the common resource properties section of the PRD.
# --------------------------------------------------------------------------

class Community(TypedDict, total=False):
    id: str
    name: str
    holdback_cost_multiplier: float
    holdback_min_cents: int
    holdback_max_cents: int
    orientation_min_days_before_closing: int
    orientation_max_days_before_closing: int
    appointment_duration_minutes: int
    appointment_buffer_minutes: int
    survey_window_days: int
    cosmetic_photo_required: bool
    created_at: str
    updated_at: str
    version: int


class Homebuyer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomerCareRep(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    active: bool
    daily_visit_capacity_minutes: int
    created_at: str
    updated_at: str
    version: int


class Home(TypedDict, total=False):
    id: str
    community_id: str
    primary_buyer_id: str
    lot_number: str
    address: str
    sales_price_cents: int
    closing_date: str
    status: str
    open_before_closing_count: int
    open_after_closing_count: int
    created_at: str
    updated_at: str
    version: int


class OrientationAppointment(TypedDict, total=False):
    id: str
    home_id: str
    rep_id: str
    scheduled_start: str
    duration_minutes: int
    status: str
    reschedule_count: int
    cancel_reason: Optional[str]
    completed_at: Optional[str]
    checklist_items: List[Dict[str, Any]]
    checklist_total_count: int
    checklist_demonstrated_count: int
    checklist_pending_count: int
    checklist_skipped_count: int
    created_at: str
    updated_at: str
    version: int


class Attendee(TypedDict, total=False):
    id: str
    appointment_id: str
    attendee_type: str
    buyer_id: Optional[str]
    proxy_name: Optional[str]
    poa_document_ref: Optional[str]
    verification_status: str
    decided_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeficiencyItem(TypedDict, total=False):
    id: str
    home_id: str
    appointment_id: str
    system_key: Optional[str]
    title: str
    description: Optional[str]
    classification: Optional[str]
    estimated_repair_cost_cents: Optional[int]
    photo_evidence_ref: Optional[str]
    resolution: Optional[str]
    status: str
    signed_off_at: Optional[str]
    holdback_released: bool
    created_at: str
    updated_at: str
    version: int


class ReinspectionVisit(TypedDict, total=False):
    id: str
    home_id: str
    rep_id: str
    scheduled_start: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowHoldback(TypedDict, total=False):
    id: str
    home_id: str
    status: str
    holdback_amount_cents: int
    final_holdback_cents: Optional[int]
    funded_amount_cents: int
    released_amount_cents: int
    remaining_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AcknowledgmentSignature(TypedDict, total=False):
    id: str
    home_id: str
    appointment_id: str
    status: str
    signer_buyer_id: Optional[str]
    signed_at: Optional[str]
    open_item_snapshot_count: Optional[int]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedbackSurvey(TypedDict, total=False):
    id: str
    home_id: str
    appointment_id: str
    status: str
    overall_rating: Optional[int]
    systems_demo_rating: Optional[int]
    timeliness_rating: Optional[int]
    would_recommend: Optional[bool]
    comments: Optional[str]
    composite_score: Optional[float]
    submitted_at: Optional[str]
    window_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
