"""Domain thresholds and numeric constants from the Cruise Booking PRD.

All money is integer cents. Percentages/factors are fractions. Generic
NON_EXISTENT_UUID comes from the framework.
"""

# Guest fare assessment (PRD 3.4)
THIRD_FOURTH_PCT = 0.55           # third/fourth occupant rate
PORT_FEE_PCT = 0.115              # port-fee percentage on final fare
FLAT_PORT_PER_GUEST_CENTS = 8900  # flat per-guest port charge

# Deposit schedule (PRD 3.4)
DEPOSIT_PCT = 0.20
DEPOSIT_MIN_PER_GUEST_CENTS = 25000

# Cancellation refund (PRD 3.8)
CANCEL_ADMIN_FEE_CENTS = 5000     # applies only at the 0% penalty tier (CASH)
FCC_PENALTY_FACTOR = 0.50         # FCC charges half the cash-tier penalty

# Folio gratuity (PRD 3.7)
GRATUITY_PER_GUEST_PER_NIGHT_CENTS = 1800

# Group discount bounds (PRD 2.9)
GROUP_DISCOUNT_DEFAULT = 0.15
GROUP_DISCOUNT_MIN = 0.0
GROUP_DISCOUNT_MAX = 0.5

# Dining turnover buffer (PRD 3.6) — fixed forty-five-minute symmetric spacing.
DINING_TURNOVER_MINUTES = 45

# Pagination defaults (PRD 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# A syntactically valid UUID that resolves to no resource.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Common reusable test fixture values.
TEST_DEFAULTS = {
    "BALCONY_BASE_FARE_CENTS": 119900,
    "EMBARK_DATE": "2026-09-01T16:00:00Z",
    "DISEMBARK_DATE": "2026-09-08T16:00:00Z",
    "NIGHTS": 7,
}
