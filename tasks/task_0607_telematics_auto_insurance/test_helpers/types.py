"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    DRIVER_USER = "DriverUser"
    UNDERWRITING_OPS = "UnderwritingOps"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# --- Status enums (PRD §3) ---
class RatePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class EnrollmentStatus(str, Enum):
    SCORING = "SCORING"
    READY_TO_QUOTE = "READY_TO_QUOTE"
    QUOTED = "QUOTED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"


class QuoteStatus(str, Enum):
    OPEN = "OPEN"
    BOUND = "BOUND"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class PolicyBillingStatus(str, Enum):
    PERIOD_OPEN = "PERIOD_OPEN"
    PERIOD_CLOSING = "PERIOD_CLOSING"
    PERIOD_SETTLED = "PERIOD_SETTLED"


class PolicyTelematicsStatus(str, Enum):
    CAPTURING = "CAPTURING"
    SUSPENDED = "SUSPENDED"


class PolicyLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class TripStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class TripEventType(str, Enum):
    HARD_BRAKE = "HARD_BRAKE"
    SPEEDING = "SPEEDING"
    PHONE_USE = "PHONE_USE"
    CRASH = "CRASH"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class RenewalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class ClaimStatus(str, Enum):
    FNOL = "FNOL"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class ClaimOrigin(str, Enum):
    AUTO_FNOL = "AUTO_FNOL"
    MANUAL = "MANUAL"


class ConsentAction(str, Enum):
    GRANT = "GRANT"
    REVOKE = "REVOKE"


class GrantLeg(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
# common_fields: false -> ONLY id + created_at

class RatePlan(TypedDict):
    id: str
    name: str
    state_code: str
    base_premium_cents: int
    per_mile_rate_cents: float
    included_miles_per_period: int
    hard_brake_weight: float
    speeding_weight: float
    phone_use_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    telematics_opted_out: bool
    lifetime_safe_miles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivacyConsent(TypedDict):
    # common_fields: false — append-only
    id: str
    driver_id: str
    action: str
    reason: Optional[str]
    effective_at: str
    created_at: str


class Enrollment(TypedDict):
    id: str
    driver_id: str
    rate_plan_id: str
    scoring_days: int
    scoring_started_at: str
    scoring_deadline: str
    captured_trip_count: int
    provisional_risk_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    driver_id: str
    enrollment_id: str
    rate_plan_id: str
    locked_risk_score: float
    risk_multiplier: float
    quoted_annual_premium_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    driver_id: str
    quote_id: str
    rate_plan_id: str
    bound_premium_cents: int
    current_risk_score: float
    current_risk_multiplier: float
    period_index: int
    billing_status: str
    telematics_status: str
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    policy_id: Optional[str]
    enrollment_id: Optional[str]
    started_at: str
    ended_at: str
    distance_miles: float
    hard_brake_count: int
    speeding_count: int
    phone_use_count: int
    crash_detected: bool
    billed_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TripEvent(TypedDict):
    # common_fields: false — append-only
    id: str
    trip_id: str
    event_type: str
    severity: int
    occurred_at: str
    created_at: str


class RiskScoreSnapshot(TypedDict):
    # common_fields: false — append-only
    id: str
    policy_id: str
    trigger_reason: str
    risk_score: float
    risk_multiplier: float
    snapshot_at: str
    created_at: str


class PremiumStatement(TypedDict):
    id: str
    policy_id: str
    period_index: int
    billed_miles: float
    overage_miles: float
    base_charge_cents: int
    mileage_charge_cents: int
    applied_discount_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict):
    id: str
    policy_id: str
    prior_premium_cents: int
    recalculated_risk_score: float
    recalculated_premium_cents: int
    banked_discount_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    trip_id: Optional[str]
    origin: str
    reported_severity: int
    reserve_cents: int
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscountBank(TypedDict):
    id: str
    driver_id: str
    earned_cents: int
    redeemed_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class DiscountGrant(TypedDict):
    # common_fields: false — append-only
    id: str
    discount_bank_id: str
    leg: str
    amount_cents: int
    source_reason: str
    granted_at: str
    created_at: str
