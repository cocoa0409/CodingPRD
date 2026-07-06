"""Domain types: entity TypedDicts, status enums, role enum for the Record Expungement API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PETITIONER = "Petitioner"
    CLERK = "Clerk"
    AGENCY = "Agency"
    JUDGE = "Judge"


# ---- Field value enums ----
class OffenseClass(str, Enum):
    INFRACTION = "INFRACTION"
    MISDEMEANOR = "MISDEMEANOR"
    FELONY_CLASS_C = "FELONY_CLASS_C"
    FELONY_CLASS_B = "FELONY_CLASS_B"
    FELONY_CLASS_A = "FELONY_CLASS_A"
    VIOLENT_FELONY = "VIOLENT_FELONY"


class Disposition(str, Enum):
    CONVICTED = "CONVICTED"
    DISMISSED = "DISMISSED"
    ARREST_ONLY = "ARREST_ONLY"
    ACQUITTED = "ACQUITTED"


# ---- Status enums ----
class CriminalRecordStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SEALED = "SEALED"


class IneligibleReason(str, Enum):
    NEVER_ELIGIBLE = "NEVER_ELIGIBLE"
    WAITING_PERIOD = "WAITING_PERIOD"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENED = "SCREENED"
    FILED = "FILED"
    OBJECTION_REVIEW = "OBJECTION_REVIEW"
    HEARING_SET = "HEARING_SET"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class FeeWaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class DeterminationBasis(str, Enum):
    INCOME_UNDER_125 = "INCOME_UNDER_125"
    OVER_THRESHOLD = "OVER_THRESHOLD"


class AgencyNotificationStatus(str, Enum):
    PENDING = "PENDING"
    SERVED = "SERVED"
    OBJECTED = "OBJECTED"
    CLEARED = "CLEARED"


class AgencyType(str, Enum):
    DA = "DA"
    ARRESTING_AGENCY = "ARRESTING_AGENCY"
    STATE_REPOSITORY = "STATE_REPOSITORY"


class ObjectionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    VACATED = "VACATED"
    SUPERSEDED = "SUPERSEDED"


class CourtOrderStatus(str, Enum):
    ENTERED = "ENTERED"
    DISTRIBUTED = "DISTRIBUTED"
    VACATED = "VACATED"


class CourtOrderDisposition(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class SealingDistributionStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RecipientType(str, Enum):
    DA = "DA"
    ARRESTING_AGENCY = "ARRESTING_AGENCY"
    STATE_REPOSITORY = "STATE_REPOSITORY"
    BACKGROUND_VENDOR = "BACKGROUND_VENDOR"


# ---- Entity TypedDicts ----
# common_fields: true -> id + created_at + updated_at + version
class Petitioner(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    annual_income_cents: int
    household_size: int
    monthly_liquid_assets_cents: int
    fee_paid_cents: int
    fee_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class CriminalRecord(TypedDict):
    id: str
    petitioner_id: str
    offense_code: str
    offense_class: str
    disposition: str
    disposition_date: str
    sentence_completion_date: Optional[str]
    status: str
    eligible_on: Optional[str]
    ineligible_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict):
    id: str
    petitioner_id: str
    jurisdiction_code: str
    status: str
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    amount_paid_cents: int
    fee_due_cents: Optional[int]
    fee_waived: bool
    created_at: str
    updated_at: str
    version: int


class FeeWaiver(TypedDict):
    id: str
    petitioner_id: str
    petition_id: str
    status: str
    determination_basis: str
    income_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class AgencyNotification(TypedDict):
    id: str
    petition_id: str
    agency_type: str
    status: str
    served_at: Optional[str]
    objection_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict):
    id: str
    notification_id: str
    grounds: str
    status: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    petition_id: str
    courtroom_id: str
    judge_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtOrder(TypedDict):
    id: str
    petition_id: str
    hearing_id: str
    disposition: str
    status: str
    entered_at: str
    created_at: str
    updated_at: str
    version: int


class SealingDistribution(TypedDict):
    id: str
    court_order_id: str
    recipient_type: str
    recipient_ref: str
    status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class Courtroom(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    created_at: str


class Judge(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    created_at: str


class BackgroundVendor(TypedDict):
    id: str
    name: str
    api_endpoint: str
    records_updated_count: int
    created_at: str


class PetitionItem(TypedDict):
    id: str
    petition_id: str
    record_id: str
    eligibility_at_screening: Optional[str]
    fee_at_screening_cents: Optional[int]
    created_at: str
