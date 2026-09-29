"""Domain thresholds and numeric constants taken from the PRD's pricing narratives."""

# The logical clock's fixed startup default, before any client moves it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Basis-point unit scale: 10000 bp is exactly one times the underlying quantity.
    "BP_ONE": 10000,
    # Facility posture rule 3: five stale-priced ACTIVE items restrict the facility.
    "STALE_PRICE_RESTRICT_COUNT": 5,
    # Change-request revision loop ceiling.
    "MAX_REVISION_ROUND": 3,
    # Duplicate similarity threshold; exactly 0.8000 passes.
    "DUPLICATE_SIMILARITY_THRESHOLD": 0.8000,
    # Per-line variance tolerance in basis points; exactly 100 is MATCHED.
    "LINE_VARIANCE_TOLERANCE_BP": 100,
    # Department capture-hold trip point in cents ($5,000).
    "CAPTURE_HOLD_CENTS": 500000,
    # Per-day capture-batch capacity for one department.
    "BATCH_DAY_CAPACITY": 2,
}

FACILITY_DEFAULTS = {
    "rounding_mode": "NEAREST_DOLLAR",
    "aggregate_markup_limit_bp": 40000,
    "volume_growth_bp": 10500,
    "impact_lookback_days": 90,
    "duplicate_detection_mode": "STRICT_CODE",
}

PRICE_RULE_DEFAULTS = {
    "min_medicare_multiple_bp": 12000,
    "market_cap_multiple_bp": 11000,
}

# The standard three-band ladder adopted when markup_tiers is omitted.
STANDARD_MARKUP_TIERS = [
    {"min_cost_basis_cents": 0, "markup_bp": 32000},
    {"min_cost_basis_cents": 50000, "markup_bp": 24000},
    {"min_cost_basis_cents": 250000, "markup_bp": 18000},
]

CODE_UPDATE_DEFAULTS = {
    "cost_inflator_bp": 10300,
}

PAYER_CONTRACT_DEFAULTS = {
    "trailing_units": 0,
    "renegotiation_notice_days": 30,
}

CHARGE_ITEM_DEFAULTS = {
    "companion_window_hours": 24,
}
