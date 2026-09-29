"""Domain constants declared by the PRD calculation rules."""

from __future__ import annotations

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- precision ---------------------------------------------------------------
MONEY_DP = 2
QUANTITY_DP = 3
UNIT_PRICE_DP = 4
FX_DP = 6

# --- incoterm cost allocation ------------------------------------------------
INLAND_ORIGIN_RATE_PER_1000KG_USD = 42.00
INLAND_DEST_RATE_PER_1000KG_USD = 55.00
EXPORT_CLEARANCE_FEE_USD = 180.00
TERMINAL_HANDLING_ORIGIN_USD = 320.00
TERMINAL_HANDLING_DEST_USD = 295.00
MIN_OCEAN_FREIGHT_USD = 450.00
MIN_MARINE_PREMIUM_USD = 75.00
MARINE_INSURANCE_RATE_PCT = 0.35
INSURANCE_COVER_FACTOR = 1.10
IMPORT_DUTY_PCT = 6.50

ZONE_MULTIPLIER = {
    "ZONE_1": 1.00,
    "ZONE_2": 1.15,
    "ZONE_3": 1.35,
}

CONTAINER_MIN_WEIGHT_KG = {
    "LCL": 0.000,
    "DRY_20": 8000.000,
    "DRY_40": 15000.000,
    "REEFER_40": 12000.000,
}

# --- invoice totalling -------------------------------------------------------
MAX_LINES_PER_INVOICE = 50

# --- discrepancy risk score --------------------------------------------------
SEVERITY_WEIGHT = {"CRITICAL": 40, "MAJOR": 15, "MINOR": 5}
CLAUSE_MULTIPLIER_ELEVATED = 1.5
CLAUSE_MULTIPLIER_PLAIN = 1.0
ELEVATED_CLAUSE_REFS = ("AMOUNT", "EXPIRY", "LATEST_SHIPMENT")
RISK_SCORE_CEILING = 100.00
RISK_ACCEPT_CEILING = 45.00
RISK_REJECT_FLOOR = 60.00
CARRYOVER_FACTOR_SAME_ROUND = 1.0
CARRYOVER_FACTOR_EARLIER_ROUND = 0.5
MAX_CURE_ROUNDS = 3

# --- negotiable amount -------------------------------------------------------
PARTIAL_UNDERDRAW_PCT = 5.00
MIN_NEGOTIATION_FEE_USD = 150.00
NEGOTIATION_FEE_PCT = 0.125
USANCE_DISCOUNT_RATE_PCT = 4.75
USANCE_DAY_BASIS = 360
MIN_USANCE_DAYS = 30

# --- insurance premium -------------------------------------------------------
TIER_1_CEILING_USD = 250000.00
TIER_2_CEILING_USD = 1000000.00
TIER_1_RATE_PCT = 0.85
TIER_2_RATE_PCT = 1.15
TIER_3_RATE_PCT = 1.60
RATING_MULTIPLIER = {
    "AAA": 0.80,
    "AA": 0.85,
    "A": 0.90,
    "BBB": 1.00,
    "BB": 1.20,
    "B": 1.45,
    "CCC": 1.80,
}
POLICY_FEE_MIN_USD = 250.00
POLICY_FEE_PCT = 0.10
DEDUCTIBLE_FEE_WAIVER_USD = 5000.00

# --- ledgers -----------------------------------------------------------------
EXHAUSTION_EPSILON_USD = 0.00
DOC_BUFFER_HOURS = 24
MAX_NEGOTIATION_ROUNDS = 3

# --- credit defaults ---------------------------------------------------------
DEFAULT_TOLERANCE_PCT = 0.00
DEFAULT_USANCE_DAYS = 0
DEFAULT_PRESENTATION_PERIOD_DAYS = 21

# --- required document types set --------------------------------------------
ALL_DOC_TYPES = [
    "COMMERCIAL_INVOICE",
    "PACKING_LIST",
    "CERTIFICATE_OF_ORIGIN",
    "BILL_OF_LADING",
    "INSURANCE_CERTIFICATE",
    "INSPECTION_CERTIFICATE",
]

# --- reserved literals -------------------------------------------------------
RESTRICTED_PARTY_CASCADE_REASON = "RESTRICTED_PARTY_CASCADE"
DENIED_PARTY_SCREENING_HIT_REASON = "DENIED_PARTY_SCREENING_HIT"
