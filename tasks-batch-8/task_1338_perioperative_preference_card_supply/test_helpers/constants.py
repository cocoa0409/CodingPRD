"""Domain thresholds — numeric constants from PRD rules."""

THRESHOLDS = {
    # PRD §3.5: waste_flag fires when rounded waste_pct reaches 20.0
    "WASTE_FLAG_THRESHOLD_PCT": 20.0,
    # PRD §3.4: substitute price cap multiplier
    "SUBSTITUTE_PRICE_MULTIPLIER": 1.25,
    # PRD §3.3: surgeon turnover buffer in minutes
    "SURGEON_TURNOVER_MIN": 30,
    # PRD §3.5 waste multipliers
    "HOLD_WASTE_MULTIPLIER": 1.5,
    "CONSIGNMENT_WASTE_MULTIPLIER": 1.0,
    "OPEN_WASTE_MULTIPLIER": 1.0,
    # PRD §3.7: quorum
    "ENDORSEMENT_QUORUM": 2,
}
