"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycles described in the Building Permit &
Inspection PRD (§2.4 common properties, §3 business logic).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ──────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PERMIT_CLERK = "PermitClerk"
    PLAN_REVIEWER = "PlanReviewer"
    INSPECTOR = "Inspector"
    BUILDING_OFFICIAL = "BuildingOfficial"


# ─── Status / enum value sets ──────────────────────────
class ContractorLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ContractorBondStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    REVOKED = "REVOKED"


class ContractorVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class WorkClass(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    ADDITION = "ADDITION"
    ALTERATION = "ALTERATION"
    REPAIR = "REPAIR"


class FeeMethod(str, Enum):
    VALUATION = "VALUATION"
    SQUARE_FOOT = "SQUARE_FOOT"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"
    FINALED = "FINALED"
    WITHDRAWN = "WITHDRAWN"


class WorkStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"


class PlanReviewDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CORRECTIONS = "CORRECTIONS"


class PlanReviewStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class CorrectionItemStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class InspectionType(str, Enum):
    ROUGH = "ROUGH"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StopWorkOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class CertificateType(str, Enum):
    FINAL = "FINAL"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class PaymentStatus(str, Enum):
    CLEARED = "CLEARED"
    VOID = "VOID"


# ─── Entity TypedDicts ─────────────────────────────────
# Entities below carry id + created_at + updated_at + version (PRD §2.4),
# except FeePayment and PermitEvent which are leaner (id + created_at only).

class Jurisdiction(TypedDict):
    id: str
    name: str
    code_edition: str
    valuation_fee_rate_per_1000: float
    square_foot_rate: float
    plan_review_fee_pct: float
    minimum_permit_fee: float
    renewal_fee_pct: float
    permit_valid_days: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    business_name: str
    license_number: str
    license_status: str
    license_expiry: str
    bond_amount: float
    bond_status: str
    verification_status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    jurisdiction_id: str
    contractor_id: str
    work_class: str
    fee_method: str
    declared_valuation: float
    floor_area_sqft: float
    assessed_valuation: float
    base_permit_fee: float
    plan_review_fee: float
    total_permit_fee: float
    amount_paid: float
    balance_due: float
    accrued_renewal_fees: float
    status: str
    work_status: str
    open_correction_count: int
    review_cycle: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    approving_reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanReview(TypedDict):
    id: str
    permit_id: str
    reviewer_id: str
    cycle_number: int
    decision: str
    review_status: str
    created_at: str
    updated_at: str
    version: int


class CorrectionNotice(TypedDict):
    id: str
    plan_review_id: str
    permit_id: str
    code_section: str
    description: str
    item_status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    badge_number: str
    created_at: str
    updated_at: str
    version: int


class PlanReviewer(TypedDict):
    id: str
    full_name: str
    cert_number: str
    created_at: str
    updated_at: str
    version: int


class InspectionSlot(TypedDict):
    id: str
    inspector_id: str
    window_start: str
    window_end: str
    max_inspections: int
    booked_count: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    permit_id: str
    slot_id: str
    inspector_id: str
    inspection_type: str
    scheduled_start: str
    scheduled_end: str
    inspection_status: str
    created_at: str
    updated_at: str
    version: int


class StopWorkOrder(TypedDict):
    id: str
    permit_id: str
    reason: str
    order_status: str
    created_at: str
    updated_at: str
    version: int


class CertificateOfOccupancy(TypedDict):
    id: str
    permit_id: str
    final_inspection_id: str
    co_type: str
    co_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, id + created_at only (PRD §2.4)
class FeePayment(TypedDict):
    id: str
    permit_id: str
    amount: float
    payment_status: str
    created_at: str


# common_fields: false — immutable audit record, id + created_at only (PRD §2.4)
class PermitEvent(TypedDict):
    id: str
    permit_id: str
    event_type: str
    detail: str
    created_at: str
