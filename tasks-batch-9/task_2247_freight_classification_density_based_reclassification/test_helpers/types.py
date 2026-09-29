"""Domain types for the LTL Freight Classification API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Two resources -- the capture event and the credit memo -- are
append-only records and therefore carry only ``id`` and ``created_at``; their
TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    PRICING_ANALYST = "PricingAnalyst"
    TERMINAL_OPERATOR = "TerminalOperator"
    FREIGHT_INSPECTOR = "FreightInspector"
    CLASSIFICATION_AUDITOR = "ClassificationAuditor"
    DISPUTE_REVIEWER = "DisputeReviewer"
    SHIPPER = "Shipper"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class DimensionerStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    OUT_OF_CALIBRATION = "OUT_OF_CALIBRATION"


class BillingPosture(str, Enum):
    OPEN = "OPEN"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class EducationStatus(str, Enum):
    NONE = "NONE"
    REQUIRED = "REQUIRED"
    COMPLETED = "COMPLETED"


class OffenderTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class TariffVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ClassificationBasis(str, Enum):
    DENSITY_BASED = "DENSITY_BASED"
    FIXED_CLASS = "FIXED_CLASS"


class HandlingCode(str, Enum):
    STANDARD = "STANDARD"
    FRAGILE = "FRAGILE"
    HAZMAT = "HAZMAT"
    OVERLENGTH = "OVERLENGTH"


class StowabilityCode(str, Enum):
    STACKABLE = "STACKABLE"
    NON_STACKABLE = "NON_STACKABLE"
    HAZ_SEGREGATED = "HAZ_SEGREGATED"


class LiabilityCode(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RateProgramStatus(str, Enum):
    MODELING = "MODELING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProgramType(str, Enum):
    CLASS_BASED = "CLASS_BASED"
    DENSITY_BASED = "DENSITY_BASED"
    FAK = "FAK"


class MigrationRecommendation(str, Enum):
    MIGRATE_DENSITY_BASED = "MIGRATE_DENSITY_BASED"
    HOLD_CLASS_BASED = "HOLD_CLASS_BASED"
    NEGOTIATE_FAK = "NEGOTIATE_FAK"


class ExceptionAgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class AgreementType(str, Enum):
    EXCEPTION_CLASS = "EXCEPTION_CLASS"
    FAK = "FAK"


class ClassStatus(str, Enum):
    DECLARED = "DECLARED"
    CAPTURED = "CAPTURED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    RECLASS_PENDING = "RECLASS_PENDING"
    RECLASSED = "RECLASSED"
    CLASS_CONFIRMED = "CLASS_CONFIRMED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    REBILLED = "REBILLED"
    CREDITED = "CREDITED"
    CLOSED = "CLOSED"


class ClassificationSource(str, Enum):
    BOL_DECLARED = "BOL_DECLARED"
    FIXED_CLASS = "FIXED_CLASS"
    DIMENSIONER = "DIMENSIONER"
    INSPECTION = "INSPECTION"
    EXCEPTION_AGREEMENT = "EXCEPTION_AGREEMENT"
    FAK = "FAK"


class DeviceType(str, Enum):
    DIMENSIONER = "DIMENSIONER"
    SCALE = "SCALE"
    COMBINED = "COMBINED"


class InspectionFindingStatus(str, Enum):
    RECORDED = "RECORDED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class FindingBasis(str, Enum):
    DENSITY = "DENSITY"
    STOWABILITY = "STOWABILITY"
    HANDLING = "HANDLING"
    LIABILITY = "LIABILITY"
    COMMODITY_MISMATCH = "COMMODITY_MISMATCH"


class CorrectionNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    UPHELD = "UPHELD"
    PARTIALLY_OVERTURNED = "PARTIALLY_OVERTURNED"
    OVERTURNED = "OVERTURNED"
    VOID = "VOID"


class NoticeType(str, Enum):
    REWEIGH = "REWEIGH"
    RECLASS = "RECLASS"
    BOTH = "BOTH"


class NoticeOrigin(str, Enum):
    AUTOMATED_CAPTURE = "AUTOMATED_CAPTURE"
    AUDITOR_MANUAL = "AUDITOR_MANUAL"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    SUPPLEMENT_REQUESTED = "SUPPLEMENT_REQUESTED"
    SUPPLEMENTED = "SUPPLEMENTED"
    RESOLVED = "RESOLVED"


class ClaimBasis(str, Enum):
    DENSITY_RECOMPUTE = "DENSITY_RECOMPUTE"
    EXCEPTION_AGREEMENT = "EXCEPTION_AGREEMENT"
    DEVICE_CALIBRATION = "DEVICE_CALIBRATION"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"


class DisputeOutcome(str, Enum):
    UPHELD_CARRIER = "UPHELD_CARRIER"
    PARTIAL = "PARTIAL"
    OVERTURNED = "OVERTURNED"


class CreditMemoReason(str, Enum):
    FULL_OVERTURN = "FULL_OVERTURN"
    PARTIAL_OVERTURN = "PARTIAL_OVERTURN"


class RepricingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"
    COMMITTED = "COMMITTED"


class RepricingScope(str, Enum):
    ALL_CLASS_BASED = "ALL_CLASS_BASED"
    ALL_DENSITY_BASED = "ALL_DENSITY_BASED"
    ALL_ACTIVE = "ALL_ACTIVE"


# --------------------------------------------------------------------------
# Entity shapes -- resources carrying id/created_at/updated_at/version
# --------------------------------------------------------------------------

class Terminal(TypedDict):
    id: str
    code: str
    name: str
    calibration_interval_captures: int
    captures_since_calibration: int
    dimensioner_status: str
    last_capture_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    account_code: str
    name: str
    billing_posture: str
    education_status: str
    education_strike_interval: int
    education_threshold_strikes: int
    education_required_at: Optional[str]
    offender_strike_count: int
    liability_index_rolling: float
    liability_index_lifetime: float
    offender_tier: str
    dispute_window_days: int
    active_program_type: Optional[str]
    active_rate_program_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DensityBreak(TypedDict):
    min_density_pcf: float
    class_code: float


class TariffVersion(TypedDict):
    id: str
    code: str
    effective_at: str
    density_breaks: List[DensityBreak]
    status: str
    published_at: Optional[str]
    superseded_by_tariff_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommodityProfile(TypedDict):
    id: str
    tariff_version_id: str
    nmfc_item: str
    description: str
    classification_basis: str
    fixed_class_code: Optional[float]
    handling_code: str
    stowability_code: str
    liability_code: str
    min_class_floor: float
    created_at: str
    updated_at: str
    version: int


class RateProgram(TypedDict):
    id: str
    customer_id: str
    program_type: str
    base_rate_per_cwt_cents: int
    discount_pct: float
    min_charge_cents: int
    fak_class_code: Optional[float]
    status: str
    pinned_tariff_version_id: Optional[str]
    effective_from: Optional[str]
    effective_to: Optional[str]
    baseline_revenue_cents: int
    modeled_annual_revenue_cents: int
    modeled_shipment_count: int
    modeled_delta_pct: float
    migration_recommendation: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExceptionAgreement(TypedDict):
    id: str
    customer_id: str
    commodity_profile_id: str
    agreement_type: str
    agreed_class_code: float
    effective_from: str
    effective_to: str
    status: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    customer_id: str
    origin_terminal_id: str
    pro_number: str
    pickup_at: str
    bol_declared_total_weight_lb: int
    rate_program_id: str
    tariff_version_id: str
    class_status: str
    billing_status: str
    line_count: int
    declared_total_weight_lb: int
    measured_total_weight_lb: Optional[int]
    weight_variance_pct: Optional[float]
    reweigh_required: bool
    declared_vs_found_class_delta_count: int
    original_charge_cents: int
    assessed_total_cents: int
    open_notice_count: int
    billed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict):
    id: str
    shipment_id: str
    line_no: int
    commodity_profile_id: str
    declared_class_code: float
    declared_weight_lb: int
    pieces: int
    declared_length_in: float
    declared_width_in: float
    declared_height_in: float
    declared_cubic_ft: float
    declared_density_pcf: float
    measured_weight_lb: Optional[int]
    measured_length_in: Optional[float]
    measured_width_in: Optional[float]
    measured_height_in: Optional[float]
    measured_cubic_ft: Optional[float]
    measured_density_pcf: Optional[float]
    found_class_code: Optional[float]
    effective_class_code: float
    classification_source: str
    class_floor_applied: bool
    line_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict):
    id: str
    shipment_line_id: str
    finding_basis: str
    found_class_code: float
    found_commodity_profile_id: Optional[str]
    evidence_photo_count: int
    notes: Optional[str]
    status: str
    inspector_user_id: str
    accepted_by_user_id: Optional[str]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectionNotice(TypedDict):
    id: str
    shipment_id: str
    notice_type: str
    origin: str
    status: str
    basis_capture_event_id: Optional[str]
    supersedes_notice_id: Optional[str]
    superseded_by_notice_id: Optional[str]
    provisional_delta_cents: int
    final_delta_cents: int
    applied_delta_cents: int
    inspection_fee_cents: int
    evidence_bundle_count: int
    uses_inspection_findings: bool
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    dispute_deadline_at: Optional[str]
    dispute_round_count: int
    supplement_request_count: int
    credited_total_cents: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    correction_notice_id: str
    filed_by_customer_id: str
    claim_basis: str
    claimed_class_code: Optional[float]
    evidence_doc_count: int
    status: str
    round_no: int
    reviewer_user_id: Optional[str]
    outcome: Optional[str]
    outcome_class_code: Optional[float]
    resolution_note: Optional[str]
    filed_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepricingRun(TypedDict):
    id: str
    new_tariff_version_id: str
    scope: str
    sample_window_start_at: str
    sample_window_end_at: str
    status: str
    impacted_customer_count: int
    aggregate_delta_cents: int
    modeled_at: Optional[str]
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only records -- ONLY id + created_at (no updated_at, no version)
# --------------------------------------------------------------------------

class CaptureEvent(TypedDict):
    id: str
    shipment_id: str
    terminal_id: str
    device_type: str
    measured_total_weight_lb: int
    capture_sequence: int
    variance_pct: float
    triggered_reweigh: bool
    triggered_reclass: bool
    reclassed_line_count: int
    captured_at: str
    captured_by_user_id: str
    created_at: str


class CreditMemo(TypedDict):
    id: str
    correction_notice_id: str
    customer_id: str
    reason: str
    freight_credit_cents: int
    fee_credit_cents: int
    interest_credit_cents: int
    amount_cents: int
    issued_at: str
    created_at: str
