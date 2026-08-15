"""Domain thresholds — numeric constants named in the PRD."""

THRESHOLDS = {
    # Payer compliance terms (CMS standard values used across the PRD, §3.1)
    "COMPLIANCE_THRESHOLD_PCT": 70,
    "COMPLIANCE_MIN_HOURS_PER_NIGHT": 4.0,
    "COMPLIANCE_WINDOW_DAYS": 30,
    "COMPLIANCE_MIN_NIGHTS": 21,
    # Resupply cadence defaults (PRD §3.1 typical values)
    "RENTAL_MONTHS_TO_OWN": 3,
    "MASK_CADENCE_DAYS": 90,
    "CUSHION_CADENCE_DAYS": 30,
    "FILTER_CADENCE_DAYS": 14,
    "TUBING_CADENCE_DAYS": 90,
    # Mask exchange window defaults (PRD §3.1 / §3.6)
    "MASK_EXCHANGE_WINDOW_DAYS": 30,
    "MAX_EXCHANGES_PER_WINDOW": 1,
    # Daily sweep reminder look-ahead (PRD §3.5: "looks ahead one week")
    "REMINDER_LOOKAHEAD_DAYS": 7,
    # Retrieval deadline (PRD §3.8: "a due_on deadline fourteen days after creation")
    "RETRIEVAL_DUE_DAYS": 14,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD §2.5)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Patient coinsurance fraction on an invoiced order (PRD §3.5: "twenty percent")
    "COINSURANCE_RATE": "0.20",
}
