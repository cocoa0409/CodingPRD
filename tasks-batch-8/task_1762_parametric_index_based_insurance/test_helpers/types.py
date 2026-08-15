"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class IndexStatus(str, Enum):
    PENDING_AGREEMENT = "PENDING_AGREEMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class StationStatus(str, Enum):
    COMMISSIONED = "COMMISSIONED"
    OFFLINE = "OFFLINE"
    DECOMMISSIONED = "DECOMMISSIONED"


class StationKind(str, Enum):
    PHYSICAL_STATION = "PHYSICAL_STATION"
    GRID_MODEL = "GRID_MODEL"


class SourcePriorityMode(str, Enum):
    STATION_PRIMARY = "STATION_PRIMARY"
    MODEL_PRIMARY = "MODEL_PRIMARY"


class StrikeDirection(str, Enum):
    BELOW = "BELOW"
    ABOVE = "ABOVE"


class HolderStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"


class PolicyLifecycle(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SettlementPosture(str, Enum):
    CLEAR = "CLEAR"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    SETTLED_QUIET = "SETTLED_QUIET"


class EventStatus(str, Enum):
    DETECTED = "DETECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ANNULLED = "ANNULLED"


class VerificationMethod(str, Enum):
    STATION_VERIFIED = "STATION_VERIFIED"
    MODEL_FALLBACK = "MODEL_FALLBACK"


class ClaimStatus(str, Enum):
    GENERATED = "GENERATED"
    ADJUSTED = "ADJUSTED"
    APPROVED = "APPROVED"
    FRAUD_HOLD = "FRAUD_HOLD"
    PAID = "PAID"
    RECOVERY_CEDED = "RECOVERY_CEDED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DisputeReason(str, Enum):
    BASIS_RISK_MISMATCH = "BASIS_RISK_MISMATCH"
    DATA_SOURCE_ERROR = "DATA_SOURCE_ERROR"
    THRESHOLD_BOUNDARY = "THRESHOLD_BOUNDARY"
    LATE_REVISION = "LATE_REVISION"


class DisputeResolution(str, Enum):
    NONE = "NONE"
    UPHELD = "UPHELD"
    PARTIAL_UPHELD = "PARTIAL_UPHELD"
    DENIED = "DENIED"


class TreatyStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    COMMUTED = "COMMUTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class RegulatoryClassification(str, Enum):
    ADMITTED_INSURANCE = "ADMITTED_INSURANCE"
    SURPLUS_LINES = "SURPLUS_LINES"
    DERIVATIVE_CONTRACT = "DERIVATIVE_CONTRACT"


class PerilType(str, Enum):
    RAINFALL_DEFICIT = "RAINFALL_DEFICIT"
    WINDSPEED = "WINDSPEED"
    EARTHQUAKE_MAGNITUDE = "EARTHQUAKE_MAGNITUDE"
    TEMPERATURE_EXCESS = "TEMPERATURE_EXCESS"


class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    ACTUARY = "Actuary"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    TREASURY_OFFICER = "TreasuryOfficer"
    FRAUD_ANALYST = "FraudAnalyst"
    DATA_OPERATIONS = "DataOperations"
    SERVICING_AGENT = "ServicingAgent"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# IndexObservation is the single append-only exception: id + created_at only.


class InsuranceProgram(TypedDict, total=False):
    id: str
    program_code: str
    peril_type: str
    regulatory_classification: str
    contract_wording_version: str
    exposure_limit_cents: int
    gross_written_premium_cents: int
    incurred_claims_cents: int
    ceded_recovery_cents: int
    net_retained_exposure_cents: int
    fraud_alert_count: int
    reporting_epoch: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IndexDefinition(TypedDict, total=False):
    id: str
    program_id: str
    index_code: str
    measurement_unit: str
    aggregation_window_days: int
    data_source_agreement_ref: str
    source_priority_mode: str
    trigger_thresholds: list
    strike_direction: str
    historical_breach_frequency: float
    expected_loss_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasurementStation(TypedDict, total=False):
    id: str
    program_id: str
    station_code: str
    station_kind: str
    reliability_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class IndexObservation(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at (no updated_at, no version).
    id: str
    index_definition_id: str
    station_id: str
    window_end_date: str
    measured_value: float
    sequence_no: int
    supersedes_observation_id: Optional[str]
    is_effective: bool
    created_at: str


class Policyholder(TypedDict, total=False):
    id: str
    program_id: str
    legal_name: str
    tax_id: str
    basis_risk_disclosure_acknowledged: bool
    fraud_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ParametricPolicy(TypedDict, total=False):
    id: str
    policyholder_id: str
    program_id: str
    index_definition_id: str
    sum_insured_cents: int
    policy_start_date: str
    policy_end_date: str
    premium_cents: int
    premium_tax_cents: int
    lifecycle_status: str
    settlement_posture: str
    created_at: str
    updated_at: str
    version: int


class TriggerEvent(TypedDict, total=False):
    id: str
    index_definition_id: str
    program_id: str
    window_end_date: str
    blended_index_value: float
    max_tier_breached: int
    verification_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutClaim(TypedDict, total=False):
    id: str
    policy_id: str
    trigger_event_id: str
    tier_applied: int
    provisional_payout_cents: int
    final_payout_cents: int
    ceded_recovery_cents: int
    net_payment_cents: int
    approver_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict, total=False):
    id: str
    claim_id: str
    opened_by_role: str
    dispute_reason: str
    claimed_tier: int
    resolution: str
    adjustment_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinsuranceTreaty(TypedDict, total=False):
    id: str
    program_id: str
    treaty_name: str
    ceded_percentage: float
    attachment_point_cents: int
    treaty_limit_cents: int
    recovered_to_date_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict, total=False):
    id: str
    policy_id: str
    invoice_amount_cents: int
    amount_paid_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
