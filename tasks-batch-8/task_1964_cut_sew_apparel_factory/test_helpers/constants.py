"""Domain thresholds — numeric constants from PRD §3 calculations."""

THRESHOLDS = {
    # PRD §3.5: 2% end-loss allowance + 0.5 yd splice allowance on marker approve.
    "END_LOSS_PCT": 0.02,
    "SPLICE_YARDS": 0.5,
    # PRD §3.7: guaranteed-minimum floor rate, cents per hour.
    "HOURLY_GUARANTEE_CENTS": 1500,
    # PRD §3.7: efficiency bonus tiers (inclusive lower bounds).
    "BONUS_TIER_LOW": 90,
    "BONUS_TIER_HIGH": 100,
    # PRD §3.2: cost-basis qualification threshold.
    "DOMESTIC_COST_THRESHOLD": 0.7,
    # PRD §3.6: operator changeover buffer between same-day assignments.
    "CHANGEOVER_BUFFER_MINUTES": 15,
}

# PRD §3.8: AQL lot-size tiers (inclusive both ends) -> code letter.
AQL_LOT_TIERS = [
    (2, 8, "A"),
    (9, 15, "B"),
    (16, 25, "C"),
    (26, 50, "D"),
    (51, 90, "E"),
    (91, 150, "F"),
    (151, 280, "G"),
    (281, 500, "H"),
    (501, 1200, "J"),
]

AQL_SAMPLE_SIZES = {"A": 2, "B": 3, "C": 5, "D": 8, "E": 13, "F": 20, "G": 32, "H": 50, "J": 80}

AQL_ACCEPT_REJECT = {
    "AQL_2_5": {"A": (0, 1), "B": (0, 1), "C": (0, 1), "D": (0, 1), "E": (1, 2),
                "F": (1, 2), "G": (2, 3), "H": (3, 4), "J": (5, 6)},
    "AQL_4_0": {"A": (0, 1), "B": (0, 1), "C": (0, 1), "D": (1, 2), "E": (1, 2),
                "F": (2, 3), "G": (3, 4), "H": (5, 6), "J": (7, 8)},
}

TEST_DEFAULTS = {
    "WORK_DATE": "2026-08-03",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-31",
    "RECEIVED_YARDS_41_3": 41.3,
    "MARKER_LENGTH_40": 40.0,
    "ALLOCATED_FOR_40": 41.3,  # round(40.0 * 1.02, 2) + 0.5
}
