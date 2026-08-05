"""Domain types: entity TypedDicts, status enums, and the role enum for the
Pole-Attachment & Joint-Use Management API (PRD §2, §3).

Every resource type carries the four common system fields id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    JOINT_USE_COORDINATOR = "JointUseCoordinator"
    ENGINEER = "Engineer"
    PERMIT_OFFICER = "PermitOfficer"
    FIELD_AUDITOR = "FieldAuditor"
    ATTACHER = "Attacher"


# --------------------------------------------------------------------------
# Status enums (PRD §3)
# --------------------------------------------------------------------------
class PoleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OwnerCategory(str, Enum):
    ELECTRIC_UTILITY = "ELECTRIC_UTILITY"
    ILEC = "ILEC"
    MUNICIPAL = "MUNICIPAL"


class ApplicationPurpose(str, Enum):
    FIBER = "FIBER"
    COAX = "COAX"
    POWER_SUPPLY = "POWER_SUPPLY"
    WIRELESS = "WIRELESS"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SURVEYED = "SURVEYED"
    ESTIMATE_ISSUED = "ESTIMATE_ISSUED"
    ESTIMATE_ACCEPTED = "ESTIMATE_ACCEPTED"
    ESTIMATE_REJECTED = "ESTIMATE_REJECTED"
    ESTIMATE_EXPIRED = "ESTIMATE_EXPIRED"
    PERMIT_GRANTED = "PERMIT_GRANTED"
    PERMIT_DENIED = "PERMIT_DENIED"
    WITHDRAWN = "WITHDRAWN"


class PermitDecision(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ShotClockStatus(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class AttachmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    ABANDONED = "ABANDONED"


class FindingStatus(str, Enum):
    FLAGGED = "FLAGGED"
    LEGALIZED = "LEGALIZED"
    REMOVED = "REMOVED"
    DISPUTED = "DISPUTED"


class InvoiceType(str, Enum):
    MAKE_READY = "MAKE_READY"
    ANNUAL_RENTAL = "ANNUAL_RENTAL"
    UNAUTHORIZED = "UNAUTHORIZED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"
    OVERDUE = "OVERDUE"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    ADJUSTED = "ADJUSTED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    WITHDRAWN = "WITHDRAWN"


class ComplexityClass(str, Enum):
    SIMPLE = "SIMPLE"
    COMPLEX = "COMPLEX"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry the four common fields — PRD §2.4)
# --------------------------------------------------------------------------
class PoleOwner(TypedDict):
    id: str
    legal_name: str
    owner_category: str
    annual_rental_rate_cents: int
    make_ready_labor_rate_cents_per_hour: int
    created_at: str
    updated_at: str
    version: int


class MakeReadyCrew(TypedDict):
    id: str
    pole_owner_id: str
    crew_name: str
    region: str
    created_at: str
    updated_at: str
    version: int


class Pole(TypedDict):
    id: str
    pole_owner_id: str
    tag: str
    height_ft: int
    usable_communication_space_inches: int
    occupied_space_inches: int
    reserved_space_inches: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Attacher(TypedDict):
    id: str
    company_name: str
    cin: str
    contact_email: str
    credit_limit_cents: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AttachmentApplication(TypedDict):
    id: str
    pole_id: str
    attacher_id: str
    requested_space_inches: int
    requested_position_inches: int
    purpose: str
    reserved_space_inches: int
    submitted_at: str
    surveyed_at: Optional[str]
    estimate_issued_at: Optional[str]
    estimate_expires_at: Optional[str]
    estimate_accepted_at: Optional[str]
    survey_deadline: str
    estimate_deadline: Optional[str]
    permit_deadline: Optional[str]
    make_ready_required: Optional[bool]
    make_ready_fee_estimate_cents: Optional[int]
    make_ready_fee_final_cents: Optional[int]
    annual_rental_fee_cents: Optional[int]
    surveyor_user_id: Optional[str]
    permit_officer_user_id: Optional[str]
    permit_decision: Optional[str]
    permit_issued_at: Optional[str]
    shot_clock_status: Optional[str]
    make_ready_invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeReadySurvey(TypedDict):
    id: str
    application_id: str
    crew_id: str
    surveyor_user_id: str
    window_start: str
    window_end: str
    estimated_labor_hours: float
    make_ready_required: bool
    existing_attacher_count: int
    complexity_class: str
    findings: str
    created_at: str
    updated_at: str
    version: int


class Attachment(TypedDict):
    id: str
    pole_id: str
    attacher_id: str
    application_id: Optional[str]
    allotted_space_inches: int
    position_inches: int
    authorized: bool
    transferred_from_attacher_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnauthorizedAttachmentFinding(TypedDict):
    id: str
    pole_id: str
    attacher_id: str
    auditor_user_id: str
    audited_at: str
    discovered_space_inches: int
    discovered_position_inches: int
    good_faith: bool
    estimated_install_years_ago: int
    penalty_cents: int
    back_rental_cents: int
    penalty_invoice_id: str
    resulting_attachment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    attacher_id: str
    pole_owner_id: Optional[str]
    application_id: Optional[str]
    finding_id: Optional[str]
    invoice_type: str
    amount_cents: int
    line_items: List[dict]
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    attacher_id: str
    invoice_id: Optional[str]
    finding_id: Optional[str]
    reason: str
    round_count: int
    resolution: Optional[str]
    adjusted_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
