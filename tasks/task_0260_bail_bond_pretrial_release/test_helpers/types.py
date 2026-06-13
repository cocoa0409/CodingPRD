"""Domain types for the Bail Bond & Pretrial Release API.

Entity TypedDicts, status enums, and the role enum. Mutable resources carry the
full id/created_at/updated_at/version set; the three append-only audit records
(Notification, CheckIn, LedgerEntry) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BONDS_AGENT = "BondsAgent"
    COURT = "Court"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RECOVERY_AGENT = "RecoveryAgent"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class DefendantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BailOrderStatus(str, Enum):
    OPEN = "OPEN"
    BONDED = "BONDED"
    RESOLVED = "RESOLVED"


class BondType(str, Enum):
    CASH = "CASH"
    SURETY = "SURETY"
    PR = "PR"


class BondTypeAllowed(str, Enum):
    CASH = "CASH"
    SURETY = "SURETY"
    PR = "PR"
    ANY = "ANY"


class BondCoverageStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FORFEITED = "FORFEITED"
    EXONERATED = "EXONERATED"
    REVOKED = "REVOKED"


class BondSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    PREMIUM_COLLECTED = "PREMIUM_COLLECTED"
    COLLATERAL_REFUNDED = "COLLATERAL_REFUNDED"
    JUDGMENT_ENTERED = "JUDGMENT_ENTERED"


class IndemnityAgreementStatus(str, Enum):
    PENDING = "PENDING"
    BINDING = "BINDING"
    DISCHARGED = "DISCHARGED"
    CALLED = "CALLED"


class CollateralKind(str, Enum):
    CASH = "CASH"
    PROPERTY_LIEN = "PROPERTY_LIEN"
    VEHICLE_TITLE = "VEHICLE_TITLE"


class CollateralStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    LIQUIDATED = "LIQUIDATED"


class CourtDateStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTIFIED = "NOTIFIED"
    APPEARED = "APPEARED"
    FAILED_TO_APPEAR = "FAILED_TO_APPEAR"
    CONTINUED = "CONTINUED"


class HearingType(str, Enum):
    ARRAIGNMENT = "ARRAIGNMENT"
    PRETRIAL = "PRETRIAL"
    TRIAL = "TRIAL"
    SENTENCING = "SENTENCING"


class NotificationChannel(str, Enum):
    SMS = "SMS"
    VOICE = "VOICE"
    EMAIL = "EMAIL"


class ConditionCode(str, Enum):
    GPS = "GPS"
    CURFEW = "CURFEW"
    DRUG_TEST = "DRUG_TEST"
    NO_CONTACT = "NO_CONTACT"


class CheckInResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MISSED = "MISSED"


class GpsDeviceStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    TAMPER = "TAMPER"
    RETURNED = "RETURNED"


class ForfeitureStatus(str, Enum):
    FORFEITED = "FORFEITED"
    RECOVERY_OPEN = "RECOVERY_OPEN"
    REINSTATED = "REINSTATED"
    JUDGMENT = "JUDGMENT"
    REMITTED = "REMITTED"


class LedgerEntryType(str, Enum):
    PREMIUM_COLLECTED = "PREMIUM_COLLECTED"
    COLLATERAL_REFUND = "COLLATERAL_REFUND"
    FORFEITURE_JUDGMENT = "FORFEITURE_JUDGMENT"
    REMISSION_CREDIT = "REMISSION_CREDIT"


# ---------------------------------------------------------------------------
# Entity TypedDicts — mutable resources (id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Defendant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    phone_e164: str
    risk_tier: str
    total_active_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BailOrder(TypedDict):
    id: str
    defendant_id: str
    case_number: str
    bail_amount_cents: int
    bond_type_allowed: str
    condition_codes: List[str]
    gps_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    bail_order_id: str
    defendant_id: str
    bond_type: str
    bail_amount_cents: int
    premium_rate_bps: int
    premium_cents: int
    premium_earned_cents: int
    required_collateral_cents: int
    collateral_held_cents: int
    coverage_status: str
    settlement_status: str
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Indemnitor(TypedDict):
    id: str
    full_name: str
    phone_e164: str
    credit_limit_cents: int
    total_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class IndemnityAgreement(TypedDict):
    id: str
    bond_id: str
    indemnitor_id: str
    liability_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralItem(TypedDict):
    id: str
    bond_id: str
    kind: str
    pledged_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtDate(TypedDict):
    id: str
    bond_id: str
    scheduled_utc: str
    duration_minutes: int
    hearing_type: str
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GpsDevice(TypedDict):
    id: str
    serial_number: str
    assigned_bond_id: Optional[str]
    violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForfeitureProceeding(TypedDict):
    id: str
    bond_id: str
    trigger_court_date_id: str
    forfeited_utc: str
    grace_deadline_utc: str
    judgment_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only audit records — id + created_at only (no updated_at, no version)
# ---------------------------------------------------------------------------
class Notification(TypedDict):
    id: str
    court_date_id: str
    channel: str
    lead_hours: int
    destination: str
    created_at: str


class CheckIn(TypedDict):
    id: str
    bond_id: str
    condition_code: str
    result: str
    occurred_utc: str
    weight: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    bond_id: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
