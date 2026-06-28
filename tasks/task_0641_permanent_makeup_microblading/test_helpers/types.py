"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Permanent Makeup Studio PRD. Entities that carry the common
mutable fields (id, created_at, updated_at, version) are distinguished from the
append-only audit records (ConsentRecord, DepositTransaction, HealingLog) which
carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ------------------------------------------------------
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    FRONT_DESK = "FrontDesk"
    TECHNICIAN = "Technician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums --------------------------------------------------------------
class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class LicenseStatus(str, Enum):
    LICENSE_ACTIVE = "LICENSE_ACTIVE"
    LICENSE_SUSPENDED = "LICENSE_SUSPENDED"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"


class RiskBand(str, Enum):
    STANDARD = "STANDARD"
    HIGH_RISK = "HIGH_RISK"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ConsentType(str, Enum):
    PROCEDURE_CONSENT = "PROCEDURE_CONSENT"
    MEDICAL_DISCLOSURE = "MEDICAL_DISCLOSURE"
    PHOTO_RELEASE = "PHOTO_RELEASE"


class PatchTestStatus(str, Enum):
    APPLIED = "APPLIED"
    READ = "READ"
    VOIDED = "VOIDED"


class PatchTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ProcedureType(str, Enum):
    BROWS = "BROWS"
    EYELINER = "EYELINER"
    LIP_BLUSH = "LIP_BLUSH"


class AppointmentKind(str, Enum):
    INITIAL = "INITIAL"
    TOUCH_UP = "TOUCH_UP"
    ANNUAL_REFRESH = "ANNUAL_REFRESH"
    REDO = "REDO"


class LifecycleStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROCEDURE = "IN_PROCEDURE"
    HEALING = "HEALING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    BALANCE_DUE = "BALANCE_DUE"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class HealingOutcome(str, Enum):
    GOOD = "GOOD"
    POOR = "POOR"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class PricingMode(str, Enum):
    PAYG = "PAYG"
    BUNDLE = "BUNDLE"


class TxnType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"


class RedoStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"


# --- Entities carrying id + created_at + updated_at + version -------------------
class Studio(TypedDict):
    id: str
    name: str
    state_code: str
    min_client_age: int
    sterile_kit_total: int
    sterile_kit_consumed: int
    sterile_kit_available: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    studio_id: str
    full_name: str
    license_number: str
    bbp_cert_expiry: str
    license_expiry: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    studio_id: str
    full_name: str
    date_of_birth: str
    medical_flag_count: int
    prior_adverse_reactions: int
    skin_sensitivity_self: int
    skin_sensitivity_observed: Optional[int]
    risk_score: int
    risk_band: str
    medical_cleared: bool
    no_show_strikes: int
    client_status: str
    created_at: str
    updated_at: str
    version: int


class PatchTest(TypedDict):
    id: str
    client_id: str
    applied_at: str
    read_at: Optional[str]
    status: str
    reaction_grade: Optional[int]
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ColorFormula(TypedDict):
    id: str
    studio_id: str
    name: str
    procedure_type: str
    pigment_count: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    client_id: str
    technician_id: str
    color_formula_id: str
    patch_test_id: str
    procedure_type: str
    appointment_kind: str
    is_corrective: bool
    scheduled_start: str
    lifecycle_status: str
    payment_status: str
    session_price_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    balance_due_cents: int
    kit_consumed: bool
    healing_outcome: Optional[str]
    completed_at: Optional[str]
    parent_appointment_id: Optional[str]
    package_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageOrder(TypedDict):
    id: str
    client_id: str
    source_appointment_id: str
    included_sessions: int
    remaining_sessions: int
    pricing_mode: str
    package_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RedoRequest(TypedDict):
    id: str
    appointment_id: str
    reason: str
    status: str
    redo_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only audit records: ONLY id + created_at ---------------------------
class ConsentRecord(TypedDict):
    id: str
    client_id: str
    consent_type: str
    age_verified: bool
    signed_by_name: str
    created_at: str


class DepositTransaction(TypedDict):
    id: str
    appointment_id: str
    txn_type: str
    amount_cents: int
    created_at: str


class HealingLog(TypedDict):
    id: str
    appointment_id: str
    day_offset: int
    outcome_flag: str
    notes: Optional[str]
    created_at: str
