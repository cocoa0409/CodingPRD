"""Domain thresholds and numeric constants from PRD §2.7, §3.2-§3.7."""

# --- condition factors (PRD §3.2, §3.7): condition_grade -> basis points ---
CONDITION_FACTOR_BP = {"A": 6000, "B": 4000, "C": 2500}

# --- ROM pricing (PRD §3.3) ---
ROM_RATE_CENTS_PER_SQFT = {"A_SIMPLE": 9000, "B_STANDARD": 14000, "C_COMPLEX": 22000}
URGENCY_WINDOW_DAYS = 28
URGENCY_MULTIPLIER_BP = 12500

# --- Detailed pricing (PRD §3.3) ---
VOLUME_TIER_MIN_CENTS = 500000
VOLUME_TIER_DISCOUNT_BP = 500

# --- Engineering safety factors (PRD §3.4) ---
SF_STATIC_MIN = 1.50
SF_DYNAMIC_MIN = 2.00

# --- Change-order pricing (PRD §3.5) ---
RUSH_PER_DAY_BP = 500
RUSH_CAP_BP = 3000
REWORK_BP = 12000
DELTA_MATERIALS_ABS_CAP_CENTS = 100000000

# --- Capacity posture (PRD §2.7) ---
TIGHT_THRESHOLD_BP = 8000
SATURATED_THRESHOLD_BP = 10000

# --- Complete-build load-in buffer (PRD §3.4) ---
LOAD_IN_BUFFER_DAYS = 2

# --- Logical clock default (PRD §2.4) ---
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --- Shared shop config used by all fixtures (PRD §3.1) ---
STANDARD_SHOP_PAYLOAD = {
    "name": "Metro Scenic",
    "weekly_crew_hours_capacity": 100,
    "horizon_weeks": 4,
    "bay_count": 2,
    "truck_fleet_size": 6,
    "labor_rate_cents_per_hour": 8000,
    "overtime_multiplier_bp": 15000,
    "overhead_pct_bp": 1000,
    "margin_pct_bp": 2000,
}
# Derived: capacity horizon = 100 * 4 = 400 crew-hours.
STANDARD_CAPACITY_HORIZON_HOURS = (
    STANDARD_SHOP_PAYLOAD["weekly_crew_hours_capacity"]
    * STANDARD_SHOP_PAYLOAD["horizon_weeks"]
)

# Standard fixed dates used by fixtures (load_in comfortably beyond the 28-day
# urgency window from the default 2026-08-01 logical clock).
STD_LOAD_IN_AT = "2026-09-26T00:00:00Z"
STD_STRIKE_AT = "2026-10-10T00:00:00Z"
STD_BUILD_START_AT = "2026-09-01T00:00:00Z"
STD_BAY_WINDOW = ("2026-09-01T00:00:00Z", "2026-09-26T00:00:00Z")
STD_TRANSPORT_WINDOW = ("2026-09-11T00:00:00Z", "2026-09-12T00:00:00Z")
STD_SHOW_TITLE = "Hamlet"
STD_VENUE = "Lyric Theatre"
STD_COMPANY_NAME = "Northlight Productions"
STD_CONTACT_EMAIL = "pm@northlight.example"
