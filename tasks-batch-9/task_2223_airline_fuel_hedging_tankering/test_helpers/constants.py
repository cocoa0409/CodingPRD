"""Business constants for the Airline Fuel Hedging & Tankering API.

Every value here is quoted from the PRD; nothing is invented. Tests import
these instead of repeating magic numbers so that a formula change surfaces in
exactly one place.
"""

# ─── Mount point and envelope ─────────────────────────

API_PREFIX = "/fuel"
CLOCK_PATH = "/_clock/set_current_utc"

#: PRD §2.4 — "That clock starts at the fixed instant `2026-08-01T00:00:00Z`".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

#: PRD §2.3 — limit "defaults to 10, may not be lower than 1, and may not be
#: higher than 100"; offset "defaults to 0".
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ─── Roles (PRD §2.1) ─────────────────────────────────

ROLE_RISK_POLICY_ADMIN = "RiskPolicyAdmin"
ROLE_FUEL_ANALYST = "FuelAnalyst"
ROLE_TREASURY_RISK_MANAGER = "TreasuryRiskManager"
ROLE_HEDGE_ACCOUNTANT = "HedgeAccountant"
ROLE_FUEL_OPS_CONTROLLER = "FuelOpsController"
ROLE_STATION_COORDINATOR = "StationCoordinator"

ALL_ROLES = [
    ROLE_RISK_POLICY_ADMIN,
    ROLE_FUEL_ANALYST,
    ROLE_TREASURY_RISK_MANAGER,
    ROLE_HEDGE_ACCOUNTANT,
    ROLE_FUEL_OPS_CONTROLLER,
    ROLE_STATION_COORDINATOR,
]

#: A syntactically fine but undeclared role — PRD §2.1 makes this
#: ERR_UNAUTHENTICATED, not ERR_FORBIDDEN_ROLE.
UNDECLARED_ROLE = "FuelDirector"

# ─── Enumerations ─────────────────────────────────────

FLEET_TYPES = ["NARROWBODY", "WIDEBODY", "REGIONAL"]
ROUTE_GROUPS = [
    "DOMESTIC_SHORT",
    "DOMESTIC_LONG",
    "TRANSATLANTIC",
    "TRANSPACIFIC",
    "LATAM",
]
SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"]
INSTRUMENT_TYPES = ["SWAP", "COLLAR", "CALL_OPTION"]
CREDIT_RATINGS = ["AA", "A", "BBB", "BB"]
INDEX_BASES = ["PLATTS_USGC", "PLATTS_NWE", "PLATTS_SGP"]
COLLATERAL_TYPES = ["CASH", "LETTER_OF_CREDIT"]
COLLATERAL_ORIGINS = ["MANUAL", "MTM_MARGIN_CALL"]
EXCEPTION_REASON_CODES = [
    "COVERAGE_LIMIT",
    "COUNTERPARTY_CONCENTRATION",
    "EARNINGS_VOLATILITY_BREACH",
    "TANKERING_UNECONOMIC",
    "INVENTORY_SHORT",
]
EXCEPTION_ORIGINS = ["MANUAL", "SYSTEM_BREACH"]

POLICY_STATUSES = ["ACTIVE", "SUPERSEDED"]
COUNTERPARTY_STATUSES = ["APPROVED", "SUSPENDED"]
CREDIT_POSTURES = ["NORMAL", "WATCH", "CONSTRAINED", "BREACH"]
SUPPLY_POSTURES = ["SHORT", "WATCH", "NORMAL"]
CONTRACT_STATUSES = ["SCHEDULED", "ACTIVE", "EXPIRED"]
FORECAST_STATUSES = ["DRAFT", "PUBLISHED"]
PROGRAM_STATUSES = ["DRAFT", "SIZING", "PENDING_APPROVAL", "ACTIVE", "CLOSED"]
COMPLIANCE_POSTURES = ["COMPLIANT", "BREACH"]
TRADE_STATUSES = ["PROPOSED", "EXECUTED", "SETTLED", "TERMINATED"]
ACCOUNTING_STATUSES = ["UNDESIGNATED", "DESIGNATED", "DEDESIGNATED"]
POSTING_STATUSES = ["REQUIRED", "POSTED", "RETURNED"]
MTM_RUN_STATUSES = ["OPEN", "COMPUTED", "PUBLISHED"]
DIRECTIVE_STATUSES = [
    "PROPOSED",
    "NEEDS_REVISION",
    "APPROVED",
    "REJECTED",
    "EXECUTED",
    "RECONCILED",
    "SUPERSEDED",
]
EFFECTIVENESS_RESULTS = ["PASS", "FAIL"]
EXCEPTION_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]

# ─── Sizing (PRD §3.3) ────────────────────────────────

#: "`WINTER` counts at 1.00, `SPRING` at 0.95, `SUMMER` at 1.10 and `FALL` at 0.98."
SEASON_FACTOR = {
    "WINTER": 1.00,
    "SPRING": 0.95,
    "SUMMER": 1.10,
    "FALL": 0.98,
}

# ─── Instrument book (PRD §3.4) ───────────────────────

#: "1.00 for a `SWAP`, 0.65 for a `COLLAR`, 0.50 for a `CALL_OPTION`"
INSTRUMENT_DELTA_FACTOR = {
    "SWAP": 1.00,
    "COLLAR": 0.65,
    "CALL_OPTION": 0.50,
}

#: "a per-gallon margin rate that is 0.06 for a `SWAP`, 0.04 for a `COLLAR`
#: and 0.02 for a `CALL_OPTION`"
MARGIN_RATE_PER_GAL = {
    "SWAP": 0.06,
    "COLLAR": 0.04,
    "CALL_OPTION": 0.02,
}

#: "the absolute size of that negative mark-to-market multiplied by an
#: adverse-mark factor of 1.10"
ADVERSE_MTM_FACTOR = 1.10

#: Concentration add-on ladder, lower bounds inclusive (PRD §3.4 step four).
CONCENTRATION_ADDON_TIERS = [
    (0.0, 50.0, 0.00),
    (50.0, 75.0, 0.10),
    (75.0, 90.0, 0.25),
    (90.0, None, 0.50),
]

#: Credit posture ladder, lower bounds inclusive (PRD §3.1).
CREDIT_POSTURE_NORMAL_MAX = 70.0
CREDIT_POSTURE_WATCH_MAX = 90.0
CREDIT_POSTURE_CONSTRAINED_MAX = 100.0

# ─── Effectiveness testing (PRD §3.6) ─────────────────

#: "`PASS` when the rounded `cumulative_ratio` falls between 0.8000 and
#: 1.2500 with both bounds inclusive"
EFFECTIVENESS_RATIO_MIN = 0.8000
EFFECTIVENESS_RATIO_MAX = 1.2500

#: The exact justification string a breach cascade writes (PRD §3.6).
SYSTEM_BREACH_JUSTIFICATION = (
    "Auto-raised: undesignated mark-to-market exceeds policy earnings "
    "volatility limit."
)

# ─── Tankering (PRD §3.8) ─────────────────────────────

#: "a fixed 900-gallon reserve that is never available for tankering"
TANKERING_RESERVE_GALLONS = 900

#: "converted from pounds to gallons by dividing by 6.7 pounds per gallon"
LBS_PER_GALLON = 6.7

#: "a fleet factor of 0.030 for a `NARROWBODY`, 0.024 for a `WIDEBODY` or
#: 0.038 for a `REGIONAL`"
FLEET_TANKER_BURN_FACTOR = {
    "NARROWBODY": 0.030,
    "WIDEBODY": 0.024,
    "REGIONAL": 0.038,
}

#: "the excess of that payload ratio over the hinge point of 0.85 ...
#: multiplied by a slope of 2.0"
PAYLOAD_RATIO_HINGE = 0.85
PAYLOAD_PENALTY_SLOPE = 2.0

# ─── Supply contracts (PRD §3.2) ──────────────────────

#: "separated by a changeover buffer of at least a full week"
CHANGEOVER_BUFFER_DAYS = 7

# ─── Station supply posture (PRD §3.2) ────────────────

#: A station at exactly `min_days_cover` is WATCH; at twice the minimum or
#: above it is NORMAL.
SUPPLY_POSTURE_NORMAL_MULTIPLE = 2

# ─── Rounding tolerances ──────────────────────────────

MONEY_TOLERANCE = 0.01
PRICE_TOLERANCE = 0.0001
RATIO_TOLERANCE = 0.0001
GALLON_TENTH_TOLERANCE = 0.05
PCT_TOLERANCE = 0.01
