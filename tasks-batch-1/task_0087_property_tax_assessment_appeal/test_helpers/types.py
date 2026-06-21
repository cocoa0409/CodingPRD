"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD (Property Tax Assessment & Appeal).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    ASSESSOR = "Assessor"
    REVIEWER = "Reviewer"
    HEARING_OFFICER = "HearingOfficer"
    TAXPAYER = "Taxpayer"
    ANONYMOUS = "Anonymous"


# --- Status enums ----------------------------------------------------------
class TaxRollStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CERTIFIED = "CERTIFIED"
    CLOSED = "CLOSED"


class ParcelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    NOTICED = "NOTICED"
    UNDER_APPEAL = "UNDER_APPEAL"
    FINAL = "FINAL"


class ExemptionStatus(str, Enum):
    CLAIMED = "CLAIMED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExemptionType(str, Enum):
    HOMESTEAD = "HOMESTEAD"
    SENIOR = "SENIOR"
    VETERAN = "VETERAN"
    DISABILITY = "DISABILITY"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    SETTLED = "SETTLED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class DeferralAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    DEFAULTED = "DEFAULTED"


class ReassessmentEvent(str, Enum):
    NONE = "NONE"
    SALE = "SALE"
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"


class TaxBillStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    DEFERRED = "DEFERRED"


# --- Entity TypedDicts -----------------------------------------------------
# All common_fields:true entities carry id, created_at, updated_at, version.

class TaxRoll(TypedDict):
    id: str
    tax_year: int
    mill_rate: float
    growth_cap_pct: float
    prior_roll_id: Optional[str]
    senior_age_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    full_name: str
    email: str
    birth_date: str
    is_veteran: bool
    disability_pct: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    owner_id: str
    apn: str
    situs_address: str
    is_primary_residence: bool
    last_certified_capped_base: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    parcel_id: str
    tax_roll_id: str
    market_value: float
    reassessment_event: str
    capped_base_value: float
    assessed_value: float
    exemption_total: float
    taxable_value: float
    appealed_value: Optional[float]
    final_taxable_value: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Exemption(TypedDict):
    id: str
    assessment_id: str
    exemption_type: str
    claimed_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    assessment_id: str
    filed_by_owner_id: str
    requested_taxable_value: float
    opinion_of_value: float
    round_no: int
    determined_taxable_value: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardPanel(TypedDict):
    id: str
    name: str
    setup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    appeal_id: str
    board_panel_id: str
    hearing_officer_role_user_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeferralAgreement(TypedDict):
    id: str
    parcel_id: str
    owner_id: str
    annual_interest_rate: float
    deferred_principal_cents: int
    accrued_interest_cents: int
    outstanding_balance_cents: int
    total_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxBill(TypedDict):
    id: str
    assessment_id: str
    billed_taxable_value: float
    tax_amount_cents: int
    is_deferred: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields:false — append-only immutable event: id + created_at only.
class DeferralPayment(TypedDict):
    id: str
    deferral_agreement_id: str
    amount_cents: int
    applied_to_interest_cents: int
    applied_to_principal_cents: int
    created_at: str
