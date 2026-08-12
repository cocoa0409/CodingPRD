"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD Section 2.4 (common properties on every resource) and
the per-resource narratives of PRD Section 3.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    REGISTRATION_PRINCIPAL = "RegistrationPrincipal"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_CLERK = "FinanceClerk"
    SYSTEM_OPERATOR = "SystemOperator"
    REGULATOR = "Regulator"


class FirmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RegistrationRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENT = "DEFICIENT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


class RegistrationCategory(str, Enum):
    RR = "RR"
    IA = "IA"
    PRINCIPAL = "PRINCIPAL"


class JurisdictionType(str, Enum):
    STATE = "STATE"
    SRO = "SRO"


class JurisdictionSelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELINQUISHED = "RELINQUISHED"


class SubmissionChannel(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    HARD_CARD = "HARD_CARD"


class FingerprintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class QuestionCode(str, Enum):
    CRIMINAL = "CRIMINAL"
    REGULATORY = "REGULATORY"
    FINANCIAL = "FINANCIAL"
    CIVIL = "CIVIL"
    EMPLOYMENT = "EMPLOYMENT"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class ExamCode(str, Enum):
    SIE = "SIE"
    S7 = "S7"
    S63 = "S63"
    S66 = "S66"
    S24 = "S24"


class ExamRequirementStatus(str, Enum):
    REQUIRED = "REQUIRED"
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class ExamWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    USED = "USED"
    CANCELLED = "CANCELLED"


class ExamResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NO_SHOW = "NO_SHOW"


class DisclosureEventType(str, Enum):
    CRIMINAL_CHARGE = "CRIMINAL_CHARGE"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    BANKRUPTCY = "BANKRUPTCY"
    CIVIL_JUDGMENT = "CIVIL_JUDGMENT"
    CUSTOMER_COMPLAINT = "CUSTOMER_COMPLAINT"


class DisclosureEventStatus(str, Enum):
    OPEN = "OPEN"
    AMENDED = "AMENDED"
    LATE_AMENDED = "LATE_AMENDED"


class AmendmentFilingStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    PERMITTED_TO_RESIGN = "PERMITTED_TO_RESIGN"
    DISCHARGED = "DISCHARGED"
    DECEASED = "DECEASED"


class TerminationFilingStatus(str, Enum):
    FILED = "FILED"
    AMENDMENT_OPEN = "AMENDMENT_OPEN"
    CLOSED = "CLOSED"


class U5AuthorRole(str, Enum):
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    REGISTRATION_PRINCIPAL = "REGISTRATION_PRINCIPAL"


class U5CommentDisposition(str, Enum):
    PENDING = "PENDING"
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"


class AffiliationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class RenewalInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class SubjectFilingType(str, Enum):
    REGISTRATION_REQUEST = "REGISTRATION_REQUEST"
    AMENDMENT_FILING = "AMENDMENT_FILING"
    TERMINATION_FILING = "TERMINATION_FILING"


class RegulatoryInquiryStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_RESPONSE = "PENDING_RESPONSE"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"


class DeadlineBasis(str, Enum):
    CALENDAR = "CALENDAR"
    REGULATORY = "REGULATORY"


# --- Entity TypedDicts (all resources carry the PRD Section 2.4 common set) ---


class Firm(TypedDict, total=False):
    id: str
    crd_number: str
    legal_name: str
    status: str
    open_inquiry_count: int
    created_at: str
    updated_at: str
    version: int


class IndividualApplicant(TypedDict, total=False):
    id: str
    crd_number: str
    full_name: str
    date_of_birth: str
    fingerprint_required: bool
    created_at: str
    updated_at: str
    version: int


class RegistrationRequest(TypedDict, total=False):
    id: str
    applicant_id: str
    firm_id: str
    registration_category: str
    status: str
    deficiency_count: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JurisdictionSelection(TypedDict, total=False):
    id: str
    registration_request_id: str
    jurisdiction_code: str
    jurisdiction_type: str
    status: str
    annual_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FingerprintSubmission(TypedDict, total=False):
    id: str
    registration_request_id: str
    submission_channel: str
    status: str
    rejection_reason: Optional[str]
    processed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundDisclosure(TypedDict, total=False):
    id: str
    registration_request_id: str
    question_code: str
    answer: bool
    explanation_text: Optional[str]
    review_status: str
    created_at: str
    updated_at: str
    version: int


class ExamRequirement(TypedDict, total=False):
    id: str
    registration_request_id: str
    exam_code: str
    status: str
    pass_recorded_at: Optional[str]
    credit_expiry_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamWindow(TypedDict, total=False):
    id: str
    exam_requirement_id: str
    window_start: str
    window_end: str
    status: str
    result_recorded: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureEvent(TypedDict, total=False):
    id: str
    applicant_id: str
    event_type: str
    event_date: str
    reported_at: str
    amendment_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AmendmentFiling(TypedDict, total=False):
    id: str
    disclosure_event_id: str
    registration_request_id: str
    filed_at: str
    is_late: bool
    narrative_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TerminationFiling(TypedDict, total=False):
    id: str
    registration_request_id: str
    termination_reason: str
    termination_date: str
    filed_at: str
    filing_deadline_at: str
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class U5Comment(TypedDict, total=False):
    id: str
    termination_filing_id: str
    author_role: str
    comment_text: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class AffiliationRequest(TypedDict, total=False):
    id: str
    applicant_id: str
    second_firm_id: str
    first_registration_request_id: str
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalInvoice(TypedDict, total=False):
    id: str
    registration_request_id: str
    cycle_year: int
    jurisdiction_fee_cents: int
    base_fee_cents: int
    late_surcharge_cents: int
    total_cents: int
    payable_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryInquiry(TypedDict, total=False):
    id: str
    firm_id: str
    subject_filing_type: str
    subject_filing_id: str
    inquiry_text: str
    response_due_at: str
    response_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
