"""Domain thresholds — numeric constants from PRD calculations (PRD §3.5, §3.6)."""

# Combined online rate hard cap (PRD §3.3: 5,000 basis points / 50.00%).
RATE_CAP_BPS = 5000

# Cash-out fee schedule (PRD §3.6).
CHECK_FEE_CENTS = 200
SMALL_CASHOUT_FEE_BPS = 200      # 2.00% for sub-large PayPal / gift-card cash-outs
LARGE_CASHOUT_CENTS = 5000       # $50.00; at/above this PayPal & gift card are fee-free

# Per-method cash-out minimums (PRD §3.6, inclusive at the boundary).
MIN_PAYPAL_CENTS = 500           # $5.00
MIN_CHECK_CENTS = 2500           # $25.00
MIN_GIFT_CARD_CENTS = 1000       # $10.00

# Streak bonus (PRD §3.8).
STREAK_BASE_CENTS = 25
STREAK_GROWTH = 0.5

# Double-dip buffer (PRD §3.4: within 24 hours of the receipt's purchased_at).
DOUBLE_DIP_WINDOW_HOURS = 24

# Server-startup logical clock (PRD §2.10).
CLOCK_START_ISO = "2026-01-01T00:00:00Z"
