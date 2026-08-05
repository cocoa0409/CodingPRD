"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROSTHODONTIST = "Prosthodontist"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    LAB_TECHNICIAN = "LabTechnician"
    FRONT_OFFICE = "FrontOffice"
    PATIENT = "Patient"
    PLATFORM_ADMIN = "PlatformAdmin"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    EXAM_COMPLETE = "EXAM_COMPLETE"
    IN_FABRICATION = "IN_FABRICATION"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ArchStatus(str, Enum):
    PLANNED = "PLANNED"
    IMPRESSION_PENDING = "IMPRESSION_PENDING"
    MILESTONE_PENDING = "MILESTONE_PENDING"
    LAB_FABRICATION = "LAB_FABRICATION"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    REMAKE_PENDING = "REMAKE_PENDING"
    ARCH_CLOSED = "ARCH_CLOSED"
    ARCH_ABANDONED = "ARCH_ABANDONED"


class QualityStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    PROVISIONAL_ACCEPTED = "PROVISIONAL_ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ADJUST_REQUESTED = "ADJUST_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED_FOR_REMAKE = "REJECTED_FOR_REMAKE"
    CANCELLED = "CANCELLED"


class LabStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    RESENT = "RESENT"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class WarrantyStatus(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    WARRANTY_CONSUMED = "WARRANTY_CONSUMED"
    WARRANTY_EXPIRED = "WARRANTY_EXPIRED"
    WARRANTY_VOIDED = "WARRANTY_VOIDED"


class RecallStatus(str, Enum):
    RECALL_SCHEDULED = "RECALL_SCHEDULED"
    RECALL_DUE = "RECALL_DUE"
    RECALL_OVERDUE = "RECALL_OVERDUE"
    RECALL_COMPLETED = "RECALL_COMPLETED"
    RECALL_CLOSED_SUPERSEDED = "RECALL_CLOSED_SUPERSEDED"


class ServiceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_CHAIR = "IN_CHAIR"
    AT_LAB = "AT_LAB"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ChargeBasis(str, Enum):
    INCLUDED = "INCLUDED"
    CHARGEABLE = "CHARGEABLE"
    WARRANTY_NO_CHARGE = "WARRANTY_NO_CHARGE"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    CLINIC_FAULT = "CLINIC_FAULT"
    LAB_FAULT = "LAB_FAULT"
    PATIENT_FAULT = "PATIENT_FAULT"


class AuthorizationStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FINAL_DENIED = "FINAL_DENIED"


class RemakeEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    FINAL_DENIED = "FINAL_DENIED"


class DeterminationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ALTERNATE_BENEFIT = "ALTERNATE_BENEFIT"
    EXPIRED = "EXPIRED"


class AdjudicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_PRIMARY = "SUBMITTED_PRIMARY"
    PRIMARY_PAID = "PRIMARY_PAID"
    SUBMITTED_SECONDARY = "SUBMITTED_SECONDARY"
    SECONDARY_PAID = "SECONDARY_PAID"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    PAID_OFF = "PAID_OFF"
    SUPERSEDED = "SUPERSEDED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MISSED = "MISSED"
    PAID = "PAID"
    WAIVED = "WAIVED"


# Every resource type in this API carries id, created_at, updated_at and version.


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    phone: str
    write_gate_active: bool
    delivered_prosthesis_count: int
    last_frequency_anchor_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    patient_id: str
    carrier_name: str
    rank: str
    effective_date: str
    annual_maximum_amount: float
    coinsurance_major_rate: float
    waiting_period_days: int
    replacement_frequency_months: int
    cob_convention: str
    alternate_benefit_enabled: bool
    benefit_used_ytd: float
    benefit_remaining: float
    created_at: str
    updated_at: str
    version: int


class DentalLab(TypedDict):
    id: str
    lab_name: str
    bench_line_count: int
    standard_turnaround_days: int
    rush_turnaround_days: int
    credit_issued_total: float
    credit_applied_total: float
    credit_available_balance: float
    created_at: str
    updated_at: str
    version: int


class ProsthesisCase(TypedDict):
    id: str
    patient_id: str
    prosthesis_type: str
    case_status: str
    fee_schedule_total: float
    predetermination_required: bool
    billed_amount: float
    insurance_paid_amount: float
    prompt_pay_discount_amount: float
    patient_responsibility_amount: float
    fabrication_started_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseArch(TypedDict):
    id: str
    case_id: str
    arch_position: str
    arch_status: str
    required_milestones: List[str]
    completed_milestones: List[str]
    next_required_milestone: Optional[str]
    retake_count: int
    remake_count: int
    remake_request_count: int
    remake_eligibility: str
    fee_schedule_amount: float
    last_lab_received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImpressionRecord(TypedDict):
    id: str
    case_arch_id: str
    capture_method: str
    attempt_number: int
    quality_score: Optional[int]
    quality_status: str
    retake_required: bool
    reviewed_at: Optional[str]
    superseded_by_impression_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TryInMilestone(TypedDict):
    id: str
    case_arch_id: str
    milestone_kind: str
    approval_status: str
    adjust_count: int
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabCase(TypedDict):
    id: str
    case_arch_id: str
    dental_lab_id: str
    bench_line: int
    turnaround_class: str
    unit_count: int
    lab_invoice_amount: float
    purpose: str
    lab_status: str
    dispatched_at: Optional[str]
    promised_due_at: Optional[str]
    shelf_life_expires_at: Optional[str]
    rush_fee_amount: float
    received_at: Optional[str]
    resend_count: int
    qc_result: Optional[str]
    expired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Prosthesis(TypedDict):
    id: str
    case_arch_id: str
    superseded_prosthesis_id: Optional[str]
    prosthesis_type: str
    is_remake: bool
    delivered_at: str
    warranty_status: str
    warranty_expires_at: str
    frequency_anchor_at: str
    replacement_eligible_date: str
    recall_status: str
    recall_due_at: str
    recall_cycle_count: int
    adjustments_used: int
    adjustments_remaining: int
    adjustment_window_ends_at: str
    in_patient_possession: bool
    mandatory_reline_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostDeliveryService(TypedDict):
    id: str
    prosthesis_id: str
    lab_case_id: Optional[str]
    service_type: str
    is_emergency_repair: bool
    service_status: str
    charge_basis: Optional[str]
    charge_amount: float
    completed_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    prosthesis_id: str
    post_delivery_service_id: Optional[str]
    attributed_lab_case_id: Optional[str]
    reported_issue: str
    claim_status: str
    fault_verdict: Optional[str]
    lab_credit_amount: float
    patient_charge_amount: float
    warranty_consumed: bool
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemakeRequest(TypedDict):
    id: str
    case_arch_id: str
    warranty_claim_id: Optional[str]
    reason_code: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    authorization_status: str
    attempt_number: int
    charge_basis: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Predetermination(TypedDict):
    id: str
    case_id: str
    coverage_id: str
    requested_amount: float
    determination_status: str
    alternate_benefit_type: Optional[str]
    allowed_amount: float
    estimated_plan_payment: float
    estimated_patient_responsibility: float
    determined_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    case_id: str
    coverage_id: str
    predetermination_id: Optional[str]
    billed_amount: float
    allowed_amount: float
    adjudication_status: str
    submission_target: str
    primary_paid_amount: float
    secondary_paid_amount: float
    plan_paid_amount: float
    patient_responsibility_amount: float
    cob_convention_applied: Optional[str]
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    patient_id: str
    case_id: str
    superseded_by_plan_id: Optional[str]
    principal_amount: float
    installment_count: int
    down_payment_amount: float
    pay_in_full: bool
    first_due_date: str
    frequency: str
    plan_status: str
    paid_amount: float
    outstanding_amount: float
    missed_count: int
    applied_lab_credit_amount: float
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    payment_plan_id: str
    sequence_number: int
    amount: float
    due_date: str
    installment_status: str
    is_residual_installment: bool
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
