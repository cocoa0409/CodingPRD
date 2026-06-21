"""Domain constants from SCAFFOLD.yaml §domain_constants and §3 of the PRD."""

HIGH_RISK_MCC_SET = {"5933", "5967", "7995", "5122"}
RISK_BAND_RESERVE_BPS = {"LOW": 0, "MEDIUM": 500, "HIGH": 1000}
RISK_BAND_FUNDING_DELAY = {"LOW": 1, "MEDIUM": 2, "HIGH": 2}
RESERVE_HOLD_DAYS = 90
AUTH_HOLD_DAYS = 7
EVIDENCE_WINDOW_DAYS = 14
MAX_REPRESENTMENT_ROUNDS = 2
REPORTING_THRESHOLD_CENTS = 250000
INTERCHANGE_BPS = 165
INTERCHANGE_FIXED_CENTS = 10

# Roles
ROLE_MERCHANT = "MerchantUser"
ROLE_UNDERWRITER = "UnderwritingOfficer"
ROLE_OPERATOR = "PlatformOperator"
ROLE_ANONYMOUS = "Anonymous"
ALL_ROLES = {ROLE_MERCHANT, ROLE_UNDERWRITER, ROLE_OPERATOR, ROLE_ANONYMOUS}

# Enumerations (PRD §2.8)
ENUMS = {
    "onboarding_status": {"PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"},
    "risk_band": {"LOW", "MEDIUM", "HIGH"},
    "assigned_risk_band": {"LOW", "MEDIUM", "HIGH"},
    "payout_method": {"BANK_ACCOUNT", "DEBIT_CARD"},
    "pricing_model": {"FLAT", "INTERCHANGE_PLUS"},
    "auth_status": {"AUTHORIZED", "CAPTURED", "VOIDED", "EXPIRED"},
    "settlement_status": {"PENDING", "BATCHED", "SETTLED", "REVERSED"},
    "refund_status": {"PENDING", "SETTLED", "FAILED"},
    "reason": {"REQUESTED_BY_CUSTOMER", "DUPLICATE", "FRAUDULENT"},
    "dispute_status": {"OPEN", "UNDER_REVIEW", "REPRESENTED", "WON", "LOST", "ACCEPTED"},
    "batch_status": {"OPEN", "SETTLED", "FUNDED"},
    "payout_status": {"REQUESTED", "PAID", "RETURNED"},
    "reserve_status": {"HELD", "RELEASED"},
    "decision": {"OPEN", "APPROVED", "REJECTED"},
    "account": {"AVAILABLE", "RESERVE"},
    "event_type": {
        "CHARGE_CAPTURED", "REFUND_SETTLED", "DISPUTE_OPENED", "DISPUTE_RESOLVED",
        "BATCH_FUNDED", "PAYOUT_PAID", "RESERVE_RELEASED",
    },
}
