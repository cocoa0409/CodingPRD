"""Domain types: entity TypedDicts, status enums, role enum.

Field names and status values are taken verbatim from the PRD. Entities that the
PRD describes as leaner (a Payer, a ComplianceCheck, and the ClockState carry only
``id`` and ``created_at``) deliberately omit ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class PhysicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class StateLicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class IssuanceType(str, Enum):
    FULL = "FULL"
    COMPACT_EXPEDITED = "COMPACT_EXPEDITED"


class VisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLIANCE_CLEARED = "COMPLIANCE_CLEARED"
    APPROVED_INSURANCE = "APPROVED_INSURANCE"
    APPROVED_SELF_PAY = "APPROVED_SELF_PAY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class Modality(str, Enum):
    VIDEO = "VIDEO"
    AUDIO_ONLY = "AUDIO_ONLY"


class Routing(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class ComplianceOutcome(str, Enum):
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    OVERRIDDEN = "OVERRIDDEN"


class ComplianceReasonCode(str, Enum):
    LICENSE_MATCH = "LICENSE_MATCH"
    NO_LICENSE_IN_STATE = "NO_LICENSE_IN_STATE"
    LICENSE_NOT_ACTIVE = "LICENSE_NOT_ACTIVE"
    AUDIO_ONLY_NOT_PERMITTED = "AUDIO_ONLY_NOT_PERMITTED"
    OFFICER_OVERRIDE = "OFFICER_OVERRIDE"


class DeaSchedule(str, Enum):
    NONE = "NONE"
    II = "II"
    III = "III"
    IV = "IV"
    V = "V"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class FollowUpStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class UserRole(str, Enum):
    Anonymous = "Anonymous"
    Physician = "Physician"
    Patient = "Patient"
    LicensingBoard = "LicensingBoard"
    ComplianceOfficer = "ComplianceOfficer"


# ─── Entity TypedDicts ────────────────────────────────
# common_fields: true → id + created_at + updated_at + version

class Physician(TypedDict):
    id: str
    full_name: str
    npi: str
    dea_number: Optional[str]
    imlc_eligible: bool
    home_state_code: str
    active_license_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StateLicense(TypedDict):
    id: str
    physician_id: str
    state_code: str
    issuance_type: str
    controlled_substance_authority: bool
    effective_date: str
    expiration_date: str
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    email: str
    residence_state_code: str
    insurance_payer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    physician_id: str
    patient_id: str
    modality: str
    scheduled_at: str
    determined_state_code: str
    list_fee_cents: int
    platform_fee_cents: int
    routing: Optional[str]
    patient_cost_cents: Optional[int]
    prescription_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    visit_id: str
    drug_name: str
    dea_schedule: str
    days_supply: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    visit_id: str
    payer_id: str
    billed_cents: int
    allowed_cents: Optional[int]
    plan_paid_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUp(TypedDict):
    id: str
    source_visit_id: str
    due_at: str
    linked_visit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → id + created_at only (NO updated_at, NO version)

class Payer(TypedDict):
    id: str
    name: str
    telehealth_parity: bool
    copay_cents: int
    covered_state_codes: List[str]
    allowed_amount_cents: int
    created_at: str


class ComplianceCheck(TypedDict):
    id: str
    visit_id: str
    outcome: str
    matched_license_id: Optional[str]
    reason_code: str
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
