"""Domain thresholds and pinned numeric constants from the PRD's calculations."""

# ─── Pinned domain constants ──────────────────────────

THRESHOLDS = {
    # Feed freshness: cadence_minutes * multiplier is the staleness limit.
    # Exactly at the limit the feed is fresh; one minute past it the feed is stale.
    "STALE_CADENCE_MULTIPLIER": 3,
    # Flat reverse-freight amount used by the return waterfall.
    "REVERSE_FREIGHT_FLAT_CENTS": 1295,
    # Per-line penalty posted on the vendor-cancellation cascade.
    "CANCELLATION_PENALTY_CENTS": 500,
    # A vendor whose latest published defect rate exceeds this is ineligible
    # to receive routed returns.
    "DEFECT_ROUTING_MAX_DEFECT_RATE_BPS": 1500,
    # Maximum number of fallback links walked from the current offer.
    "MAX_FALLBACK_HOPS": 3,
    # Padding applied when no published scorecard exists.
    "PROMISE_DEFAULT_PADDING_DAYS": 2,
    "BPS_DENOMINATOR": 10000,
}

# Composite score weights.
SCORE_WEIGHTS = {
    "ON_TIME": 0.50,
    "CANCELLATION": 0.30,
    "DEFECT": 0.20,
}

# Composite score → tier cutoffs (inclusive lower bounds, descending).
TIER_CUTOFFS = [
    ("PLATINUM", 95.0),
    ("GOLD", 90.0),
    ("SILVER", 80.0),
    ("WATCH", 70.0),
    ("PROBATION", None),
]

# Tier → promise padding days propagated onto the vendor at publish time.
TIER_PADDING_DAYS = {
    "UNRATED": 2,
    "PLATINUM": 0,
    "GOLD": 1,
    "SILVER": 2,
    "WATCH": 3,
    "PROBATION": 5,
}

# Restocking-fee tiers keyed on the PRE-FEE refund base, in basis points.
RESTOCK_FEE_TIERS = [
    (0, 5000, 0),
    (5000, 20000, 500),
    (20000, None, 1000),
]

# Reason codes that waive the restocking fee entirely.
FEE_WAIVED_REASONS = ["DEFECTIVE", "NOT_AS_DESCRIBED", "LATE_DELIVERY"]

# Reason codes that force the vendor to own reverse freight.
VENDOR_FREIGHT_REASONS = ["DEFECTIVE", "NOT_AS_DESCRIBED"]

# Reason codes that count toward the scorecard defect rate.
DEFECT_REASON_CODES = ["DEFECTIVE", "NOT_AS_DESCRIBED"]


# ─── Logical clock ────────────────────────────────────

# The mandatory default the logical clock holds before any explicit set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"


# ─── Pagination ───────────────────────────────────────

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}


# ─── Test-scenario defaults ───────────────────────────

TEST_DEFAULTS = {
    "VENDOR_CODE": "V1",
    "LEGAL_NAME": "Northwind Dropship LLC",
    "COMMISSION_RATE_BPS": 1500,
    "WHOLESALE_DISCOUNT_BPS": 1500,
    "CADENCE_MINUTES": 60,
    "SAFETY_BUFFER_UNITS": 5,
    "OVERSELL_GRACE_UNITS": 0,
    "DEFAULT_LEAD_TIME_DAYS": 3,
    "ACK_SLA_HOURS": 24,
    "SHIP_SLA_GRACE_HOURS": 12,
    "ZONE_CODE": "US-WEST",
    "SHIP_METHOD": "GROUND",
    "TRANSIT_DAYS": 4,
    "CUTOFF_HOUR_UTC": 18,
    "SURCHARGE_CENTS": 0,
    "SKU": "SKU-CHAIR-1",
    "UNIT_RETAIL_CENTS": 24999,
    "UNIT_WHOLESALE_COST_CENTS": 12000,
    "LEAD_TIME_DAYS": 3,
    "DEFECT_WINDOW_DAYS": 30,
    "ON_HAND_UNITS": 60,
    "TRACKING_NUMBER": "1Z999AA10123456784",
}

# Constraint ranges used by boundary probes.
FIELD_RANGES = {
    "commission_rate_bps": (0, 5000),
    "wholesale_discount_bps": (0, 5000),
    "inventory_refresh_cadence_minutes": (1, 1440),
    "default_lead_time_days": (0, 60),
    "ack_sla_hours": (1, 168),
    "ship_sla_grace_hours": (0, 168),
    "promise_padding_days": (0, 5),
    "transit_days": (1, 30),
    "cutoff_hour_utc": (0, 23),
    "reopen_buffer_days": (0, 14),
    "lead_time_days": (0, 60),
    "defect_window_days": (1, 365),
    "sample_payload_digest_len": (8, 64),
    "tracking_number_len": (4, 40),
    "vendor_code_len": (1, 32),
    "legal_name_len": (1, 200),
    "sku_len": (1, 40),
    "zone_code_len": (1, 16),
    "order_ref_len": (1, 40),
    "defect_notes_len": (0, 500),
}
