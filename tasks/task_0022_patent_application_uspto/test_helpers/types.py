"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §2.4 (audit fields) and PRD §3 (entity definitions).
FeePayment is append-only (PRD §2.4) — no `updated_at` and no `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────

class ApplicationStatus(str, Enum):
    FILED = "FILED"
    AWAITING_EXAMINATION = "AWAITING_EXAMINATION"
    OFFICE_ACTION_OUTSTANDING = "OFFICE_ACTION_OUTSTANDING"
    RESPONSE_FILED = "RESPONSE_FILED"
    ALLOWED = "ALLOWED"
    ISSUED = "ISSUED"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"


class OfficeActionStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class OfficeActionResponseStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_LATE = "REJECTED_LATE"


class MaintenanceFeeStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LAPSED = "LAPSED"


class FeePaymentStatus(str, Enum):
    POSTED = "POSTED"


class PCTPhaseStatus(str, Enum):
    ENTERED = "ENTERED"


class EntitySize(str, Enum):
    LARGE = "LARGE"
    SMALL = "SMALL"
    MICRO = "MICRO"


class ApplicationType(str, Enum):
    UTILITY = "UTILITY"
    DESIGN = "DESIGN"
    PROVISIONAL = "PROVISIONAL"
    PCT_NATIONAL = "PCT_NATIONAL"


class ContinuationType(str, Enum):
    CONTINUATION = "CONTINUATION"
    CIP = "CIP"


class ActionType(str, Enum):
    NON_FINAL = "NON_FINAL"
    FINAL = "FINAL"
    NOTICE_OF_ALLOWANCE = "NOTICE_OF_ALLOWANCE"


class PaymentCategory(str, Enum):
    FILING = "FILING"
    EXCESS_CLAIMS = "EXCESS_CLAIMS"
    EXTENSION = "EXTENSION"
    ISSUE = "ISSUE"
    MAINTENANCE_W1 = "MAINTENANCE_W1"
    MAINTENANCE_W2 = "MAINTENANCE_W2"
    MAINTENANCE_W3 = "MAINTENANCE_W3"
    PCT_NATIONAL_PHASE = "PCT_NATIONAL_PHASE"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    USPTO_EXAMINER = "USPTOExaminer"
    USPTO_ADMIN = "USPTOAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────────────

# common_fields: true — carries id + created_at + updated_at + version (PRD §2.4)

class Applicant(TypedDict, total=False):
    id: str
    legal_name: str
    entity_size: str
    micro_qualifying_year: Optional[int]
    gross_income_prior_year_cents: Optional[int]
    prior_applications_filed: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    application_type: str
    title: str
    claim_count: int
    independent_claim_count: int
    filing_date: str
    status: str
    parent_application_id: Optional[str]
    continuation_type: Optional[str]
    priority_date: str
    total_fees_paid_cents: int
    issued_patent_number: Optional[str]
    issue_date: Optional[str]
    term_expiration_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OfficeAction(TypedDict, total=False):
    id: str
    application_id: str
    action_type: str
    issue_date: str
    shortened_due_date: str
    maximum_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfficeActionResponse(TypedDict, total=False):
    id: str
    office_action_id: str
    response_filed_at: str
    extension_months_requested: int
    claim_amendment_count: int
    extension_fee_cents: int
    response_status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceFee(TypedDict, total=False):
    id: str
    application_id: str
    window_number: int
    window_open_date: str
    window_due_date: str
    window_grace_date: str
    base_fee_cents: int
    fee_status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PCTPhaseEntry(TypedDict, total=False):
    id: str
    application_id: str
    pct_international_filing_date: str
    national_phase_due_date: str
    phase_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, ONLY id + created_at (PRD §2.4)

class FeePayment(TypedDict, total=False):
    id: str
    application_id: str
    payment_category: str
    amount_cents: int
    maintenance_fee_id: Optional[str]
    payment_status: str
    created_at: str
