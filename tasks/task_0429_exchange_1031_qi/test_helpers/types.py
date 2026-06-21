"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD verbatim. Entities carrying the full system field
set (id, created_at, updated_at, version) are distinguished from the lone
append-only entity (IdentifiedProperty) which carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ── Enums ────────────────────────────────────────────────────────────

class ExchangeType(str, Enum):
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"
    IMPROVEMENT = "IMPROVEMENT"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    IDENTIFIED = "IDENTIFIED"
    AT_RISK = "AT_RISK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExchangeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"


class IdentificationMethod(str, Enum):
    THREE_PROPERTY = "THREE_PROPERTY"
    TWO_HUNDRED_PCT = "TWO_HUNDRED_PCT"


class IdentificationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REVOKED = "REVOKED"


class IdentifiedPropertyStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACQUIRED = "ACQUIRED"
    WITHDRAWN = "WITHDRAWN"


class DisbursementPurpose(str, Enum):
    QI_FEE = "QI_FEE"
    ACQUISITION = "ACQUISITION"
    IMPROVEMENT_DRAW = "IMPROVEMENT_DRAW"
    BOOT_RETURN = "BOOT_RETURN"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    QI_COORDINATOR = "QICoordinator"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    EXCHANGER = "Exchanger"


# Disbursement priority buckets derived from purpose.
DISBURSEMENT_PRIORITY = {
    "QI_FEE": 1,
    "ACQUISITION": 2,
    "IMPROVEMENT_DRAW": 3,
    "BOOT_RETURN": 4,
}


# ── Entity TypedDicts (full system-field set) ────────────────────────

class Exchanger(TypedDict):
    id: str
    legal_name: str
    taxpayer_id: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Exchange(TypedDict):
    id: str
    exchanger_id: str
    exchange_type: str
    compliance_posture: Optional[str]
    status: str
    relinquished_closing_at: Optional[str]
    id_deadline_at: Optional[str]
    exchange_deadline_at: Optional[str]
    realized_gain: Optional[float]
    recognized_gain: Optional[float]
    deferred_gain: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RelinquishedProperty(TypedDict):
    id: str
    exchange_id: str
    address: str
    fair_market_value: float
    selling_expenses: float
    mortgage_payoff: float
    adjusted_basis: float
    net_proceeds: float
    created_at: str
    updated_at: str
    version: int


class QualifiedTrust(TypedDict):
    id: str
    exchange_id: str
    deposited_amount: float
    available_balance: float
    is_locked: bool
    created_at: str
    updated_at: str
    version: int


class Identification(TypedDict):
    id: str
    exchange_id: str
    method: str
    status: str
    aggregate_identified_fmv: float
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplacementProperty(TypedDict):
    id: str
    exchange_id: str
    identified_property_id: str
    purchase_price: float
    replacement_debt: float
    improvement_value: float
    cash_applied: float
    acquired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    exchange_id: str
    replacement_property_id: Optional[str]
    purpose: str
    priority: int
    amount: float
    settlement_status: str
    settlement_officer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Append-only entity (common_fields: false) ────────────────────────
# IdentifiedProperty carries ONLY id and created_at — no updated_at, no version.

class IdentifiedProperty(TypedDict):
    id: str
    identification_id: str
    description: str
    estimated_fmv: float
    status: str
    created_at: str
