"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.5 distinguishes two common-fields shapes:

- Persisted resources carrying id + created_at + updated_at + version:
  Case, Party, FinancialDisclosure, ParentingPlan, SupportOrder,
  TemporaryOrder, FinalJudgment.
- Append-only / singleton entities: MediationSession (lightweight log;
  id + created_at only) and ServerClock (singleton with only `now`).
  PRD §2.5: "MediationSession is treated as a lightweight log; it
  carries id and created_at but does not have updated_at or version."
  PRD §2.5: "ServerClock is a singleton system entity exposing only
  the now field; it has neither updated_at nor version."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PETITIONER = "Petitioner"
    RESPONDENT = "Respondent"
    ATTORNEY_OF_RECORD = "AttorneyOfRecord"
    JUDGE = "Judge"
    MEDIATOR = "Mediator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    FILED = "FILED"
    AWAITING_ANSWER = "AWAITING_ANSWER"
    ANSWERED = "ANSWERED"
    DEFAULTED = "DEFAULTED"
    DISCLOSURE = "DISCLOSURE"
    MEDIATION = "MEDIATION"
    TEMP_ORDERED = "TEMP_ORDERED"
    AWAITING_JUDGMENT = "AWAITING_JUDGMENT"
    FINALIZED = "FINALIZED"
    DISMISSED = "DISMISSED"


class PartyRole(str, Enum):
    PETITIONER = "PETITIONER"
    RESPONDENT = "RESPONDENT"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ParentingPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    CONTESTED = "CONTESTED"
    COURT_IMPOSED = "COURT_IMPOSED"
    SUPERSEDED = "SUPERSEDED"


class LegalCustody(str, Enum):
    JOINT = "JOINT"
    PETITIONER_SOLE = "PETITIONER_SOLE"
    RESPONDENT_SOLE = "RESPONDENT_SOLE"


class PhysicalCustody(str, Enum):
    JOINT = "JOINT"
    PETITIONER_PRIMARY = "PETITIONER_PRIMARY"
    RESPONDENT_PRIMARY = "RESPONDENT_PRIMARY"


class SupportType(str, Enum):
    CHILD = "CHILD"
    SPOUSAL = "SPOUSAL"


class OrderKind(str, Enum):
    TEMPORARY = "TEMPORARY"
    FINAL = "FINAL"


class SupportOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class GuidelineModel(str, Enum):
    INCOME_SHARES = "INCOME_SHARES"
    PERCENT_OBLIGOR = "PERCENT_OBLIGOR"


class MediationSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class MediationOutcome(str, Enum):
    AGREEMENT = "AGREEMENT"
    PARTIAL = "PARTIAL"
    IMPASSE = "IMPASSE"


class TemporaryOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class FinalJudgmentStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"


class DivisionModel(str, Enum):
    COMMUNITY_PROPERTY = "COMMUNITY_PROPERTY"
    EQUITABLE_DISTRIBUTION = "EQUITABLE_DISTRIBUTION"


class JurisdictionState(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FL = "FL"
    IL = "IL"
    WA = "WA"


# ---------------------------------------------------------------------------
# Persisted entities carrying id + created_at + updated_at + version — PRD §2.5
# ---------------------------------------------------------------------------
class Case(TypedDict, total=False):
    id: str
    docket_number: str
    petitioner_party_id: str
    respondent_party_id: str
    jurisdiction_state: str
    marriage_date: str
    separation_date: str
    has_minor_children: bool
    status: str
    answer_deadline_at: str
    response_received_at: Optional[str]
    mediation_round: int
    temporary_order_id: Optional[str]
    final_judgment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    case_id: str
    role: str
    full_name: str
    date_of_birth: str
    gross_monthly_income_cents: int
    counsel_user_id: Optional[str]
    served_at: Optional[str]
    has_filed_answer: bool
    created_at: str
    updated_at: str
    version: int


class FinancialDisclosure(TypedDict, total=False):
    id: str
    case_id: str
    party_id: str
    gross_monthly_income_cents: int
    deductible_taxes_cents: int
    monthly_health_insurance_cents: int
    monthly_childcare_cents: int
    assets_total_cents: int
    debts_total_cents: int
    status: str
    rejection_reason: Optional[str]
    net_monthly_income_cents: int
    created_at: str
    updated_at: str
    version: int


class ParentingPlan(TypedDict, total=False):
    id: str
    case_id: str
    proposing_party_id: str
    legal_custody: str
    physical_custody: str
    petitioner_overnights_per_year: int
    respondent_overnights_per_year: int
    status: str
    countered_by_plan_id: Optional[str]
    pinned_petitioner_disclosure_version: Optional[int]
    pinned_respondent_disclosure_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SupportOrder(TypedDict, total=False):
    id: str
    case_id: str
    support_type: str
    order_kind: str
    parenting_plan_id: Optional[str]
    obligor_party_id: str
    obligee_party_id: str
    monthly_amount_cents: int
    guideline_model: Optional[str]
    status: str
    effective_from: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemporaryOrder(TypedDict, total=False):
    id: str
    case_id: str
    child_support_order_id: Optional[str]
    spousal_support_order_id: Optional[str]
    parenting_plan_id: Optional[str]
    status: str
    effective_from: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinalJudgment(TypedDict, total=False):
    id: str
    case_id: str
    child_support_order_id: Optional[str]
    spousal_support_order_id: Optional[str]
    parenting_plan_id: Optional[str]
    petitioner_asset_share_cents: int
    respondent_asset_share_cents: int
    division_model: str
    status: str
    effective_from: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lightweight log / singleton — id + created_at only (no updated_at, no
# version). PRD §2.5.
# ---------------------------------------------------------------------------
class MediationSession(TypedDict, total=False):
    id: str
    case_id: str
    mediator_user_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    round_index: int
    status: str
    outcome: Optional[str]
    parenting_plan_id: Optional[str]
    created_at: str


class ServerClock(TypedDict, total=False):
    now: str


__all__ = [
    "UserRole",
    "CaseStatus",
    "PartyRole",
    "DisclosureStatus",
    "ParentingPlanStatus",
    "LegalCustody",
    "PhysicalCustody",
    "SupportType",
    "OrderKind",
    "SupportOrderStatus",
    "GuidelineModel",
    "MediationSessionStatus",
    "MediationOutcome",
    "TemporaryOrderStatus",
    "FinalJudgmentStatus",
    "DivisionModel",
    "JurisdictionState",
    "Case",
    "Party",
    "FinancialDisclosure",
    "ParentingPlan",
    "SupportOrder",
    "TemporaryOrder",
    "FinalJudgment",
    "MediationSession",
    "ServerClock",
]
