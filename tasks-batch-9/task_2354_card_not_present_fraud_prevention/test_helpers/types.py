"""Entity shapes and enumerations for the Aegis CNP fraud-prevention API.

Every TypedDict mirrors the resource object the API returns in the envelope's
``data`` field. Field names are spelled exactly as the PRD spells them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role:
    """The five recognised role names, spelled exactly as the PRD spells them."""

    CHECKOUT_SERVICE = "CheckoutService"
    RISK_ANALYST = "RiskAnalyst"
    REVIEW_LEAD = "ReviewLead"
    POLICY_ENGINEER = "PolicyEngineer"
    PLATFORM_ADMIN = "PlatformAdmin"

    ALL = (
        CHECKOUT_SERVICE,
        RISK_ANALYST,
        REVIEW_LEAD,
        POLICY_ENGINEER,
        PLATFORM_ADMIN,
    )
    # Roles whose X-User-ID is the id of the acting Analyst row.
    ENTITY_BACKED = (RISK_ANALYST, REVIEW_LEAD)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


class CustomerTier:
    STANDARD = "STANDARD"
    HIGH_VALUE = "HIGH_VALUE"
    BUSINESS = "BUSINESS"

    ALL = (STANDARD, HIGH_VALUE, BUSINESS)


class AccountStatus:
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"

    ALL = (ACTIVE, LOCKED, CLOSED)


class AtoPosture:
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    CONTAINED = "CONTAINED"

    ALL = (CLEAR, WATCH, CONTAINED)


class LockedReason:
    ATO_CONTAINMENT = "ATO_CONTAINMENT"


class Customer(TypedDict):
    id: str
    email: str
    home_country: str
    tier: str
    account_status: str
    ato_posture: str
    locked_reason: Optional[str]
    good_customer_flag: bool
    lifetime_net_approved_cents: int
    approved_count: int
    declined_count: int
    confirmed_fraud_count: int
    failed_login_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Device profile
# ---------------------------------------------------------------------------


class DeviceReputation:
    NEW = "NEW"
    TRUSTED = "TRUSTED"
    SUSPECT = "SUSPECT"
    BLOCKED = "BLOCKED"

    ALL = (NEW, TRUSTED, SUSPECT, BLOCKED)


class DeviceProfile(TypedDict):
    id: str
    device_hash: str
    tz_offset_minutes: int
    emulator_flag: bool
    reputation: str
    distinct_customer_count: int
    approved_use_count: int
    fraud_confirmed_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------


class AddressClassification:
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    FREIGHT_FORWARDER = "FREIGHT_FORWARDER"
    PO_BOX = "PO_BOX"

    ALL = (RESIDENTIAL, COMMERCIAL, FREIGHT_FORWARDER, PO_BOX)


class DropRiskState:
    CLEAN = "CLEAN"
    WATCH = "WATCH"
    KNOWN_DROP = "KNOWN_DROP"

    ALL = (CLEAN, WATCH, KNOWN_DROP)


class Address(TypedDict):
    id: str
    line1: str
    postal_code: str
    country_code: str
    classification: str
    canonical_parent_address_id: Optional[str]
    canonical_address_id: str
    distinct_customer_count: int
    approved_use_count: int
    fraud_confirmed_count: int
    promo_redemption_count: int
    drop_risk_state: str
    reshipper_confidence: float
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Rule pack and fraud rule
# ---------------------------------------------------------------------------


class RulePackStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"

    ALL = (DRAFT, ACTIVE, RETIRED)


class BlendMode:
    WEIGHTED = "WEIGHTED"
    RULE_DOMINANT = "RULE_DOMINANT"

    ALL = (WEIGHTED, RULE_DOMINANT)


class SignalFamily:
    DEVICE = "DEVICE"
    BEHAVIORAL = "BEHAVIORAL"
    VELOCITY = "VELOCITY"
    IDENTITY = "IDENTITY"
    ADDRESS = "ADDRESS"
    PROMO = "PROMO"
    MODEL = "MODEL"

    ALL = (DEVICE, BEHAVIORAL, VELOCITY, IDENTITY, ADDRESS, PROMO, MODEL)
    # MODEL is a valid analyst skill and a valid primary_signal_family, but no
    # rule code belongs to it.
    RULE_FAMILIES = (DEVICE, BEHAVIORAL, VELOCITY, IDENTITY, ADDRESS, PROMO)


class RuleCode:
    DEV_MULTI_ACCOUNT = "DEV_MULTI_ACCOUNT"
    DEV_EMULATOR = "DEV_EMULATOR"
    BEH_FAST_CHECKOUT = "BEH_FAST_CHECKOUT"
    BEH_BULK_CART = "BEH_BULK_CART"
    VEL_CUSTOMER_1H = "VEL_CUSTOMER_1H"
    VEL_DEVICE_CARD_24H = "VEL_DEVICE_CARD_24H"
    ID_GEO_MISMATCH = "ID_GEO_MISMATCH"
    ADDR_DROP_RISK = "ADDR_DROP_RISK"
    ADDR_FREIGHT_FORWARDER = "ADDR_FREIGHT_FORWARDER"
    PROMO_ADDRESS_ABUSE = "PROMO_ADDRESS_ABUSE"

    ALL = (
        DEV_MULTI_ACCOUNT,
        DEV_EMULATOR,
        BEH_FAST_CHECKOUT,
        BEH_BULK_CART,
        VEL_CUSTOMER_1H,
        VEL_DEVICE_CARD_24H,
        ID_GEO_MISMATCH,
        ADDR_DROP_RISK,
        ADDR_FREIGHT_FORWARDER,
        PROMO_ADDRESS_ABUSE,
    )


#: The family each rule code actually belongs to, per the code-prefix mapping.
RULE_CODE_FAMILY: Dict[str, str] = {
    RuleCode.DEV_MULTI_ACCOUNT: SignalFamily.DEVICE,
    RuleCode.DEV_EMULATOR: SignalFamily.DEVICE,
    RuleCode.BEH_FAST_CHECKOUT: SignalFamily.BEHAVIORAL,
    RuleCode.BEH_BULK_CART: SignalFamily.BEHAVIORAL,
    RuleCode.VEL_CUSTOMER_1H: SignalFamily.VELOCITY,
    RuleCode.VEL_DEVICE_CARD_24H: SignalFamily.VELOCITY,
    RuleCode.ID_GEO_MISMATCH: SignalFamily.IDENTITY,
    RuleCode.ADDR_DROP_RISK: SignalFamily.ADDRESS,
    RuleCode.ADDR_FREIGHT_FORWARDER: SignalFamily.ADDRESS,
    RuleCode.PROMO_ADDRESS_ABUSE: SignalFamily.PROMO,
}


class RulePack(TypedDict):
    id: str
    version_label: str
    status: str
    blend_mode: str
    rule_weight: float
    model_weight: float
    review_floor_score: float
    decline_floor_score: float
    effective_from: str
    effective_until: str
    rule_count: int
    created_by_user_id: str
    activated_by_user_id: Optional[str]
    activated_at: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudRule(TypedDict):
    """A fraud rule is immutable: it carries only ``id`` and ``created_at``.

    Both ``updated_at`` and ``version`` are absent from it entirely.
    """

    id: str
    rule_pack_id: str
    code: str
    signal_family: str
    points: int
    evaluation_order: int
    hard_decline: bool
    created_at: str


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------


class RiskModelStatus:
    DRAFT = "DRAFT"
    TRAINING = "TRAINING"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"

    ALL = (DRAFT, TRAINING, SHADOW, ACTIVE, RETIRED)


class RiskModelAction:
    START_TRAINING = "START_TRAINING"
    PUBLISH_SHADOW = "PUBLISH_SHADOW"
    REJECT = "REJECT"
    PROMOTE = "PROMOTE"
    RETIRE = "RETIRE"

    ALL = (START_TRAINING, PUBLISH_SHADOW, REJECT, PROMOTE, RETIRE)


class RiskModel(TypedDict):
    id: str
    model_version_label: str
    status: str
    calibration_intercept: float
    calibration_slope: float
    trained_on_chargeback_cutoff_at: Optional[str]
    training_segment_counts: Optional[Dict[str, int]]
    scored_assessment_count: int
    promoted_at: Optional[str]
    retired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Checkout assessment
# ---------------------------------------------------------------------------


class AssessmentState:
    PENDING_SIGNALS = "PENDING_SIGNALS"
    IN_REVIEW = "IN_REVIEW"
    DECIDED_APPROVE = "DECIDED_APPROVE"
    DECIDED_DECLINE = "DECIDED_DECLINE"

    ALL = (PENDING_SIGNALS, IN_REVIEW, DECIDED_APPROVE, DECIDED_DECLINE)
    TERMINAL = (DECIDED_APPROVE, DECIDED_DECLINE)


class Decision:
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    DECLINE = "DECLINE"

    ALL = (APPROVE, REVIEW, DECLINE)


class DecisionReason:
    HARD_RULE = "HARD_RULE"
    SCORE_BAND = "SCORE_BAND"
    POLICY_EXCEPTION = "POLICY_EXCEPTION"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    ATO_CONTAINMENT = "ATO_CONTAINMENT"

    ALL = (HARD_RULE, SCORE_BAND, POLICY_EXCEPTION, MANUAL_REVIEW, ATO_CONTAINMENT)


class FinalDisposition:
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"

    ALL = (APPROVED, DECLINED)


class OutcomeLabel:
    UNKNOWN = "UNKNOWN"
    FRAUD = "FRAUD"
    LEGIT = "LEGIT"

    ALL = (UNKNOWN, FRAUD, LEGIT)


class CheckoutAssessment(TypedDict):
    id: str
    customer_id: str
    device_profile_id: str
    shipping_address_id: str
    billing_address_id: str
    rule_pack_id: str
    risk_model_id: str
    amount_cents: int
    card_bin: str
    ip_country: str
    session_seconds: int
    cart_item_count: int
    promo_code: Optional[str]
    model_raw_probability: float
    state: str
    velocity_customer_assessment_count_1h: Optional[int]
    velocity_device_distinct_card_bin_count_24h: Optional[int]
    velocity_promo_address_count_30d: Optional[int]
    rule_score: Optional[int]
    model_points: Optional[float]
    blended_score: Optional[float]
    triggered_rule_codes: Optional[List[str]]
    hard_decline_triggered: bool
    primary_signal_family: Optional[str]
    decision: Optional[str]
    decision_reason: Optional[str]
    applied_exception_id: Optional[str]
    final_disposition: Optional[str]
    outcome_label: str
    good_customer_at_decision: Optional[bool]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Analyst and review case
# ---------------------------------------------------------------------------


class Seniority:
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    LEAD = "LEAD"

    ALL = (JUNIOR, SENIOR, LEAD)


#: Seniority rank ascending: JUNIOR is lower than SENIOR, SENIOR lower than LEAD.
SENIORITY_RANK: Dict[str, int] = {
    Seniority.JUNIOR: 0,
    Seniority.SENIOR: 1,
    Seniority.LEAD: 2,
}


class AnalystStatus:
    AVAILABLE = "AVAILABLE"
    OFF_SHIFT = "OFF_SHIFT"
    SUSPENDED = "SUSPENDED"

    ALL = (AVAILABLE, OFF_SHIFT, SUSPENDED)


class Analyst(TypedDict):
    id: str
    display_name: str
    seniority: str
    skill_families: List[str]
    shift_capacity_cases: int
    status: str
    open_case_count: int
    resolved_case_count: int
    created_at: str
    updated_at: str
    version: int


class CaseState:
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    ESCALATED = "ESCALATED"
    RESOLVED_APPROVE = "RESOLVED_APPROVE"
    RESOLVED_DECLINE = "RESOLVED_DECLINE"

    ALL = (QUEUED, ASSIGNED, ESCALATED, RESOLVED_APPROVE, RESOLVED_DECLINE)
    TERMINAL = (RESOLVED_APPROVE, RESOLVED_DECLINE)
    OPEN = (QUEUED, ASSIGNED, ESCALATED)


class CaseAction:
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    ESCALATE = "ESCALATE"

    ALL = (APPROVE, DECLINE, ESCALATE)


class ReviewCase(TypedDict):
    id: str
    assessment_id: str
    primary_signal_family: str
    state: str
    priority_score: float
    sla_due_at: str
    assigned_analyst_id: Optional[str]
    escalated_by_analyst_id: Optional[str]
    assigned_at: Optional[str]
    resolved_at: Optional[str]
    resolved_late: Optional[bool]
    resolution_note: Optional[str]
    requeue_count: int
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Authentication event and step-up challenge
# ---------------------------------------------------------------------------


class AuthEventType:
    LOGIN = "LOGIN"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    EMAIL_CHANGE = "EMAIL_CHANGE"
    SHIP_ADDRESS_ADD = "SHIP_ADDRESS_ADD"
    PAYMENT_INSTRUMENT_ADD = "PAYMENT_INSTRUMENT_ADD"

    ALL = (
        LOGIN,
        PASSWORD_CHANGE,
        EMAIL_CHANGE,
        SHIP_ADDRESS_ADD,
        PAYMENT_INSTRUMENT_ADD,
    )


class AuthOutcome:
    ALLOWED = "ALLOWED"
    STEP_UP_REQUIRED = "STEP_UP_REQUIRED"
    BLOCKED = "BLOCKED"

    ALL = (ALLOWED, STEP_UP_REQUIRED, BLOCKED)


class ChallengeState:
    NONE = "NONE"
    ISSUED = "ISSUED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

    ALL = (NONE, ISSUED, PASSED, FAILED, EXPIRED)
    TERMINAL = (PASSED, EXPIRED)


class ChallengeMethod:
    OTP_SMS = "OTP_SMS"
    OTP_EMAIL = "OTP_EMAIL"
    THREE_DS = "THREE_DS"

    ALL = (OTP_SMS, OTP_EMAIL, THREE_DS)


class ChallengeAction:
    PASS = "PASS"
    FAIL = "FAIL"
    REISSUE = "REISSUE"
    EXPIRE = "EXPIRE"

    ALL = (PASS, FAIL, REISSUE, EXPIRE)


class AuthEvent(TypedDict):
    id: str
    customer_id: str
    device_profile_id: str
    event_type: str
    ip_country: str
    prior_password_change_hours: Optional[float]
    device_first_seen_for_customer: bool
    ato_score: float
    outcome: str
    challenge_state: str
    challenge_method: Optional[str]
    challenge_expires_at: Optional[str]
    challenge_attempts: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Chargeback
# ---------------------------------------------------------------------------


class ChargebackReasonCode:
    FRAUD_CNP = "FRAUD_CNP"
    FRAUD_ATO = "FRAUD_ATO"
    PRODUCT_NOT_RECEIVED = "PRODUCT_NOT_RECEIVED"
    SUBSCRIPTION_CANCELED = "SUBSCRIPTION_CANCELED"

    ALL = (FRAUD_CNP, FRAUD_ATO, PRODUCT_NOT_RECEIVED, SUBSCRIPTION_CANCELED)
    #: The two reason codes that set outcome_label to FRAUD on a loss.
    FRAUD_CODES = (FRAUD_CNP, FRAUD_ATO)


class ChargebackState:
    RECEIVED = "RECEIVED"
    REPRESENTED = "REPRESENTED"
    WON = "WON"
    LOST = "LOST"

    ALL = (RECEIVED, REPRESENTED, WON, LOST)
    TERMINAL = (WON, LOST)


class ChargebackAction:
    REPRESENT = "REPRESENT"
    WIN = "WIN"
    LOSE = "LOSE"

    ALL = (REPRESENT, WIN, LOSE)


class GuaranteeState:
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REIMBURSED = "REIMBURSED"
    DENIED = "DENIED"

    ALL = (NOT_APPLICABLE, REIMBURSED, DENIED)


class GuaranteeDenialReason:
    LIABILITY_SHIFTED = "LIABILITY_SHIFTED"
    REASON_NOT_COVERED = "REASON_NOT_COVERED"
    EXCEPTION_OVERRIDE = "EXCEPTION_OVERRIDE"
    DECISION_NOT_ELIGIBLE = "DECISION_NOT_ELIGIBLE"

    ALL = (
        LIABILITY_SHIFTED,
        REASON_NOT_COVERED,
        EXCEPTION_OVERRIDE,
        DECISION_NOT_ELIGIBLE,
    )


class Chargeback(TypedDict):
    id: str
    assessment_id: str
    reason_code: str
    amount_cents: int
    liability_shift: bool
    received_at: str
    evidence_note: Optional[str]
    state: str
    guarantee_state: str
    guarantee_denial_reason: Optional[str]
    guarantee_eligible_cents: int
    guarantee_fee_cents: int
    guarantee_reimbursed_cents: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Policy exception
# ---------------------------------------------------------------------------


class ExceptionScope:
    AUTO_APPROVE_UNDER_AMOUNT = "AUTO_APPROVE_UNDER_AMOUNT"
    ADDRESS_WHITELIST = "ADDRESS_WHITELIST"

    ALL = (AUTO_APPROVE_UNDER_AMOUNT, ADDRESS_WHITELIST)


class ExceptionState:
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"

    ALL = (REQUESTED, APPROVED, REJECTED, REVOKED)


class ExceptionAction:
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"

    ALL = (APPROVE, REJECT, REVOKE)


class PolicyException(TypedDict):
    id: str
    customer_id: str
    requested_by_analyst_id: str
    approved_by_analyst_id: Optional[str]
    scope: str
    whitelisted_address_id: Optional[str]
    max_amount_cents: int
    effective_from: str
    expires_at: str
    justification: str
    state: str
    decided_at: Optional[str]
    decision_note: Optional[str]
    consumed_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Performance report
# ---------------------------------------------------------------------------


class Cohort:
    DECISION_COHORT = "DECISION_COHORT"
    GOOD_CUSTOMER_COHORT = "GOOD_CUSTOMER_COHORT"

    ALL = (DECISION_COHORT, GOOD_CUSTOMER_COHORT)


class PerformanceReport(TypedDict):
    cohort: str
    denominator_count: int
    approved_count: int
    declined_count: int
    false_positive_count: int
    confirmed_fraud_count: int
    insult_rate: float
    fraud_capture_rate: float


#: Convenience alias for loosely-typed envelope payloads.
JsonDict = Dict[str, Any]
