"""Domain thresholds and reusable literal values from the PRD.

Every numeric constant here is stated in PRD prose; the test suite reads them
from this module so a threshold is never re-typed in two places.
"""

# ─── Money and pricing ────────────────────────────────

# PRD §3.2 — a bag valued at 25000 cents already requires a signature.
SIGNATURE_VALUE_THRESHOLD_CENTS = 25_000

# PRD §3.3 line 6 — 400 cents per billable attempt beyond the first, capped at two units.
REATTEMPT_SURCHARGE_CENTS = 400
REATTEMPT_SURCHARGE_MAX_UNITS = 2

# PRD §2.5 / §3.3 line 5 — after-hours window boundaries in UTC hours.
AFTER_HOURS_START_UTC_HOUR = 20
AFTER_HOURS_END_UTC_HOUR = 6

# PRD §3.3 — the pharmacy goodwill absorption tiers, keyed on the
# member's pre-absorption net.
ABSORPTION_TIER3_FLOOR_CENTS = 1_000
ABSORPTION_TIER3_CENTS = 500
ABSORPTION_TIER2_FLOOR_CENTS = 500
ABSORPTION_TIER2_CENTS = 200
ABSORPTION_TIER1_CENTS = 50

# ─── Courier reliability ──────────────────────────────

# PRD §3.7 — at most three most-recent attempts, weight 0.8 ** index.
ROLLING_WINDOW_SIZE = 3
ROLLING_DECAY_FACTOR = 0.8
# PRD §3.7 — suspension needs attempt_total_count >= 3 and lifetime score < 60.00.
COURIER_SCORE_MIN_ATTEMPTS = 3
COURIER_MIN_LIFETIME_SCORE = 60.00
DEFAULT_RELIABILITY_SCORE = 100.00

# ─── Routing and custody ──────────────────────────────

# PRD §3.4 — an offer expires ten minutes after it is made.
OFFER_TTL_MINUTES = 10
# PRD §3.4 — a courier's committed interval is padded 15 minutes on each end.
COURIER_TURNAROUND_BUFFER_MINUTES = 15
# PRD §3.6 — a bag gets at most three door-step runs.
MAX_DELIVERY_ATTEMPTS = 3
REATTEMPT_COOLDOWN_STAGE1_MINUTES = 60
REATTEMPT_COOLDOWN_STAGE2_MINUTES = 180
# PRD §3.6 — the INTAKE/READY revision loop is bounded at two round trips.
MAX_ORDER_HOLDS = 2
# PRD §3.3 — a SCHEDULED reservation must arrive two hours before window_start.
DISPATCH_LEAD_MINUTES = 120
# PRD §3.5 — 120 minutes out of the box forces COLD_BREACH.
COLD_CHAIN_MAX_EXCURSION_MINUTES = 120
# PRD §2.11 — the courier projection withholds exactly six fields.
COURIER_PROJECTION_REDACTED_FIELD_COUNT = 6
COURIER_PROJECTION_KEYS = [
    "delivery_id",
    "order_id",
    "patient_masked_name",
    "patient_phone_last4",
    "address_line",
    "window_start",
    "window_end",
    "handling_class",
    "signature_required",
    "required_id_verification",
    "rx_line_count",
    "redacted_field_count",
    "disclosure_id",
]

# ─── Logical clock helpers ────────────────────────────

# PRD §2.5 — the clock starts here and stays until an operator moves it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"


def utc_ts(day: int, hour: int, minute: int = 0, month: int = 8, year: int = 2026) -> str:
    """Build an ISO 8601 UTC instant for the logical clock and window bounds."""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


# Recurring instants used across the suite.
CLOCK_INTAKE_DAY3 = utc_ts(3, 9)            # 2026-08-03T09:00:00Z
CLOCK_DISPATCH_DAY3 = utc_ts(3, 13, 45)     # 2026-08-03T13:45:00Z
CLOCK_PICKUP_DAY3 = utc_ts(3, 13, 50)       # 2026-08-03T13:50:00Z
CLOCK_DOORSTEP_DAY3 = utc_ts(3, 14)         # 2026-08-03T14:00:00Z

WINDOW_START_DAY3 = utc_ts(3, 14)           # 2026-08-03T14:00:00Z
WINDOW_END_DAY3 = utc_ts(3, 16)             # 2026-08-03T16:00:00Z

# ─── Reference-data test defaults ─────────────────────

# Zone Z1: base 705, per mile 123 over a 6.4-mile band (ceils to 7 → 861),
# cold pack 455, controlled handling 605, after hours 305.
ZONE_Z1 = {
    "zone_code": "Z1",
    "distance_band_miles": 6.4,
    "base_fee_cents": 705,
    "per_mile_cents": 123,
    "cold_pack_fee_cents": 455,
    "controlled_handling_fee_cents": 605,
    "after_hours_fee_cents": 305,
    "cold_chain_supported": True,
    "controlled_delivery_allowed": True,
}

# Zone Z2: base 2005, per mile 155 over an 8.2-mile band (ceils to 9 → 1395),
# no cold-chain support.
ZONE_Z2 = {
    "zone_code": "Z2",
    "distance_band_miles": 8.2,
    "base_fee_cents": 2005,
    "per_mile_cents": 155,
    "cold_pack_fee_cents": 500,
    "controlled_handling_fee_cents": 700,
    "after_hours_fee_cents": 305,
    "cold_chain_supported": False,
    "controlled_delivery_allowed": True,
}

# The Z1 standard-bag line vector and its derived figures at a 10% cost share.
Z1_STANDARD_LINES = [705, 861, 0, 0, 0, 0]
Z1_STANDARD_SUBTOTAL_CENTS = 1566
# The Z1 cold-chain controlled line vector on a provisional (single-run) bill.
Z1_COLD_CONTROLLED_LINES = [705, 861, 455, 605, 0, 0]
Z1_COLD_CONTROLLED_SUBTOTAL_CENTS = 2626

# Named operations users. PRD §2.1 makes X-User-ID an opaque operator identifier
# for NetworkOps, and §3.8 needs two distinct ones to carry a case to adjudication.
OPS_USER_A = "9f000000-0000-4000-8000-0000000000a1"
OPS_USER_B = "9f000000-0000-4000-8000-0000000000b2"
OPS_USER_C = "9f000000-0000-4000-8000-0000000000c3"
OPS_REVIEWER = "ops-reviewer-1"

# A syntactically valid identifier that names no stored row.
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"
