"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions and lifecycle state machines. Most
entities are mutable, audited resources carrying id/created_at/updated_at/version
(§2.5). The ActivityCategory is the lone exception: an immutable configuration
rulebook carrying only id and created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums (lifecycle states) ──────────────────────────────────────
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ZONING_CLEARED = "ZONING_CLEARED"
    VARIANCE_REQUIRED = "VARIANCE_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    WITHDRAWN = "WITHDRAWN"


class ZoningStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    VARIANCE_REQUIRED = "VARIANCE_REQUIRED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    REVOKED = "REVOKED"
    SURRENDERED = "SURRENDERED"


class InspectionResult(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EndorsementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    VOIDED = "VOIDED"


class EndorsementKind(str, Enum):
    LATE_HOURS = "LATE_HOURS"
    OUTDOOR_SEATING = "OUTDOOR_SEATING"
    HAZMAT_HANDLING = "HAZMAT_HANDLING"
    SIDEWALK_USE = "SIDEWALK_USE"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BusinessStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    REVOKED = "REVOKED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FeeKind(str, Enum):
    APPLICATION_FEE = "APPLICATION_FEE"
    ISSUANCE_FEE = "ISSUANCE_FEE"
    RENEWAL_FEE = "RENEWAL_FEE"
    DELINQUENCY_PENALTY = "DELINQUENCY_PENALTY"
    TRANSFER_FEE = "TRANSFER_FEE"
    REVERSAL = "REVERSAL"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    LICENSING_OFFICER = "LicensingOfficer"
    INSPECTION_OFFICER = "InspectionOfficer"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────

# common_fields: false — immutable config rulebook; ONLY id + created_at.
class ActivityCategory(TypedDict):
    id: str
    created_at: str
    code: str
    risk_tier: str
    activity_base_risk: int
    required_inspection_count: int
    requires_zoning_check: bool
    term_months: int
    allowed_zones: List[str]


# common_fields: true — id + created_at + updated_at + version.
class Business(TypedDict):
    id: str
    legal_name: str
    owner_name: str
    zone_code: str
    standing: str
    prior_revocation_flag: bool
    compliance_risk_score: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    business_id: str
    activity_category_id: str
    declared_employee_count: int
    requested_zone_code: str
    status: str
    zoning_status: str
    estimated_fee: float
    reviewed_by_user_id: Optional[str]
    license_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    application_id: str
    inspector_user_id: str
    result: str
    verified_employee_count: int
    failed_item_count: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    business_id: str
    application_id: str
    activity_category_id: str
    status: str
    issued_on: str
    expires_on: str
    final_fee: float
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    license_id: str
    kind: str
    status: str
    condition_text: str
    created_at: str
    updated_at: str
    version: int


class OwnershipTransfer(TypedDict):
    id: str
    license_id: str
    from_business_id: str
    to_business_id: str
    status: str
    transfer_fee: float
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    license_id: Optional[str]
    application_id: Optional[str]
    kind: str
    amount: float
    settled: bool
    created_at: str
    updated_at: str
    version: int
