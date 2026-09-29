"""Domain types for the Dealer Floorplan Curtailment Audit API.

Entity TypedDicts, lifecycle enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DEALER_PRINCIPAL = "DealerPrincipal"
    CREDIT_OFFICER = "CreditOfficer"
    CREDIT_RISK_MANAGER = "CreditRiskManager"
    FIELD_AUDITOR = "FieldAuditor"
    AUDIT_MANAGER = "AuditManager"
    SYSTEM_OPERATOR = "SystemOperator"


# ---------------------------------------------------------------------------
# Lifecycle / classification enums
# ---------------------------------------------------------------------------
class DealerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"


class FranchiseType(str, Enum):
    FRANCHISE_NEW_CAR = "FRANCHISE_NEW_CAR"
    INDEPENDENT_USED = "INDEPENDENT_USED"
    POWERSPORTS = "POWERSPORTS"


class RiskRating(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class CovenantResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CovenantFailureReasonCode(str, Enum):
    CAPITAL = "CAPITAL"
    CASH_FLOW = "CASH_FLOW"
    OUT_OF_TRUST = "OUT_OF_TRUST"


class CreditLineStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SuspensionReasonCode(str, Enum):
    SOT_EXPOSURE_THRESHOLD = "SOT_EXPOSURE_THRESHOLD"
    COVENANT_BREACH_LIMIT = "COVENANT_BREACH_LIMIT"
    REMEDY_ACTION = "REMEDY_ACTION"


class InventoryClass(str, Enum):
    NEW = "NEW"
    USED = "USED"
    DEMONSTRATOR = "DEMONSTRATOR"


class TitleDocumentType(str, Enum):
    MSO = "MSO"
    TITLE = "TITLE"


class FundingStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PENDING_FUNDING = "PENDING_FUNDING"
    FLOORED = "FLOORED"
    DELINQUENT_CURTAILMENT = "DELINQUENT_CURTAILMENT"
    SOT_OPEN = "SOT_OPEN"
    PAID_OFF = "PAID_OFF"
    REPOSSESSED = "REPOSSESSED"


class TitleCustodyStatus(str, Enum):
    NOT_RECEIVED = "NOT_RECEIVED"
    LENDER_HELD = "LENDER_HELD"
    LOST = "LOST"
    RELEASED_FOR_SALE = "RELEASED_FOR_SALE"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE_DAMAGE = "INELIGIBLE_DAMAGE"
    INELIGIBLE_WHOLESALE = "INELIGIBLE_WHOLESALE"
    INELIGIBLE_MISSING = "INELIGIBLE_MISSING"
    INELIGIBLE_TITLE_DEFECT = "INELIGIBLE_TITLE_DEFECT"
    INELIGIBLE_SOLD_OUT_OF_TRUST = "INELIGIBLE_SOLD_OUT_OF_TRUST"


class IneligibilityReasonCode(str, Enum):
    DAMAGE = "DAMAGE"
    WHOLESALE = "WHOLESALE"
    MISSING = "MISSING"
    TITLE_DEFECT = "TITLE_DEFECT"
    SOLD_OUT_OF_TRUST = "SOLD_OUT_OF_TRUST"


class AdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FUNDED = "FUNDED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    REVERSED = "REVERSED"


class AdvanceReasonCode(str, Enum):
    CREDIT_DECLINE = "CREDIT_DECLINE"
    TITLE_DEFECT = "TITLE_DEFECT"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    LINE_SUSPENDED = "LINE_SUSPENDED"
    DEALER_REQUEST = "DEALER_REQUEST"
    FUNDING_ERROR = "FUNDING_ERROR"


class RateAdjustmentCode(str, Enum):
    HIGH_MILEAGE_DEMO = "HIGH_MILEAGE_DEMO"
    AGED_INVOICE = "AGED_INVOICE"


class ObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ExceptionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class JustificationCode(str, Enum):
    RETAIL_DEAL_PENDING = "RETAIL_DEAL_PENDING"
    TITLE_DELAY = "TITLE_DELAY"
    FLEET_ORDER = "FLEET_ORDER"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"


class ExceptionDecisionReasonCode(str, Enum):
    RELIEF_GRANTED = "RELIEF_GRANTED"
    INSUFFICIENT_JUSTIFICATION = "INSUFFICIENT_JUSTIFICATION"
    EXPOSURE_TOO_HIGH = "EXPOSURE_TOO_HIGH"
    DOCUMENTATION_MISSING = "DOCUMENTATION_MISSING"


class AuditType(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    UNANNOUNCED = "UNANNOUNCED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED_CLEAN = "RECONCILED_CLEAN"
    RECONCILED_EXCEPTIONS = "RECONCILED_EXCEPTIONS"
    ABORTED = "ABORTED"


class AbortReasonCode(str, Enum):
    DEALER_UNAVAILABLE = "DEALER_UNAVAILABLE"
    AUDITOR_REASSIGNED = "AUDITOR_REASSIGNED"
    DATA_ERROR = "DATA_ERROR"


class ObservedCondition(str, Enum):
    PRESENT = "PRESENT"
    PRESENT_DAMAGED = "PRESENT_DAMAGED"
    SOLD_NO_PAYOFF = "SOLD_NO_PAYOFF"
    WHOLESALED = "WHOLESALED"
    MISSING = "MISSING"


class ObservationClassification(str, Enum):
    VERIFIED = "VERIFIED"
    TITLE_EXCEPTION = "TITLE_EXCEPTION"
    DAMAGE_EXCEPTION = "DAMAGE_EXCEPTION"
    WHOLESALE_EXCEPTION = "WHOLESALE_EXCEPTION"
    SOLD_OUT_OF_TRUST = "SOLD_OUT_OF_TRUST"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    CHARGED_OFF = "CHARGED_OFF"


class IncidentResolutionReasonCode(str, Enum):
    DEALER_PAYOFF = "DEALER_PAYOFF"
    REPOSSESSION_CHARGE_OFF = "REPOSSESSION_CHARGE_OFF"


class RemittanceIntent(str, Enum):
    CURTAILMENT = "CURTAILMENT"
    PRINCIPAL_PREPAYMENT = "PRINCIPAL_PREPAYMENT"
    UNIT_PAYOFF = "UNIT_PAYOFF"
    SOT_CURE = "SOT_CURE"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"


class RemedyActionType(str, Enum):
    LINE_SUSPENSION = "LINE_SUSPENSION"
    REPOSSESSION = "REPOSSESSION"
    LINE_TERMINATION = "LINE_TERMINATION"


class RemedyStatus(str, Enum):
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"


class RemedyReasonCode(str, Enum):
    SOT_INCIDENT = "SOT_INCIDENT"
    COVENANT_BREACH = "COVENANT_BREACH"
    CURTAILMENT_DELINQUENCY = "CURTAILMENT_DELINQUENCY"


# ---------------------------------------------------------------------------
# Entity shapes.  Resources that the PRD says carry only an id and a
# created_at deliberately omit updated_at and version.
# ---------------------------------------------------------------------------
class Dealer(TypedDict):
    id: str
    legal_name: str
    dba_name: Optional[str]
    franchise_type: str
    state_code: str
    status: str
    risk_score: int
    risk_rating: str
    audit_frequency_days: int
    next_audit_due_at: Optional[str]
    open_sot_incident_count: int
    open_sot_exposure_cents: int
    delinquent_unit_count: int
    covenant_breach_count: int
    last_covenant_result: Optional[str]
    unapplied_credit_cents: int
    audit_in_progress: bool
    created_at: str
    updated_at: str
    version: int


class CreditLine(TypedDict):
    id: str
    dealer_id: str
    status: str
    credit_limit_cents: int
    advance_rate_bps_new: int
    advance_rate_bps_used: int
    advance_rate_bps_demonstrator: int
    max_unit_advance_cents_new: int
    max_unit_advance_cents_used: int
    max_unit_advance_cents_demonstrator: int
    class_sublimit_cents_used: int
    class_sublimit_cents_demonstrator: int
    curtailment_grace_days: int
    outstanding_principal_cents: int
    charged_off_principal_cents: int
    available_credit_cents: int
    eligible_collateral_cents: int
    borrowing_base_deficiency_cents: int
    class_outstanding_cents_used: int
    class_outstanding_cents_demonstrator: int
    activated_at: Optional[str]
    suspension_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CurtailmentTier(TypedDict):
    """Immutable ladder rung: id and created_at only."""
    id: str
    credit_line_id: str
    inventory_class: str
    age_days_from: int
    age_days_to: Optional[int]
    cumulative_paydown_bps: int
    created_at: str


class InventoryUnit(TypedDict):
    id: str
    dealer_id: str
    credit_line_id: str
    vin: str
    inventory_class: str
    invoice_amount_cents: int
    invoice_date: str
    odometer_miles: int
    title_document_type: str
    funding_status: str
    title_custody_status: str
    eligibility_status: str
    advance_amount_cents: int
    outstanding_principal_cents: int
    principal_paid_cents: int
    floored_at: Optional[str]
    funded_by_user_id: Optional[str]
    aging_exception_count: int
    curtailment_extension_days_total: int
    ineligibility_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAdvance(TypedDict):
    id: str
    unit_id: str
    credit_line_id: str
    status: str
    requested_amount_cents: int
    dealer_invoice_reference: str
    disbursement_reference: Optional[str]
    approved_advance_amount_cents: int
    effective_advance_rate_bps: int
    rate_adjustment_codes: List[str]
    invoice_age_days_at_funding: Optional[int]
    funded_at: Optional[str]
    funded_by_user_id: Optional[str]
    reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CurtailmentObligation(TypedDict):
    id: str
    unit_id: str
    dealer_id: str
    supersedes_obligation_id: Optional[str]
    status: str
    tier_age_days_from: int
    tier_cumulative_paydown_bps: int
    due_date: str
    projected_principal_cents: int
    required_principal_cents: int
    late_fee_cents: int
    total_amount_due_cents: int
    principal_paid_cents: int
    fee_paid_cents: int
    became_due_at: Optional[str]
    became_delinquent_at: Optional[str]
    extension_days_applied: int
    created_at: str
    updated_at: str
    version: int


class AgingExceptionRequest(TypedDict):
    id: str
    obligation_id: str
    status: str
    requested_extension_days: int
    justification_code: str
    requested_by_user_id: str
    decided_extension_days: Optional[int]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    reason_code: Optional[str]
    replacement_obligation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FloorPlanAudit(TypedDict):
    id: str
    dealer_id: str
    audit_type: str
    status: str
    window_start_date: str
    window_end_date: str
    started_at: Optional[str]
    reconciled_at: Optional[str]
    units_in_scope_count: int
    units_verified_count: int
    units_exception_count: int
    units_unobserved_count: int
    sot_exposure_cents: int
    observer_user_ids: List[str]
    reconciled_by_user_id: Optional[str]
    abort_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnitAuditObservation(TypedDict):
    """Immutable audit reading: id and created_at only."""
    id: str
    audit_id: str
    unit_id: str
    observed_condition: str
    title_verified: bool
    odometer_miles: Optional[int]
    sale_contract_reference: Optional[str]
    classification: str
    is_out_of_trust: bool
    observed_by_user_id: str
    unit_outstanding_principal_cents_at_observation: int
    created_at: str


class OutOfTrustIncident(TypedDict):
    id: str
    dealer_id: str
    unit_id: str
    audit_id: str
    observation_id: str
    status: str
    exposure_cents: int
    cure_deadline_at: str
    cured_at: Optional[str]
    charged_off_at: Optional[str]
    resolution_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentRemittance(TypedDict):
    id: str
    dealer_id: str
    target_unit_id: Optional[str]
    target_obligation_id: Optional[str]
    intent: str
    amount_cents: int
    payment_reference: str
    status: str
    applied_principal_cents: int
    applied_fee_cents: int
    applied_sot_cure_cents: int
    unapplied_cents: int
    allocation_breakdown: List[Dict[str, Any]]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CovenantTest(TypedDict):
    """Immutable covenant filing: id and created_at only."""
    id: str
    dealer_id: str
    period_end_date: str
    reported_tangible_net_worth_cents: int
    reported_ebitda_cents: int
    reported_interest_expense_cents: int
    reported_curtailment_paid_cents: int
    reported_unrestricted_cash_cents: int
    required_tangible_net_worth_cents: int
    dscr_lender_standard: float
    dscr_dealer_adjusted: float
    trailing_sot_incident_count: int
    result: str
    failure_reason_codes: List[str]
    submitted_by_user_id: str
    created_at: str


class RemedyAction(TypedDict):
    id: str
    dealer_id: str
    action_type: str
    status: str
    reason_code: str
    justification_snapshot: Dict[str, Any]
    issued_by_user_id: str
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    units_repossessed_count: int
    principal_charged_off_cents: int
    created_at: str
    updated_at: str
    version: int
