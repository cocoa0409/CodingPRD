"""Domain thresholds and tiered values — numeric constants from PRD calculations (§3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Thresholds (PRD §3.1, §3.2, §3.3)
THRESHOLDS = {
    "INTAKE_FLAG_THRESHOLD": 7,      # reactivity_score >= 7 ⇒ FLAGGED (§3.1)
    "TRAINER_BUFFER_MIN": 15,        # required gap between a trainer's sessions (§3.3)
    "BULK_THRESHOLD": 8,             # base_credits >= 8 ⇒ discount + bonus (§3.12)
    "BONUS_CREDITS": 1,              # bonus credit above bulk threshold (§3.12)
}

BULK_DISCOUNT = 0.10                 # 10% off base price above bulk threshold (§3.12)

# Tiered package pricing table (PRD §3.12): tier -> (credits_total, price_paid_cents)
# STARTER: 4 credits, 20000c (no discount/bonus).
# VALUE:   8 base -> 8+1 = 9 credits; 36000c -> round(36000*0.9) = 32400c.
# PRO:     16 base -> 16+1 = 17 credits; 64000c -> round(64000*0.9) = 57600c.
PACKAGE_TIERS = {
    "STARTER": {"credits_total": 4, "price_paid_cents": 20000, "base_credits": 4, "base_price": 20000},
    "VALUE": {"credits_total": 9, "price_paid_cents": 32400, "base_credits": 8, "base_price": 36000},
    "PRO": {"credits_total": 17, "price_paid_cents": 57600, "base_credits": 16, "base_price": 64000},
}

# The three required vaccine types (PRD §3.2).
REQUIRED_VACCINES = ["RABIES", "DHPP", "BORDETELLA"]

# Default test instants / dates used throughout fixtures.
DEFAULT_CLOCK_ISO = "2026-06-01T00:00:00Z"
