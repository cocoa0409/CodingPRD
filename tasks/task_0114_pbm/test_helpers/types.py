"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- ``Member``, ``Plan``, ``Drug``, ``FormularyEntry``,
  ``PriorAuthorization``, ``Claim``, ``CopayCard``, and
  ``RebateAgreement`` carry id, created_at, updated_at, and version.
  PRD §2.4: "All primary, top-level resources — Member, Plan, Drug,
  FormularyEntry, PriorAuthorization, Claim, CopayCard, and
  RebateAgreement — carry the following system-managed fields …: id …,
  created_at …, updated_at …, and version …."

- ``LedgerEntry`` is append-only audit data and carries only id and
  created_at (plus its own posted_at). PRD §2.4: "The LedgerEntry
  resource is append-only audit data and carries only id and
  created_at; it has no updated_at and no version, because once a
  rebate accrual or clawback is posted it is never altered."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PBM_ADMIN = "PBMAdmin"
    PRESCRIBER = "Prescriber"
    CLINICAL_REVIEWER = "ClinicalReviewer"
    CLAIMS_ADJUDICATOR = "ClaimsAdjudicator"


# ---------------------------------------------------------------------------
# Plan — PRD §3.1
# ---------------------------------------------------------------------------
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Drug — PRD §3.1
# ---------------------------------------------------------------------------
class DrugStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# FormularyEntry — PRD §3.1
# ---------------------------------------------------------------------------
class FormularyEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Member — PRD §3.2
# ---------------------------------------------------------------------------
class MemberEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# PriorAuthorization — PRD §3.3
# ---------------------------------------------------------------------------
class PriorAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Claim — PRD §3.4 / §3.5 / §3.6 / §3.7
# ---------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    REJECTED = "REJECTED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ClaimChannel(str, Enum):
    RETAIL_30 = "RETAIL_30"
    MAIL_ORDER_90 = "MAIL_ORDER_90"
    SPECIALTY = "SPECIALTY"


# ---------------------------------------------------------------------------
# CopayCard — PRD §3.8
# ---------------------------------------------------------------------------
class CopayCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# RebateAgreement — PRD §3.6
# ---------------------------------------------------------------------------
class RebateAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# LedgerEntry — PRD §3.9
# ---------------------------------------------------------------------------
class LedgerEntryType(str, Enum):
    REBATE_ACCRUED = "REBATE_ACCRUED"
    REBATE_CLAWBACK = "REBATE_CLAWBACK"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# Plan — common_fields: true
class Plan(TypedDict, total=False):
    id: str
    name: str
    deductible_cents: int
    oop_max_cents: int
    coinsurance_rate: float
    mail_order_discount_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Drug — common_fields: true
class Drug(TypedDict, total=False):
    id: str
    ndc: str
    generic_name: str
    brand_name: str
    is_specialty: bool
    requires_prior_auth: bool
    step_therapy_predecessor_ndc: Optional[str]
    unit_allowed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# FormularyEntry — common_fields: true
class FormularyEntry(TypedDict, total=False):
    id: str
    plan_id: str
    drug_id: str
    tier: int
    copay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Member — common_fields: true
class Member(TypedDict, total=False):
    id: str
    plan_id: str
    full_name: str
    date_of_birth: str
    enrollment_status: str
    ytd_deductible_paid_cents: int
    ytd_oop_paid_cents: int
    benefit_year_start: str
    created_at: str
    updated_at: str
    version: int


# PriorAuthorization — common_fields: true
class PriorAuthorization(TypedDict, total=False):
    id: str
    member_id: str
    drug_id: str
    prescriber_npi: str
    clinical_rationale: str
    status: str
    effective_start: Optional[str]
    effective_end: Optional[str]
    revision_count: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Claim — common_fields: true
class Claim(TypedDict, total=False):
    id: str
    member_id: str
    drug_id: str
    channel: str
    days_supply: int
    quantity: int
    prior_auth_id: Optional[str]
    copay_card_id: Optional[str]
    estimated_member_cost_cents: int
    adjudicated_allowed_cents: int
    adjudicated_member_cost_cents: int
    adjudicated_plan_paid_cents: int
    copay_card_paid_cents: int
    status: str
    payment_status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# CopayCard — common_fields: true
class CopayCard(TypedDict, total=False):
    id: str
    member_id: str
    drug_id: str
    max_benefit_cents: int
    per_claim_cap_cents: int
    used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# RebateAgreement — common_fields: true
class RebateAgreement(TypedDict, total=False):
    id: str
    drug_id: str
    manufacturer_name: str
    rebate_rate: float
    clawback_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


# LedgerEntry — common_fields: false (PRD §2.4: id + created_at only,
# plus its own posted_at field; no updated_at, no version).
class LedgerEntry(TypedDict, total=False):
    id: str
    claim_id: str
    rebate_agreement_id: str
    entry_type: str
    amount_cents: int
    posted_at: str
    created_at: str


__all__ = [
    "UserRole",
    "PlanStatus",
    "DrugStatus",
    "FormularyEntryStatus",
    "MemberEnrollmentStatus",
    "PriorAuthorizationStatus",
    "ClaimStatus",
    "ClaimPaymentStatus",
    "ClaimChannel",
    "CopayCardStatus",
    "RebateAgreementStatus",
    "LedgerEntryType",
    "Plan",
    "Drug",
    "FormularyEntry",
    "Member",
    "PriorAuthorization",
    "Claim",
    "CopayCard",
    "RebateAgreement",
    "LedgerEntry",
]
