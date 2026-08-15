"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------- Role ----------

class UserRole(str, Enum):
    SITE_MANAGER = "SiteManager"
    FARM_OWNER = "FarmOwner"
    CERTIFIED_APPLICATOR = "CertifiedApplicator"
    SAFETY_OFFICER = "SafetyOfficer"


# ---------- Crop / grade / product enums ----------

class Crop(str, Enum):
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    WHEAT = "WHEAT"


class Grade(str, Enum):
    GRADE_1 = "GRADE_1"
    GRADE_2 = "GRADE_2"
    GRADE_3 = "GRADE_3"


class FumigationProduct(str, Enum):
    PHOSPHINE = "PHOSPHINE"
    SULFURYL_FLUORIDE = "SULFURYL_FLUORIDE"


# ---------- Entity status enums ----------

class BinPosture(str, Enum):
    SOUND = "SOUND"
    WATCH = "WATCH"
    ALERT = "ALERT"
    FUMIGATION_LOCKOUT = "FUMIGATION_LOCKOUT"


class LotStatus(str, Enum):
    STORED = "STORED"
    PARTIALLY_DRAWN = "PARTIALLY_DRAWN"
    SUSPENDED = "SUSPENDED"
    DEPLETED = "DEPLETED"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CONFIRMED_LOSS = "CONFIRMED_LOSS"


class FumigationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    DELIVERING = "DELIVERING"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"


class TransportStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class ValuationClause(str, Enum):
    SPOT = "SPOT"
    CONTRACT_AVG = "CONTRACT_AVG"


class ShrinkEventKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    INVISIBLE_LOSS = "INVISIBLE_LOSS"


class CarryVariant(str, Enum):
    CASH = "CASH"
    ECONOMIC = "ECONOMIC"


class CarryRecommendation(str, Enum):
    HOLD = "HOLD"
    SELL = "SELL"


# ---------- Entity TypedDicts ----------

# common_fields: true -> id + created_at + updated_at + version
class Bin(TypedDict, total=False):
    id: str
    name: str
    capacity_bu: float
    crop: str
    current_inventory_bu: float
    risk_score: float
    posture: str
    insect_activity: bool
    last_reading_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrainLot(TypedDict, total=False):
    id: str
    bin_id: str
    crop: str
    grade: str
    fill_date: str
    original_bu: float
    fill_moisture_pct: float
    fill_basis_cents: int
    reference_price_cents_per_bu: int
    current_moisture_pct: float
    provisional_shrink_bu: float
    current_bu: float
    drawn_bu: float
    cumulative_invisible_loss_bu: float
    cumulative_storage_charge_cents: int
    months_assessed: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY (append-only event log)
class TemperatureReading(TypedDict, total=False):
    id: str
    bin_id: str
    recorded_at: str
    ambient_temp_f: float
    cable_temps_f: List[float]
    insect_activity: bool
    max_cable_temp_f: float
    temp_delta_f: float
    hotspot_triggered: bool
    score_after: float
    created_at: str


class SpoilageAlert(TypedDict, total=False):
    id: str
    bin_id: str
    reading_id: str
    source: str
    status: str
    loss_bu: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FumigationRecord(TypedDict, total=False):
    id: str
    bin_id: str
    applicator_id: str
    product: str
    application_start: str
    application_end: str
    lockout_until: str
    status: str
    cleared_at: Optional[str]
    cleared_by_applicator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BinEntryPermit(TypedDict, total=False):
    id: str
    bin_id: str
    planned_start: str
    planned_end: str
    atmosphere_test_passed: bool
    loto_confirmed: bool
    requester_user_id: str
    approver_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageContract(TypedDict, total=False):
    id: str
    crop: str
    contracted_bu: float
    window_start: str
    window_end: str
    basis_cents_per_bu: int
    futures_ref_cents_per_bu: int
    early_bonus_cents_per_bu: int
    early_cutoff: Optional[str]
    contract_unit_price_cents: int
    committed_bu: float
    delivered_bu: float
    settled_value_cents: int
    fulfillment_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict, total=False):
    ticket_no: str
    gross_bu: float
    moisture_pct: float


class LoadOut(TypedDict, total=False):
    id: str
    contract_id: str
    bin_id: str
    scheduled_start: str
    scheduled_end: str
    planned_bu: float
    transport_status: str
    settlement_status: str
    scale_tickets: List[ScaleTicket]
    delivered_at: Optional[str]
    gross_bu: Optional[float]
    ticket_shrink_bu: Optional[float]
    settled_net_bu: Optional[float]
    grain_value_cents: Optional[int]
    service_fee_cents: Optional[int]
    early_bonus_cents: Optional[int]
    settlement_net_cents: Optional[int]
    draws: List[Any]
    held_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicator(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    cert_expires_at: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    crop: str
    coverage_limit_cents: int
    deductible_cents: int
    valuation_clause: str
    period_start: str
    period_end: str
    remaining_coverage_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    policy_id: str
    spoilage_alert_id: str
    loss_bu: float
    unit_value_cents: Optional[float]
    gross_indemnity_cents: Optional[int]
    indemnity_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at ONLY
class StorageAssessment(TypedDict, total=False):
    id: str
    period: str
    lots_assessed: int
    total_storage_charge_cents: int
    total_invisible_loss_bu: float
    contracts_defaulted: int
    contracts_fulfilled: int
    permits_expired: int
    loadouts_expired: int
    policies_expired: int
    created_at: str


# common_fields: false -> id + created_at ONLY
class ShrinkEvent(TypedDict, total=False):
    id: str
    lot_id: str
    kind: str
    shrink_bu: float
    period: Optional[str]
    created_at: str
