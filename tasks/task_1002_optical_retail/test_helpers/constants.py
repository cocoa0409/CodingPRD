"""Domain thresholds — the numeric constants the PRD's calculations name."""

# PRD §2.5 — the logical clock reads exactly this before any client touches it.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.5 — the lens upcharge.
    "COATING_BUNDLE_PCT": 0.15,
    "COATING_BUNDLE_MIN_COUNT": 2,
    "PRISM_SURCHARGE_CENTS": 4500,
    "PRISM_TRIGGER_DIOPTERS": 0.50,
    "HIGH_POWER_RATE_CENTS_PER_DIOPTER": 1000,
    "HIGH_POWER_CAP_CENTS": 6000,
    "HIGH_POWER_BASE_DIOPTERS": 6.00,
    # PRD §3.6 — the volume discount tiers.
    "DISCOUNT_TIER_1_CENTS": 25000,
    "DISCOUNT_TIER_1_PCT": 0.10,
    "DISCOUNT_TIER_2_CENTS": 50000,
    "DISCOUNT_TIER_2_PCT": 0.15,
    # PRD §3.4 — the return-risk score.
    "ROLLING_WINDOW_DAYS": 180,
    "STRICT_HISTORY_THRESHOLD": 3,
    "W_ZERO_KEPT": 0.6,
    "W_OVERDUE": 0.4,
    "BLOCK_THRESHOLD": 70,
    # PRD §3.4 — the late fee.
    "LATE_FEE_PER_DAY_CENTS": 500,
    "LATE_FEE_CAP_CENTS": 5000,
    # PRD §3.9 — the remake liability.
    "WARRANTY_WINDOW_DAYS": 365,
    "RX_CHANGE_GRACE_DAYS": 30,
    "REMAKE_SHARE_PCT": 0.50,
    "REMAKE_SHIPPING_CENTS": 1500,
    # PRD §3.2 / §3.4 / §3.7 — hard limits.
    "PD_MIN_MM": 45.0,
    "PD_MAX_MM": 80.0,
    "KIT_MAX_FRAMES": 5,
    "REMAKE_FAILURE_LIMIT": 2,
}

# PRD §3.5 — the required index tier the prescription's power selects.
REQUIRED_INDEX_TIERS = [
    (0.00, 1.50),  # power < 4.00
    (4.00, 1.60),  # 4.00 <= power < 6.00
    (6.00, 1.67),  # 6.00 <= power < 8.00
    (8.00, 1.74),  # power >= 8.00
]

MATERIAL_INDICES = [1.50, 1.60, 1.67, 1.74]

TEST_DEFAULTS = {
    "FRAME_PRICE_CENTS": 9500,
    "FRAME_MIN_PD_MM": 50.0,
    "FRAME_MAX_PD_MM": 75.0,
    "FRAME_TRYON_STOCK": 1,
    "PD_MM": 62.0,
    "ISSUED_AT": "2026-04-01T00:00:00Z",
    "EXPIRES_AT": "2027-04-01T00:00:00Z",
}
