"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Callback requirement (PRD §3.2): wires of at least $1,000,000.00
    "CALLBACK_THRESHOLD_CENTS": 100000000,
    # Callback verification window (PRD §3.2)
    "CALLBACK_WINDOW_HOURS": 4,
    # Fraud-hold customer confirmation window (PRD §3.8)
    "FRAUD_HOLD_WINDOW_HOURS": 24,
    # Recall beneficiary-bank response window (PRD §3.9)
    "RECALL_RESPONSE_WINDOW_HOURS": 72,
    # Risk score bands and components (PRD §3.3)
    "AMOUNT_BAND_1_CENTS": 100000000,
    "AMOUNT_BAND_2_CENTS": 500000000,
    "VELOCITY_THRESHOLD_CENTS": 1000000000,
    "VELOCITY_WINDOW_DAYS": 30,
    "RISK_REVIEW_THRESHOLD": 50,
    # Fee schedule (PRD §3.7)
    "BASE_FEE_FEDWIRE_CENTS": 2500,
    "BASE_FEE_SWIFT_CENTS": 3500,
    "BASE_FEE_CHIPS_CENTS": 1800,
    "PRIORITY_SURCHARGE_SAME_DAY_CENTS": 1000,
    # Repair / tracer caps (PRD §3.4, §3.10)
    "MAX_REPAIR_ATTEMPTS": 2,
    "MAX_TRACERS": 3,
}

# Beneficiary-pays share of the base fee, and bank-absorbed share of a
# DEDUCTED_FROM_PRINCIPAL charge (PRD §3.7).
BENEPAY_SHARE = 0.40
DEDUCTED_FACTOR = 0.50

# The logical clock reads exactly this instant at startup (PRD §2.5).
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "DAILY_OUTGOING_LIMIT_CENTS": 250000000,
    "WIRE_AMOUNT_CENTS": 100000,
    "OPERATOR_USER_ID": "op-1",
    "APPROVER_1_USER_ID": "ap-1",
    "APPROVER_2_USER_ID": "ap-2",
    "SCREENER_USER_ID": "ss-1",
    "OFFICER_USER_ID": "co-1",
    "FRAUD_ANALYST_USER_ID": "fa-1",
    "REPAIR_SPECIALIST_USER_ID": "rs-1",
    "INVESTIGATOR_USER_ID": "inv-1",
    "BENEFICIARY_BANK_USER_ID": "benebank-1",
    "ADMIN_USER_ID": "admin-1",
    "AUDITOR_USER_ID": "aud-1",
}
