"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Scoring thresholds of the standard test ruleset (RS-STD)
    "RS_BASE_SCORE": 10,
    "RS_REVIEW_THRESHOLD": 60,
    "RS_DECLINE_THRESHOLD": 100,
    # Alert priority model
    "TIER_POINTS_LOW": 0,
    "TIER_POINTS_MEDIUM": 100,
    "TIER_POINTS_HIGH": 200,
    "MANUAL_BAND": 25,
    "BAND_CAP": 49,
    # Risk tier cutoffs
    "HIGH_OPEN_ALERTS": 2,
    "HIGH_ROLLING_LOSS_CENTS": 100000,
    "MEDIUM_ROLLING_LOSS_CENTS": 25000,
    # Temporal rules
    "ALERT_SLA_HOURS": 72,
    "REISSUE_DUE_DAYS": 5,
    "CONTACT_GAP_MINUTES": 60,
    "FINALIZE_WINDOW_DAYS": 30,
    "REOPEN_WINDOW_DAYS": 30,
    "ROLLING_LOSS_WINDOW_DAYS": 90,
    "REOPEN_LIMIT": 2,
    # Fiscal / exposure rules
    "DECLINE_MANAGER_THRESHOLD_CENTS": 50000,
    "FINALIZE_TOLERANCE_PCT": 0.10,
    "RECOVERY_RATE_VISA": 0.45,
    "RECOVERY_RATE_MASTERCARD": 0.40,
    "RING_MIN_ACCOUNTS": 3,
    "RING_MIN_EVIDENCE_TXNS": 2,
}

# Standard ruleset payload shared by most scenarios ("RS-STD"):
# base 10, review 60, decline 100; tiers [0->5, 25000->20, 100000->45];
# channels {CHIP 0, CONTACTLESS 5, CNP 25, ATM 30}; cross 20; high-risk x2 on RU;
# watch 15; compromised 50.
STD_RULESET = {
    "scope": "GLOBAL",
    "base_score": 10,
    "review_threshold": 60,
    "decline_threshold": 100,
    "amount_tiers": [
        {"min_amount_cents": 0, "points": 5},
        {"min_amount_cents": 25000, "points": 20},
        {"min_amount_cents": 100000, "points": 45},
    ],
    "channel_weights": {"CHIP": 0, "CONTACTLESS": 5, "CNP": 25, "ATM": 30},
    "cross_border_weight": 20,
    "high_risk_multiplier": 2,
    "watch_weight": 15,
    "compromised_weight": 50,
    "high_risk_countries": ["RU"],
}

# Logical-clock anchor used as the default "now" at server start
CLOCK_START = "2026-08-01T00:00:00Z"

# Standard user ids (opaque roles)
USER_ANALYST_1 = "analyst-1"
USER_ANALYST_2 = "analyst-2"
USER_MANAGER_1 = "mgr-1"
USER_ACCOUNTANT_1 = "acct-1"
USER_RECOVERY_1 = "rec-1"
USER_GATEWAY = "gateway-1"
