"""Domain thresholds and pre-computed expected values from PRD charge math.

All amounts are integer cents. The canonical scenario used across the design
indices fixes a GOLD package (per_head 15000, fb_min 2000000, service 0.22,
tax 0.08) on a DUAL space (rental 500000), with expected_guest_count 120.
The values below are the exact figures the PRD's pinned rounding order yields.
"""

# Milestone split fractions (deposit / interim; final absorbs the remainder).
DEPOSIT_PCT = 0.25
INTERIM_PCT = 0.35

# Standard soft-hold window in hours (PRD §3.3: "the standard soft-hold window
# of six hours").
HOLD_DURATION_HOURS = 6

# ─── Canonical GOLD-package charge math (expected_guest_count = 120) ───
# 120 * 15000 = 1_800_000 < fb_minimum 2_000_000 → floor binds.
PROVISIONAL = {
    "FB_SUBTOTAL": 2_000_000,                 # max(1_800_000, 2_000_000)
    "SERVICE": 440_000,                       # round_half_up(2_000_000 * 0.22)
    "TAX": 195_200,                           # round_half_up(2_440_000 * 0.08)
    "RENTAL": 500_000,                        # one distinct DUAL space
    "EVENT_CHARGE": 3_135_200,                # 2_000_000 + 440_000 + 195_200 + 500_000
    # milestone schedule on 3_135_200:
    "DEPOSIT_DUE": 783_800,                   # round_half_up(3_135_200 * 0.25)
    "INTERIM_DUE": 1_097_320,                 # round_half_up(3_135_200 * 0.35)
    "FINAL_DUE": 1_254_080,                   # 3_135_200 - 783_800 - 1_097_320
}

# ─── Final charge math (guaranteed_count = 150) ───
# 150 * 15000 = 2_250_000 > fb_minimum 2_000_000 → per-head total binds.
FINAL = {
    "FB_SUBTOTAL": 2_250_000,                 # max(2_250_000, 2_000_000)
    "SERVICE": 495_000,                       # round_half_up(2_250_000 * 0.22)
    "TAX": 219_600,                           # round_half_up(2_745_000 * 0.08)
    "RENTAL": 500_000,
    "EVENT_CHARGE": 3_464_600,                # 2_250_000 + 495_000 + 219_600 + 500_000
}

# Standard deposit amount paid to settle the deposit milestone in fixtures.
STANDARD_DEPOSIT_CENTS = PROVISIONAL["DEPOSIT_DUE"]   # 783_800

# Balance remaining after the deposit milestone on the provisional charge.
BALANCE_AFTER_DEPOSIT = PROVISIONAL["EVENT_CHARGE"] - STANDARD_DEPOSIT_CENTS   # 2_351_400


# ─── Cancellation retention table (cancellation_tier × booking_status) ───
RETENTION_TABLE = {
    "STANDARD": {"HELD": 0.00, "CONFIRMED": 0.25, "GUARANTEED": 0.50},
    "STRICT": {"HELD": 0.00, "CONFIRMED": 0.50, "GUARANTEED": 1.00},
    "FLEXIBLE": {"HELD": 0.00, "CONFIRMED": 0.00, "GUARANTEED": 0.25},
}


# ─── Canonical clock / schedule constants used across fixtures ───
BASE_CLOCK_ISO = "2026-06-01T00:00:00Z"
EVENT_DATE = "2026-09-12"
CEREMONY_START = "2026-09-12T20:00:00Z"
CEREMONY_END = "2026-09-12T21:00:00Z"
RECEPTION_START = "2026-09-12T21:00:00Z"
RECEPTION_END = "2026-09-13T02:00:00Z"
