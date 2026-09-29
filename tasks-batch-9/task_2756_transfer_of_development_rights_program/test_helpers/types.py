"""Domain types for the Transfer of Development Rights (TDR) program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    SEVERANCE_REVIEWER = "SeveranceReviewer"
    DESIGN_REVIEW_BOARD = "DesignReviewBoard"
    EASEMENT_MONITOR = "EasementMonitor"
    LANDOWNER = "Landowner"
    DEVELOPER = "Developer"


class PartyKind(str, Enum):
    LANDOWNER = "LANDOWNER"
    DEVELOPER = "DEVELOPER"
    MUNICIPAL_BANK = "MUNICIPAL_BANK"


class PartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountAction(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class SendingAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ReceivingAreaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AllocationFormulaVersion(str, Enum):
    V1_NET_ACRE = "V1_NET_ACRE"
    V2_GROSS_DISCOUNTED = "V2_GROSS_DISCOUNTED"


class EquityTier(str, Enum):
    HIGH_VALUE = "HIGH_VALUE"
    MODERATE = "MODERATE"
    UNDERSERVED = "UNDERSERVED"


class AppraisalScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SoilClass(str, Enum):
    PRIME = "PRIME"
    STATEWIDE = "STATEWIDE"
    LOCAL = "LOCAL"
    NONE = "NONE"


class ParcelStatus(str, Enum):
    UNSEVERED = "UNSEVERED"
    PARTIALLY_SEVERED = "PARTIALLY_SEVERED"
    FULLY_SEVERED = "FULLY_SEVERED"


class ParcelEasementStatus(str, Enum):
    NONE = "NONE"
    RECORDED = "RECORDED"


class SeveranceApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUIRE_REVISION = "REQUIRE_REVISION"
    DENY = "DENY"


class RecordingStatus(str, Enum):
    PENDING_RECORDING = "PENDING_RECORDING"
    RECORDED = "RECORDED"
    AMENDED = "AMENDED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION_NOTICED = "VIOLATION_NOTICED"
    UNDER_CURE = "UNDER_CURE"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class CertificateLifecycleStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    REDEEMED = "REDEEMED"
    RETIRED = "RETIRED"


class CertificateMarketStatus(str, Enum):
    HELD = "HELD"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    FROZEN = "FROZEN"


class TransferType(str, Enum):
    ISSUANCE = "ISSUANCE"
    PRIVATE_SALE = "PRIVATE_SALE"
    BANK_PURCHASE = "BANK_PURCHASE"
    BANK_RESALE = "BANK_RESALE"
    SPLIT_OUT = "SPLIT_OUT"
    REDEMPTION = "REDEMPTION"
    RETIREMENT = "RETIREMENT"
    REVERSAL = "REVERSAL"


class MarketChannel(str, Enum):
    PRIVATE = "PRIVATE"
    BANK_PURCHASE = "BANK_PURCHASE"
    BANK_RESALE = "BANK_RESALE"


class ConveyanceMode(str, Enum):
    WHOLE = "WHOLE"
    PARTIAL = "PARTIAL"


class MarketTransactionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class ReceivingSiteApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    REVISIONS_REQUIRED = "REVISIONS_REQUIRED"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    BACKING_DEFICIENT = "BACKING_DEFICIENT"
    FINALIZED = "FINALIZED"
    DENIED = "DENIED"


class DesignReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUIRE_REVISIONS = "REQUIRE_REVISIONS"
    DENY = "DENY"


class RedemptionStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    HELD_PENDING_COMPLIANCE = "HELD_PENDING_COMPLIANCE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class InspectionFinding(str, Enum):
    COMPLIANT = "COMPLIANT"
    MINOR_VIOLATION = "MINOR_VIOLATION"
    MAJOR_VIOLATION = "MAJOR_VIOLATION"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    CURE_PENDING = "CURE_PENDING"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class CureOutcome(str, Enum):
    CURED = "CURED"
    CURE_IN_PROGRESS = "CURE_IN_PROGRESS"


class EquityWeighting(str, Enum):
    ACREAGE_WEIGHTED = "ACREAGE_WEIGHTED"
    PARCEL_COUNT_WEIGHTED = "PARCEL_COUNT_WEIGHTED"


class EvaluationStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SUPERSEDED = "SUPERSEDED"


# ── Entity shapes ───────────────────────────────────────────────────────────
# Every entity except CertificateTransfer carries id, created_at, updated_at
# and version.  CertificateTransfer is append-only: it carries only id and
# created_at.


class Party(TypedDict):
    id: str
    kind: str
    legal_name: str
    contact_email: str
    neighborhood_code: Optional[str]
    cash_balance_cents: int
    fee_revenue_cents: int
    units_held: int
    certificates_held_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SendingArea(TypedDict):
    id: str
    code: str
    name: str
    neighborhood_code: str
    allocation_formula_version: str
    base_rate_units_per_acre: float
    gross_discount_factor: float
    equity_tier: str
    sending_cap_units: int
    severed_units_total: int
    issued_certificate_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReceivingArea(TypedDict):
    id: str
    code: str
    name: str
    neighborhood_code: str
    base_density_units_per_acre: float
    max_bonus_pct: float
    absorption_cap_units: int
    design_review_required: bool
    eligible_sending_area_codes: List[str]
    absorbed_units: int
    reserved_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppraisalSchedule(TypedDict):
    id: str
    neighborhood_code: str
    per_unit_value_cents: int
    equity_adjustment_bps: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SendingParcel(TypedDict):
    id: str
    owner_party_id: str
    sending_area_id: str
    apn: str
    gross_acres: float
    constrained_acres: float
    soil_class: str
    existing_dwelling_units: int
    baseline_allocation_units: int
    severed_units: int
    remaining_units: int
    restricted_acres: float
    easement_status: str
    parcel_status: str
    created_at: str
    updated_at: str
    version: int


class SeveranceApplication(TypedDict):
    id: str
    sending_parcel_id: str
    applicant_party_id: str
    requested_units: int
    status: str
    revision_round: int
    screened_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    allocated_units: Optional[int]
    applied_formula_version: Optional[str]
    residual_units_retained: Optional[int]
    decision_note: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConservationEasement(TypedDict):
    id: str
    sending_parcel_id: str
    severance_application_id: str
    recording_reference: str
    restricted_acres: float
    permitted_residual_units: int
    units_issued_total: int
    units_redeemed_confirmed: int
    units_retired: int
    units_outstanding: int
    amendment_count: int
    recording_status: str
    compliance_status: str
    recorded_at: Optional[str]
    last_inspection_at: Optional[str]
    prior_violation_count: int
    cure_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    conservation_easement_id: str
    holder_party_id: str
    parent_certificate_id: Optional[str]
    origin_sending_area_id: str
    serial_number: str
    origin_neighborhood_code: str
    generation: int
    split_count: int
    units_face: int
    units_remaining: int
    units_split_out: int
    units_encumbered: int
    units_redeemed: int
    units_retired: int
    lifecycle_status: str
    market_status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class CertificateTransfer(TypedDict):
    # Append-only chain-of-title row: no updated_at and no version.
    id: str
    certificate_id: str
    from_party_id: Optional[str]
    to_party_id: Optional[str]
    market_transaction_id: Optional[str]
    seq_no: int
    transfer_type: str
    units: int
    price_cents: Optional[int]
    recorded_at: str
    created_at: str


class MarketTransaction(TypedDict):
    id: str
    certificate_id: str
    seller_party_id: str
    buyer_party_id: str
    channel: str
    units: int
    agreed_price_cents: Optional[int]
    applied_neighborhood_code: str
    applied_per_unit_value_cents: int
    appraised_reference_cents: int
    gross_price_cents: int
    price_deviation_bps: int
    program_fee_cents: int
    equity_surcharge_cents: int
    net_to_seller_cents: int
    status: str
    conveyance_mode: Optional[str]
    conveyed_certificate_id: Optional[str]
    settled_at: Optional[str]
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReceivingSiteApplication(TypedDict):
    id: str
    developer_party_id: str
    receiving_area_id: str
    site_acres: float
    requested_bonus_units: int
    base_units: int
    max_bonus_units: int
    required_backing_units: int
    provisional_bonus_units: int
    allocated_bonus_units: int
    backed_units: int
    pending_backed_units: int
    design_review_round: int
    design_reviewed_by_user_id: Optional[str]
    status: str
    finalized_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificateRedemption(TypedDict):
    id: str
    receiving_site_application_id: str
    certificate_id: str
    source_easement_id: str
    units: int
    status: str
    allocated_at: str
    confirmed_at: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringInspection(TypedDict):
    id: str
    conservation_easement_id: str
    inspector_user_id: str
    inspection_date: str
    finding: str
    affected_acres: float
    severity_score: float
    cure_deadline: Optional[str]
    status: str
    cure_verified_at: Optional[str]
    cure_verified_by_user_id: Optional[str]
    escalated_at: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramEvaluation(TypedDict):
    id: str
    period_start: str
    period_end: str
    equity_weighting: str
    preserved_acres: float
    easement_count: int
    issued_units: int
    redeemed_units: int
    retired_units: int
    absorption_pct: float
    equity_index: float
    outstanding_units: int
    total_cash_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
