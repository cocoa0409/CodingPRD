"""Domain thresholds — numeric constants from the PRD business rules."""

# Span-of-control ceiling (PRD §3.2): a manager may have at most eight
# non-abolished direct reports; the ninth is rejected.
MAX_SPAN_OF_CONTROL = 8

# Pagination (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Reusable grade-band profiles used across fixtures. Literals pinned to match
# the design-index conventions (all cents).
GRADE_G05 = {
    "code": "G05",
    "band_min_cents": 6000000,
    "band_mid_cents": 8000000,
    "band_max_cents": 10000000,
    "rank": 5,
}
GRADE_G07 = {
    "code": "G07",
    "band_min_cents": 10000000,
    "band_mid_cents": 12000000,
    "band_max_cents": 15000000,
    "rank": 7,
}
GRADE_G09 = {
    "code": "G09",
    "band_min_cents": 14000000,
    "band_mid_cents": 18000000,
    "band_max_cents": 22000000,
    "rank": 9,
}
# High-midpoint grade used for the round-per-position-then-sum boundary
# (band_mid 10000001 * 0.5 = 5000000.5 -> rounds half-up to 5000001).
GRADE_GH = {
    "code": "GH",
    "band_min_cents": 9000000,
    "band_mid_cents": 10000001,
    "band_max_cents": 11000000,
    "rank": 6,
}
