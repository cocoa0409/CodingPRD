"""Domain types for the Assigned Risk Automobile Plan API.

Status enums, role enum and entity TypedDicts. Field names and vocabularies are
taken verbatim from the PRD.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    COMPLIANCE_EXAMINER = "ComplianceExaminer"
    SERVICING_CARRIER = "ServicingCarrier"
    PRODUCER_AGENT = "ProducerAgent"


# --------------------------------------------------------------------------
# State vocabularies
# --------------------------------------------------------------------------
class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXIT_NOTICED = "EXIT_NOTICED"
    EXIT_COMPLETE = "EXIT_COMPLETE"


class CarrierPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CURE = "RETURNED_FOR_CURE"
    REJECTED = "REJECTED"
    CERTIFIED_AWAITING_ASSIGNMENT = "CERTIFIED_AWAITING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    DEFERRED_NO_CARRIER = "DEFERRED_NO_CARRIER"
    POLICY_ISSUED = "POLICY_ISSUED"
    CLOSED_CANCELLED = "CLOSED_CANCELLED"
    CLOSED_EXITED = "CLOSED_EXITED"


class PlanPeriodStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class AssignmentCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class AssignmentStatus(str, Enum):
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    POLICY_ISSUED = "POLICY_ISSUED"
    RESCINDED = "RESCINDED"
    REASSIGNED = "REASSIGNED"
    CLOSED = "CLOSED"


class AssignmentKind(str, Enum):
    INITIAL = "INITIAL"
    REASSIGNMENT = "REASSIGNMENT"


class RescissionReasonCode(str, Enum):
    ISSUANCE_DEADLINE_MISSED = "ISSUANCE_DEADLINE_MISSED"
    CARRIER_INELIGIBLE = "CARRIER_INELIGIBLE"
    ASSIGNMENT_ERROR = "ASSIGNMENT_ERROR"


class PolicyStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    NON_RENEWAL_PENDING = "NON_RENEWAL_PENDING"
    NON_RENEWED = "NON_RENEWED"
    REASSIGNMENT_PENDING = "REASSIGNMENT_PENDING"
    CANCELLED = "CANCELLED"
    EXITED_TO_VOLUNTARY = "EXITED_TO_VOLUNTARY"


class PremiumSettlementStatus(str, Enum):
    PREMIUM_OUTSTANDING = "PREMIUM_OUTSTANDING"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUND_ISSUED = "REFUND_ISSUED"
    BALANCE_DUE_AT_CANCELLATION = "BALANCE_DUE_AT_CANCELLATION"


class RefundBasis(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class CancellationInitiatedBy(str, Enum):
    CARRIER = "CARRIER"
    PLAN = "PLAN"
    INSURED = "INSURED"


class CancellationReasonCode(str, Enum):
    NON_PAYMENT_OF_PREMIUM = "NON_PAYMENT_OF_PREMIUM"
    LICENSE_SUSPENDED = "LICENSE_SUSPENDED"
    MATERIAL_MISREPRESENTATION = "MATERIAL_MISREPRESENTATION"
    VEHICLE_NOT_GARAGED_IN_STATE = "VEHICLE_NOT_GARAGED_IN_STATE"
    INSURED_REQUEST = "INSURED_REQUEST"
    PLAN_ORDERED = "PLAN_ORDERED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED_PAID = "CLOSED_PAID"
    CLOSED_DENIED = "CLOSED_DENIED"


class CoverageLine(str, Enum):
    BI = "BI"
    PD = "PD"
    UM = "UM"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_NOT_UPHELD = "RESOLVED_NOT_UPHELD"


class ComplaintType(str, Enum):
    CLAIM_HANDLING_DELAY = "CLAIM_HANDLING_DELAY"
    RATING_DISPUTE = "RATING_DISPUTE"
    CANCELLATION_DISPUTE = "CANCELLATION_DISPUTE"
    SERVICE_STANDARD = "SERVICE_STANDARD"


class ComplaintDisposition(str, Enum):
    UPHELD = "UPHELD"
    NOT_UPHELD = "NOT_UPHELD"
    RETURNED_FOR_FURTHER_REVIEW = "RETURNED_FOR_FURTHER_REVIEW"


class QuotaReconciliationStatus(str, Enum):
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class ReconciliationBasis(str, Enum):
    POLICY_COUNT = "POLICY_COUNT"
    CAR_YEAR_EXPOSURE = "CAR_YEAR_EXPOSURE"


class DriverClass(str, Enum):
    ADULT = "ADULT"
    SENIOR = "SENIOR"
    YOUTHFUL_OPERATOR = "YOUTHFUL_OPERATOR"


class VehicleClassCode(str, Enum):
    PLEASURE = "PLEASURE"
    WORK_LT10 = "WORK_LT10"
    WORK_GE10 = "WORK_GE10"
    BUSINESS = "BUSINESS"


class TerritoryCode(str, Enum):
    T01 = "T01"
    T02 = "T02"
    T03 = "T03"


class ViolationCode(str, Enum):
    SPEEDING_MINOR = "SPEEDING_MINOR"
    SPEEDING_MAJOR = "SPEEDING_MAJOR"
    AT_FAULT_ACCIDENT = "AT_FAULT_ACCIDENT"
    LICENSE_SUSPENSION = "LICENSE_SUSPENSION"
    RECKLESS_DRIVING = "RECKLESS_DRIVING"
    DUI = "DUI"


class MarketRejectionReasonCode(str, Enum):
    UNACCEPTABLE_DRIVING_RECORD = "UNACCEPTABLE_DRIVING_RECORD"
    UNDERWRITING_GUIDELINES = "UNDERWRITING_GUIDELINES"
    NO_APPETITE_TERRITORY = "NO_APPETITE_TERRITORY"
    PRIOR_CANCELLATION = "PRIOR_CANCELLATION"


class CertificationDecision(str, Enum):
    CERTIFY = "CERTIFY"
    REJECT = "REJECT"


class ClaimDisposition(str, Enum):
    PAID = "PAID"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Carrier(TypedDict):
    id: str
    name: str
    naic_code: str
    voluntary_market_share_bps: int
    licensed_territories: List[str]
    enrollment_sequence: int
    status: str
    exit_effective_date: Optional[str]
    performance_score: int
    breach_count_current_period: int
    upheld_complaint_count: int
    non_renewal_count_current_period: int
    assigned_risk_count: int
    voluntary_credit_units: float
    quota_target_units: int
    quota_variance_units: float
    overallocated: bool
    posture: str
    penalty_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Producer(TypedDict):
    id: str
    name: str
    license_number: str
    appointed_territories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    driver_license_number: str
    territory_code: str
    driver_class: str
    first_licensed_date: str
    last_chargeable_event_date: Optional[str]
    clean_years_credited: int
    voluntary_market_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    applicant_id: str
    vin: str
    vehicle_class_code: str
    garaging_territory_code: str
    model_year: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    producer_id: str
    vehicle_id: str
    intake_sequence: int
    requested_effective_date: str
    declared_violations: List[Dict[str, Any]]
    verified_violations: Optional[List[Dict[str, Any]]]
    mvr_verified_at: Optional[str]
    status: str
    cure_count: int
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    rejection_reason_code: Optional[str]
    distinct_rejection_count: int
    surcharge_points_estimated: int
    estimated_annual_premium_cents: int
    estimated_expense_charge_cents: int
    estimated_total_charge_cents: int
    required_deposit_cents: int
    deposit_paid_total_cents: int
    deposit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class MarketRejection(TypedDict):
    """An immutable evidentiary filing: it carries only ``id`` and ``created_at``."""
    id: str
    application_id: str
    rejecting_carrier_naic_code: str
    rejection_date: str
    reason_code: str
    document_reference: str
    created_at: str


class PlanPeriod(TypedDict):
    id: str
    period_code: str
    window_start: str
    window_end: str
    underserved_territories: List[str]
    status: str
    total_assignable_units: int
    total_assignable_car_years: float
    created_at: str
    updated_at: str
    version: int


class AssignmentCycle(TypedDict):
    id: str
    plan_period_id: str
    window_start: str
    window_end: str
    status: str
    assigned_count: int
    deferred_count: int
    run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    application_id: str
    carrier_id: str
    assignment_cycle_id: Optional[str]
    predecessor_assignment_id: Optional[str]
    batch_sequence: int
    assignment_kind: str
    status: str
    acceptance_deadline: str
    accepted_at: Optional[str]
    deficit_score_at_selection: float
    provisional_premium_cents: int
    rescission_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    assignment_id: str
    carrier_id: str
    policy_number: str
    effective_date: str
    expiration_date: str
    policy_status: str
    premium_settlement_status: str
    surcharge_points_applied: int
    surcharge_factor_applied: float
    premium_lines: Dict[str, int]
    final_premium_cents: int
    plan_expense_charge_cents: int
    total_annual_charge_cents: int
    premium_credited_cents: int
    additional_premium_due_cents: int
    refund_paid_cents: int
    balance_due_cents: int
    earned_premium_cents: int
    refund_basis: Optional[str]
    cancellation_reason_code: Optional[str]
    cancellation_effective_date: Optional[str]
    cancellation_initiated_by: Optional[str]
    non_renewal_notice_count: int
    non_renewal_effective_date: Optional[str]
    rating_revision: int
    reassignment_required: bool
    open_complaint_count: int
    complaint_freeze_active: bool
    exposure_car_years_current_period: float
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    loss_date: str
    at_fault: bool
    coverage_line: str
    reserve_cents: int
    reported_at: str
    acknowledgement_deadline: str
    acknowledged_at: Optional[str]
    status: str
    standard_breach: bool
    paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    policy_id: str
    carrier_id: str
    complaint_type: str
    narrative: str
    status: str
    findings_recorded_by_user_id: Optional[str]
    findings_note: Optional[str]
    resolved_by_user_id: Optional[str]
    disposition: Optional[str]
    review_round: int
    created_at: str
    updated_at: str
    version: int


class QuotaReconciliation(TypedDict):
    id: str
    carrier_id: str
    plan_period_id: str
    basis: str
    obligation_units: float
    credited_units: float
    variance_units: float
    voluntary_credit_units_applied: float
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
