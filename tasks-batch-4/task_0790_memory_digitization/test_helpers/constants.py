"""Domain thresholds — numeric constants from the PRD's pricing, payout,
risk, retention, download, and claim-window rules."""

# --- order_subtotal (per-item rates + volume-discount tiers) ---
RATE_TAPE = 1200
RATE_FILM = 1500
RATE_PHOTO = 50
RATE_AUDIO = 1000
VOL_TIER_1_MIN_ITEMS = 20
VOL_TIER_1_PCT = 0.10
VOL_TIER_2_MIN_ITEMS = 40
VOL_TIER_2_PCT = 0.20

# --- order_total (fees + promo bands) ---
RUSH_PCT = 0.30
PROTECTION_BASE = 1500
PROTECTION_PCT = 0.02
PROMO_BAND_HI_MIN = 13000
PROMO_BAND_HI_AMT = 1000
PROMO_BAND_LO_MIN = 10000
PROMO_BAND_LO_AMT = 500
SAVE5_CODE = "SAVE5"

# --- customer_risk_score ---
W_APPROVED = 20
W_PENDING = 5
SCORE_CAP = 100

# --- damage_payout ---
BASE_VALUE = {"TAPE": 4000, "FILM": 6000, "PHOTO": 200, "AUDIO": 3000}
PROTECTION_CAP = 10000
NO_PROTECTION_CAP = 1000

# --- system constants ---
MAX_QC_ATTEMPTS = 3
RETENTION_DAYS = 30
DOWNLOAD_EXPIRY_DAYS = 30
MAX_DOWNLOADS_PER_ARTIFACT = 3
CLAIM_WINDOW_DAYS = 90

# --- logical clock ---
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
