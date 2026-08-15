"""Domain thresholds and shared scenario constants from the PRD.

Numeric constants come from the calculation rules in PRD §2.8-§2.10 and
§3.1-§3.9. The logical clock starts at CLOCK_DEFAULT before any admin set
call (PRD §2.4).
"""

# --- logical clock (PRD §2.4) ---
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --- region codes used across scenarios ---
REGION_OR = "OR-WILLAMETTE"
REGION_CA_NORTH = "CA-NORTH"
REGION_CA_CENTRAL = "CA-CENTRAL"
REGION_WA = "WA-YAKIMA"
REGION_NV = "NV-NORTH"

# --- weather window evaluation (PRD §3.1) ---
WET_DAY_THRESHOLD_MM = 2.0        # exactly 2.0 still counts as dry
DRYING_INDEX_MIN = 60             # exactly 60 qualifies
WINDOW_DRY_DAYS_REQUIRED = 3

# --- quality tier assignment (PRD §3.4) ---
RFV_SUPREME_MIN = 185.0
RFV_PREMIUM_MIN = 170.0
RFV_GOOD_MIN = 150.0
RFV_FAIR_MIN = 125.0
MOISTURE_TIER_CAP_PCT = 16.0      # exactly 16.0 does NOT cap

# --- market regime classification (PRD §3.3) ---
DROUGHT_REGIME_PCT = 0.15         # exactly +15% qualifies
VOLATILE_REGIME_PCT = 0.08        # exactly +/-8% qualifies
REGIME_LOOKBACK_DAYS = 30

# --- quote pricing (PRD §3.5) ---
TIER_MULTIPLIER_SUPREME = 1.30
TIER_MULTIPLIER_PREMIUM = 1.15
TIER_MULTIPLIER_GOOD = 1.00
TIER_MULTIPLIER_FAIR = 0.85
DROUGHT_SURCHARGE_PCT = 0.05
FUEL_TIER1_MAX_MILES = 100        # under 100 -> no surcharge
FUEL_TIER2_MAX_MILES = 300        # 100..299 -> 6%; 300+ -> 11%
FUEL_TIER2_PCT = 0.06
FUEL_TIER3_PCT = 0.11

# --- shrink tonnage (PRD §2.9) ---
SHRINK_MONTHLY_PCT = 0.015
SHRINK_CONTROLLED_MONTHLY_PCT = 0.0075
SHRINK_CAP_PCT = 0.12

# --- grower settlement (PRD §3.8) ---
COMMISSION_TIER1_MAX_TONS = 500   # below 500 -> 8%; exactly 500 -> 6%
COMMISSION_TIER2_MAX_TONS = 1500  # below 1500 -> 6%; 1500+ -> 4%
COMMISSION_TIER1_PCT = 0.08
COMMISSION_TIER2_PCT = 0.06
COMMISSION_TIER3_PCT = 0.04
PROTEIN_BONUS_THRESHOLD = 20.0    # exactly 20.0 earns the bonus
PROTEIN_BONUS_PCT = 0.02

# --- baling service billing (PRD §3.9) ---
BALE_RATE_TIER1_CENTS = 1200      # bales 1..500
BALE_RATE_TIER2_CENTS = 1050      # bales 501..1000
BALE_RATE_TIER3_CENTS = 900       # bales 1001+
BALE_TIER1_MAX = 500
BALE_TIER2_MAX = 1000
MIN_BALING_CHARGE_CENTS = 600000
WET_BALING_MOISTURE_PCT = 18.0    # exactly 18.0 pays no surcharge
WET_BALING_SURCHARGE_PCT = 0.15
UNSAFE_BALING_MOISTURE_PCT = 20.0  # above 20.0 rejected at completion

# --- shared scenario values (mirror the design indices' canonical figures) ---
STD_INDEX_PRICE_CENTS = 20000
STD_LANE_MILES = 420
STD_LANE_RATE_CENTS = 350
STD_LANE_MIN_CENTS = 90000
STD_WINDOW_START = "2026-07-25"
STD_WINDOW_END = "2026-08-10"
STD_DRY_DATES = ["2026-07-29", "2026-07-30", "2026-07-31"]
STD_CUT_DATE = "2026-07-31"
STD_HARVEST_DATE = "2026-08-01"
STD_SHIP_DATE = "2026-08-07"
STD_DELIVERY_BY = "2026-08-20"

# Lab technician operator ids (opaque identities; segregation of duties
# requires the certifier to differ from the recorder).
TECH_RECORDER = "tech-1"
TECH_CERTIFIER = "tech-2"
