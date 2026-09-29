"""Role names and the enumerated field values declared by the PRD."""

from enum import Enum


class Role(str, Enum):
    """The eight principal roles carried in the X-User-Role header."""

    CREDIT_OFFICER = "CreditOfficer"
    TRADE_FINANCE_OFFICER = "TradeFinanceOfficer"
    DOCUMENT_EXAMINER = "DocumentExaminer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    APPLICANT_USER = "ApplicantUser"
    BENEFICIARY_USER = "BeneficiaryUser"
    CORRESPONDENT_BANK = "CorrespondentBank"
    SYSTEM_OPERATOR = "SystemOperator"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class InternalRiskGrade(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"


class ApplicantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class UtilisationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class FacilityAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    CLOSE = "CLOSE"


class SuspendedReason(str, Enum):
    RESTRICT_THRESHOLD_BREACH = "RESTRICT_THRESHOLD_BREACH"
    MANUAL_SUSPENSION = "MANUAL_SUSPENSION"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"


class AllocationBasis(str, Enum):
    COMMITTED_ISSUANCE = "COMMITTED_ISSUANCE"
    AMENDED_INCREASE = "AMENDED_INCREASE"
    AMENDED_DECREASE = "AMENDED_DECREASE"


class BankStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CreditRating(str, Enum):
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class CreditStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CREDIT_APPROVAL = "PENDING_CREDIT_APPROVAL"
    APPROVED = "APPROVED"
    ON_HOLD = "ON_HOLD"
    ISSUED = "ISSUED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    UTILISED = "UTILISED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConfirmationStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMATION_REQUESTED = "CONFIRMATION_REQUESTED"
    CONFIRMED = "CONFIRMED"
    CONFIRMATION_DECLINED = "CONFIRMATION_DECLINED"


class AvailableBy(str, Enum):
    SIGHT_PAYMENT = "SIGHT_PAYMENT"
    ACCEPTANCE = "ACCEPTANCE"
    DEFERRED_PAYMENT = "DEFERRED_PAYMENT"
    NEGOTIATION = "NEGOTIATION"


class Incoterm(str, Enum):
    EXW = "EXW"
    FCA = "FCA"
    FOB = "FOB"
    CFR = "CFR"
    CIF = "CIF"
    CPT = "CPT"
    CIP = "CIP"
    DAP = "DAP"
    DPU = "DPU"
    DDP = "DDP"


class DocType(str, Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    BILL_OF_LADING = "BILL_OF_LADING"
    AIR_WAYBILL = "AIR_WAYBILL"
    INSURANCE_CERTIFICATE = "INSURANCE_CERTIFICATE"
    PACKING_LIST = "PACKING_LIST"
    CERTIFICATE_OF_ORIGIN = "CERTIFICATE_OF_ORIGIN"
    INSPECTION_CERTIFICATE = "INSPECTION_CERTIFICATE"
    DRAFT_BILL_OF_EXCHANGE = "DRAFT_BILL_OF_EXCHANGE"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PENDING_CONSENT = "PENDING_CONSENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED_NO_CONSENT = "EXPIRED_NO_CONSENT"
    SUPERSEDED = "SUPERSEDED"


class ExaminationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    COMPLYING = "COMPLYING"
    DISCREPANT = "DISCREPANT"
    WAIVER_REQUESTED = "WAIVER_REQUESTED"
    REFUSED = "REFUSED"
    PRECLUDED = "PRECLUDED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    CLAIM_LODGED = "CLAIM_LODGED"
    PAID = "PAID"
    ACCEPTED = "ACCEPTED"
    MATURED = "MATURED"
    NEGOTIATED = "NEGOTIATED"
    REIMBURSED = "REIMBURSED"
    VOID = "VOID"


class DisposalInstruction(str, Enum):
    HOLD_AT_DISPOSAL = "HOLD_AT_DISPOSAL"
    RETURN_TO_PRESENTER = "RETURN_TO_PRESENTER"


class DiscrepancyCode(str, Enum):
    LATE_SHIPMENT = "LATE_SHIPMENT"
    LATE_PRESENTATION = "LATE_PRESENTATION"
    CREDIT_EXPIRED = "CREDIT_EXPIRED"
    MISSING_DOCUMENT = "MISSING_DOCUMENT"
    INSUFFICIENT_ORIGINALS = "INSUFFICIENT_ORIGINALS"
    INVOICE_OVERDRAWN = "INVOICE_OVERDRAWN"
    GOODS_DESCRIPTION_MISMATCH = "GOODS_DESCRIPTION_MISMATCH"
    INCOTERM_MISMATCH = "INCOTERM_MISMATCH"
    INSURANCE_UNDERVALUED = "INSURANCE_UNDERVALUED"
    TRANSHIPMENT_NOT_ALLOWED = "TRANSHIPMENT_NOT_ALLOWED"


class DiscrepancySeverity(str, Enum):
    MATERIAL = "MATERIAL"
    MINOR = "MINOR"


class DiscrepancyStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    WAIVED = "WAIVED"
    UPHELD = "UPHELD"


class WaiverRequestStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class WaiverDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class ClaimType(str, Enum):
    PAYMENT = "PAYMENT"
    ACCEPTANCE = "ACCEPTANCE"
    NEGOTIATION = "NEGOTIATION"
    DEFERRED_PAYMENT = "DEFERRED_PAYMENT"
    REIMBURSEMENT = "REIMBURSEMENT"


class ClaimStatus(str, Enum):
    LODGED = "LODGED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class SettlementVariant(str, Enum):
    SIGHT_HONOUR = "SIGHT_HONOUR"
    NEGOTIATION_UNDER_DISCOUNT = "NEGOTIATION_UNDER_DISCOUNT"
    ACCEPTANCE_AT_MATURITY = "ACCEPTANCE_AT_MATURITY"


class ScreeningScope(str, Enum):
    CREDIT_PARTIES = "CREDIT_PARTIES"
    PRESENTED_DOCUMENTS = "PRESENTED_DOCUMENTS"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    HIT_PENDING_REVIEW = "HIT_PENDING_REVIEW"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"
    ESCALATED = "ESCALATED"


class ScreeningDecision(str, Enum):
    RELEASE = "RELEASE"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN_TO_DRAFT = "RETURN_TO_DRAFT"


class ConsentDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ConfirmationDecision(str, Enum):
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"
