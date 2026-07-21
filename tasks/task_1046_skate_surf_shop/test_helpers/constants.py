"""Domain thresholds — numeric constants from the PRD calculations and scheduling rules."""

# --- Build final price (PRD §3.3) ---
TIER_DISCOUNT = {"STANDARD": 0.0, "PRO": 0.10, "TEAM": 0.20}
SETUP_FEE_CENTS = 2500

# --- Trade-in payout (PRD §3.6) ---
CASH_RATE = 0.50
CREDIT_RATE = 0.70
CONSIGNMENT_FEE = 0.30

# --- Loyalty accrual (PRD §2.9) ---
POINTS_DIVISOR = 100
TIER_MULTIPLIER = {"STANDARD": 1, "PRO": 2, "TEAM": 3}
MAX_POINTS_PER_TXN = 500

# --- Rental charge (PRD §3.5 / §2.8) ---
LATE_FEE_PER_DAY_CENTS = 1500
MAX_RENTAL_DAYS = 14

# --- Service charge (PRD §3.4) ---
SERVICE_LABOR_CENTS = {"GRIP": 800, "WHEEL": 1500, "WAX": 500}

# --- Bay scheduling (PRD §2.8) ---
SETUP_BUFFER_MINUTES = 30

# --- Logical clock (PRD §2.12) ---
CLOCK_START_UTC = "2026-07-01T00:00:00Z"
