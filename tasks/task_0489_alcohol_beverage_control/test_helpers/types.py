"""Domain types: entity TypedDicts, status enums, role enum.

All field names are PRD-exact. Every entity in this domain is mutable and carries
the common fields id / created_at / updated_at / version (PRD section 2.4 states
there are no immutable, version-less entities here).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ───────────────────────────────────────────────────────────
class UserRole(str, Enum):
    DIRECTOR = "Director"
    LICENSING_EXAMINER = "LicensingExaminer"
    ZONING_OFFICER = "ZoningOfficer"
    ADJUDICATION_OFFICER = "AdjudicationOfficer"
    INVESTIGATOR = "Investigator"
    APPLICANT = "Applicant"
    ANONYMOUS = "Anonymous"


# ─── Status enums ────────────────────────────────────────────────────────
class LicenseApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PROTEST_PERIOD = "PROTEST_PERIOD"
    PROTEST_HEARING = "PROTEST_HEARING"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class BackgroundCheckResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ZoningReviewResult(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    VARIANCE_GRANTED = "VARIANCE_GRANTED"
    BLOCKED = "BLOCKED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    SCHEDULED = "SCHEDULED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    WITHDRAWN = "WITHDRAWN"


class HearingOutcome(str, Enum):
    PENDING = "PENDING"
    PROTEST_SUSTAINED = "PROTEST_SUSTAINED"
    PROTEST_OVERRULED = "PROTEST_OVERRULED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ServerPermitStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ViolationStatus(str, Enum):
    ALLEGED = "ALLEGED"
    CONTESTED = "CONTESTED"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"


class AdministrativeActionType(str, Enum):
    FINE = "FINE"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class TransferRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PremiseType(str, Enum):
    ON_PREMISE = "ON_PREMISE"
    OFF_PREMISE = "OFF_PREMISE"
    MANUFACTURER = "MANUFACTURER"


class ZoningDistrict(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MIXED_USE = "MIXED_USE"
    RESIDENTIAL = "RESIDENTIAL"
    INDUSTRIAL = "INDUSTRIAL"


class ProtestGrounds(str, Enum):
    PUBLIC_NUISANCE = "PUBLIC_NUISANCE"
    OVER_CONCENTRATION = "OVER_CONCENTRATION"
    ZONING = "ZONING"
    MORAL_CHARACTER = "MORAL_CHARACTER"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    EGREGIOUS = "EGREGIOUS"


class ComplianceTier(str, Enum):
    SUPPLIER = "SUPPLIER"
    WHOLESALER = "WHOLESALER"
    RETAILER = "RETAILER"


class TransferType(str, Enum):
    OWNERSHIP = "OWNERSHIP"
    LOCATION = "LOCATION"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ───────
class LicenseClass(TypedDict):
    id: str
    code: str
    premise_type: str
    quota_managed: bool
    base_fee_cents: int
    renewal_cycle_months: int
    requires_zoning: bool
    max_servers_per_license: int
    created_at: str
    updated_at: str
    version: int


class QuotaRegion(TypedDict):
    id: str
    region_code: str
    population: int
    persons_per_license: int
    moratorium: bool
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    legal_name: str
    disqualified: bool
    felony_flag: bool
    created_at: str
    updated_at: str
    version: int


class Premise(TypedDict):
    id: str
    applicant_id: str
    region_code: str
    street_address: str
    distance_to_school_m: int
    zoning_district: str
    created_at: str
    updated_at: str
    version: int


class LicenseApplication(TypedDict):
    id: str
    applicant_id: str
    premise_id: str
    license_class_code: str
    status: str
    submitted_at: Optional[str]
    protest_period_ends_at: Optional[str]
    fee_quoted_cents: Optional[int]
    fee_paid_cents: int
    quota_slot_held: bool
    background_check_id: Optional[str]
    zoning_review_id: Optional[str]
    examiner_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    result: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ZoningReview(TypedDict):
    id: str
    application_id: str
    premise_id: str
    result: str
    buffer_satisfied: bool
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    application_id: str
    protester_name: str
    grounds: str
    status: str
    hearing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    application_id: str
    room_code: str
    starts_at: str
    ends_at: str
    outcome: str
    officer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    application_id: str
    license_class_code: str
    region_code: str
    status: str
    term_start_at: str
    term_end_at: str
    renewal_window_opens_at: str
    renewal_count: int
    demerit_points: int
    active_server_count: int
    outstanding_fine_cents: int
    created_at: str
    updated_at: str
    version: int


class ServerPermit(TypedDict):
    id: str
    license_id: str
    holder_name: str
    status: str
    training_completed: bool
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    license_id: str
    investigator_user_id: str
    severity: str
    status: str
    action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdministrativeAction(TypedDict):
    id: str
    violation_id: str
    license_id: str
    action_type: str
    fine_cents: int
    fine_paid_cents: int
    suspension_days: int
    adjudicator_user_id: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    license_id: str
    tier: str
    period_code: str
    gross_sales_cents: int
    excise_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    license_id: str
    transfer_type: str
    new_applicant_id: Optional[str]
    new_premise_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
