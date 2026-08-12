"""Domain thresholds and money constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Overtime begins strictly beyond this many minutes of a WORK day (PRD §3.6).
    "OT_THRESHOLD_MINUTES": 480,
    # Double time applies beyond this many minutes of a WORK day (PRD §3.6).
    "DT_THRESHOLD_MINUTES": 960,
    # STANDBY days bill a flat eight hours (PRD §3.6).
    "STANDBY_FLAT_MINUTES": 480,
    # Exactly three open requests flips intake posture to RESTRICTED (PRD §2.8).
    "OPEN_REQUEST_RESTRICTION_THRESHOLD": 3,
    # Certification must occur no later than this many days after work_date (PRD §3.6).
    "CERTIFICATION_WINDOW_DAYS": 14,
    # Invoice submission closes this many days after demobilized_at (PRD §3.8).
    "INVOICE_WINDOW_DAYS": 30,
}

# Rate-card figures for the canonical "S1" schedule used across tests.
SCHEDULE_S1 = {
    "HOURLY_RATE_CENTS": 12000,     # LINE crew base rate
    "OT_MULTIPLIER_BPS": 15000,     # 1.5x (default)
    "DT_MULTIPLIER_BPS": 20000,     # 2.0x (default)
    "STORM_PREMIUM_BPS": 1000,      # 10%
    "PER_DIEM_RATE_CENTS": 8950,
    "FEE_BPS": 800,                 # 8% on the pre-fee subtotal (tier from 0)
}

# Precomputed canonical money figures (PRD §2.6 rounding discipline applied):
#   WORK 600 min on 2026-05-04 (inside premium window), equipment 35000:
#     reg 480 -> 96000; ot 120 -> 36000; labor 132000; premium -> 145200;
#     amount 145200 + 35000 = 180200.
WORK_600_WITH_EQUIP_35000 = 180200
#   WORK 480 min (exactly the OT threshold) inside premium window, equipment 35000:
#     labor 96000 -> premium 105600; amount 105600 + 35000 = 140600.
WORK_480_WITH_EQUIP_35000 = 140600
#   WORK 481 min inside premium window, equipment 35000:
#     reg 96000 + ot 300 = 96300 -> premium 105930; amount = 140930.
WORK_481_WITH_EQUIP_35000 = 140930
#   WORK 480 min, premium window end (2026-05-20, inclusive), no equipment: 105600.
WORK_480_NO_EQUIP_IN_WINDOW = 105600
#   WORK 480 min one day past the window (2026-05-21), no equipment: 96000.
WORK_480_NO_EQUIP_OUTSIDE_WINDOW = 96000
#   TRAVEL 300 min at base, no premium, no equipment: 300*12000/60 = 60000.
TRAVEL_300_AMOUNT = 60000
#   STANDBY flat 480 at base, no premium, equipment 35000: 96000 + 35000 = 131000.
STANDBY_WITH_EQUIP_35000 = 131000
#   Per-diem STANDARD, 1 member, 0 meals, TRAVEL factor: round_half_up(8950*0.75) = 6713.
PER_DIEM_STANDARD_TRAVEL_1_MEMBER = 6713
#   Two per-day rounded claims summed: 6713 + 6713 (per-day rounding precedes summation).
PER_DIEM_TWO_DAY_SUM = 13426

# Canonical invoice (T1 certified 180200 + P1 approved 6713, fee tier 800bps):
#   subtotal 186913; fee round_half_up(186913*800/10000) = 14953; total 201866.
CANONICAL_LABOR_SUBTOTAL = 180200
CANONICAL_PER_DIEM_SUBTOTAL = 6713
CANONICAL_DIRECT_SUBTOTAL = 186913
CANONICAL_FEE = 14953
CANONICAL_FINAL_TOTAL = 201866

TEST_DEFAULTS = {
    "CLOCK_START": "2026-05-01T08:00:00Z",
    "CLOCK_DEFAULT_ISO": "2026-05-01T00:00:00",
    "CERTIFY_CLOCK": "2026-05-05T09:00:00Z",
}
