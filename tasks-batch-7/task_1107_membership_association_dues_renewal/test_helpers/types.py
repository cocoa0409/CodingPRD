"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------- Role ----------

class UserRole(str, Enum):
    MEMBER = "Member"
    MEMBERSHIP_ADMINISTRATOR = "MembershipAdministrator"
    DUES_ADMINISTRATOR = "DuesAdministrator"


# ---------- Status enums ----------

class MembershipCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DuesScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ChapterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISSOLVED = "DISSOLVED"


class RenewalCyclePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RenewalCycleMode(str, Enum):
    ANNIVERSARY = "ANNIVERSARY"
    CALENDAR = "CALENDAR"


class ProrationMethod(str, Enum):
    PRO_RATA_DAILY = "PRO_RATA_DAILY"
    FULL_PERIOD = "FULL_PERIOD"
    NONE = "NONE"


class MemberStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    REINSTATED = "REINSTATED"
    EXPELLED = "EXPELLED"
    RESIGNED = "RESIGNED"


class MembershipTermStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOID = "VOID"


class MembershipTermOpenedBy(str, Enum):
    JOIN = "JOIN"
    RENEWAL = "RENEWAL"
    REINSTATEMENT = "REINSTATEMENT"
    ADMIN_ADJUST = "ADMIN_ADJUST"


class InvoicePaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    REFUNDED = "REFUNDED"
    WRITTEN_OFF = "WRITTEN_OFF"


class InvoiceFulfillmentStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    COVERAGE_ACTIVE = "COVERAGE_ACTIVE"
    COVERAGE_SUSPENDED = "COVERAGE_SUSPENDED"
    COVERAGE_ENDED = "COVERAGE_ENDED"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    DECLINED_TRANSIENT = "DECLINED_TRANSIENT"
    DECLINED_HARD = "DECLINED_HARD"


class AutoRenewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUSPENDED_HARD_DECLINE = "SUSPENDED_HARD_DECLINE"


class BenefitCode(str, Enum):
    JOURNAL_ACCESS = "JOURNAL_ACCESS"
    CONFERENCE_DISCOUNT = "CONFERENCE_DISCOUNT"
    CERTIFICATION_REGISTRY = "CERTIFICATION_REGISTRY"
    VOTING_BALLOT = "VOTING_BALLOT"
    DIRECTORY_LISTING = "DIRECTORY_LISTING"


class BenefitEntitlementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class DirectoryVisibilityState(str, Enum):
    VISIBLE = "VISIBLE"
    HIDDEN_LAPSE = "HIDDEN_LAPSE"
    HIDDEN_OPT_OUT = "HIDDEN_OPT_OUT"
    HIDDEN_CATEGORY = "HIDDEN_CATEGORY"


class DuesIncreaseNoticeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class RevenueKind(str, Enum):
    CONFERENCE_REGISTRATION = "CONFERENCE_REGISTRATION"
    PUBLICATION_SALE = "PUBLICATION_SALE"
    CERTIFICATION_FEE = "CERTIFICATION_FEE"
    DONATION = "DONATION"


class ReinstatementRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


# ---------- Entity TypedDicts ----------
# All entities have common_fields: true per PRD §2.4.

class MembershipCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    is_voting: bool
    is_directory_eligible: bool
    allows_auto_renew: bool
    lapse_grace_days: int
    reinstatement_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesSchedule(TypedDict, total=False):
    id: str
    category_id: str
    effective_from: str
    effective_to: Optional[str]
    annual_amount_cents: int
    chapter_share_bps: int
    increase_notice_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chapter(TypedDict, total=False):
    id: str
    code: str
    name: str
    is_affiliate: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalCyclePolicy(TypedDict, total=False):
    id: str
    code: str
    mode: str
    calendar_anchor_month: int
    calendar_anchor_day: int
    proration_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    category_id: str
    home_chapter_id: str
    cycle_policy_id: str
    joined_at: str
    status: str
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    lifetime_dues_paid_cents: int
    risk_score: int
    created_at: str
    updated_at: str
    version: int


class MembershipTerm(TypedDict, total=False):
    id: str
    member_id: str
    period_start: str
    period_end: str
    opened_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict, total=False):
    id: str
    member_id: str
    membership_term_id: str
    dues_schedule_id: str
    amount_cents: int
    chapter_share_cents: Optional[int]
    issued_at: str
    due_at: str
    settled_at: Optional[str]
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class PaymentAttempt(TypedDict, total=False):
    id: str
    invoice_id: str
    attempt_index: int
    attempted_at: str
    outcome: str
    decline_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AutoRenewAuthorization(TypedDict, total=False):
    id: str
    member_id: str
    payment_method_token: str
    authorized_at: str
    revoked_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitEntitlement(TypedDict, total=False):
    id: str
    member_id: str
    benefit_code: str
    granted_at: str
    suspended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DirectoryListing(TypedDict, total=False):
    id: str
    member_id: str
    display_name: str
    specialty_tags: List[str]
    is_public: bool
    visibility_state: str
    created_at: str
    updated_at: str
    version: int


class DuesIncreaseNotice(TypedDict, total=False):
    id: str
    schedule_id: str
    noticed_at: str
    effective_from: str
    audience_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueAttribution(TypedDict, total=False):
    id: str
    member_id: str
    revenue_kind: str
    amount_cents: int
    occurred_at: str
    fiscal_period: str
    created_at: str
    updated_at: str
    version: int


class ReinstatementRequest(TypedDict, total=False):
    id: str
    member_id: str
    requested_at: str
    back_dues_invoice_id: str
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
