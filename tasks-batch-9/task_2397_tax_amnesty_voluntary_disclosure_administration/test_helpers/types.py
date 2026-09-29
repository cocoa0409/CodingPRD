"""Entity shapes, enumerations and role names for the Tax Amnesty & Voluntary
Disclosure Administration API.

Field names and nullability mirror PRD §2.4, §2.10 and §3 exactly.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
ROLE_DISCLOSURE_OFFICER = "DisclosureOfficer"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_REPRESENTATIVE = "Representative"
ROLE_TAXPAYER = "Taxpayer"

ALL_ROLES = (
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_DISCLOSURE_OFFICER,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_REPRESENTATIVE,
    ROLE_TAXPAYER,
)

# ---------------------------------------------------------------------------
# Enumerations (PRD §2.10)
# ---------------------------------------------------------------------------

TAX_TYPES = (
    "SALES_USE",
    "CORPORATE_INCOME",
    "PERSONAL_INCOME",
    "WITHHOLDING",
    "EXCISE_FUEL",
)

TAXPAYER_TYPES = ("INDIVIDUAL", "BUSINESS")

CASE_TYPES = ("FIELD_AUDIT", "DESK_AUDIT", "CRIMINAL_INVESTIGATION", "COLLECTION")

PLAN_TYPES = ("LUMP_SUM", "INSTALLMENT")

ACTION_TYPES = ("NOTICE", "ASSESSMENT", "LIEN_REFERRAL")
ACTION_ORIGINS = ("MANUAL", "BREACH_CASCADE")

PROPOSED_BY_VALUES = ("STATE", "REPRESENTATIVE")

LIABILITY_VARIANTS = ("AMNESTY_STATUTORY", "VDA_NEGOTIATED")

SCREENING_RESULTS = (
    "ELIGIBLE",
    "INELIGIBLE_SELF_REPORTED_AUDIT",
    "INELIGIBLE_CRIMINAL_INVESTIGATION",
    "INELIGIBLE_AUDIT_IN_PROGRESS",
)

ESCALATION_TIERS = ("T0", "T1", "T2")

# ---------------------------------------------------------------------------
# Lifecycle state sets (PRD §3)
# ---------------------------------------------------------------------------

PROGRAM_STATUSES = ("DRAFT", "OPEN", "CLOSED", "RECONCILED")
CASE_STATUSES = ("OPEN", "CLOSED", "REFERRED")
REPRESENTATIVE_STATUSES = ("ACTIVE", "SUSPENDED")
PRE_CLEARANCE_STATUSES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "TERMS_OFFERED",
    "COUNTERED",
    "ACCEPTED",
    "REJECTED",
    "EXPIRED",
)
AGREEMENT_STATUSES = (
    "DRAFTED",
    "EXECUTED",
    "FULFILLED",
    "BREACHED",
    "LAPSED",
    "SUPERSEDED",
)
AGREEMENT_PAYMENT_STATUSES = ("UNPAID", "PARTIAL", "PAID_IN_FULL", "DELINQUENT")
RETURN_STATUSES = ("DRAFT", "FILED", "ASSESSED", "SETTLED", "REINSTATED", "VOIDED")
PLAN_STATUSES = (
    "PROPOSED",
    "ACTIVE",
    "REJECTED",
    "SUPERSEDED",
    "COMPLETED",
    "DEFAULTED",
)
INSTALLMENT_STATUSES = ("SCHEDULED", "LATE", "PAID", "DEFAULTED", "VOIDED")
ACTION_STATUSES = ("DRAFT", "ISSUED", "ABATED")

FORECAST_STATUSES = ("ON_TRACK", "WATCH", "SHORTFALL")

# Literal strings the server itself writes (PRD §3.6, §3.7)
DEFAULT_REASON_BREACH_CASCADE = "BREACH_CASCADE"
DEFAULT_REASON_SWEEP_GRACE_EXPIRED = "SWEEP_GRACE_EXPIRED"
ABATEMENT_REASON_BREACH_RESCINDED = "BREACH_RESCINDED"
SYSTEM_USER_ID = "SYSTEM"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every entity below carries id / created_at / updated_at / version per
# PRD §2.4, with the single documented exception of NegotiationRound, which
# "carries only `id` and `created_at` — it has neither `updated_at` nor
# `version`."
# ---------------------------------------------------------------------------


class AuditedEntity(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AmnestyProgram(AuditedEntity, total=False):
    name: str
    window_open_at: str
    window_close_at: str
    lookback_months: int
    base_penalty_waiver_pct: float
    base_interest_waiver_pct: float
    post_program_penalty_multiplier: float
    revenue_forecast_cents: int
    prospective_compliance_months: int
    installment_max_count: int
    status: str
    closed_at: Optional[str]
    collected_cents: int
    waived_total_cents: int
    reinstated_total_cents: int
    participant_count: int
    nonparticipant_count: int
    final_realization_pct: Optional[float]


class ProgramTaxTypeTerm(AuditedEntity, total=False):
    program_id: str
    tax_type: str
    eligible_period_start: str
    eligible_period_end: str
    min_liability_cents: int
    penalty_waiver_pct: Optional[float]
    interest_waiver_pct: Optional[float]
    requires_prior_nonfiler: bool


class Taxpayer(AuditedEntity, total=False):
    legal_name: str
    taxpayer_type: str
    tin_last4: str
    is_registered: bool
    escalation_tier: str
    compliance_behavior_score: int
    nonparticipant_flag: bool
    open_case_count: int
    open_enforcement_action_count: int
    nonfiler_period_count: int


class EnforcementCase(AuditedEntity, total=False):
    taxpayer_id: str
    case_type: str
    tax_type: str
    opened_at: str
    status: str
    closed_at: Optional[str]
    opened_by_user_id: str


class Representative(AuditedEntity, total=False):
    firm_name: str
    bar_number: str
    status: str


class PreClearanceRequest(AuditedEntity, total=False):
    program_id: str
    representative_id: str
    tax_type: str
    anonymous_alias: str
    estimated_liability_cents: int
    self_reported_under_audit: bool
    earliest_unfiled_period_start: str
    disclosed_taxpayer_id: Optional[str]
    status: str
    screening_result: Optional[str]
    rejection_reason: Optional[str]
    round_index: int
    counter_count: int
    current_offer_lookback_months: Optional[int]
    current_offer_penalty_waiver_pct: Optional[float]
    current_offer_interest_waiver_pct: Optional[float]
    last_offer_officer_user_id: Optional[str]


class NegotiationRound(TypedDict, total=False):
    """Append-only record: PRD §2.4 gives it only `id` and `created_at`."""

    id: str
    created_at: str
    pre_clearance_id: str
    round_index: int
    proposed_by: str
    lookback_months: int
    penalty_waiver_pct: float
    interest_waiver_pct: float
    note: Optional[str]
    actor_user_id: str


class VoluntaryDisclosureAgreement(AuditedEntity, total=False):
    program_id: str
    taxpayer_id: str
    pre_clearance_id: Optional[str]
    amends_agreement_id: Optional[str]
    tax_types: List[str]
    lookback_start_date: str
    lookback_end_date: str
    prospective_compliance_months: int
    liability_variant: str
    status: str
    drafted_by_user_id: str
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    compliance_due_at: Optional[str]
    breach_reason: Optional[str]
    gross_liability_cents: int
    haircut_pct: float
    waived_amount_cents: int
    reinstated_amount_cents: int
    total_due_cents: int
    paid_total_cents: int
    unapplied_credit_cents: int
    down_payment_applied_cents: int
    payment_status: str


class DisclosureReturn(AuditedEntity, total=False):
    agreement_id: str
    tax_type: str
    period_start_date: str
    period_end_date: str
    original_due_date: str
    reported_tax_cents: int
    is_nonfiler_period: bool
    status: str
    filed_at: Optional[str]
    accrual_end_date: Optional[str]
    days_late: int
    penalty_rate_applied: Optional[float]
    gross_penalty_cents: int
    gross_interest_cents: int
    waived_penalty_cents: int
    waived_interest_cents: int
    payable_penalty_cents: int
    payable_interest_cents: int
    balance_due_cents: int
    assessed_by_user_id: Optional[str]


class PaymentPlan(AuditedEntity, total=False):
    agreement_id: str
    plan_type: str
    installment_count: int
    down_payment_cents: int
    scheduled_total_cents: int
    status: str
    proposed_by_user_id: str
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    default_reason: Optional[str]


class Installment(AuditedEntity, total=False):
    payment_plan_id: str
    seq_index: int
    amount_cents: int
    paid_cents: int
    due_date: str
    status: str


class Payment(AuditedEntity, total=False):
    agreement_id: str
    amount_cents: int
    payment_reference: Optional[str]
    status: str
    received_at: str
    allocations: List[Dict[str, Any]]
    unapplied_delta_cents: int
    reversal_reason: Optional[str]


class EnforcementAction(AuditedEntity, total=False):
    taxpayer_id: str
    program_id: str
    agreement_id: Optional[str]
    action_type: str
    origin: str
    base_tax_cents: int
    escalation_tier_applied: str
    multiplier_applied: float
    behavior_adjustment_applied: float
    assessed_penalty_cents: int
    status: str
    created_by_user_id: Optional[str]
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    abatement_reason: Optional[str]
