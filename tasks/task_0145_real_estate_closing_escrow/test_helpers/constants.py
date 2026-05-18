"""Domain thresholds and pinned numeric/temporal constants from PRD.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Title insurance — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "The first one hundred thousand dollars is rated at five
# dollars per thousand; the band from one hundred thousand and one
# through five hundred thousand is rated at four dollars per thousand;
# every dollar above five hundred thousand is rated at three dollars per
# thousand."
TIER1_RATE: float = 5.00
TIER2_RATE: float = 4.00
TIER3_RATE: float = 3.00
TIER1_CAP_THOUSANDS: float = 100.0   # first $100,000
TIER2_CAP_THOUSANDS: float = 400.0   # span (100, 500]
TIER_BREAKPOINT_500K_THOUSANDS: float = 500.0

# PRD §3.3: "the owner's-policy floor" of $300; "the lender's-policy
# floor" of $200; simultaneous-issue discount factor 0.40.
OWNERS_MIN_PREMIUM: float = 300.00
LENDERS_MIN_PREMIUM: float = 200.00
SIMULTANEOUS_DISCOUNT_FACTOR: float = 0.40


# ---------------------------------------------------------------------------
# EMD floor — PRD §3.2
# ---------------------------------------------------------------------------
# PRD §3.2: "the amount must be greater than or equal to one percent of
# the parent escrow file's purchase_price".
EMD_FLOOR_PCT: float = 0.01


# ---------------------------------------------------------------------------
# Cash-to-close — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "divided by the year basis of 365 days (leap years are
# ignored by design)".
YEAR_BASIS_DAYS: int = 365


# ---------------------------------------------------------------------------
# CD cooling-off — PRD §2.10
# ---------------------------------------------------------------------------
# PRD §2.10: "The Closing Disclosure cooling-off period is three
# business days".
CD_WAITING_PERIOD_BUSINESS_DAYS: int = 3


# ---------------------------------------------------------------------------
# §1031 deadlines — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "identification_deadline_at is 45 calendar days after the
# relinquished sale's closing_date_planned, and exchange_deadline_at is
# 180 calendar days after the same instant."
SECTION_1031_IDENTIFY_DAYS: int = 45
SECTION_1031_EXCHANGE_DAYS: int = 180


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "defaults to 10 when omitted, with an enforced minimum of 1
# and an enforced maximum of 100".
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Enum allowed-sets — PRD §3
# ---------------------------------------------------------------------------
PARTY_KINDS = {"BUYER", "SELLER", "LENDER", "QUALIFIED_INTERMEDIARY"}
ESCROW_FILE_STATUSES = {
    "OPEN", "CONTINGENT_TITLE", "CONTINGENT_CD",
    "CONTINGENT_WIRE", "READY_TO_CLOSE", "CLOSED", "CANCELLED",
}
EMD_STATUSES = {
    "PENDING_FUNDS", "HELD",
    "RELEASED_TO_SELLER", "RELEASED_TO_BUYER", "SPLIT",
}
EMD_RELEASED_STATUSES = {
    "RELEASED_TO_SELLER", "RELEASED_TO_BUYER", "SPLIT",
}
TITLE_SEARCH_STATUSES = {"ORDERED", "COMPLETED", "CLEARED", "DEFECTIVE"}
TITLE_POLICY_STATUSES = {"QUOTED", "BOUND", "VOIDED"}
POLICY_KINDS = {"OWNERS", "LENDERS"}
CD_STATUSES = {
    "DRAFT", "ISSUED", "ACKNOWLEDGED", "READY_TO_FUND",
    "REVISED", "VOIDED",
}
CD_TRIGGERING_CHANGE_KINDS = {
    "NONE", "APR_DELTA_OVER_THRESHOLD", "LOAN_PRODUCT_CHANGE",
    "PREPAYMENT_PENALTY_ADDED", "FEE_DELTA_UNDER_THRESHOLD",
}
CD_MAJOR_CHANGE_KINDS = {
    "APR_DELTA_OVER_THRESHOLD", "LOAN_PRODUCT_CHANGE",
    "PREPAYMENT_PENALTY_ADDED",
}
WIRE_STATUSES = {
    "DRAFT", "PENDING_CONFIRMATION", "CONFIRMED",
    "VOIDED", "REJECTED_FRAUD_FLAG",
}
BENEFICIARY_KINDS = {
    "SELLER", "LENDER_PAYOFF",
    "QUALIFIED_INTERMEDIARY", "TAX_AUTHORITY",
}
CALLBACK_CHANNELS = {"VOICE_VERIFIED", "IN_PERSON_VERIFIED"}
DISBURSEMENT_STATUSES = {
    "PROPOSED", "APPROVED", "SENT", "SETTLED", "REVERSED",
}
EXCHANGE_STATUSES = {
    "INITIATED", "IDENTIFIED",
    "CLOSED_DEFERRED", "FAILED_TAXABLE",
}
CANCEL_REASONS = {
    "BUYER_DEFAULT", "SELLER_DEFAULT",
    "TITLE_DEFECT", "MUTUAL_RELEASE",
}
AUDIT_SUBJECT_KINDS = {
    "EMD", "TITLE_SEARCH", "TITLE_POLICY", "CCR",
    "CD", "WIRE", "DISBURSEMENT", "EXCHANGE_1031",
}


# ---------------------------------------------------------------------------
# Test defaults — values that pass all PRD constraints by default
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PURCHASE_PRICE": 300000.00,
    "LOAN_AMOUNT": 240000.00,
    "EMD_AMOUNT": 3000.00,   # 1% of 300k purchase
    "TAX_ANNUAL": 1234.0,
    "HOA_ANNUAL_DUES": 789.0,
    "SELLER_DAYS_OWNED": 100,
    "TOTAL_LOAN_COSTS": 5000.00,
    "SELLER_CREDITS": 0.00,
    "INSURED_AMOUNT_OWNERS": 300000.00,
    "INSURED_AMOUNT_LENDERS": 240000.00,
    "ROUTING_NUMBER": "021000021",  # 9 digits
    "ACCOUNT_LAST4": "1234",
    "CCR_HASH": "a" * 64,  # 64-char SHA-256 hex
    # PRD §3.8: closing_date_planned is the base from which 45/180 day
    # deadlines are computed.
    "CLOSING_DATE_PLANNED": "2026-06-01T00:00:00.000Z",
}


__all__ = [
    "TIER1_RATE",
    "TIER2_RATE",
    "TIER3_RATE",
    "TIER1_CAP_THOUSANDS",
    "TIER2_CAP_THOUSANDS",
    "TIER_BREAKPOINT_500K_THOUSANDS",
    "OWNERS_MIN_PREMIUM",
    "LENDERS_MIN_PREMIUM",
    "SIMULTANEOUS_DISCOUNT_FACTOR",
    "EMD_FLOOR_PCT",
    "YEAR_BASIS_DAYS",
    "CD_WAITING_PERIOD_BUSINESS_DAYS",
    "SECTION_1031_IDENTIFY_DAYS",
    "SECTION_1031_EXCHANGE_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "PARTY_KINDS",
    "ESCROW_FILE_STATUSES",
    "EMD_STATUSES",
    "EMD_RELEASED_STATUSES",
    "TITLE_SEARCH_STATUSES",
    "TITLE_POLICY_STATUSES",
    "POLICY_KINDS",
    "CD_STATUSES",
    "CD_TRIGGERING_CHANGE_KINDS",
    "CD_MAJOR_CHANGE_KINDS",
    "WIRE_STATUSES",
    "BENEFICIARY_KINDS",
    "CALLBACK_CHANNELS",
    "DISBURSEMENT_STATUSES",
    "EXCHANGE_STATUSES",
    "CANCEL_REASONS",
    "AUDIT_SUBJECT_KINDS",
    "TEST_DEFAULTS",
]
