"""Literal value sets and shape helpers for the Home Improvement POS Financing API.

Every enumerated value the API accepts or returns is named here once so that
tests never spell a string literal twice.  Nothing in this module performs I/O.
"""

from typing import Any, Dict, List

# ─── Roles ────────────────────────────────────────────

ROLE_MERCHANT = "Merchant"
ROLE_CONSUMER = "Consumer"
ROLE_PROGRAM_UNDERWRITER = "ProgramUnderwriter"
ROLE_RISK_ANALYST = "RiskAnalyst"
ROLE_SERVICING_AGENT = "ServicingAgent"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES: List[str] = [
    ROLE_MERCHANT,
    ROLE_CONSUMER,
    ROLE_PROGRAM_UNDERWRITER,
    ROLE_RISK_ANALYST,
    ROLE_SERVICING_AGENT,
    ROLE_PROGRAM_ADMIN,
]

ENTITY_BACKED_ROLES: List[str] = [ROLE_MERCHANT, ROLE_CONSUMER]
OPAQUE_ROLES: List[str] = [
    ROLE_PROGRAM_UNDERWRITER,
    ROLE_RISK_ANALYST,
    ROLE_SERVICING_AGENT,
    ROLE_PROGRAM_ADMIN,
]

# ─── Enumerations ─────────────────────────────────────

TRADE_TYPES: List[str] = ["ROOFING", "HVAC", "SOLAR", "WINDOWS", "GENERAL_REMODEL"]

PROMOTION_TYPES: List[str] = [
    "DEFERRED_INTEREST",
    "ZERO_INTEREST_EQUAL_PAY",
    "REDUCED_APR",
    "STANDARD_REVOLVING",
]

MERCHANT_ENROLLMENT_STATUSES: List[str] = [
    "DRAFT",
    "PENDING_REVIEW",
    "DOCS_REQUIRED",
    "APPROVED",
    "SUSPENDED",
    "DECLINED",
    "TERMINATED",
]

LICENSE_VERIFICATION_STATUSES: List[str] = ["UNVERIFIED", "VERIFIED", "REJECTED", "EXPIRED"]

ENROLLMENT_STATUSES: List[str] = ["ACTIVE", "SUSPENDED", "TERMINATED"]

APPLICATION_DECISIONS: List[str] = [
    "PENDING",
    "APPROVED",
    "COUNTER_OFFERED",
    "DECLINED",
    "ACTIVATED",
    "REVOKED",
    "EXPIRED",
]

DISCLOSURE_STATUSES: List[str] = [
    "NOT_SENT",
    "DELIVERED",
    "ACKNOWLEDGED",
    "EXPIRED_UNACKNOWLEDGED",
]

DECISION_REASON_CODES: List[str] = [
    "FICO_BELOW_FLOOR",
    "DTI_ABOVE_CEILING",
    "WITHIN_LIMIT",
    "LIMIT_BELOW_TICKET",
    "REVOKED_DTI_BREACH",
    "OFFER_LAPSED",
    "MERCHANT_TERMINATED",
]

PROMO_STATUSES: List[str] = ["PROMO_ACTIVE", "PROMO_SATISFIED", "PROMO_EXPIRED_CAPITALIZED"]

BALANCE_STATUSES: List[str] = ["CURRENT", "DELINQUENT", "PAID_OFF", "CHARGED_OFF"]

PROJECT_COMPLETION_STATUSES: List[str] = [
    "IN_PROGRESS",
    "SUBSTANTIALLY_COMPLETE",
    "CERTIFIED_COMPLETE",
    "ABANDONED",
]

MILESTONE_STATUSES: List[str] = ["PENDING", "CLAIMED", "VERIFIED", "REJECTED"]

DRAW_STATUSES: List[str] = ["REQUESTED", "SETTLED", "DENIED", "REVERSED"]

SETTLEMENT_SPEEDS: List[str] = ["NEXT_DAY", "STANDARD_3DAY"]

DISPUTE_STATUSES: List[str] = [
    "SUBMITTED",
    "MERCHANT_RESPONSE_PENDING",
    "ESCALATED_NO_RESPONSE",
    "RESOLVED_MERCHANT_FAVOR",
    "RESOLVED_CONSUMER_FAVOR",
]

DISPUTE_RESPONSE_TYPES: List[str] = ["WORK_COMPLETE_EVIDENCE", "CONCEDE"]

DISPUTE_OUTCOMES: List[str] = ["MERCHANT_FAVOR", "CONSUMER_FAVOR"]

ALERT_TYPES: List[str] = [
    "PHANTOM_PROJECT",
    "PRE_COMPLETION_FULL_DRAW",
    "VELOCITY_SPIKE",
    "DUPLICATE_CONSUMER",
]

ALERT_STATUSES: List[str] = ["OPEN", "CONFIRMED", "CLEARED"]
ALERT_SOURCES: List[str] = ["ANALYST", "SYSTEM"]
ALERT_OUTCOMES: List[str] = ["CONFIRMED", "CLEARED"]

RISK_TIERS: List[str] = ["LOW", "STANDARD", "ELEVATED", "HIGH"]
PORTFOLIO_GRADES: List[str] = ["A", "B", "C", "D"]

SUSPENSION_REASON_CODES: List[str] = ["ANALYST_ACTION", "RESERVE_COVERAGE", "FRAUD_CONFIRMED"]
DENIAL_REASON_CODES: List[str] = ["MERCHANT_SUSPENDED", "MERCHANT_TERMINATED"]

PROGRAM_ACTIONS: List[str] = ["SUSPEND", "REINSTATE", "TERMINATE"]
ENROLLMENT_DECISIONS: List[str] = ["APPROVE", "DECLINE", "REQUEST_DOCS"]
LICENSE_VERIFICATION_OUTCOMES: List[str] = ["VERIFIED", "REJECTED"]
MILESTONE_VERIFICATION_OUTCOMES: List[str] = ["VERIFY", "REJECT"]
DRAW_SETTLEMENT_DECISIONS: List[str] = ["SETTLE", "DENY"]
ADJUSTMENT_TYPES: List[str] = ["DEPOSIT", "RELEASE"]
PAYMENT_SOURCE_ROLES: List[str] = ["CONSUMER", "SERVICING_AGENT"]

SWEEP_COUNT_KEYS: List[str] = [
    "expired_licenses",
    "expired_offers",
    "expired_disclosures",
    "capitalized_loans",
    "delinquent_loans",
    "charged_off_loans",
    "escalated_disputes",
]

# ─── Field groups ─────────────────────────────────────

# Every resource carries id + created_at.  All but Payment additionally carry
# updated_at and version.
COMMON_FIELDS_FULL: List[str] = ["id", "created_at", "updated_at", "version"]
COMMON_FIELDS_EVENT_ONLY: List[str] = ["id", "created_at"]

JsonDict = Dict[str, Any]
