"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities with the "four common properties" (id, created_at,
  updated_at, version): District, Student, ParentAccount, FrlApplication,
  MenuItem, MealServingRecord, UsdaReimbursementClaim.
- Append-only event records that carry ONLY id and created_at (PRD §2.4:
  "Two entity types are append-only event records and deliberately omit
  updated_at and version: AllergyProfileEntry and PaidLedgerEntry"):
  AllergyProfileEntry, PaidLedgerEntry.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PARENT = "Parent"
    DISTRICT_REVIEWER = "DistrictReviewer"
    CAFETERIA_MANAGER = "CafeteriaManager"
    AUDIT_OFFICER = "AuditOfficer"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class FrlApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RENEWED_FROM_PRIOR = "RENEWED_FROM_PRIOR"


class DecidedTier(str, Enum):
    FREE = "FREE"
    REDUCED = "REDUCED"
    DENIED_PAID = "DENIED_PAID"


class EligibilityTier(str, Enum):
    FREE = "FREE"
    REDUCED = "REDUCED"
    PAID = "PAID"


class MenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MealServingStatus(str, Enum):
    SERVED = "SERVED"
    VOIDED = "VOIDED"


class UsdaReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class AllergyProfileEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Allergen(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    DAIRY = "DAIRY"
    EGG = "EGG"
    SOY = "SOY"
    WHEAT = "WHEAT"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"


class AllergySeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class PaidLedgerEntryType(str, Enum):
    TOP_UP = "TOP_UP"
    CHARGE = "CHARGE"
    REFUND = "REFUND"


# ---------------------------------------------------------------------------
# Entities carrying the four common fields (id, created_at, updated_at,
# version) — PRD §2.4.
# ---------------------------------------------------------------------------
class District(TypedDict, total=False):
    id: str
    name: str
    school_year_start: str
    usda_reimbursement_total_cents: int
    top_up_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    district_id: str
    parent_account_id: str
    full_name: str
    grade_level: int
    eligibility_tier: str
    eligibility_application_id: Optional[str]
    allergy_block_active: bool
    meals_served_today_count: int
    created_at: str
    updated_at: str
    version: int


class ParentAccount(TypedDict, total=False):
    id: str
    district_id: str
    parent_email: str
    prepaid_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FrlApplication(TypedDict, total=False):
    id: str
    district_id: str
    student_id: str
    school_year_start: str
    household_size: int
    declared_annual_income_cents: int
    documents_attached_count: int
    status: str
    decided_tier: Optional[str]
    federal_poverty_guideline_cents: Optional[int]
    prior_year_application_id: Optional[str]
    review_note: Optional[str]
    reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    district_id: str
    name: str
    contains_allergens: List[str]
    calories: int
    sodium_mg: int
    full_price_cents: int
    reimbursable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MealServingRecord(TypedDict, total=False):
    id: str
    district_id: str
    student_id: str
    menu_item_id: str
    serving_date: str
    status: str
    tier_at_serving: str
    charged_cents: int
    provisional_reimbursement_cents: int
    created_at: str
    updated_at: str
    version: int


class UsdaReimbursementClaim(TypedDict, total=False):
    id: str
    district_id: str
    period_start: str
    period_end: str
    status: str
    serving_record_ids: List[str]
    final_reimbursement_cents: int
    provisional_total_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only event records — id + created_at ONLY per PRD §2.4.
# ---------------------------------------------------------------------------
class AllergyProfileEntry(TypedDict, total=False):
    id: str
    student_id: str
    allergen: str
    severity: str
    status: str
    doctor_note_attached: bool
    created_at: str


class PaidLedgerEntry(TypedDict, total=False):
    id: str
    parent_account_id: str
    type: str
    amount_cents: int
    serving_record_id: Optional[str]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "FrlApplicationStatus",
    "DecidedTier",
    "EligibilityTier",
    "MenuItemStatus",
    "MealServingStatus",
    "UsdaReimbursementClaimStatus",
    "AllergyProfileEntryStatus",
    "Allergen",
    "AllergySeverity",
    "PaidLedgerEntryType",
    "District",
    "Student",
    "ParentAccount",
    "FrlApplication",
    "MenuItem",
    "MealServingRecord",
    "UsdaReimbursementClaim",
    "AllergyProfileEntry",
    "PaidLedgerEntry",
]
