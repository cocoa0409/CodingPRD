"""Domain types for the Hand Tool Manufacturing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Two resources are immutable once written — a pack member line and a
claim replacement line — and therefore carry only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    CHANNEL_MANAGER = "ChannelManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    QUALITY_ENGINEER = "QualityEngineer"
    WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
    BRAND_PROTECTION_ANALYST = "BrandProtectionAnalyst"
    CLAIMANT = "Claimant"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Catalogue enums (PRD §3.1)
# ---------------------------------------------------------------------------


class ToolFamily(str, Enum):
    WRENCH = "WRENCH"
    SOCKET = "SOCKET"
    PLIER = "PLIER"


class Channel(str, Enum):
    BRANDED = "BRANDED"
    PRIVATE_LABEL = "PRIVATE_LABEL"
    PROFESSIONAL = "PROFESSIONAL"


class AlloyGrade(str, Enum):
    CR_V = "CR_V"
    CR_MO = "CR_MO"
    S2 = "S2"


class WarrantyTier(str, Enum):
    LIFETIME = "LIFETIME"
    LIMITED_5Y = "LIMITED_5Y"
    NONE = "NONE"


class WarrantyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Shop-floor enums (PRD §3.2 – §3.5)
# ---------------------------------------------------------------------------


class ProcessStatus(str, Enum):
    FORGED = "FORGED"
    HEAT_TREATED = "HEAT_TREATED"
    MACHINED = "MACHINED"
    PLATED = "PLATED"
    ASSEMBLED = "ASSEMBLED"


class CertStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_TEST = "IN_TEST"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class Disposition(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class FurnaceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class CampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class TestType(str, Enum):
    HARDNESS = "HARDNESS"
    PROOF_TORQUE = "PROOF_TORQUE"
    DIMENSIONAL = "DIMENSIONAL"
    SALT_SPRAY = "SALT_SPRAY"
    MECHANISM_CYCLE = "MECHANISM_CYCLE"


class TestRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOID = "VOID"


# ---------------------------------------------------------------------------
# Packaging enums (PRD §3.6)
# ---------------------------------------------------------------------------


class PackType(str, Enum):
    RETAIL_DISPLAY = "RETAIL_DISPLAY"
    SECURITY = "SECURITY"
    MULTIPACK = "MULTIPACK"


class PackStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Warranty enums (PRD §3.7 – §3.8)
# ---------------------------------------------------------------------------


class ClaimantType(str, Enum):
    CONSUMER = "CONSUMER"
    PRO_ACCOUNT = "PRO_ACCOUNT"


class ClaimantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ClaimReason(str, Enum):
    BREAKAGE = "BREAKAGE"
    MECHANISM_FAILURE = "MECHANISM_FAILURE"
    CORROSION = "CORROSION"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FRAUD_HOLD = "FRAUD_HOLD"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"
    DENIED_FRAUD = "DENIED_FRAUD"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Brand-protection enums (PRD §3.9)
# ---------------------------------------------------------------------------


class EvidenceGrade(str, Enum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class ToolSku(TypedDict):
    id: str
    sku_code: str
    tool_family: str
    channel: str
    nominal_size_mm: int
    alloy_grade: str
    list_price_cents: int
    warranty_tier: str
    supersedes_sku_id: Optional[str]
    lineage_depth: int
    proof_torque_required_nm: float
    brand_risk_score: int
    warranty_posture: str
    confirmed_counterfeit_count: int
    units_received_total: int
    units_on_hand: int
    units_reserved: int
    units_shipped: int
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict):
    id: str
    sku_id: str
    lot_code: str
    unit_count: int
    specimen_pool_total: int
    specimens_available: int
    specimens_committed: int
    specimens_consumed: int
    process_status: str
    cert_status: str
    disposition: str
    hardness_index_sample: Optional[float]
    hardness_index_pooled: Optional[float]
    proof_torque_required_nm: float
    rework_cycle_count: int
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HeatTreatFurnace(TypedDict):
    id: str
    furnace_code: str
    max_charge_kg: int
    alloy_grades_supported: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FurnaceCampaign(TypedDict):
    id: str
    lot_id: str
    furnace_id: str
    window_start: str
    window_end: str
    charge_kg: int
    buffered_end: str
    soak_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaltSprayChamber(TypedDict):
    id: str
    chamber_code: str
    coupon_capacity: int
    created_at: str
    updated_at: str
    version: int


class TestRun(TypedDict):
    id: str
    lot_id: str
    chamber_id: Optional[str]
    test_type: str
    specimen_count: int
    window_start: str
    window_end: str
    mandatory: bool
    readings: Optional[List[float]]
    mean_reading: Optional[float]
    governing_statistic: Optional[float]
    requirement_value: Optional[float]
    result_margin_pct: Optional[float]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackConfiguration(TypedDict):
    id: str
    pack_code: str
    pack_type: str
    primary_sku_id: str
    member_subtotal_cents: int
    security_surcharge_cents: int
    pack_total_cents: int
    distinct_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackMember(TypedDict):
    """Immutable once written — carries only id and created_at from the
    common field set."""

    id: str
    pack_id: str
    sku_id: str
    quantity: int
    line_extended_cents: int
    created_at: str


class WarrantyProgram(TypedDict):
    id: str
    program_code: str
    reserve_funded_cents: int
    fraud_score_threshold: int
    reserve_balance_cents: int
    open_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    email: str
    claimant_type: str
    status: str
    fraud_risk_score_intake: int
    fraud_risk_score_adjudication: int
    lifetime_claim_count: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    claimant_id: str
    sku_id: str
    program_id: str
    serial_code: str
    claim_reason: str
    status: str
    fraud_score_at_intake: int
    reserve_charge_cents: int
    replacement_unit_count: int
    line_count: int
    hold_reason: Optional[str]
    held_by_user_id: Optional[str]
    fraud_cleared: bool
    denial_code: Optional[str]
    shipment_ref: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    """Immutable once written — carries only id and created_at from the
    common field set."""

    id: str
    claim_id: str
    component_code: str
    component_list_price_cents: int
    quantity: int
    line_reserve_cents: int
    created_at: str


class CounterfeitReport(TypedDict):
    id: str
    sku_id: str
    channel_name: str
    seller_handle: str
    evidence_grade: str
    unit_estimate: int
    risk_points: int
    status: str
    confirmation_note: Optional[str]
    dismissal_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
