"""Domain thresholds — numeric constants from PRD calculations (PRD §3.2, §3.4, §3.7)."""


# ─── Title insurance tier breaks and rates (PRD §3.2) ──────────────
# Prices and tier breaks are stated in dollars in PRD prose; the
# equivalent values in cents (the API's unit) are listed below.
TIER1_BREAK_CENTS = 10_000_000     # $100,000
TIER2_BREAK_CENTS = 50_000_000     # $500,000
TIER3_BREAK_CENTS = 100_000_000    # $1,000,000

TIER1_RATE = 0.00450
TIER2_RATE = 0.00400
TIER3_RATE = 0.00350
TIER4_RATE = 0.00300

LENDER_CONCURRENT_DISCOUNT = 0.15  # 15% rebate when LENDER wire exists (non-REJECTED)


# ─── Closing Disclosure clock & material-change threshold (PRD §3.4) ──
CD_WAIT_PERIOD_SECONDS = 72 * 3600  # 72 hours of clock time
APR_REISSUE_BPS_THRESHOLD = 12      # >=12 bps absolute delta is "material"


# ─── 1031 Exchange deadlines (PRD §3.7) ────────────────────────────
EXCHANGE_IDENTIFICATION_DAYS = 45
EXCHANGE_DEADLINE_DAYS = 180
EXCHANGE_IDENTIFICATION_SECONDS = 45 * 86400
EXCHANGE_DEADLINE_SECONDS = 180 * 86400


# ─── Purchase price range (PRD §3.1) ───────────────────────────────
PRICE_FLOOR_CENTS = 100_000          # 100,000 cents = $1,000
PRICE_CEILING_CENTS = 1_000_000_000_000  # one trillion cents = $10B
