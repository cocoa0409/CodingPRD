"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model. Immutable audit records (the ROW
segment, the node review, the inspection, the payment, the incompleteness
notice) carry only ``id`` and ``created_at`` and therefore omit ``updated_at``
and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    ROW_REVIEWER = "ROWReviewer"
    AESTHETIC_REVIEWER = "AestheticReviewer"
    APPROVER = "Approver"
    INSPECTOR = "Inspector"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status / enum vocabularies ───────────────────────────────────────────
class ApplicantCertification(str, Enum):
    REGISTERED = "REGISTERED"


class StructureType(str, Enum):
    EXISTING_UTILITY = "EXISTING_UTILITY"
    EXISTING_MUNICIPAL = "EXISTING_MUNICIPAL"
    NEW_POLE = "NEW_POLE"


class StructureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DesignDistrict(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    HISTORIC = "HISTORIC"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INCOMPLETE = "INCOMPLETE"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    DEEMED_GRANTED = "DEEMED_GRANTED"
    WITHDRAWN = "WITHDRAWN"
    UNDER_APPEAL = "UNDER_APPEAL"
    APPEAL_GRANTED = "APPEAL_GRANTED"
    APPEAL_DENIED = "APPEAL_DENIED"


class FacilityType(str, Enum):
    COLLOCATION = "COLLOCATION"
    NEW_POLE = "NEW_POLE"


class NodeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PERMITTED = "PERMITTED"
    ACTIVATED = "ACTIVATED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DesignReviewStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class AestheticReviewStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    WAIVED = "WAIVED"


class ReviewType(str, Enum):
    DESIGN_STANDARD = "DESIGN_STANDARD"
    AESTHETIC_HISTORIC = "AESTHETIC_HISTORIC"


class ReviewOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FeeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PaymentType(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"


class RentalStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class AppealStatus(str, Enum):
    FILED = "FILED"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true → id, created_at, updated_at, version
class Applicant(TypedDict):
    id: str
    company_name: str
    contact_email: str
    certification_status: str
    master_agreement_signed: bool
    master_agreement_signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportStructure(TypedDict):
    id: str
    structure_type: str
    max_collocations: int
    reserved_collocations: int
    active_collocations: int
    available_collocations: int
    status: str
    in_design_district: str
    location_desc: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false → id, created_at only
class ROWSegment(TypedDict):
    id: str
    name: str
    corridor_code: str
    last_paved_at: Optional[str]
    moratorium_months: int
    in_historic_district: bool
    created_at: str


class PermitApplication(TypedDict):
    id: str
    applicant_id: str
    project_name: Optional[str]
    status: str
    node_count: int
    shot_clock_base_days: Optional[int]
    submitted_at: Optional[str]
    toll_days_accumulated: float
    shot_clock_deadline: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Node(TypedDict):
    id: str
    application_id: str
    support_structure_id: str
    row_segment_id: str
    facility_type: str
    proposed_construction_date: str
    location_desc: Optional[str]
    status: str
    design_review_status: str
    aesthetic_review_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class NodeReview(TypedDict):
    id: str
    node_id: str
    review_type: str
    outcome: str
    reviewer_user_id: str
    findings: Optional[str]
    created_at: str


# common_fields: false
class Inspection(TypedDict):
    id: str
    node_id: str
    outcome: str
    inspector_user_id: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    notes: Optional[str]
    created_at: str


class FeeInvoice(TypedDict):
    id: str
    application_id: str
    fee_variant: str
    assessed_amount_cents: int
    paid_amount_cents: int
    refunded_amount_cents: int
    outstanding_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class Payment(TypedDict):
    id: str
    fee_invoice_id: str
    amount_cents: int
    payment_type: str
    status: str
    created_at: str


class RecurringRental(TypedDict):
    id: str
    node_id: str
    status: str
    billing_year: int
    period_start: str
    period_end: str
    estimated_amount_cents: int
    actual_amount_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false
class IncompletenessNotice(TypedDict):
    id: str
    application_id: str
    issued_at: str
    cured_at: Optional[str]
    toll_days: float
    deficiencies: Optional[str]
    created_at: str


class Appeal(TypedDict):
    id: str
    application_id: str
    grounds: str
    status: str
    decided_by_user_id: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
