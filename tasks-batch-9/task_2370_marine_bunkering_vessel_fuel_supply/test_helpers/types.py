"""Domain types for the Marine Bunkering & Vessel Fuel Supply API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────

class UserRole(str, Enum):
    OPS_COORDINATOR = "OpsCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SURVEYOR = "Surveyor"
    CREDIT_CONTROLLER = "CreditController"
    LAB_TECHNICIAN = "LabTechnician"
    CUSTOMER_REP = "CustomerRep"
    BARGE_MASTER = "BargeMaster"


# ─── Reference-data enums ─────────────────────────────

class SpillResponseTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CrossContaminationGroup(str, Enum):
    DISTILLATE = "DISTILLATE"
    RESIDUAL = "RESIDUAL"
    BIOBLEND = "BIOBLEND"


class QuoteSource(str, Enum):
    PLATTS = "PLATTS"
    ARGUS = "ARGUS"


class AssetType(str, Enum):
    BARGE = "BARGE"
    TRUCK = "TRUCK"


class DeliveryMode(str, Enum):
    BARGE = "BARGE"
    TRUCK = "TRUCK"


class SettlementBasis(str, Enum):
    SUPPLIER_FIGURES = "SUPPLIER_FIGURES"
    JOINT_SURVEY_MANDATORY = "JOINT_SURVEY_MANDATORY"


# ─── Status dimensions ────────────────────────────────

class CustomerCreditStatus(str, Enum):
    OK = "OK"
    WATCH = "WATCH"
    HOLD = "HOLD"


class DeliveryAssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"


class NominationComplianceStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class NominationFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    AWAITING_SCHEDULE = "AWAITING_SCHEDULE"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class OrderLogisticsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLEARED = "CLEARED"
    PUMPING = "PUMPING"
    DELIVERED = "DELIVERED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class OrderMeasurementStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    FIGURES_RECORDED = "FIGURES_RECORDED"
    RESURVEYED = "RESURVEYED"
    AGREED = "AGREED"
    DISPUTED = "DISPUTED"


class MeasurementBasis(str, Enum):
    SUPPLIER_FIGURES = "SUPPLIER_FIGURES"
    JOINT_SURVEY = "JOINT_SURVEY"


class BdnStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class SampleCustodyStatus(str, Enum):
    RETAINED = "RETAINED"
    RELEASED_TO_LAB = "RELEASED_TO_LAB"
    EXPIRED = "EXPIRED"


class ClaimedDefect(str, Enum):
    SULFUR_EXCEEDANCE = "SULFUR_EXCEEDANCE"
    WATER_CONTENT = "WATER_CONTENT"
    DENSITY_DEVIATION = "DENSITY_DEVIATION"


class QualityClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_ANALYSIS = "UNDER_ANALYSIS"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    REMEDIATION_ACCEPTED = "REMEDIATION_ACCEPTED"
    REJECTED = "REJECTED"


class RemediationType(str, Enum):
    PRICE_ALLOWANCE = "PRICE_ALLOWANCE"
    DEBUNKER = "DEBUNKER"


class LabVerdict(str, Enum):
    ON_SPEC = "ON_SPEC"
    OFF_SPEC = "OFF_SPEC"


class InvoiceStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ISSUED = "ISSUED"
    CREDIT_APPLIED = "CREDIT_APPLIED"
    VOID = "VOID"


class SpillSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class SpillIncidentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ─── Request-body decision enums ──────────────────────

class ComplianceDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REOPEN = "REOPEN"


class QuantityDecision(str, Enum):
    AGREE = "AGREE"
    DISPUTE = "DISPUTE"


class SurveyorClaimDecision(str, Enum):
    PROPOSE = "PROPOSE"
    REJECT = "REJECT"


# ─── Entity TypedDicts ────────────────────────────────
# Every resource carries id + created_at (PRD §2.5). All resources except index
# quotes additionally carry updated_at and version.

class Port(TypedDict):
    id: str
    port_code: str
    name: str
    eca_zone: bool
    eca_sulfur_limit_pct: float
    notice_lead_hours: int
    concurrent_ops_capacity: int
    spill_response_tier: str
    created_at: str
    updated_at: str
    version: int


class FuelGrade(TypedDict):
    id: str
    grade_code: str
    max_sulfur_pct: float
    eca_permitted: bool
    test_tolerance_pct: float
    index_code: str
    base_barging_rate_usd_per_mt: float
    min_barging_fee_usd: float
    cross_contamination_group: str
    created_at: str
    updated_at: str
    version: int


class IndexQuote(TypedDict):
    """An IndexQuote is immutable once posted: it carries only id and created_at
    — it has neither updated_at nor version (PRD §2.5)."""
    id: str
    grade_id: str
    quote_date: str
    price_usd_per_mt: float
    source: str
    created_at: str


class Customer(TypedDict):
    id: str
    name: str
    credit_limit_usd: float
    payment_terms_days: int
    settlement_basis: str
    credit_status: str
    outstanding_balance_usd: float
    conservative_exposure_usd: float
    available_credit_usd: float
    open_commitment_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryAsset(TypedDict):
    id: str
    name: str
    asset_type: str
    capacity_mt: float
    home_port_id: str
    boom_certified: bool
    segregated_tanks: bool
    turnaround_buffer_minutes: int
    last_grade_id: Optional[str]
    status: str
    committed_quantity_mt: float
    compliance_score: float
    created_at: str
    updated_at: str
    version: int


class Nomination(TypedDict):
    id: str
    customer_id: str
    port_id: str
    grade_id: str
    vessel_imo: str
    vessel_name: str
    scrubber_fitted: bool
    nominated_quantity_mt: float
    declared_sulfur_pct: float
    delivery_mode: str
    window_start: str
    window_end: str
    eca_documentation_ref: Optional[str]
    fulfillment_status: str
    compliance_status: str
    compliance_reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    nomination_id: str
    asset_id: str
    planned_quantity_mt: float
    slot_start: str
    slot_end: str
    logistics_status: str
    measurement_status: str
    port_clearance_ref: Optional[str]
    cleared_at: Optional[str]
    barge_sounding_mt: Optional[float]
    vessel_sounding_mt: Optional[float]
    meter_mt: Optional[float]
    surveyed_mt: Optional[float]
    agreed_quantity_mt: Optional[float]
    measurement_basis: Optional[str]
    shortfall_mt: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BunkerDeliveryNote(TypedDict):
    id: str
    delivery_order_id: str
    bdn_number: str
    declared_sulfur_pct: float
    sample_seal_number: str
    delivered_quantity_mt: float
    status: str
    issued_by_user_id: str
    sample_retention_until: str
    sample_custody_status: str
    sample_released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict):
    id: str
    bdn_id: str
    customer_id: str
    claimed_defect: str
    affected_quantity_mt: float
    quantity_basis_mt: float
    replacement_price_usd_per_mt: Optional[float]
    status: str
    analysis_round: int
    credit_usd: float
    remediation_type: Optional[str]
    proposed_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabAnalysis(TypedDict):
    id: str
    claim_id: str
    lab_ref: str
    measured_sulfur_pct: float
    retest_of_analysis_id: Optional[str]
    round_index: int
    verdict: str
    exceedance_pct: float
    analyzed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    delivery_order_id: str
    customer_id: str
    pricing_date: str
    quantity_basis_mt: float
    index_price_usd_per_mt: float
    baf_pct: float
    fuel_cost_usd: float
    baf_usd: float
    barging_fee_usd: float
    eca_surcharge_usd: float
    provisional_amount_usd: float
    claim_credit_usd: float
    final_amount_usd: float
    status: str
    issued_at: Optional[str]
    due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpillIncident(TypedDict):
    id: str
    delivery_order_id: str
    asset_id: str
    port_id: str
    reported_at: str
    volume_liters: float
    boom_deployed: bool
    severity: str
    penalty_points: float
    status: str
    containment_confirmed: bool
    response_ref: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "SpillResponseTier",
    "CrossContaminationGroup",
    "QuoteSource",
    "AssetType",
    "DeliveryMode",
    "SettlementBasis",
    "CustomerCreditStatus",
    "DeliveryAssetStatus",
    "NominationComplianceStatus",
    "NominationFulfillmentStatus",
    "OrderLogisticsStatus",
    "OrderMeasurementStatus",
    "MeasurementBasis",
    "BdnStatus",
    "SampleCustodyStatus",
    "ClaimedDefect",
    "QualityClaimStatus",
    "RemediationType",
    "LabVerdict",
    "InvoiceStatus",
    "SpillSeverity",
    "SpillIncidentStatus",
    "ComplianceDecision",
    "QuantityDecision",
    "SurveyorClaimDecision",
    "Port",
    "FuelGrade",
    "IndexQuote",
    "Customer",
    "DeliveryAsset",
    "Nomination",
    "DeliveryOrder",
    "BunkerDeliveryNote",
    "QualityClaim",
    "LabAnalysis",
    "Invoice",
    "SpillIncident",
]
