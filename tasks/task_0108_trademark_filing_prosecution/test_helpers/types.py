"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle states. NiceClass is an
immutable reference record (id + created_at only); every other entity carries
the standard id/created_at/updated_at/version property set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    ATTORNEY = "Attorney"
    EXAMINER = "Examiner"
    TTAB_CLERK = "TTABClerk"


# ─── Status / enum value sets ─────────────────────────────────────────────
class ApplicantEntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    LLC = "LLC"


class AttorneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    OFFICE_ACTION_ISSUED = "OFFICE_ACTION_ISSUED"
    PUBLISHED = "PUBLISHED"
    ALLOWED = "ALLOWED"
    ABANDONED = "ABANDONED"
    REGISTERED = "REGISTERED"


class FilingBasis(str, Enum):
    USE = "USE"
    INTENT = "INTENT"


class FilingTier(str, Enum):
    TEAS_PLUS = "TEAS_PLUS"
    TEAS_STANDARD = "TEAS_STANDARD"


class GoodsServicesUseStatus(str, Enum):
    NOT_IN_USE = "NOT_IN_USE"
    IN_USE = "IN_USE"


class OfficeActionGround(str, Enum):
    LIKELIHOOD_OF_CONFUSION = "LIKELIHOOD_OF_CONFUSION"
    MERELY_DESCRIPTIVE = "MERELY_DESCRIPTIVE"
    SPECIMEN_DEFECT = "SPECIMEN_DEFECT"
    IDENTIFICATION_INDEFINITE = "IDENTIFICATION_INDEFINITE"


class OfficeActionStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class StatementOfUseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class ProceedingType(str, Enum):
    OPPOSITION = "OPPOSITION"
    CANCELLATION = "CANCELLATION"


class ClaimStatus(str, Enum):
    PLEADED = "PLEADED"
    TRIAL = "TRIAL"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class DefenseStatus(str, Enum):
    AWAITING_ANSWER = "AWAITING_ANSWER"
    ANSWERED = "ANSWERED"
    DEFAULTED = "DEFAULTED"


class RegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MaintenanceFilingType(str, Enum):
    SECTION_8 = "SECTION_8"
    SECTION_8_AND_9 = "SECTION_8_AND_9"


class MaintenanceFilingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class MadridStatus(str, Enum):
    PENDING_CERTIFICATION = "PENDING_CERTIFICATION"
    CERTIFIED = "CERTIFIED"
    FORWARDED_TO_WIPO = "FORWARDED_TO_WIPO"
    CEASED = "CEASED"


class DocketSubjectType(str, Enum):
    OFFICE_ACTION = "OFFICE_ACTION"
    OPPOSITION_ANSWER = "OPPOSITION_ANSWER"
    SOU = "SOU"
    MAINTENANCE = "MAINTENANCE"
    OPPOSITION_WINDOW = "OPPOSITION_WINDOW"


class DocketStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class TTabDecision(str, Enum):
    SUSTAIN = "SUSTAIN"
    DISMISS = "DISMISS"


# ─── Entity TypedDicts (carry id/created_at/updated_at/version) ────────────
class Applicant(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    country_code: str
    is_foreign_domiciled: bool
    open_application_count: int
    created_at: str
    updated_at: str
    version: int


class Attorney(TypedDict):
    id: str
    full_name: str
    bar_number: str
    bar_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrademarkApplication(TypedDict):
    id: str
    applicant_id: str
    attorney_id: Optional[str]
    mark_text: str
    filing_basis: str
    filing_tier: str
    status: str
    class_count: int
    filing_fee_cents: int
    office_action_round: int
    filed_at: Optional[str]
    published_at: Optional[str]
    notice_of_allowance_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GoodsServicesItem(TypedDict):
    id: str
    application_id: str
    nice_class_id: str
    description: str
    pre_approved: bool
    use_status: str
    created_at: str
    updated_at: str
    version: int


class OfficeAction(TypedDict):
    id: str
    application_id: str
    round_number: int
    is_final: bool
    ground: str
    issued_at: str
    response_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficeActionResponse(TypedDict):
    id: str
    office_action_id: str
    argument_text: str
    amends_identification: bool
    submitted_at: str
    days_late: int
    created_at: str
    updated_at: str
    version: int


class StatementOfUse(TypedDict):
    id: str
    application_id: str
    specimen_url: str
    first_use_date: str
    extension_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TTABProceeding(TypedDict):
    id: str
    proceeding_type: str
    target_application_id: Optional[str]
    target_registration_id: Optional[str]
    petitioner_applicant_id: str
    claim_status: str
    defense_status: str
    filed_at: str
    answer_deadline: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    application_id: str
    registration_number: str
    registered_at: str
    status: str
    maintenance_cycle: int
    next_maintenance_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceFiling(TypedDict):
    id: str
    registration_id: str
    filing_type: str
    filed_at: str
    in_grace_period: bool
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MadridApplication(TypedDict):
    id: str
    basic_application_id: str
    designated_countries: List[str]
    status: str
    dependency_end_at: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class DocketDeadline(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    application_id: Optional[str]
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable reference record (id + created_at only) ────────────────────
class NiceClass(TypedDict):
    id: str
    class_number: int
    title: str
    is_service_class: bool
    created_at: str
