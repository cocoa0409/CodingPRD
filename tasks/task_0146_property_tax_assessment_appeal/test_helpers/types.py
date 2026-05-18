"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Mutable resources (Owner, Property, HearingOfficer, Assessment,
  ExemptionApplication, Appeal, Hearing, TaxBill, DeferralPlan) carry
  id + created_at + updated_at + version.
- Append-only Payment carries ONLY id + created_at. PRD §2.4: "The
  single exception is Payment. Payments are immutable once written: a
  Payment carries id and created_at and ... Payment therefore exposes
  neither updated_at nor version."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ASSESSOR = "Assessor"
    TREASURER = "Treasurer"
    HEARING_OFFICER = "HearingOfficer"
    OWNER = "Owner"


# ---------------------------------------------------------------------------
# Assessment states — PRD §2.7
# ---------------------------------------------------------------------------
class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# ExemptionApplication states — PRD §2.7
# ---------------------------------------------------------------------------
class ExemptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ExemptionType(str, Enum):
    HOMESTEAD = "HOMESTEAD"
    SENIOR = "SENIOR"
    VETERAN = "VETERAN"
    DISABILITY = "DISABILITY"


class RevokedReason(str, Enum):
    OWNERSHIP_CHANGE = "OWNERSHIP_CHANGE"
    INELIGIBLE = "INELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Appeal states — PRD §2.7
# ---------------------------------------------------------------------------
class AppealStatus(str, Enum):
    FILED = "FILED"
    SCHEDULED = "SCHEDULED"
    HEARD = "HEARD"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


class DecisionOutcome(str, Enum):
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    INCREASED = "INCREASED"


class FiledGrounds(str, Enum):
    OVER_MARKET = "OVER_MARKET"
    EXEMPTION_DENIED = "EXEMPTION_DENIED"
    CAP_MISAPPLIED = "CAP_MISAPPLIED"
    CLERICAL_ERROR = "CLERICAL_ERROR"


# ---------------------------------------------------------------------------
# Hearing — PRD §2.7
# ---------------------------------------------------------------------------
class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class HearingRoom(str, Enum):
    ROOM_A = "ROOM_A"
    ROOM_B = "ROOM_B"
    ROOM_C = "ROOM_C"


# ---------------------------------------------------------------------------
# TaxBill — PRD §2.7
# ---------------------------------------------------------------------------
class TaxBillStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    IN_DEFERRAL = "IN_DEFERRAL"
    DELINQUENT = "DELINQUENT"


# ---------------------------------------------------------------------------
# DeferralPlan — PRD §2.7
# ---------------------------------------------------------------------------
class DeferralPlanStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"


# ---------------------------------------------------------------------------
# Payment — PRD §2.7
# ---------------------------------------------------------------------------
class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class RefundReason(str, Enum):
    APPEAL_REDUCED = "APPEAL_REDUCED"
    OVERPAYMENT = "OVERPAYMENT"


# ===========================================================================
# Mutable resources — PRD §2.4 (id + created_at + updated_at + version)
# ===========================================================================
class Owner(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    veteran_status: bool
    disability_rating: int
    created_at: str
    updated_at: str
    version: int


class HearingOfficer(TypedDict, total=False):
    id: str
    full_name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    owner_id: str
    parcel_number: str
    market_value: float
    capped_value: float
    ownership_change_date: Optional[str]
    current_assessment_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    property_id: str
    roll_year: int
    prior_assessment_id: Optional[str]
    prior_capped_value: float
    market_value_at_roll: float
    capped_value: float
    cap_reset_applied: bool
    status: str
    issued_at: Optional[str]
    finalized_at: Optional[str]
    appeal_window_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExemptionApplication(TypedDict, total=False):
    id: str
    property_id: str
    owner_id: str
    exemption_type: str
    effective_roll_year: int
    status: str
    approved_amount: Optional[float]
    approved_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    property_id: str
    assessment_id: str
    assessment_version: int
    owner_id: str
    filed_grounds: str
    claimed_value: float
    status: str
    decision_outcome: Optional[str]
    decided_value: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    appeal_id: str
    property_id: str
    scheduled_start: str
    scheduled_end: str
    hearing_room: str
    officer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxBill(TypedDict, total=False):
    id: str
    property_id: str
    assessment_id: str
    roll_year: int
    taxable_value: float
    total_exemption_amount: float
    mill_rate: float
    base_tax_amount: float
    amount_due: float
    total_payments_applied: float
    status: str
    due_date: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeferralPlan(TypedDict, total=False):
    id: str
    tax_bill_id: str
    property_id: str
    principal_deferred: float
    annual_interest_rate: float
    accrued_interest: float
    started_at: Optional[str]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only Payment — PRD §2.4 (id + created_at only)
# ===========================================================================
class Payment(TypedDict, total=False):
    id: str
    tax_bill_id: str
    amount: float
    applied_at: str
    status: str
    refund_reason: Optional[str]
    created_at: str


__all__ = [
    "UserRole",
    "AssessmentStatus",
    "ExemptionApplicationStatus",
    "ExemptionType",
    "RevokedReason",
    "AppealStatus",
    "DecisionOutcome",
    "FiledGrounds",
    "HearingStatus",
    "HearingRoom",
    "TaxBillStatus",
    "DeferralPlanStatus",
    "PaymentStatus",
    "RefundReason",
    "Owner",
    "HearingOfficer",
    "Property",
    "Assessment",
    "ExemptionApplication",
    "Appeal",
    "Hearing",
    "TaxBill",
    "DeferralPlan",
    "Payment",
]
