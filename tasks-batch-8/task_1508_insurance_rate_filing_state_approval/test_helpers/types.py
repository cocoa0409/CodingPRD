"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCT_ACTUARY = "ProductActuary"
    FILING_ANALYST = "FilingAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STATE_REGULATOR = "StateRegulator"
    IMPLEMENTATION_LEAD = "ImplementationLead"


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FilingMethod(str, Enum):
    PRIOR_APPROVAL = "PRIOR_APPROVAL"
    FILE_AND_USE = "FILE_AND_USE"
    USE_AND_FILE = "USE_AND_FILE"


class IndicationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_ACTUARIAL_REVIEW = "IN_ACTUARIAL_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class IndicationVariant(str, Enum):
    INCURRED_CREDIBILITY = "INCURRED_CREDIBILITY"
    PAID_PURE = "PAID_PURE"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    UNDER_OBJECTION = "UNDER_OBJECTION"
    APPROVED = "APPROVED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISAPPROVED = "DISAPPROVED"
    WITHDRAWN = "WITHDRAWN"


class FilingType(str, Enum):
    RATE_CHANGE = "RATE_CHANGE"
    RATE_RULE_FORM = "RATE_RULE_FORM"
    RULE_ONLY = "RULE_ONLY"
    FORM_ONLY = "FORM_ONLY"


class ComponentType(str, Enum):
    RATE = "RATE"
    RULE = "RULE"
    FORM = "FORM"


class ComponentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class DeviationType(str, Enum):
    RATE_FACTOR = "RATE_FACTOR"
    RULE_TEXT = "RULE_TEXT"
    FORM_TEXT = "FORM_TEXT"


class DeviationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class ObjectionStatus(str, Enum):
    RAISED = "RAISED"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    OVERDUE = "OVERDUE"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class ResponseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class WaveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PolicyStatus(str, Enum):
    PENDING = "PENDING"
    RATED = "RATED"
    NOTICE_SENT = "NOTICE_SENT"
    COMPLETED = "COMPLETED"
    RESCINDED = "RESCINDED"


class ExclusionReason(str, Enum):
    LATE_NOTICE_BY_CONSTRUCTION = "LATE_NOTICE_BY_CONSTRUCTION"
    LATE_NOTICE_SWEEP = "LATE_NOTICE_SWEEP"


class CalendarEntryType(str, Enum):
    OBJECTION_RESPONSE_DUE = "OBJECTION_RESPONSE_DUE"
    DEEMER_DATE = "DEEMER_DATE"
    WAVE_WINDOW = "WAVE_WINDOW"
    RENEWAL_NOTICE_DUE = "RENEWAL_NOTICE_DUE"
    EFFECTIVE_DATE = "EFFECTIVE_DATE"


class CalendarEntryStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class Product(TypedDict, total=False):
    id: str
    product_code: str
    name: str
    current_locked_indication_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateRegulatoryProfile(TypedDict, total=False):
    id: str
    product_id: str
    state_code: str
    filing_method: str
    min_effective_lead_days: int
    objection_response_sla_days: int
    deemer_days: int
    max_single_change_pct: float
    renewal_notice_days: int
    disapproval_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateIndication(TypedDict, total=False):
    id: str
    product_id: str
    scope_state_code: Optional[str]
    variant: str
    earned_premium_cents: int
    incurred_loss_cents: int
    paid_loss_cents: int
    exposure_units: int
    trend_factor: float
    countrywide_change_pct: float
    credibility_z: float
    indicated_change_pct: float
    alternate_change_pct: float
    status: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    review_round: int
    created_at: str
    updated_at: str
    version: int


class RateFiling(TypedDict, total=False):
    id: str
    product_id: str
    profile_id: str
    indication_id: str
    state_code: str
    filing_type: str
    proposed_change_pct: float
    proposed_effective_date: str
    filing_number: Optional[str]
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    actual_effective_date: Optional[str]
    deemer_date: Optional[str]
    superseded_at_date: Optional[str]
    open_objection_count: int
    created_at: str
    updated_at: str
    version: int


class FilingComponent(TypedDict, total=False):
    id: str
    filing_id: str
    component_type: str
    name: str
    content_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deviation(TypedDict, total=False):
    id: str
    filing_id: str
    deviation_type: str
    base_reference: str
    deviation_factor: float
    justification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict, total=False):
    id: str
    filing_id: str
    question_text: str
    raised_at: str
    due_at: str
    status: str
    reopen_count: int
    late_breach: bool
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObjectionResponse(TypedDict, total=False):
    id: str
    objection_id: str
    response_text: str
    status: str
    drafted_by_user_id: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImplementationWave(TypedDict, total=False):
    id: str
    filing_id: str
    product_id: str
    state_code: str
    wave_start_date: str
    wave_end_date: str
    cap_pct: float
    approved_change_pct: float
    balance_factor: Optional[float]
    target_book_delta_cents: Optional[int]
    final_book_delta_cents: Optional[int]
    rated_policy_count: int
    excluded_late_notice_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalPolicy(TypedDict, total=False):
    id: str
    product_id: str
    wave_id: Optional[str]
    state_code: str
    policy_number: str
    current_premium_cents: int
    class_rel_factor: float
    renewal_effective_date: str
    baseline_premium_cents: Optional[int]
    raw_change_pct: Optional[float]
    raw_new_premium_cents: Optional[int]
    was_capped: Optional[bool]
    final_premium_cents: Optional[int]
    notice_due_date: Optional[str]
    notice_sent_at: Optional[str]
    status: str
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceCalendarEntry(TypedDict, total=False):
    id: str
    filing_id: Optional[str]
    wave_id: Optional[str]
    objection_id: Optional[str]
    entry_type: str
    due_date: str
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
