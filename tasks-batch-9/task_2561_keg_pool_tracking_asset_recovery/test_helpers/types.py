"""Domain types for the keg pool tracking and asset recovery API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Append-only records (scan events and commodity index rows)
deliberately omit ``updated_at`` and ``version``: the PRD declares that those
rows are immutable and carry only an identifier and a creation timestamp.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    POOL_OPERATOR = "PoolOperator"
    BREWER = "Brewer"
    DISTRIBUTOR = "Distributor"
    SERVICE_TECHNICIAN = "ServiceTechnician"
    ASSET_RECOVERY_ANALYST = "AssetRecoveryAnalyst"


class BrewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class DistributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CooperationTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PoolPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CustodyState(str, Enum):
    IN_FLOAT = "IN_FLOAT"
    ISSUED_TO_BREWER = "ISSUED_TO_BREWER"
    FILLED = "FILLED"
    IN_TRADE = "IN_TRADE"
    AT_RETAIL = "AT_RETAIL"
    IN_SERVICE = "IN_SERVICE"
    QUARANTINED = "QUARANTINED"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    LOST = "LOST"
    STOLEN = "STOLEN"
    SCRAPPED = "SCRAPPED"


class ServiceState(str, Enum):
    SERVICE_OK = "SERVICE_OK"
    SERVICE_DUE = "SERVICE_DUE"
    SERVICE_OVERDUE = "SERVICE_OVERDUE"
    SERVICE_FAILED = "SERVICE_FAILED"


class DwellFlag(str, Enum):
    WITHIN_LIMIT = "WITHIN_LIMIT"
    APPROACHING = "APPROACHING"
    OVERDUE = "OVERDUE"


class ScanPoint(str, Enum):
    FILL = "FILL"
    DISTRIBUTION = "DISTRIBUTION"
    RETAIL = "RETAIL"
    RETURN = "RETURN"


class PartyType(str, Enum):
    BREWER = "BREWER"
    DISTRIBUTOR = "DISTRIBUTOR"
    RETAIL_ACCOUNT = "RETAIL_ACCOUNT"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class FloatPosture(str, Enum):
    HEALTHY = "HEALTHY"
    TIGHT = "TIGHT"
    SUSPENDED = "SUSPENDED"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class ServiceStage(str, Enum):
    RECEIVED = "RECEIVED"
    CLEANED = "CLEANED"
    INSPECTED = "INSPECTED"
    PRESSURE_TESTED = "PRESSURE_TESTED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class ServiceStep(str, Enum):
    CLEAN = "CLEAN"
    INSPECT = "INSPECT"
    PRESSURE_TEST = "PRESSURE_TEST"


class InspectionResult(str, Enum):
    PASS = "PASS"
    MINOR_DEFECT = "MINOR_DEFECT"
    MAJOR_DEFECT = "MAJOR_DEFECT"


class PressureTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LossCause(str, Enum):
    LOST_IN_TRADE = "LOST_IN_TRADE"
    DAMAGED_BEYOND_REPAIR = "DAMAGED_BEYOND_REPAIR"
    NOT_RETURNED_DWELL = "NOT_RETURNED_DWELL"
    STOLEN_SUSPECTED = "STOLEN_SUSPECTED"


class AssessmentBasis(str, Enum):
    REPLACEMENT_COST = "REPLACEMENT_COST"
    DEPRECIATED_BOOK = "DEPRECIATED_BOOK"


class AssessmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    SUPERSEDED = "SUPERSEDED"


class ChargebackStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClaimResponse(str, Enum):
    COUNTER = "COUNTER"
    AGREE = "AGREE"
    REJECT = "REJECT"
    WITHDRAW = "WITHDRAW"


class AccrualType(str, Enum):
    RETURN_DWELL = "RETURN_DWELL"
    RECONCILIATION_OFFSET = "RECONCILIATION_OFFSET"


class AccrualStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    CLOSED_RECOVERED = "CLOSED_RECOVERED"
    CLOSED_WRITTEN_OFF = "CLOSED_WRITTEN_OFF"


class InvestigationAction(str, Enum):
    EVIDENCE_HOLD = "EVIDENCE_HOLD"
    RESUME = "RESUME"
    CLOSE = "CLOSE"


class InvestigationOutcome(str, Enum):
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ChargebackAction(str, Enum):
    SETTLE = "SETTLE"
    REVERSE = "REVERSE"


class LossResolution(str, Enum):
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class LossRateBasis(str, Enum):
    TRAILING_90D = "TRAILING_90D"
    LIFETIME = "LIFETIME"


# --- Entity shapes -------------------------------------------------------
# Brewer, Distributor, KegPool, Keg, FloatAgreement, IssuanceOrder,
# ServiceCenter, ServiceCycle, LossAssessment, ReconciliationClaim,
# ReturnIncentiveAccrual and TheftInvestigation are mutable records and carry
# id, created_at, updated_at and version.  ScanEvent and CommodityIndex rows
# are immutable and carry only id and created_at.


class Brewer(TypedDict):
    id: str
    name: str
    brand_code: str
    status: str
    credit_limit_cents: int
    chargeback_balance_cents: int
    lifetime_fill_count: int
    upheld_loss_count: int
    loss_rate_bp_trailing_90d: int
    loss_rate_bp_lifetime: int
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    name: str
    region_code: str
    cooperation_tier: str
    return_incentive_rate_cents_per_keg: int
    status: str
    total_returns_count: int
    on_time_returns_count: int
    on_time_return_pct: float
    incentive_accrual_cents: int
    avg_dwell_days: float
    cooperation_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KegPool(TypedDict):
    id: str
    pool_code: str
    size_liters: int
    stainless_weight_kg: float
    replacement_cost_cents: int
    region_code: str
    restrict_threshold_pct: int
    freeze_threshold_pct: int
    restricted_max_kegs_per_order: int
    kegs_total: int
    kegs_available: int
    kegs_circulating: int
    kegs_servicing: int
    kegs_held: int
    kegs_written_off: int
    available_pct: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class Keg(TypedDict):
    id: str
    pool_id: str
    asset_tag: str
    custody_state: str
    service_state: str
    dwell_flag: str
    fill_count: int
    fills_at_last_pressure_test: int
    last_pressure_test_at: str
    current_brewer_id: Optional[str]
    current_distributor_id: Optional[str]
    filling_brewer_id: Optional[str]
    issuance_order_id: Optional[str]
    theft_investigation_id: Optional[str]
    filled_brand_code: Optional[str]
    dwell_started_at: Optional[str]
    distributor_custody_started_at: Optional[str]
    cumulative_dwell_days: int
    last_scanned_at: Optional[str]
    scan_count: int
    pre_hold_custody_state: Optional[str]
    misdelivery_open: bool
    assessment_open: bool
    stainless_scrap_value_cents: int
    created_at: str
    updated_at: str
    version: int


class ScanEvent(TypedDict):
    """Immutable scan record: no updated_at and no version."""

    id: str
    keg_id: str
    scan_point: str
    party_type: str
    brewer_id: Optional[str]
    distributor_id: Optional[str]
    retail_account_code: Optional[str]
    scanned_at: str
    recorded_at: str
    brand_code_scanned: str
    misdelivery_detected: bool
    is_late_arrival: bool
    custody_state_after: str
    dwell_days_closed: int
    fill_charge_net_cents: Optional[int]
    created_at: str


class FloatAgreement(TypedDict):
    id: str
    brewer_id: str
    pool_id: str
    float_size_kegs: int
    per_fill_rate_cents: int
    replenishment_threshold_pct: int
    min_fills_per_month: int
    effective_date: Optional[str]
    status: str
    float_posture: str
    kegs_issued_count: int
    kegs_at_brewer_count: int
    pending_replenishment_kegs: int
    billed_fills_count: int
    billed_amount_cents: int
    terminated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IssuanceOrder(TypedDict):
    id: str
    agreement_id: str
    brewer_id: str
    requested_keg_count: int
    allow_partial: bool
    status: str
    allocated_keg_count: int
    allocation_shortfall: int
    per_fill_price_cents_pinned: Optional[int]
    allocated_keg_ids: List[str]
    dispatched_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCenter(TypedDict):
    id: str
    name: str
    region_code: str
    concurrent_cycle_capacity: int
    intake_buffer_hours: int
    open_cycle_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceCycle(TypedDict):
    id: str
    keg_id: str
    service_center_id: str
    stage: str
    received_at: str
    cleaned_at: Optional[str]
    caustic_cycle_minutes: Optional[int]
    inspected_at: Optional[str]
    inspection_result: Optional[str]
    pressure_tested_at: Optional[str]
    pressure_test_psi: Optional[float]
    pressure_test_result: Optional[str]
    pressure_test_performed_by_user_id: Optional[str]
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LossAssessment(TypedDict):
    id: str
    keg_id: str
    brewer_id: Optional[str]
    commodity_index_id: str
    theft_investigation_id: Optional[str]
    cause: str
    assessment_basis: str
    gross_value_cents: int
    scrap_credit_cents: int
    assessed_value_cents: int
    brewer_liability_pct_bp: int
    net_chargeback_cents: int
    dwell_days_at_assessment: int
    assessment_status: str
    chargeback_status: str
    settled_amount_cents: Optional[int]
    created_by_user_id: str
    resolved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationClaim(TypedDict):
    id: str
    keg_id: str
    claimant_distributor_id: str
    owning_brewer_id: str
    misdelivered_to_brewer_id: str
    supersedes_claim_id: Optional[str]
    evidence_scanned_at: str
    claimed_offset_cents: int
    counter_offset_cents: Optional[int]
    agreed_offset_cents: Optional[int]
    round_count: int
    status: str
    last_responder_role: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnIncentiveAccrual(TypedDict):
    id: str
    distributor_id: str
    keg_id: str
    claim_id: Optional[str]
    accrual_type: str
    dwell_days: int
    tier_pct_bp: Optional[int]
    cooperation_multiplier_bp: Optional[int]
    incentive_cents: int
    triggering_scanned_at: Optional[str]
    status: str
    paid_at: Optional[str]
    clawback_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TheftInvestigation(TypedDict):
    id: str
    pool_id: str
    suspect_distributor_id: Optional[str]
    commodity_index_id: str
    status: str
    held_keg_count: int
    attached_keg_count: int
    stainless_value_at_risk_cents: int
    opened_reason: str
    opened_by_user_id: str
    hold_started_at: Optional[str]
    closed_at: Optional[str]
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommodityIndex(TypedDict):
    """Immutable index reading: no updated_at and no version."""

    id: str
    effective_date: str
    usd_cents_per_kg: int
    source: str
    created_at: str


class DwellRead(TypedDict):
    """Computed dwell read; not a stored record."""

    keg_id: str
    custody_state: str
    brewer_spell_days: int
    distributor_spell_days: int
    limit_days: Optional[int]
    approaching_days: Optional[int]
    dwell_flag: str
    cumulative_dwell_days: int
    dwell_started_at: Optional[str]
    distributor_custody_started_at: Optional[str]


class LossRateRead(TypedDict):
    """Computed loss-rate read; not a stored record."""

    brewer_id: str
    basis: str
    loss_rate_bp: int
    upheld_loss_count: int
    fill_count: int
    window_start: Optional[str]
    window_end: Optional[str]
    basis_insufficient: bool


class ReplenishmentSweep(TypedDict):
    """Computed sweep report; not a stored record."""

    pool_id: str
    swept_keg_count: int
    approaching_keg_count: int
    overdue_keg_count: int
    available_pct: float
    posture: str
    tight_agreement_ids: List[str]
    suspended_agreement_ids: List[str]
    pending_replenishment_kegs_total: int
