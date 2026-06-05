"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD (Family Court Divorce API).
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------
# Role enum (PRD §2.1: Clerk, Judge, Mediator, Petitioner, Respondent)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CLERK = "Clerk"
    JUDGE = "Judge"
    MEDIATOR = "Mediator"
    PETITIONER = "Petitioner"
    RESPONDENT = "Respondent"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CaseStatus(str, Enum):
    FILED = "FILED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"
    DEFAULT_PENDING = "DEFAULT_PENDING"
    CONTESTED = "CONTESTED"
    DISCOVERY = "DISCOVERY"
    MEDIATION = "MEDIATION"
    AWAITING_JUDGMENT = "AWAITING_JUDGMENT"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"
    DISMISSED = "DISMISSED"


class PleadingType(str, Enum):
    PETITION = "PETITION"
    ANSWER = "ANSWER"


class PleadingStatus(str, Enum):
    DRAFT = "DRAFT"
    SERVED = "SERVED"
    ANSWERED = "ANSWERED"


class PartyRole(str, Enum):
    PETITIONER = "PETITIONER"
    RESPONDENT = "RESPONDENT"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    RETURNED = "RETURNED"


class ParentingPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    REVISED = "REVISED"
    AGREED = "AGREED"
    ADOPTED = "ADOPTED"


class MediationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    PARTIAL_AGREEMENT = "PARTIAL_AGREEMENT"
    FULL_AGREEMENT = "FULL_AGREEMENT"
    IMPASSE = "IMPASSE"


class MediationOutcome(str, Enum):
    PARTIAL_AGREEMENT = "PARTIAL_AGREEMENT"
    FULL_AGREEMENT = "FULL_AGREEMENT"
    IMPASSE = "IMPASSE"


class SupportType(str, Enum):
    CHILD = "CHILD"
    SPOUSAL = "SPOUSAL"


class SupportVariant(str, Enum):
    TEMPORARY = "TEMPORARY"
    FINAL = "FINAL"


class SupportOrderStatus(str, Enum):
    CALCULATED = "CALCULATED"
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"


class OrderKind(str, Enum):
    TEMPORARY = "TEMPORARY"
    FINAL_JUDGMENT = "FINAL_JUDGMENT"


class CourtOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ENTERED = "ENTERED"
    SUPERSEDED = "SUPERSEDED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------

# GuidelineSchedule — immutable config (PRD §2.4): only id + created_at, no
# updated_at, no version.
class GuidelineSchedule(TypedDict, total=False):
    id: str
    created_at: str
    state_code: str
    basic_obligation_tiers: List[dict]
    spousal_payor_pct: float
    spousal_payee_offset_pct: float
    shared_custody_threshold_pct: float
    long_marriage_months: int


# Case — carries id + created_at + updated_at + version (PRD §2.4)
class Case(TypedDict, total=False):
    id: str
    state_code: str
    caption: str
    marriage_months: int
    filing_fee_cents: int
    status: str
    mediator_user_id: Optional[str]
    judge_user_id: Optional[str]
    active_support_total_cents: int
    net_fees_collected_cents: int
    petitioner_disclosure_verified: bool
    respondent_disclosure_verified: bool
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    case_id: str
    role: str
    user_id: str
    full_name: str
    gross_monthly_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict, total=False):
    id: str
    case_id: str
    full_name: str
    birth_year: int
    created_at: str
    updated_at: str
    version: int


class Pleading(TypedDict, total=False):
    id: str
    case_id: str
    pleading_type: str
    filed_by_party_id: str
    status: str
    served_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialDisclosure(TypedDict, total=False):
    id: str
    party_id: str
    case_id: str
    gross_monthly_income_cents: int
    tax_withholding_cents: int
    mandatory_retirement_cents: int
    health_insurance_cents: int
    net_monthly_income_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ParentingPlan(TypedDict, total=False):
    id: str
    case_id: str
    proposed_by_party_id: str
    petitioner_overnights: int
    respondent_overnights: int
    petitioner_time_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict, total=False):
    id: str
    case_id: str
    mediator_user_id: str
    scheduled_start: str
    scheduled_end: str
    round_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupportOrder(TypedDict, total=False):
    id: str
    case_id: str
    support_type: str
    payor_party_id: str
    payee_party_id: str
    variant: str
    monthly_amount_cents: int
    support_term_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtOrder(TypedDict, total=False):
    id: str
    case_id: str
    order_kind: str
    support_order_ids: List[str]
    parenting_plan_id: Optional[str]
    supersedes_order_id: Optional[str]
    status: str
    entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    case_id: str
    courtroom_code: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
