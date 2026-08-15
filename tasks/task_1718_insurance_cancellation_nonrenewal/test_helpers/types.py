"""Domain types: entity TypedDicts, status enums, role enum.

All shapes follow the PRD: primary resources carry id + created_at +
updated_at + version; the premium ledger is append-only and carries only
id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class ProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    NONRENEWAL_PENDING = "NONRENEWAL_PENDING"
    EXPIRED = "EXPIRED"


class CancellationCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    NOTICE_SENT = "NOTICE_SENT"
    EFFECTIVE = "EFFECTIVE"
    RESCINDED = "RESCINDED"
    WITHDRAWN = "WITHDRAWN"


class NonrenewalCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    NOTICE_SENT = "NOTICE_SENT"
    COMPLETED = "COMPLETED"
    RESCINDED = "RESCINDED"


class NoticeStatus(str, Enum):
    QUEUED = "QUEUED"
    MAILED = "MAILED"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"
    RETURNED_UNDELIVERABLE = "RETURNED_UNDELIVERABLE"


class ReinstatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class GroundCode(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    MATERIAL_MISREPRESENTATION = "MATERIAL_MISREPRESENTATION"
    SUBSTANTIAL_CHANGE_IN_RISK = "SUBSTANTIAL_CHANGE_IN_RISK"
    LICENSE_SUSPENSION = "LICENSE_SUSPENSION"
    INSURED_REQUEST = "INSURED_REQUEST"


class ReturnMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class InterestType(str, Enum):
    MORTGAGEE = "MORTGAGEE"
    LIENHOLDER = "LIENHOLDER"
    ADDITIONAL_INTEREST = "ADDITIONAL_INTEREST"


class RecipientKind(str, Enum):
    POLICYHOLDER = "POLICYHOLDER"
    MORTGAGEE = "MORTGAGEE"
    LIENHOLDER = "LIENHOLDER"
    ADDITIONAL_INTEREST = "ADDITIONAL_INTEREST"


class LedgerEntryKind(str, Enum):
    WRITTEN = "WRITTEN"
    RETURN_PRO_RATA = "RETURN_PRO_RATA"
    RETURN_SHORT_RATE = "RETURN_SHORT_RATE"
    LAPSE_FEE = "LAPSE_FEE"
    REINSTATEMENT_FEE = "REINSTATEMENT_FEE"


class NonrenewalReason(str, Enum):
    UNDERWRITING_GUIDELINES = "UNDERWRITING_GUIDELINES"
    LOSS_HISTORY = "LOSS_HISTORY"
    CARRIER_WITHDRAWAL = "CARRIER_WITHDRAWAL"
    RISK_INELIGIBLE = "RISK_INELIGIBLE"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    UNDERWRITER = "Underwriter"
    POLICYHOLDER = "Policyholder"


class StateFilingProfile(TypedDict, total=False):
    id: str
    state_code: str
    status: str
    permissible_grounds: List[str]
    nonpayment_notice_days: int
    other_grounds_notice_days: int
    mortgagee_notice_days: int
    nonrenewal_notice_days: int
    short_rate_penalty_pct: float
    reinstatement_window_days: int
    max_reinstatements: int
    nonrenewal_content_codes: List[str]
    version_note: str
    created_at: str
    updated_at: str
    version: int


class Policyholder(TypedDict, total=False):
    id: str
    full_name: str
    mailing_address: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    policyholder_id: str
    state_profile_id: str
    policy_number: str
    status: str
    term_start_date: str
    term_end_date: str
    total_premium_cents: int
    cancellation_effective_date: Optional[str]
    reinstatements_used: int
    lapse_flag: bool
    created_at: str
    updated_at: str
    version: int


class InsuredInterest(TypedDict, total=False):
    id: str
    policy_id: str
    interest_type: str
    institution_name: str
    mailing_address: str
    loan_number: str
    created_at: str
    updated_at: str
    version: int


class CancellationCase(TypedDict, total=False):
    id: str
    policy_id: str
    ground_code: str
    requested_by_role: str
    requested_on_date: str
    return_method: str
    earliest_effective_date: str
    scheduled_effective_date: Optional[str]
    return_premium_cents: Optional[int]
    status: str
    rescinded_reason: str
    created_at: str
    updated_at: str
    version: int


class NonrenewalCase(TypedDict, total=False):
    id: str
    policy_id: str
    reason_code: str
    reason_text: str
    content_codes_present: List[str]
    decided_on_date: Optional[str]
    notice_deadline_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NoticeRecord(TypedDict, total=False):
    id: str
    cancellation_case_id: Optional[str]
    nonrenewal_case_id: Optional[str]
    recipient_kind: str
    insured_interest_id: Optional[str]
    mailed_on_date: str
    tracking_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumLedgerEntry(TypedDict, total=False):
    # Append-only resource: carries ONLY id + created_at as common fields.
    id: str
    created_at: str
    policy_id: str
    entry_kind: str
    amount_cents: int
    effective_date: str
    cancellation_case_id: Optional[str]


class ReinstatementRequest(TypedDict, total=False):
    id: str
    policy_id: str
    cancellation_case_id: str
    submitted_on_date: str
    lapse_days: int
    reinstatement_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppealCase(TypedDict, total=False):
    id: str
    cancellation_case_id: str
    policy_id: str
    filed_by: str
    filed_on_date: str
    grounds_text: str
    status: str
    decided_on_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    state_profile_id: str
    report_period: str
    status: str
    nonrenewal_count: int
    cancellation_count: int
    rescinded_count: int
    created_at: str
    updated_at: str
    version: int
