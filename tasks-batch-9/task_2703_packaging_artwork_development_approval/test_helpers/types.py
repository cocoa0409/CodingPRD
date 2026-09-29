"""Domain types for the Packaging Artwork Development & Approval API.

Entity TypedDicts, controlled-vocabulary enums and the role enum, all taken
from the PRD's controlled vocabularies and entity narratives.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PACKAGING_COORDINATOR = "PackagingCoordinator"
    BRAND_REVIEWER = "BrandReviewer"
    LEGAL_REVIEWER = "LegalReviewer"
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    QUALITY_REVIEWER = "QualityReviewer"
    PRINTER_REP = "PrinterRep"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------


class RegulatoryScheme(str, Enum):
    FDA_FOOD = "FDA_FOOD"
    EU_FIC = "EU_FIC"
    HEALTH_CANADA = "HEALTH_CANADA"


class BriefStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ElementCode(str, Enum):
    NET_CONTENTS = "NET_CONTENTS"
    INGREDIENT_STATEMENT = "INGREDIENT_STATEMENT"
    ALLERGEN_STATEMENT = "ALLERGEN_STATEMENT"
    DATE_CODE_ZONE = "DATE_CODE_ZONE"
    BARCODE = "BARCODE"
    RECYCLING_MARK = "RECYCLING_MARK"
    ADDRESS_BLOCK = "ADDRESS_BLOCK"


class ComponentType(str, Enum):
    CARTON = "CARTON"
    LABEL = "LABEL"
    FILM = "FILM"
    SHIPPER = "SHIPPER"


class PrintProcess(str, Enum):
    OFFSET = "OFFSET"
    FLEXO = "FLEXO"
    GRAVURE = "GRAVURE"
    DIGITAL = "DIGITAL"


class SubstrateClass(str, Enum):
    COATED_PAPER = "COATED_PAPER"
    UNCOATED_PAPER = "UNCOATED_PAPER"
    FILM = "FILM"
    METALLIZED = "METALLIZED"


class MetricUom(str, Enum):
    G = "G"
    KG = "KG"
    ML = "ML"
    L = "L"


class UsUom(str, Enum):
    OZ = "OZ"
    LB = "LB"
    FLOZ = "FLOZ"


class ClaimType(str, Enum):
    NUTRIENT_CONTENT = "NUTRIENT_CONTENT"
    STRUCTURE_FUNCTION = "STRUCTURE_FUNCTION"
    ORGANIC = "ORGANIC"
    FREE_FROM = "FREE_FROM"
    SUSTAINABILITY = "SUSTAINABILITY"


class LegalStatus(str, Enum):
    DRAFT = "DRAFT"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class ObsolescenceState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDE_PENDING = "SUPERSEDE_PENDING"
    SUPERSEDED = "SUPERSEDED"


class VersionState(str, Enum):
    DRAFT = "DRAFT"
    ELEMENTS_VERIFIED = "ELEMENTS_VERIFIED"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    RELEASED_TO_PRINT = "RELEASED_TO_PRINT"
    OBSOLETE_PENDING = "OBSOLETE_PENDING"
    OBSOLETE = "OBSOLETE"


class ReasonForChangeCode(str, Enum):
    NEW_LAUNCH = "NEW_LAUNCH"
    REGULATORY_UPDATE = "REGULATORY_UPDATE"
    CLAIM_CHANGE = "CLAIM_CHANGE"
    MARKETING_REFRESH = "MARKETING_REFRESH"
    PRINTER_CHANGE = "PRINTER_CHANGE"
    ERROR_CORRECTION = "ERROR_CORRECTION"


class ElementSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ElementResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WAIVED = "WAIVED"


class RouteStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE_APPROVED = "COMPLETE_APPROVED"
    COMPLETE_REJECTED = "COMPLETE_REJECTED"


class Discipline(str, Enum):
    BRAND = "BRAND"
    LEGAL = "LEGAL"
    REGULATORY = "REGULATORY"
    QUALITY = "QUALITY"


class TaskMode(str, Enum):
    PARALLEL = "PARALLEL"
    SEQUENTIAL = "SEQUENTIAL"


class TaskDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONDITIONAL = "CONDITIONAL"
    SKIPPED = "SKIPPED"


class ColorStandard(str, Enum):
    G7_MASTER = "G7_MASTER"
    ISO12647 = "ISO12647"


class CertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"


class ColorStatus(str, Enum):
    COLOR_PENDING = "COLOR_PENDING"
    COLOR_PASS = "COLOR_PASS"
    COLOR_FAIL = "COLOR_FAIL"


class SubstrateStatus(str, Enum):
    SUBSTRATE_PENDING = "SUBSTRATE_PENDING"
    SUBSTRATE_APPROVED = "SUBSTRATE_APPROVED"
    SUBSTRATE_REJECTED = "SUBSTRATE_REJECTED"


class PressCheckStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PRESS_CHECK_REQUIRED = "PRESS_CHECK_REQUIRED"
    PRESS_CHECK_SCHEDULED = "PRESS_CHECK_SCHEDULED"
    PRESS_CHECK_ATTENDED = "PRESS_CHECK_ATTENDED"


class ProofState(str, Enum):
    PROOF_IN_REVIEW = "PROOF_IN_REVIEW"
    PROOF_APPROVED = "PROOF_APPROVED"
    PROOF_REJECTED = "PROOF_REJECTED"


class PlateOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    CANCELLED = "CANCELLED"


class RunoutState(str, Enum):
    PLANNED = "PLANNED"
    MONITORING = "MONITORING"
    RUNOUT_COMPLETE = "RUNOUT_COMPLETE"
    SCRAPPED = "SCRAPPED"


class Disposition(str, Enum):
    RUNOUT = "RUNOUT"
    SCRAP = "SCRAP"


class DefectCode(str, Enum):
    WRONG_ALLERGEN = "WRONG_ALLERGEN"
    MISSING_NET_CONTENTS = "MISSING_NET_CONTENTS"
    WRONG_LANGUAGE_VARIANT = "WRONG_LANGUAGE_VARIANT"
    COLOR_OUT_OF_TOLERANCE = "COLOR_OUT_OF_TOLERANCE"
    WRONG_DATE_CODE = "WRONG_DATE_CODE"
    OLD_ARTWORK_USED = "OLD_ARTWORK_USED"


class DiscoveredStage(str, Enum):
    PRESS = "PRESS"
    PACKING = "PACKING"
    DISTRIBUTION = "DISTRIBUTION"
    MARKET = "MARKET"


class EscapeState(str, Enum):
    OPEN = "OPEN"
    ROOT_CAUSE_ASSIGNED = "ROOT_CAUSE_ASSIGNED"
    RECOVERY_CLAIMED = "RECOVERY_CLAIMED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RootCauseParty(str, Enum):
    PRINTER = "PRINTER"
    BRAND = "BRAND"
    AGENCY = "AGENCY"
    SHARED = "SHARED"


class EscapeResolution(str, Enum):
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity in this service carries `updated_at` and an integer `version`
# in addition to `id` and `created_at`.
# ---------------------------------------------------------------------------


class Brief(TypedDict):
    id: str
    sku_code: str
    product_name: str
    regulatory_scheme: str
    market_codes: List[str]
    language_codes: List[str]
    required_element_codes: List[str]
    structural_spec: dict
    net_contents_declaration: dict
    status: str
    review_note: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    asset_count: int
    created_at: str
    updated_at: str
    version: int


class MarketingClaim(TypedDict):
    id: str
    claim_code: str
    claim_text: str
    claim_type: str
    market_code: str
    substantiation_ref: str
    legal_status: str
    cleared_from_utc: Optional[str]
    cleared_until_utc: Optional[str]
    cleared_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    usage_count: int
    created_at: str
    updated_at: str
    version: int


class ArtworkAsset(TypedDict):
    id: str
    brief_id: str
    market_code: str
    language_codes: List[str]
    component_type: str
    substrate_class: str
    brand_critical_color: bool
    plate_budget_cents: int
    standard_unit_cost_cents: int
    obsolescence_state: str
    version_counter: int
    current_approved_version_id: Optional[str]
    committed_plate_cost_cents: int
    obsolete_units_total: int
    changeover_cost_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class ArtworkVersion(TypedDict):
    id: str
    artwork_asset_id: str
    version_no: int
    author_user_id: str
    reason_for_change_code: str
    change_description: str
    mandatory_elements: dict
    claim_ids: List[str]
    supersedes_version_id: Optional[str]
    state: str
    check_run_no: int
    compliance_score: Optional[float]
    failed_element_count: int
    waived_element_count: int
    revision_cycle_count: int
    route_count: int
    requires_reverification: bool
    open_condition_codes: List[str]
    pinned_claim_snapshot: List[dict]
    approved_at: Optional[str]
    released_at: Optional[str]
    obsoleted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ElementCheck(TypedDict):
    id: str
    artwork_version_id: str
    check_run_no: int
    element_code: str
    severity: str
    result: str
    detail: str
    deduction_points: float
    waived_by_user_id: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewRoute(TypedDict):
    id: str
    artwork_version_id: str
    route_no: int
    status: str
    current_stage_no: int
    stage_plan: List[dict]
    conditional_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewTask(TypedDict):
    id: str
    review_route_id: str
    discipline: str
    mode: str
    stage_no: int
    is_active: bool
    decision: str
    comment: Optional[str]
    condition_code: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Printer(TypedDict):
    id: str
    name: str
    color_standard: str
    certified_substrates: List[str]
    recovery_liability_cap_cents: int
    certification_status: str
    performance_score: float
    recovery_balance_cents: int
    escape_count: int
    created_at: str
    updated_at: str
    version: int


class PrinterProof(TypedDict):
    id: str
    artwork_version_id: str
    printer_id: str
    proof_no: int
    substrate_code: str
    proof_note: Optional[str]
    color_status: str
    measured_delta_e_max: Optional[float]
    effective_tolerance: float
    substrate_status: str
    press_check_required: bool
    press_check_status: str
    press_line_code: Optional[str]
    press_check_start_utc: Optional[str]
    press_check_end_utc: Optional[str]
    attended_by_user_id: Optional[str]
    proof_state: str
    requires_recheck: bool
    created_at: str
    updated_at: str
    version: int


class PlateOrder(TypedDict):
    id: str
    artwork_version_id: str
    printer_id: str
    printer_proof_id: str
    plate_set_count: int
    expedite: bool
    plate_subtotal_cents: int
    setup_fee_cents: int
    expedite_fee_cents: int
    cost_cents: int
    status: str
    cancel_reason: Optional[str]
    auto_cancelled: bool
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryRunout(TypedDict):
    id: str
    artwork_asset_id: str
    obsolete_version_id: str
    on_hand_qty: int
    weekly_usage_qty: int
    runout_start_utc: str
    state: str
    projected_runout_date: str
    actual_runout_date: Optional[str]
    depletion_records: List[dict]
    remaining_qty: int
    trailing_avg_usage_qty: Optional[int]
    disposition: Optional[str]
    units_scrapped: int
    units_reworked: int
    material_writeoff_cents: int
    relabel_cost_cents: int
    changeover_base_cents: int
    changeover_expedite_cents: int
    total_changeover_cost_cents: int
    reversal_count: int
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ErrorEscape(TypedDict):
    id: str
    artwork_version_id: str
    printer_id: str
    defect_code: str
    discovered_stage: str
    units_affected: int
    discovery_note: Optional[str]
    state: str
    investigation_fee_cents: int
    root_cause_party: Optional[str]
    printer_share_pct: Optional[float]
    investigation_note: Optional[str]
    provisional_recovery_cents: Optional[int]
    liability_cap_applied: bool
    dispute_reason: Optional[str]
    dispute_count: int
    actual_reprint_cost_cents: Optional[int]
    actual_scrap_cost_cents: Optional[int]
    actual_expedite_freight_cents: Optional[int]
    final_recovery_cents: Optional[int]
    recovery_variance_cents: Optional[int]
    performance_penalty_points: Optional[float]
    resolution: Optional[str]
    settlement_note: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
