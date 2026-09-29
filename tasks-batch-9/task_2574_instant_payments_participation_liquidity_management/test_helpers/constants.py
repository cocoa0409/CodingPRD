"""Business constants of the Instant Payments Participation & Liquidity API.

Every value here is stated numerically in the PRD; nothing is invented.
All monetary quantities are integer cents.
"""

# ---------------------------------------------------------------- clock / dates
# "Before any caller sets it, the clock reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Instants used repeatedly by the scenarios below.
CLOCK_2026_08_01 = "2026-08-01T00:00:00Z"
CLOCK_2026_08_03_09_00 = "2026-08-03T09:00:00Z"
CLOCK_2026_08_03_13_00 = "2026-08-03T13:00:00Z"
BUSINESS_DATE_2026_08_01 = "2026-08-01"
BUSINESS_DATE_2026_08_02 = "2026-08-02"
BUSINESS_DATE_2026_08_03 = "2026-08-03"
BUSINESS_DATE_2026_08_04 = "2026-08-04"

# ---------------------------------------------------------------- money / bands
# "The opening deposit must be at least the network minimum of 100,000,000 cents"
MIN_PREFUND_CENTS = 100_000_000
# "the amount is additionally capped at 50,000,000 cents" while THROTTLED
THROTTLED_PER_TXN_CAP_CENTS = 50_000_000

# ---------------------------------------------------------------- fraud scoring
FRAUD_HOLD_THRESHOLD = 60          # "A score of at least 60 but below 85 is held"
FRAUD_BLOCK_THRESHOLD = 85         # "A score of 85 or more is blocked outright"
FRAUD_QUEUE_PRIORITY_THRESHOLD = 75  # queue_priority 1 at or above 75, else 2
FRAUD_SCORE_CEILING = 100          # "the result capped at 100"
BASELINE_RISK_CODE_THRESHOLD = 40  # "BASELINE_RISK when the base is at least 40"

AMOUNT_UNIT_CENTS = 100_000        # "divides it by 100,000 cents"
AMOUNT_TERM_CAP = 10               # "caps that whole number of bands at 10"
AMOUNT_WEIGHT = 2                  # "multiplies the result by a weight of 2"

VELOCITY_WEIGHT_ORIGINATION = 4
VELOCITY_FREE_COUNT_ORIGINATION = 3
VELOCITY_WEIGHT_FINAL = 3
VELOCITY_FREE_COUNT_FINAL = 5
NEW_BENEFICIARY_BONUS = 12

SEGMENT_MULTIPLIERS = {
    "CONSUMER": "1.00",
    "SMALL_BUSINESS": "1.05",
    "CORPORATE": "1.10",
    "HIGH_RISK": "1.25",
}

# ---------------------------------------------------------------- time windows
VELOCITY_WINDOW_MINUTES = 60             # rolling origination velocity window
FINAL_VELOCITY_WINDOW_MINUTES = 1440     # review-time velocity window
FRAUD_REVIEW_SLA_MINUTES = 60            # assignment instant plus 60 minutes
ALERT_ESCALATION_MINUTES = 60            # "once 60 minutes have elapsed"
QUEUE_TTL_MINUTES = 120                  # "at least 120 minutes (two hours) old"
RFP_RESPONSE_SLA_MINUTES = 30            # "the delivery instant plus 30 minutes"
RETURN_RESPONSE_SLA_MINUTES = 1440       # "lodgement instant plus 1,440 minutes"
RETURN_REQUEST_WINDOW_MINUTES = 4320     # "within 4,320 minutes (three days)"
PROJECTION_HORIZON_MINUTES = 1440        # "1,440 minutes (twenty-four hours) later"
OUTAGE_STABILIZATION_BUFFER_MINUTES = 15
MAX_AMENDMENT_ROUNDS = 2                 # "At most two amendment rounds are permitted"

# ---------------------------------------------------------------- fees / recon
FEE_RATE_BPS = 10                  # "ten basis points"
FEE_BPS_DIVISOR = 10_000
FEE_REBATE_MIN_COUNT = 10          # "settled at least 10 transfers on that date"
FEE_REBATE_NUMERATOR = 1           # "one tenth of the gross fee"
FEE_REBATE_DENOMINATOR = 10
VARIANCE_TOLERANCE_CENTS = 100     # "tolerance of 100 cents"

# ---------------------------------------------------------------- enum sets
PARTICIPATION_MODELS = ("SEND_AND_RECEIVE", "RECEIVE_ONLY", "RECEIVE_AND_REQUEST_FOR_PAYMENT")
ENROLLMENT_STATUSES = (
    "DRAFT", "ATTESTATION_PENDING", "CERTIFICATION_TESTING", "REMEDIATION",
    "CERTIFIED", "LIVE", "SUSPENDED", "WITHDRAWN",
)
OPERATIONAL_POSTURES = ("NORMAL", "THROTTLED", "SEND_FROZEN", "OFFLINE")
ALERT_TIERS = ("GREEN", "AMBER", "RED", "BREACH")
ALERT_STATUSES = ("OPEN", "ACKNOWLEDGED", "ESCALATED", "CLEARED")
SEGMENTS = ("CONSUMER", "SMALL_BUSINESS", "CORPORATE", "HIGH_RISK")
CUSTOMER_ACCOUNT_STATUSES = ("ACTIVE", "RESTRICTED")
LEDGER_ENTRY_TYPES = (
    "FUNDING_CREDIT", "RETURN_CREDIT", "WITHDRAWAL_DEBIT", "TRANSFER_DEBIT", "FEE_DEBIT",
)
CREDIT_ENTRY_TYPES = ("FUNDING_CREDIT", "RETURN_CREDIT")
DEBIT_ENTRY_TYPES = ("WITHDRAWAL_DEBIT", "TRANSFER_DEBIT", "FEE_DEBIT")
TRANSFER_DIRECTIONS = ("OUTBOUND", "INBOUND")
TRANSFER_RAILS = ("INSTANT", "FALLBACK_ACH", "FALLBACK_WIRE")
CLEARING_STATUSES = (
    "INITIATED", "FRAUD_HOLD", "QUEUED_THROTTLED", "ACCEPTED",
    "SETTLED", "REJECTED", "DIVERTED", "EXPIRED",
)
RESERVING_CLEARING_STATUSES = ("INITIATED", "FRAUD_HOLD", "ACCEPTED")
EXCEPTION_STATUSES = (
    "NONE", "RETURN_REQUESTED", "RETURN_HONORED", "RETURN_DECLINED", "RETURN_EXPIRED",
)
REJECTION_REASON_CODES = ("FRAUD_BLOCK_AUTOMATIC", "FRAUD_BLOCK_REVIEW")
FRAUD_REASON_CODES = ("BASELINE_RISK", "AMOUNT_BAND", "VELOCITY_BURST", "NEW_BENEFICIARY")
FRAUD_REVIEW_STATUSES = ("QUEUED", "UNDER_REVIEW", "RELEASED", "BLOCKED")
FRAUD_DECISIONS = ("RELEASE", "BLOCK")
RFP_STATUSES = ("CREATED", "DELIVERED", "ACCEPTED", "DECLINED", "AMENDMENT_REQUESTED", "EXPIRED")
RFP_RESPONSES = ("ACCEPT", "DECLINE", "REQUEST_AMENDMENT")
RFP_DECLINE_REASON_CODES = ("ACCOUNT_CLOSED", "AMOUNT_DISPUTED", "NOT_RECOGNIZED", "INSUFFICIENT_FUNDS")
RETURN_REASON_CODES = ("DUPLICATE_PAYMENT", "WRONG_BENEFICIARY", "FRAUD_SUSPECTED", "TECHNICAL_ERROR")
RETURN_STATUSES = ("REQUESTED", "HONORED", "DECLINED", "EXPIRED")
RETURN_DECLINE_REASON_CODES = ("FUNDS_DISBURSED", "BENEFICIARY_REFUSED", "OUT_OF_TIME")
SETTLEMENT_CYCLE_STATUSES = ("OPEN", "CUTOFF", "RECONCILING", "OUT_OF_BALANCE", "RECONCILED")
RECONCILIATION_VARIANTS = ("PROVISIONAL", "FINAL")
RECONCILIATION_OUTCOMES = ("BALANCED", "OUT_OF_BALANCE")
OUTAGE_SCOPES = ("PARTICIPANT", "NETWORK_WIDE")
OUTAGE_SEVERITIES = ("DEGRADED", "FULL_OUTAGE")
FALLBACK_RAILS = ("FALLBACK_ACH", "FALLBACK_WIRE", "NONE")
OUTAGE_STATUSES = ("DECLARED", "RESOLVED")
CERTIFICATION_OUTCOMES = ("PASS", "FAIL")
PARTICIPANT_TARGET_STATUSES = ("SUSPENDED", "LIVE", "WITHDRAWN")

# ---------------------------------------------------------------- routing numbers
ROUTING_ALPHA = "021000021"
ROUTING_BETA = "021000089"
ROUTING_GAMMA = "021000109"
ROUTING_DELTA = "021000208"
ROUTING_UNENROLLED = "021000322"
