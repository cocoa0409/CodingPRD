"""System-wide constants drawn from the PRD/SCAFFOLD calculation tables."""

# --- Pagination (PRD 2.3, scaffold response_envelope.pagination_defaults) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0

# --- Demand pricing tiers (PRD 3.4 / calc leg_fare_cents) ---
DEMAND_TIER_MID = 0.5
DEMAND_TIER_HIGH = 0.8
DEMAND_MULT_LOW = "1.00"
DEMAND_MULT_MID = "1.25"
DEMAND_MULT_HIGH = "1.60"

# --- Advance-window factors (PRD 3.4 / calc leg_fare_cents) ---
ADV_DAYS_EARLY = 14
ADV_DAYS_MID = 7
ADV_DAYS_LATE = 3
ADV_FACTOR_EARLY = "0.90"
ADV_FACTOR_MID = "1.00"
ADV_FACTOR_LATE = "1.15"
ADV_FACTOR_LAST = "1.40"

# --- Cancellation penalty tiers (PRD 3.6 / calc cancel_settlement) ---
PENALTY_FREE_DAYS = 7
PENALTY_MID_DAYS = 1
PENALTY_PCT_FREE = "0.00"
PENALTY_PCT_MID = "0.25"
PENALTY_PCT_LAST = "0.50"
CREDIT_LENIENCY_PCT = "0.10"

# --- Baggage (PRD 3.11 / calc baggage_fee_cents) ---
FREE_BAG_KG = "23.0"
OVERWEIGHT_RATE_CENTS_PER_KG = 500

# --- Operator policy defaults (PRD 3.1) ---
DEFAULT_CONNECTION_BUFFER_MIN = 30
DEFAULT_EXCHANGE_FEE_CENTS = 1000

# --- Hold time-to-live (PRD 3.3: "current clock instant plus the hold
#     time-to-live"; the numeric value is not pinned by PRD/scaffold). ---
HOLD_TTL_MIN = 30

# --- Accessible slots per service date (PRD 3.12: "per-service-date
#     accessible-slot ceiling"; numeric value not pinned by PRD/scaffold). ---
ACCESSIBLE_SLOTS_PER_SERVICE_DATE = 2

# --- Enumerations ---
OPERATOR_MODES = {"RAIL", "BUS"}
FARE_CODES = {"ECONOMY", "BUSINESS"}
SEATING_MODES = {"RESERVED", "OPEN"}
FUNDING_KINDS = {"CASH", "PASS"}
REFUND_DESTINATIONS = {"CASH", "TRAVEL_CREDIT"}
ACCOMMODATIONS = {"WHEELCHAIR_SPACE", "COMPANION_SEAT", "SERVICE_ANIMAL"}

ROLES = {"ScheduleManager", "FareAnalyst", "Passenger", "GateAgent", "SupportAgent"}
