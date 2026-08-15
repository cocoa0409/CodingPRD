"""Domain thresholds — numeric constants named by the PRD (§2.7, §3.2–§3.7)."""

THRESHOLDS = {
    # Match scoring (PRD §3.2): weights and the per-attribute ratio cap
    "MATCH_CAP": 1.25,
    "W_CLEAR_HEIGHT": 0.30,
    "W_DOCK_DOORS": 0.30,
    "W_POWER": 0.20,
    "W_YARD": 0.20,
    # Net effective rent (PRD §3.3): TI credit cap per SF
    "TI_CAP_PSF": 50,
    # Free-rent cap at submission (PRD §3.3)
    "FREE_RENT_CAP_MONTHS": 12,
    # Accept floor: 60% of asking rate (PRD §3.3)
    "NER_FLOOR_RATIO": 0.60,
    # BTS conversion (PRD §3.5)
    "TARGET_YIELD": 0.08,
    "DEV_COMM_PCT": 0.04,
    "MARKET_MARKUP": 0.05,
    # Approval cap: 110% of the LOI base rate (PRD §3.5)
    "OVERRUN_CAP_RATIO": 1.10,
    # Delivery delay grace (PRD §3.5)
    "DELAY_GRACE_DAYS": 30,
    # Broker commission tiers (PRD §3.7)
    "COMM_TIER1_RATE": 0.05,
    "COMM_TIER1_CAP": 500000,
    "COMM_TIER2_RATE": 0.03,
    "SIDE_SPLIT": 0.5,
    "INSTALLMENT_SPLIT": 0.5,
    # Tour site-schedule buffer (PRD §3.2)
    "TOUR_BUFFER_MINUTES": 30,
}

TEST_DEFAULTS = {
    # Canonical economics literals reused across tests
    "LOI_AGGREGATE_RENT": 4247308.65,  # 8.00 * 100000 * sum(1.03^k, k=0..4)
    "LOI_NER_PSF": 5.69,
    "GROSS_COMMISSION_PER_SIDE": 68709.63,
    "COMBINED_COMMISSION": 137419.26,
    "INSTALLMENT_1": 34354.82,
    "INSTALLMENT_2": 34354.81,
    # BTS pricing results for hard 10M / soft 2M / contingency 5% (PRD §3.5)
    "BTS_BASE_COST": 12600000.00,
    "BTS_PROVISIONAL_RATE": 10.08,
    "BTS_COMMISSION_ESTIMATE": 214064.36,
    "BTS_TOTAL_PROJECT_COST": 12814064.36,
    "BTS_CONVERTED_YOC": 10.25,
    "BTS_CONVERTED_MARKET": 10.76,  # max(6.00 asking, 10.25 * 1.05)
    "BTS_YIELD_ON_COST": 0.0800,
}
