"""Domain thresholds — numeric constants from the PRD's pricing, capacity,
risk, and fee rules. All money is integer cents; slot/bath hours are integers."""

# Logical clock startup value (PRD section on the logical clock)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Marginal pressing tiers (per-unit cents)
TIER1_LIMIT = 299
TIER1_RATE = 320
TIER2_LIMIT = 999
TIER2_RATE = 275
TIER3_LIMIT = 4999
TIER3_RATE = 240
TIER4_RATE = 210

# Variant / weight surcharges
VARIANT_SURCHARGE = {
    "BLACK": 0,
    "SOLID_COLOR": 35,
    "SPLATTER": 55,
    "MARBLED": 65,
    "PICTURE_DISC": 120,
}
MIN_VARIANT_SURCHARGE = 5000
WEIGHT_SURCHARGE = {140: 0, 180: 25}

# Tooling / setup
LACQUER_PER_SIDE = 17500
STAMPER_FEE = 30000
STAMPER_LIFE = 1000
SETUP_ORDER = 40000
SETUP_PER_NONBLACK_VARIANT = 15000

# Discount tier percentages
TIER_PCT = {"STANDARD": 0.0, "SILVER": 0.03, "GOLD": 0.05, "PLATINUM": 0.08}

# Invoice adjustment constants
TP_REVISION_FEE = 45000
REPRESS_FLAT = 150000

# QC tolerance per color config (percent)
TOLERANCE = {
    "BLACK": 5.0,
    "SOLID_COLOR": 6.0,
    "SPLATTER": 8.0,
    "MARBLED": 8.0,
    "PICTURE_DISC": 12.0,
}

# Order composition
ORDER_MIN_UNITS = 100
VARIANT_MINIMUM = {
    "BLACK": 1,
    "SOLID_COLOR": 100,
    "SPLATTER": 100,
    "MARBLED": 100,
    "PICTURE_DISC": 200,
}
MIN_LEAD_DAYS = 21
MAX_TEST_PRESSING_QUANTITY = 20

# Color families
COLOR_FAMILY_OF = {
    "BLACK": "STANDARD",
    "SOLID_COLOR": "STANDARD",
    "SPLATTER": "SPECIAL_EFFECT",
    "MARBLED": "SPECIAL_EFFECT",
    "PICTURE_DISC": "PICTURE",
}

# Capacity
CHANGEOVER_HOURS = 1
REPRESS_INFLATION = 0.25
UNITS_PER_PALLET = {"LP": 100, "EP": 150, "SINGLE_7": 300}
ZONE_DAILY_PALLETS = {"A": 40, "B": 25, "C": 15}

# Storage fee variants
DAILY_PALLET_RATE = 55
MONTHLY_PALLET_RATE = 1500
MIN_MONTHLY_STORAGE = 5000

# Release risk stage lead times (days)
STAGE_LEAD = {
    "CONFIRMED": 45,
    "TOOLING": 35,
    "AWAITING_TP_APPROVAL": 28,
    "QUEUED": 21,
    "PRESSING": 3,
    "QC_REVIEW": 2,
}
TP_REVISION_DELAY_DAYS = 7
REPRESS_DELAY_DAYS = 10
PRINT_TRANSIT_DAYS = 3
BUFFER_DAYS = 14

# Cancellation fee percentage by production state at cancel time
CANCEL_PCT = {
    "DRAFT": 0.0,
    "QUOTED": 0.0,
    "CONFIRMED": 0.10,
    "TOOLING": 0.25,
    "AWAITING_TP_APPROVAL": 0.25,
    "QUEUED": 0.50,
    "SCHEDULED": 0.50,
}

# Waitlist promotion tier weights
TIER_WEIGHT = {"STANDARD": 10, "SILVER": 20, "GOLD": 30, "PLATINUM": 40}

# Commonly reused expected money values (integer cents), derived from the
# pricing rules above for the canonical 1000-unit all-BLACK 180g 2-sided order.
CANONICAL_QUOTE_TOTAL = 448420          # STANDARD-tier quote for qty 1000 BLACK 180g
CANONICAL_QUOTE_SUBTOTAL = 448420
CANONICAL_QUOTE_PRESSING = 288420       # 299*320 + 700*275 + 1*240
CANONICAL_QUOTE_SURCHARGE = 25000       # 1000 * 25 weight surcharge
CANONICAL_QUOTE_TOOLING = 95000         # 2*17500 + 1*2*30000
CANONICAL_QUOTE_SETUP = 40000
CANONICAL_INVOICE_NET_ACCEPTED_970 = 439455
