"""Domain types: entity TypedDicts, status enums, role enum for the Massage Therapy Practice API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PRACTICE_ADMIN = "PracticeAdmin"
    FRONT_DESK = "FrontDesk"
    THERAPIST = "Therapist"
    CLIENT = "Client"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"


class CommissionScheme(str, Enum):
    FLAT = "FLAT"
    TIERED = "TIERED"


class CertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DrapingPolicy(str, Enum):
    FULL_DRAPE = "FULL_DRAPE"
    PARTIAL_DRAPE = "PARTIAL_DRAPE"
    DECLINE_TREATMENT = "DECLINE_TREATMENT"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class LedgerReason(str, Enum):
    GRANT = "GRANT"
    ROLLOVER_FORFEIT = "ROLLOVER_FORFEIT"
    REDEEM = "REDEEM"
    REFUND = "REFUND"
    EXPIRE = "EXPIRE"


class Payer(str, Enum):
    CASH = "CASH"
    HSA = "HSA"
    MEMBERSHIP = "MEMBERSHIP"


class SchedulingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    PRICED = "PRICED"
    PAID = "PAID"
    VOID = "VOID"


class CancelReason(str, Enum):
    CLIENT_REQUEST = "CLIENT_REQUEST"
    LATE_CANCEL = "LATE_CANCEL"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    PRACTICE_CANCEL = "PRACTICE_CANCEL"


class NoteStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class SuperbillStatus(str, Enum):
    ISSUED = "ISSUED"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Modality(TypedDict):
    id: str
    name: str
    code: str
    requires_certification: bool
    base_price_cents: int
    contraindication_tags: List[str]
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict):
    id: str
    full_name: str
    license_number: str
    license_expiry: str
    license_status: str
    commission_scheme: str
    flat_commission_pct: float
    accrued_commission_cents: int
    mtd_service_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class TherapistCertification(TypedDict):
    id: str
    therapist_id: str
    modality_code: str
    cert_status: str
    cert_expiry: str
    created_at: str
    updated_at: str
    version: int


class Table(TypedDict):
    id: str
    label: str
    room: str
    turnover_buffer_minutes: int
    supports_prenatal: bool
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    hsa_balance_cents: int
    wallet_credit_cents: int
    no_show_strikes: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Intake(TypedDict):
    id: str
    client_id: str
    risk_flags: List[str]
    intake_status: str
    signed_at: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    client_id: str
    draping_policy: str
    sensitive_area_consent: bool
    consent_status: str
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    name: str
    monthly_fee_cents: int
    included_sessions: int
    member_discount_pct: float
    rollover_cap_sessions: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    client_id: str
    plan_id: str
    credit_balance_sessions: int
    cycle_anchor_day: int
    current_cycle_end: str
    package_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, carries ONLY id + created_at (no updated_at, no version)
class CreditLedgerEntry(TypedDict):
    id: str
    package_id: str
    delta_sessions: int
    reason: str
    balance_after: int
    created_at: str


class CommissionTier(TypedDict):
    id: str
    tier_index: int
    floor_revenue_cents: int
    commission_pct: float
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    client_id: str
    therapist_id: str
    table_id: str
    modality_id: str
    consent_id: str
    package_id: Optional[str]
    start_at: str
    duration_minutes: int
    end_at: str
    payer: str
    gratuity_cents: int
    scheduling_status: str
    settlement_status: str
    service_charge_cents: int
    client_owed_cents: int
    commission_credited_cents: int
    no_show_fee_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SoapNote(TypedDict):
    id: str
    appointment_id: str
    subjective: str
    objective: str
    assessment: str
    plan: str
    clears_contraindication_tags: List[str]
    note_status: str
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict):
    id: str
    appointment_id: str
    client_id: str
    diagnosis_codes: List[str]
    cpt_code: str
    billable_amount_cents: int
    superbill_status: str
    created_at: str
    updated_at: str
    version: int
