"""Domain types: entity record shapes, status enums, and the role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ──────────────────────────────────────────────
class UserRole(str, Enum):
    SALVAGE_MASTER = "SalvageMaster"
    CONTRACTS_OFFICER = "ContractsOfficer"
    MARINE_SURVEYOR = "MarineSurveyor"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    OPERATIONS_DIRECTOR = "OperationsDirector"
    ARBITRATOR = "Arbitrator"
    INSURER_SURVEYOR = "InsurerSurveyor"


# ─── Field enums ────────────────────────────────────────
class CasualtyType(str, Enum):
    GROUNDING = "GROUNDING"
    COLLISION = "COLLISION"
    FIRE = "FIRE"
    SUNK = "SUNK"


class CasualtyLifecycle(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    PLANNED = "PLANNED"
    CONTRACTED = "CONTRACTED"
    IN_OPERATION = "IN_OPERATION"
    OPERATIONS_COMPLETE = "OPERATIONS_COMPLETE"
    CLOSED = "CLOSED"


class EnvPosture(str, Enum):
    ENV_CLEAR = "ENV_CLEAR"
    ENV_WATCH = "ENV_WATCH"
    ENV_HOLD = "ENV_HOLD"


class PollutionRiskTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AssessmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SalvageMethod(str, Enum):
    REFLOAT = "REFLOAT"
    LIGHTERING = "LIGHTERING"
    TOWAGE = "TOWAGE"
    WRECK_REMOVAL = "WRECK_REMOVAL"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class ContractForm(str, Enum):
    FIXED_PRICE = "FIXED_PRICE"
    NO_CURE_NO_PAY = "NO_CURE_NO_PAY"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    PERFORMANCE_COMPLETE = "PERFORMANCE_COMPLETE"
    AWARD_FINAL = "AWARD_FINAL"
    SETTLED = "SETTLED"
    TERMINATED = "TERMINATED"


class TerminateReason(str, Enum):
    MUTUAL = "MUTUAL"
    NO_CURE = "NO_CURE"


class SecurityStatus(str, Enum):
    LODGED = "LODGED"
    PARTIALLY_DISBURSED = "PARTIALLY_DISBURSED"
    CLOSED = "CLOSED"


class DisburseMode(str, Enum):
    RELEASE = "RELEASE"
    APPLY_TO_AWARD = "APPLY_TO_AWARD"


class AgencyType(str, Enum):
    COAST_GUARD = "COAST_GUARD"
    PORT_AUTHORITY = "PORT_AUTHORITY"
    ENV_AGENCY = "ENV_AGENCY"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AssetClass(str, Enum):
    TUG = "TUG"
    CRANE_BARGE = "CRANE_BARGE"
    PONTOON = "PONTOON"
    OIL_RESPONSE = "OIL_RESPONSE"


class AssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHARTERED = "CHARTERED"


class CharterPurpose(str, Enum):
    SALVAGE = "SALVAGE"
    POLLUTION_RESPONSE = "POLLUTION_RESPONSE"


class CharterStatus(str, Enum):
    BOOKED = "BOOKED"
    ON_HIRE = "ON_HIRE"
    STANDBY_WEATHER = "STANDBY_WEATHER"
    STANDBY_ENV = "STANDBY_ENV"
    OFF_HIRE = "OFF_HIRE"
    CANCELLED = "CANCELLED"


class WeatherWindowStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"


class PhaseType(str, Enum):
    MOBILIZATION = "MOBILIZATION"
    LIGHTERING = "LIGHTERING"
    REFLOAT = "REFLOAT"
    TOWAGE = "TOWAGE"
    WRECK_REMOVAL = "WRECK_REMOVAL"
    DEMOBILIZATION = "DEMOBILIZATION"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    WEATHER_HOLD = "WEATHER_HOLD"
    ENV_SUSPENDED = "ENV_SUSPENDED"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class PollutantClass(str, Enum):
    OIL_PERSISTENT = "OIL_PERSISTENT"
    OIL_NON_PERSISTENT = "OIL_NON_PERSISTENT"
    CHEMICAL = "CHEMICAL"
    DEBRIS = "DEBRIS"


class PollutionEventStatus(str, Enum):
    REPORTED = "REPORTED"
    ESCALATED = "ESCALATED"
    CONTAINED = "CONTAINED"
    VERIFIED_CLEAN = "VERIFIED_CLEAN"


class PropertyType(str, Enum):
    BUNKERS = "BUNKERS"
    CARGO = "CARGO"
    VESSEL_HULL = "VESSEL_HULL"
    WRECK_DEBRIS = "WRECK_DEBRIS"


class CustodyStatus(str, Enum):
    SALVED = "SALVED"
    SECURED_ASHORE = "SECURED_ASHORE"
    LIENED = "LIENED"
    REDELIVERED = "REDELIVERED"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


class DocumentationStatus(str, Enum):
    PENDING_SURVEY = "PENDING_SURVEY"
    SURVEYED = "SURVEYED"
    VALUE_VERIFIED = "VALUE_VERIFIED"


class DisposeMethod(str, Enum):
    REDELIVER = "REDELIVER"
    SELL = "SELL"
    SCRAP = "SCRAP"


class AwardStatus(str, Enum):
    COMPUTED = "COMPUTED"
    AGREED = "AGREED"
    IN_ARBITRATION = "IN_ARBITRATION"
    AWARDED = "AWARDED"
    APPEALED = "APPEALED"
    PAID = "PAID"


class DocPackStatus(str, Enum):
    COMPILING = "COMPILING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class DocEntryType(str, Enum):
    DAILY_LOG = "DAILY_LOG"
    COST_LOG = "COST_LOG"
    POLLUTION_REPORT = "POLLUTION_REPORT"
    SURVEY_REPORT = "SURVEY_REPORT"


# ─── Entity record shapes (system fields per PRD common-properties rules) ───
class Casualty(TypedDict, total=False):
    id: str
    vessel_name: str
    casualty_type: str
    declared_salved_value_cents: int
    position: str
    pollutant_inventory_note: str
    lifecycle_status: str
    env_posture: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    casualty_id: str
    casualty_seq: int
    assessor_id: str
    pollution_risk_tier: str
    wreck_removal_required: bool
    estimated_cost_cents: int
    notes: str
    status: str
    reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvagePlan(TypedDict, total=False):
    id: str
    casualty_id: str
    drafter_id: str
    method: str
    required_equipment_classes: List[str]
    status: str
    approver_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalvageContract(TypedDict, total=False):
    id: str
    casualty_id: str
    plan_id: str
    form: str
    fixed_price_cents: Optional[int]
    scopic_clause_included: bool
    status: str
    negotiation_round: int
    provisional_award_cents: Optional[int]
    security_required_cents: Optional[int]
    cost_to_date_cents: int
    overrun_flag: bool
    terminate_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecurityDeposit(TypedDict, total=False):
    id: str
    contract_id: str
    lodged_amount_cents: int
    held_cents: int
    released_cents: int
    applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    casualty_id: str
    agency_type: str
    valid_from: str
    valid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict, total=False):
    id: str
    asset_class: str
    day_rate_cents: int
    max_hs_meters: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentCharter(TypedDict, total=False):
    id: str
    casualty_id: str
    equipment_asset_id: str
    pollution_event_id: Optional[str]
    purpose: str
    window_start: str
    window_end: str
    status: str
    on_hire_at: Optional[str]
    off_hire_at: Optional[str]
    standby_hours: int
    active_days: Optional[int]
    standby_days: Optional[int]
    demurrage_days: Optional[int]
    total_cost_cents: Optional[int]
    linked_phase_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeatherWindow(TypedDict, total=False):
    id: str
    casualty_id: str
    window_start: str
    window_end: str
    forecast_hs_meters: float
    status: str
    created_at: str
    updated_at: str
    version: int


class OperationPhase(TypedDict, total=False):
    id: str
    contract_id: str
    phase_type: str
    planned_duration_hours: int
    status: str
    weather_window_id: Optional[str]
    charter_ids: List[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PollutionEvent(TypedDict, total=False):
    id: str
    casualty_id: str
    pollutant_class: str
    tier: str
    est_volume_m3: float
    status: str
    provisional_exposure_cents: int
    final_exposure_cents: Optional[int]
    special_compensation_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class RecoveredProperty(TypedDict, total=False):
    id: str
    casualty_id: str
    storage_site_id: Optional[str]
    property_type: str
    quantity_tonnes: float
    declared_value_cents: int
    verified_value_cents: Optional[int]
    custody_status: str
    documentation_status: str
    redelivered_tonnes: float
    sold_tonnes: float
    disposed_tonnes: float
    in_custody_tonnes: float
    lien_amount_cents: int
    surveyor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageSite(TypedDict, total=False):
    id: str
    name: str
    capacity_tonnes: float
    allocated_tonnes: float
    created_at: str
    updated_at: str
    version: int


class SalvageAward(TypedDict, total=False):
    id: str
    contract_id: str
    status: str
    computed_amount_cents: int
    agreed_amount_cents: Optional[int]
    awarded_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class DocPack(TypedDict, total=False):
    id: str
    contract_id: str
    status: str
    required_count: int
    satisfied_count: int
    completeness_pct: float
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only record: carries ONLY id + created_at (no updated_at, no version)
class DocEntry(TypedDict, total=False):
    id: str
    doc_pack_id: str
    entry_type: str
    ref_id: str
    entry_date: str
    summary: str
    created_at: str
