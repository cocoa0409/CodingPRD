"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity catalog (Sections 3.1-3.9). Every resource in
this domain carries the standard system-managed fields id / created_at /
updated_at / version (PRD section on common resource properties), so all
TypedDicts include them.
"""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    CODING_MANAGER = "CodingManager"
    CODER = "Coder"
    AUDITOR = "Auditor"
    BILLING_CLERK = "BillingClerk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class PatientAccountStatus(str, Enum):
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"


class PatientClass(str, Enum):
    INPATIENT = "INPATIENT"
    OBSERVATION = "OBSERVATION"


class FinancialClass(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class DischargeDisposition(str, Enum):
    HOME = "HOME"
    SNF = "SNF"
    REHAB = "REHAB"
    EXPIRED = "EXPIRED"
    AMA = "AMA"


class ChartStatus(str, Enum):
    OPEN = "OPEN"
    READY_FOR_CODING = "READY_FOR_CODING"
    IN_CODING = "IN_CODING"
    SUBMITTED = "SUBMITTED"
    CODED = "CODED"


class ChartAcuity(str, Enum):
    MEDICAL_LOW = "MEDICAL_LOW"
    MEDICAL_HIGH = "MEDICAL_HIGH"
    SURGICAL = "SURGICAL"


class DeficiencyType(str, Enum):
    MISSING_H_AND_P = "MISSING_H_AND_P"
    MISSING_DISCHARGE_SUMMARY = "MISSING_DISCHARGE_SUMMARY"
    MISSING_SIGNATURE = "MISSING_SIGNATURE"
    MISSING_OP_REPORT = "MISSING_OP_REPORT"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class PoaIndicator(str, Enum):
    Y = "Y"
    N = "N"
    U = "U"
    W = "W"
    EXEMPT = "EXEMPT"


class CcLevel(str, Enum):
    NONE = "NONE"
    CC = "CC"
    MCC = "MCC"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class Credential(str, Enum):
    CCA = "CCA"
    CCS = "CCS"
    RHIT = "RHIT"
    RHIA = "RHIA"


class CoderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class GrouperVariant(str, Enum):
    MS_DRG = "MS_DRG"
    AP_DRG = "AP_DRG"


class CodedCaseStatus(str, Enum):
    GROUPED = "GROUPED"
    LOCKED = "LOCKED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    FINAL_BILLED = "FINAL_BILLED"
    PAID = "PAID"
    POST_PAYMENT_REVIEW = "POST_PAYMENT_REVIEW"
    REBILL_REQUIRED = "REBILL_REQUIRED"
    REBILLED = "REBILLED"


class AuditStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"


class FindingType(str, Enum):
    PRINCIPAL_RESEQUENCE = "PRINCIPAL_RESEQUENCE"
    POA_CORRECTION = "POA_CORRECTION"
    CC_MCC_ADDED = "CC_MCC_ADDED"
    CC_MCC_REMOVED = "CC_MCC_REMOVED"
    PROCEDURE_ADDED = "PROCEDURE_ADDED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    DISMISSED = "DISMISSED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_REBILL = "CLOSED_REBILL"
    CLOSED_NO_CHANGE = "CLOSED_NO_CHANGE"


class RebillStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class PatientAccount(TypedDict, total=False):
    id: str
    mrn: str
    admit_at: str
    discharge_at: Optional[str]
    patient_class: str
    financial_class: str
    discharge_disposition: Optional[str]
    total_charges_cents: int
    status: str
    dnfb_flag: bool
    dnfb_flagged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chart(TypedDict, total=False):
    id: str
    account_id: str
    acuity: str
    status: str
    open_deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class ChartDeficiency(TypedDict, total=False):
    id: str
    chart_id: str
    type: str
    due_at: str
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiagnosisLine(TypedDict, total=False):
    id: str
    chart_id: str
    icd_code: str
    poa: str
    sequence: int
    is_principal: bool
    cc_level: str
    is_manifestation: bool
    manifestation_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcedureLine(TypedDict, total=False):
    id: str
    chart_id: str
    pcs_code: str
    is_or: bool
    performed_at: str
    created_at: str
    updated_at: str
    version: int


class Coder(TypedDict, total=False):
    id: str
    employee_no: str
    full_name: str
    credential: str
    status: str
    workload_units: int
    accepted_count: int
    accepted_weighted_units: float
    productivity_units_per_day: float
    accuracy_running: Optional[float]
    credential_review_required: bool
    created_at: str
    updated_at: str
    version: int


class CodingAssignment(TypedDict, total=False):
    id: str
    chart_id: str
    coder_id: Optional[str]
    status: str
    priority_score: int
    due_at: str
    assigned_at: Optional[str]
    started_at: Optional[str]
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    returned_count: int
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CodedCase(TypedDict, total=False):
    id: str
    chart_id: str
    principal_dx_id: str
    grouper_variant: str
    base_partition: str
    severity_level: str
    relative_weight: float
    expected_reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    account_id: str
    status: str
    expected_reimbursement_cents: int
    billed_amount_cents: Optional[int]
    paid_amount_cents: Optional[int]
    net_receivable_cents: Optional[int]
    finalized_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DnfbSweep(TypedDict, total=False):
    id: str
    threshold_days: int
    as_of: str
    flagged_count: int
    flagged_account_ids: List[str]
    total_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class CodingAudit(TypedDict, total=False):
    id: str
    auditor_id: str
    subject_coder_id: str
    window_start: str
    window_end: str
    sample_size: int
    sampled_case_ids: List[str]
    status: str
    applied_findings_count: int
    accuracy_code_based: Optional[float]
    accuracy_financial: Optional[float]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    audit_id: str
    coded_case_id: str
    finding_type: str
    target_diagnosis_id: Optional[str]
    corrected_poa: Optional[str]
    corrected_icd_code: Optional[str]
    corrected_cc_level: Optional[str]
    delta_reimbursement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PostPaymentReview(TypedDict, total=False):
    id: str
    bill_id: str
    payer_ref: str
    claimed_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RebillRequest(TypedDict, total=False):
    id: str
    review_id: str
    delta_cents: int
    requested_by: str
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
