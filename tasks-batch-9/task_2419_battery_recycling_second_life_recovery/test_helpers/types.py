"""Domain types for the Battery Recycling & Second-Life Recovery API.

Entity TypedDicts, status enums and the operating-role enum, all named exactly
as the PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Operating roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MARKET_ANALYST = "MarketAnalyst"
    INTAKE_CLERK = "IntakeClerk"
    PLANT_OPERATOR = "PlantOperator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRIAGE_ENGINEER = "TriageEngineer"
    ASSAY_TECHNICIAN = "AssayTechnician"
    SETTLEMENT_ACCOUNTANT = "SettlementAccountant"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    SUPPLIER_REP = "SupplierRep"


# --------------------------------------------------------------------------
# Shared domain enums
# --------------------------------------------------------------------------

class Metal(str, Enum):
    NI = "NI"
    CO = "CO"
    LI = "LI"
    CU = "CU"
    MN = "MN"
    GRAPHITE = "GRAPHITE"


class Chemistry(str, Enum):
    NMC622 = "NMC622"
    NCA = "NCA"
    LMO = "LMO"
    LFP = "LFP"


class ChemistryFamily(str, Enum):
    NICKEL_RICH = "NICKEL_RICH"
    IRON_PHOSPHATE = "IRON_PHOSPHATE"


# --------------------------------------------------------------------------
# Per-entity status enums
# --------------------------------------------------------------------------

class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierChannel(str, Enum):
    AUTOMAKER = "AUTOMAKER"
    DISMANTLER = "DISMANTLER"
    CONSUMER_COLLECTION = "CONSUMER_COLLECTION"


class CustodyState(str, Enum):
    RECEIVED = "RECEIVED"
    IDENTIFIED = "IDENTIFIED"
    DISCHARGED = "DISCHARGED"
    PACKAGED = "PACKAGED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class ComplianceState(str, Enum):
    MANIFEST_DRAFT = "MANIFEST_DRAFT"
    MANIFEST_SUBMITTED = "MANIFEST_SUBMITTED"
    MANIFEST_CLOSED = "MANIFEST_CLOSED"
    MANIFEST_REJECTED = "MANIFEST_REJECTED"


class HoldReason(str, Enum):
    MANIFEST_REJECTED = "MANIFEST_REJECTED"
    SUPPLIER_CREDIT_HOLD = "SUPPLIER_CREDIT_HOLD"


class ManifestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class UnNumber(str, Enum):
    UN3480 = "UN3480"
    UN3481 = "UN3481"
    UN3536 = "UN3536"


class PackingGroup(str, Enum):
    I = "I"
    II = "II"
    III = "III"


class ModuleStatus(str, Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    REFURB_QUEUE = "REFURB_QUEUE"
    SECOND_LIFE_QUEUE = "SECOND_LIFE_QUEUE"
    RECOVERY_QUEUE = "RECOVERY_QUEUE"
    CHARGED = "CHARGED"
    CONSUMED = "CONSUMED"
    SHIPPED = "SHIPPED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class ScoringVariant(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    FLEET_AVERAGE = "FLEET_AVERAGE"


class Disposition(str, Enum):
    REFURBISH = "REFURBISH"
    SECOND_LIFE = "SECOND_LIFE"
    MATERIAL_RECOVERY = "MATERIAL_RECOVERY"


class TriageDecisionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class LineType(str, Enum):
    MECHANICAL = "MECHANICAL"
    HYDROMET = "HYDROMET"


class LineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class CampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    OPEN = "OPEN"
    CHARGED = "CHARGED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementState(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"
    UMPIRE_ROUND = "UMPIRE_ROUND"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class PermitMedium(str, Enum):
    AIR = "AIR"
    WATER = "WATER"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DischargeEventStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class Analyte(str, Enum):
    NICKEL_DISSOLVED = "NICKEL_DISSOLVED"
    FLUORIDE = "FLUORIDE"
    TSS = "TSS"


class PassportStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


# --------------------------------------------------------------------------
# Entity shapes
#
# Thirteen resources carry the full identity set: id, created_at, updated_at
# and version (PRD §2.4).  MetalIndexPrice and RecoveryOutput are immutable
# ledger rows and carry only id and created_at.
# --------------------------------------------------------------------------

class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    status: str
    mech_capacity_kg_per_day: float
    hydro_capacity_kg_per_day: float
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    legal_name: str
    channel: str
    credit_limit_cents: int
    contact_email: Optional[str]
    payable_balance_cents: int
    paid_to_date_cents: int
    credit_hold: bool
    quality_strike_count: int
    created_at: str
    updated_at: str
    version: int


class MetalIndexPrice(TypedDict):
    """Immutable published quote — carries only id and created_at."""
    id: str
    metal: str
    effective_date: str
    price_cents_per_kg: int
    source_index: str
    created_at: str


class Intake(TypedDict):
    id: str
    supplier_id: str
    facility_id: str
    received_at: str
    declared_chemistry: str
    identified_chemistry: Optional[str]
    gross_mass_kg: float
    packaging_tare_kg: float
    net_mass_kg: float
    declared_ni_pct: float
    declared_co_pct: float
    declared_li_pct: float
    declared_cu_pct: float
    moisture_pct: float
    foreign_material_pct: float
    soc_pct: Optional[float]
    packaging_type: Optional[str]
    custody_state: str
    compliance_state: str
    hold_reason: Optional[str]
    module_mass_total_kg: float
    assigned_mass_kg: float
    unassigned_mass_kg: float
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazmatManifest(TypedDict):
    id: str
    intake_id: str
    un_number: str
    packing_group: str
    transporter_name: str
    revision: int
    status: str
    submitted_by_user_id: str
    closed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Module(TypedDict):
    id: str
    intake_id: str
    lot_id: Optional[str]
    serial_code: str
    chemistry: str
    mass_kg: float
    min_cell_capacity_pct: float
    mean_cell_capacity_pct: float
    cycle_count: int
    second_life_score: Optional[float]
    grade: Optional[str]
    status: str
    shipped_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TriageDecision(TypedDict):
    id: str
    module_id: str
    scoring_variant: str
    override_disposition: Optional[str]
    score: float
    grade: str
    derived_disposition: str
    disposition: str
    status: str
    decided_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ProcessingLine(TypedDict):
    id: str
    facility_id: str
    line_code: str
    line_type: str
    chemistry_family: str
    throughput_kg_per_hour: float
    changeover_buffer_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingCampaign(TypedDict):
    id: str
    line_id: str
    chemistry_family: str
    window_start: str
    window_end: str
    planned_input_kg: float
    committed_input_kg: float
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryLot(TypedDict):
    id: str
    campaign_id: str
    lot_code: str
    charged_mass_kg: float
    residue_mass_kg: Optional[float]
    recovered_mass_kg: float
    accounted_mass_kg: Optional[float]
    unaccounted_mass_kg: Optional[float]
    mass_balance_pct: Optional[float]
    recycled_content_pct: Optional[float]
    status: str
    finalized_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryOutput(TypedDict):
    """Append-only assay line — carries only id and created_at."""
    id: str
    lot_id: str
    metal: str
    recovered_mass_kg: float
    assay_purity_pct: float
    recorded_by_user_id: str
    created_at: str


class SettlementLine(TypedDict):
    """One entry of a settlement's per-metal line_breakdown array."""
    metal: str
    contained_kg: float
    unit_price_cents_per_kg: int
    payable_share: float
    line_cents: int


class SupplierSettlement(TypedDict):
    id: str
    intake_id: str
    supplier_id: str
    variant: str
    price_basis_date: str
    line_breakdown: List[SettlementLine]
    gross_cents: int
    processing_fee_pct: float
    processing_fee_cents: int
    quality_deduction_pct: float
    quality_deduction_cents: int
    pre_surcharge_net_cents: int
    hazmat_surcharge_cents: int
    net_payable_cents: int
    posted_amount_cents: int
    max_variance_pp: Optional[float]
    dispute_round: int
    dispute_reason: Optional[str]
    umpire_metal: Optional[str]
    umpire_contained_kg: Optional[float]
    payment_reference: Optional[str]
    void_reason: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class PermitAllotment(TypedDict):
    id: str
    facility_id: str
    medium: str
    permit_no: str
    valid_from: str
    valid_to: str
    daily_cap_kg: float
    consumed_kg: float
    status: str
    suspend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DischargeEvent(TypedDict):
    id: str
    allotment_id: str
    lot_id: str
    event_date: str
    mass_kg: float
    analyte: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PassportMetalContent(TypedDict):
    metal: str
    recovered_mass_kg: float
    assay_purity_pct: float


class BatteryPassport(TypedDict):
    id: str
    lot_id: str
    passport_code: str
    customer_name: str
    recycled_content_pct: float
    metal_content: List[PassportMetalContent]
    status: str
    issued_at: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapacityProjection(TypedDict):
    """Non-persisted projection payload returned by the campus projection read."""
    baseline_kg_per_day: float
    horizon_days: int
    projected_input_kg: float
    mech_capacity_kg_per_day: float
    hydro_capacity_kg_per_day: float
    first_deficit_day: Optional[int]
    first_deficit_date: Optional[str]
    deficit_kg: float


# Entities whose responses expose updated_at and version (PRD §2.4).
VERSIONED_ENTITIES = (
    "Facility", "Supplier", "Intake", "HazmatManifest", "Module",
    "TriageDecision", "ProcessingLine", "ProcessingCampaign", "RecoveryLot",
    "SupplierSettlement", "PermitAllotment", "DischargeEvent",
    "BatteryPassport",
)

# Immutable ledger rows: only id and created_at (PRD §2.4).
IMMUTABLE_LEDGER_ENTITIES = ("MetalIndexPrice", "RecoveryOutput")
