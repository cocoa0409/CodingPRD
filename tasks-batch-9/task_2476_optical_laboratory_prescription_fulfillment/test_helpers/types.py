"""Entity shapes and closed enumerations declared by the PRD.

Two record types are append-only event rows: a quality inspection and a
settlement entry each carry only ``id`` and ``created_at`` and therefore
deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    STORE_OPTICIAN = "StoreOptician"
    PRESCRIBER = "Prescriber"
    LAB_TECHNICIAN = "LabTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    LAB_MANAGER = "LabManager"
    BENEFITS_ADMINISTRATOR = "BenefitsAdministrator"


# --------------------------------------------------------------------------
# Status enumerations
# --------------------------------------------------------------------------


class PrescriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DesignType(str, Enum):
    SINGLE_VISION = "SINGLE_VISION"
    PROGRESSIVE = "PROGRESSIVE"
    SPECIALTY = "SPECIALTY"


class LensMaterial(str, Enum):
    CR39 = "CR39"
    POLYCARBONATE = "POLYCARBONATE"
    TRIVEX = "TRIVEX"
    HIGH_INDEX_167 = "HIGH_INDEX_167"


class Coating(str, Enum):
    HARDCOAT = "HARDCOAT"
    AR_STANDARD = "AR_STANDARD"
    AR_PREMIUM = "AR_PREMIUM"
    PHOTOCHROMIC = "PHOTOCHROMIC"
    POLARIZED = "POLARIZED"


class ProductTier(str, Enum):
    ECONOMY = "ECONOMY"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class BlankLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class MachineType(str, Enum):
    GENERATOR = "GENERATOR"
    POLISHER = "POLISHER"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CALIBRATION_HOLD = "CALIBRATION_HOLD"
    DOWN = "DOWN"


class BayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    LAYOUT_READY = "LAYOUT_READY"
    IN_LAB = "IN_LAB"
    LAB_COMPLETE = "LAB_COMPLETE"
    REMAKE_PENDING = "REMAKE_PENDING"
    DISPENSED = "DISPENSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    PROVISIONAL_QUOTED = "PROVISIONAL_QUOTED"
    BENEFIT_APPLIED = "BENEFIT_APPLIED"
    BENEFIT_VOIDED = "BENEFIT_VOIDED"
    SELF_PAY_FINAL = "SELF_PAY_FINAL"
    PATIENT_SETTLED = "PATIENT_SETTLED"
    REFUND_DUE = "REFUND_DUE"
    CANCELLED_NO_CHARGE = "CANCELLED_NO_CHARGE"


class TatCommitmentStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class QuoteVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TraceSource(str, Enum):
    DIGITAL_TRACER = "DIGITAL_TRACER"
    MANUAL_CALIPER = "MANUAL_CALIPER"
    CATALOG = "CATALOG"


class LayoutStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SUPERSEDED = "SUPERSEDED"
    BLANK_TOO_SMALL = "BLANK_TOO_SMALL"


class JobRoute(str, Enum):
    STOCK_EDGE_ONLY = "STOCK_EDGE_ONLY"
    SURFACE_AND_EDGE = "SURFACE_AND_EDGE"


class LabJobStatus(str, Enum):
    QUEUED = "QUEUED"
    SURFACING = "SURFACING"
    SURFACED = "SURFACED"
    EDGING = "EDGING"
    EDGED = "EDGED"
    REWORK_QUEUED = "REWORK_QUEUED"
    BLANK_BACKORDER = "BLANK_BACKORDER"
    PASSED = "PASSED"
    RELEASED = "RELEASED"
    SCRAPPED = "SCRAPPED"


class ScrapReason(str, Enum):
    REWORK_LIMIT = "REWORK_LIMIT"
    REMAKE_REQUESTED = "REMAKE_REQUESTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class OperationType(str, Enum):
    SURFACING = "SURFACING"
    EDGING = "EDGING"


class OperationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BROKEN = "BROKEN"
    CANCELLED = "CANCELLED"


class Eye(str, Enum):
    OD = "OD"
    OS = "OS"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FailedMetric(str, Enum):
    SPHERE = "SPHERE"
    CYLINDER = "CYLINDER"
    AXIS = "AXIS"
    PRISM = "PRISM"
    COSMETIC = "COSMETIC"


class CosmeticDefectCode(str, Enum):
    MINOR_EDGE_CHIP = "MINOR_EDGE_CHIP"
    DEEP_SCRATCH = "DEEP_SCRATCH"
    COATING_CRAZE = "COATING_CRAZE"
    INCLUSION = "INCLUSION"
    POLISH_HAZE = "POLISH_HAZE"


class DefectCode(str, Enum):
    POWER_OUT_OF_TOL = "POWER_OUT_OF_TOL"
    AXIS_OUT_OF_TOL = "AXIS_OUT_OF_TOL"
    PRISM_OUT_OF_TOL = "PRISM_OUT_OF_TOL"
    COSMETIC_DEFECT = "COSMETIC_DEFECT"
    WRONG_MATERIAL = "WRONG_MATERIAL"
    WRONG_COATING = "WRONG_COATING"
    WRONG_PD = "WRONG_PD"
    WRONG_FITTING_HEIGHT = "WRONG_FITTING_HEIGHT"
    WRONG_FRAME = "WRONG_FRAME"
    PATIENT_NONADAPT = "PATIENT_NONADAPT"
    RX_TRANSCRIPTION = "RX_TRANSCRIPTION"


class RemakeCaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    CLOSED = "CLOSED"


class Responsibility(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    STORE = "STORE"
    LAB = "LAB"
    SPLIT = "SPLIT"


class AdjudicationMethod(str, Enum):
    PROCESS_AUDIT = "PROCESS_AUDIT"
    TOLERANCE_DELTA = "TOLERANCE_DELTA"


class SettlementEntryType(str, Enum):
    ORDER_CHARGE = "ORDER_CHARGE"
    INSURANCE_BENEFIT = "INSURANCE_BENEFIT"
    BENEFIT_REVERSAL = "BENEFIT_REVERSAL"
    LAB_WRITEOFF = "LAB_WRITEOFF"
    PATIENT_PAYMENT = "PATIENT_PAYMENT"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(CommonFields):
    npi: str
    full_name: str
    license_state: str
    max_rx_validity_months: int
    status: str
    verified_rx_count: int


class InsurancePlan(CommonFields):
    plan_code: str
    frame_allowance_cents: int
    lens_base_allowance_cents: int
    coating_allowance_cents: int
    progressive_copay_cents: int
    coinsurance_pct: float
    annual_benefit_cap_cents: int
    expedite_covered: bool
    specialty_requires_prior_auth: bool


class Patient(CommonFields):
    full_name: str
    date_of_birth: str
    insurance_plan_id: Optional[str]
    member_number: Optional[str]
    benefit_period_start: Optional[str]
    status: str
    benefit_used_cents: int


class LensDesign(CommonFields):
    design_code: str
    design_type: str
    material: str
    allowed_coatings: List[str]
    retail_price_cents: int
    min_fitting_height_mm: float
    min_blank_diameter_mm: float
    product_tier: str
    stock_sku_available: bool
    base_curve: float


class ToleranceStandard(CommonFields):
    design_type: str
    power_band_min_abs: float
    power_band_max_abs: float
    sphere_tolerance_diopters: float
    cylinder_tolerance_diopters: float
    axis_tolerance_degrees: int
    prism_tolerance_pd: float
    allowed_cosmetic_defect_codes: List[str]
    effective_from: str


class LensBlankLot(CommonFields):
    lens_design_id: str
    blank_sku: str
    diameter_mm: float
    received_qty: int
    on_hand_qty: int
    allocated_qty: int
    consumed_qty: int
    scrapped_qty: int
    received_on: str
    status: str


class LabMachine(CommonFields):
    machine_code: str
    machine_type: str
    calibration_buffer_minutes: int
    status: str


class FinishingBay(CommonFields):
    bay_code: str
    concurrent_capacity: int
    status: str


class PrescriptionRecord(CommonFields):
    patient_id: str
    prescriber_id: str
    prescriber_npi_claimed: str
    prescriber_license_state_claimed: str
    sphere_od: float
    sphere_os: float
    cylinder_od: float
    cylinder_os: float
    axis_od: Optional[int]
    axis_os: Optional[int]
    add_power_od: Optional[float]
    add_power_os: Optional[float]
    prism_diopter_od: float
    prism_diopter_os: float
    pd_distance_mm: float
    issued_on: str
    expires_at: str
    requires_multifocal: bool
    verification_status: str
    verification_note: Optional[str]
    verified_at: Optional[str]
    resubmit_count: int


class RxOrder(CommonFields):
    patient_id: str
    prescription_id: str
    lens_design_id: str
    frame_sku: str
    frame_retail_cents: int
    requested_coatings: List[str]
    monocular_pd_od_mm: float
    monocular_pd_os_mm: float
    fitting_height_mm: float
    expedite_requested: bool
    prior_auth_reference: Optional[str]
    product_tier: str
    fulfillment_status: str
    billing_status: str
    tat_commitment_status: str
    quote_variant: str
    gross_charge_cents: int
    estimated_benefit_cents: int
    insurance_benefit_cents: int
    patient_portion_cents: int
    lab_writeoff_cents: int
    patient_paid_cents: int
    patient_balance_due_cents: int
    expedite_fee_cents: int
    promised_tat_hours: int
    promised_due_at: str
    benefit_applied_at: Optional[str]
    remake_count: int
    created_by_optician_id: str


class FrameLayout(CommonFields):
    rx_order_id: str
    trace_source: str
    a_mm: float
    b_mm: float
    ed_mm: float
    dbl_mm: float
    fitting_height_override_mm: Optional[float]
    effective_fitting_height_mm: float
    decentration_h_od_mm: float
    decentration_h_os_mm: float
    decentration_v_mm: float
    required_blank_diameter_mm: float
    layout_status: str


class LabJob(CommonFields):
    rx_order_id: str
    frame_layout_id: str
    blank_lot_id: Optional[str]
    route: str
    status: str
    rework_cycle_count: int
    breakage_count: int
    released_at: Optional[str]
    scrap_reason: Optional[str]


class LabOperation(CommonFields):
    lab_job_id: str
    operation_type: str
    machine_id: Optional[str]
    bay_id: Optional[str]
    blank_lot_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    performed_by_user_id: Optional[str]
    breakage_reason: Optional[str]
    cancel_reason: Optional[str]


class QualityInspection(TypedDict):
    """Append-only event row: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    lab_job_id: str
    eye: str
    cycle_index: int
    tolerance_standard_id: str
    measured_sphere: float
    measured_cylinder: float
    measured_axis: int
    measured_prism: float
    cosmetic_defect_codes: List[str]
    sphere_delta: float
    cylinder_delta: float
    axis_delta: int
    prism_delta: float
    failed_metrics: List[str]
    verdict: str
    inspector_user_id: str


class RemakeCase(CommonFields):
    rx_order_id: str
    lab_job_id: str
    quality_inspection_id: Optional[str]
    defect_codes: List[str]
    warranty_claim: bool
    warranty_covered: bool
    status: str
    responsibility: str
    adjudication_method: Optional[str]
    lab_share_pct: Optional[int]
    lab_chargeback_cents: int


class SettlementEntry(TypedDict):
    """Append-only event row: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    rx_order_id: str
    entry_type: str
    amount_cents: int
    memo: str
    effective_at: str


class ChargeSummary(TypedDict):
    gross_charge_cents: int
    estimated_benefit_cents: int
    insurance_benefit_cents: int
    patient_portion_cents: int
    lab_writeoff_cents: int
    patient_paid_cents: int
    patient_balance_due_cents: int
    expedite_fee_cents: int
    quote_variant: str
    invariant_holds: bool


JsonDict = dict[str, Any]
