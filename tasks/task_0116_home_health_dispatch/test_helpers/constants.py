"""Domain thresholds — numeric constants used by tests.

Each constant traces back to a verbatim sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# PDGM base rate and LUPA threshold — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "The base 30-day rate is 2,000.00 USD".
BASE_30DAY_RATE: float = 2000.00

# PRD §3.7: "the LUPA visit-count threshold is 5 (strictly: a completed-
# visit count of fewer than 5 triggers LUPA)."
LUPA_THRESHOLD: int = 5


# ---------------------------------------------------------------------------
# Per-visit LUPA rates by discipline — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "The per-visit LUPA rates by discipline are: 160.00 USD for
# SN, 170.00 USD for PT, 165.00 USD for OT, 175.00 USD for SLP, and
# 80.00 USD for HHA."
LUPA_PER_VISIT_RATE: dict = {
    "SN": 160.00,
    "PT": 170.00,
    "OT": 165.00,
    "SLP": 175.00,
    "HHA": 80.00,
}


# ---------------------------------------------------------------------------
# Mileage tier breakpoints — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "The first tier covers the first 30 miles … multiply by 0.70
# USD per mile."
TIER1_LIMIT_MILES: int = 30
TIER1_RATE_USD_PER_MILE: float = 0.70

# PRD §3.6: "The second tier covers miles in the range above 30 up to and
# including 100 … subtract 30 from miles_driven (floored at zero), then
# take whichever is smaller of that subtraction and 70, and multiply by
# 0.55 USD per mile."
TIER2_LIMIT_MILES: int = 70  # the additional cap above tier 1
TIER2_BOUNDARY_MILES: int = 100  # miles above which tier 3 kicks in
TIER2_RATE_USD_PER_MILE: float = 0.55

# PRD §3.6: "The third tier covers every mile beyond 100; specifically,
# subtract 100 from miles_driven (floored at zero) and multiply by 0.40
# USD per mile."
TIER3_RATE_USD_PER_MILE: float = 0.40


# ---------------------------------------------------------------------------
# Case-mix weight table — PRD §3.7
# Keys: (timing_category, clinical_grouping, functional_impairment_level,
#        admission_source).
# ---------------------------------------------------------------------------
CMW_TABLE: dict = {
    ("EARLY", "MMTA_OTHER", "LOW", "COMMUNITY"): 0.9000,
    ("EARLY", "MMTA_OTHER", "MEDIUM", "COMMUNITY"): 1.0000,
    ("EARLY", "MMTA_OTHER", "HIGH", "COMMUNITY"): 1.1500,
    ("EARLY", "MMTA_OTHER", "LOW", "INSTITUTIONAL"): 1.0500,
    ("EARLY", "MMTA_OTHER", "MEDIUM", "INSTITUTIONAL"): 1.1500,
    ("EARLY", "MMTA_OTHER", "HIGH", "INSTITUTIONAL"): 1.3000,
    ("EARLY", "NEURO", "LOW", "COMMUNITY"): 1.0000,
    ("EARLY", "NEURO", "MEDIUM", "COMMUNITY"): 1.1500,
    ("EARLY", "NEURO", "HIGH", "COMMUNITY"): 1.3500,
    ("EARLY", "NEURO", "LOW", "INSTITUTIONAL"): 1.2000,
    ("EARLY", "NEURO", "MEDIUM", "INSTITUTIONAL"): 1.3500,
    ("EARLY", "NEURO", "HIGH", "INSTITUTIONAL"): 1.5000,
    ("EARLY", "WOUND", "MEDIUM", "COMMUNITY"): 1.2000,
    ("EARLY", "WOUND", "HIGH", "COMMUNITY"): 1.4000,
    ("EARLY", "MS_REHAB", "MEDIUM", "COMMUNITY"): 1.1000,
    ("EARLY", "BEHAVIORAL", "MEDIUM", "COMMUNITY"): 0.9500,
    ("EARLY", "COMPLEX", "HIGH", "INSTITUTIONAL"): 1.6000,
    ("LATE", "MMTA_OTHER", "LOW", "COMMUNITY"): 0.8000,
    ("LATE", "MMTA_OTHER", "MEDIUM", "COMMUNITY"): 0.9000,
    ("LATE", "MMTA_OTHER", "HIGH", "COMMUNITY"): 1.0500,
    ("LATE", "NEURO", "MEDIUM", "COMMUNITY"): 1.0500,
    ("LATE", "NEURO", "HIGH", "COMMUNITY"): 1.2500,
    ("LATE", "WOUND", "HIGH", "COMMUNITY"): 1.3000,
}


# ---------------------------------------------------------------------------
# HIPPS code position mappings — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "Position 1 encodes the episode's timing_category: 1 for
# EARLY and 2 for LATE."
HIPPS_TIMING_CHARS: dict = {"EARLY": "1", "LATE": "2"}

# PRD §3.7: "Position 2 encodes the OASIS clinical_grouping as a single
# letter: A for MMTA_OTHER, B for NEURO, C for WOUND, D for MS_REHAB, E
# for BEHAVIORAL, and F for COMPLEX."
HIPPS_CLINICAL_GROUPING_CHARS: dict = {
    "MMTA_OTHER": "A",
    "NEURO": "B",
    "WOUND": "C",
    "MS_REHAB": "D",
    "BEHAVIORAL": "E",
    "COMPLEX": "F",
}

# PRD §3.7: "Position 3 encodes the OASIS functional_impairment_level: F
# for LOW, G for MEDIUM, and H for HIGH."
HIPPS_FUNCTIONAL_CHARS: dict = {"LOW": "F", "MEDIUM": "G", "HIGH": "H"}

# PRD §3.7: "Position 4 encodes the OASIS admission_source: J for
# COMMUNITY and K for INSTITUTIONAL."
HIPPS_ADMISSION_CHARS: dict = {"COMMUNITY": "J", "INSTITUTIONAL": "K"}

# PRD §3.7: "Position 5 is the literal character 1."
HIPPS_POSITION_5: str = "1"


# ---------------------------------------------------------------------------
# Episode window — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §3.4: "end_date equals start_date plus 59 days — i.e., the inclusive
# 60-day window from start_date through start_date + 59 days."
EPISODE_WINDOW_DAYS: int = 60
EPISODE_END_OFFSET_DAYS: int = 59  # end_date = start_date + 59

# PRD §3.4: "recert_due_date is end_date minus four days".
RECERT_DUE_DAYS_BEFORE_END: int = 4

# PRD §3.4: "an admin-driven sweep that scans OPEN episodes and, for each
# one whose end_date is more than seven days behind current_date (i.e.,
# current_date > end_date + 7), transitions the episode to EXPIRED."
EPISODE_EXPIRE_GRACE_DAYS: int = 7


# ---------------------------------------------------------------------------
# Visit minute range — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "start_minute and end_minute are minute-of-day integers from
# 0 through 1439 inclusive."
VISIT_MINUTE_MIN: int = 0
VISIT_MINUTE_MAX: int = 1439


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter caps the number of items returned and
# defaults to 10, with a minimum of 1 and a maximum of 100. The offset
# parameter skips that many items from the beginning of the result set
# and defaults to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test defaults — anchored to PRD-named values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # Anchor date used by all difficulty-design instances. The PRD's
    # difficulty-design recipes use January 2026 as the work month, so
    # the test clock starts on 2026-01-01.
    "CLOCK_ANCHOR_DATE": "2026-01-01",
    # Default ZIP that the implementation is free to map to any
    # wage_index. The PRD does not pin the ZIP→wage_index table, so
    # tests that need a specific wage_index use a ZIP and then read the
    # computed wage_index back off the patient row.
    "DEFAULT_HOME_ZIP": "10001",
    # Calibration ZIPs used by difficulty-design recipes that need a
    # specific wage_index. Tests read the resulting wage_index from the
    # response and compute expected payments off of it; the assertion is
    # never against the ZIP→index mapping itself, which is implementation
    # defined.
    "ZIP_FOR_WAGE_INDEX_1_0000": "94538",
    "ZIP_FOR_WAGE_INDEX_1_0500": "90210",
    # A far-future expiration so the license check never fires.
    "FAR_FUTURE_LICENSE": "2099-12-31",
    # A long horizon to use as a max clock advance target.
    "CLOCK_FAR_FUTURE": "2027-01-01",
}


__all__ = [
    "BASE_30DAY_RATE",
    "LUPA_THRESHOLD",
    "LUPA_PER_VISIT_RATE",
    "TIER1_LIMIT_MILES",
    "TIER1_RATE_USD_PER_MILE",
    "TIER2_LIMIT_MILES",
    "TIER2_BOUNDARY_MILES",
    "TIER2_RATE_USD_PER_MILE",
    "TIER3_RATE_USD_PER_MILE",
    "CMW_TABLE",
    "HIPPS_TIMING_CHARS",
    "HIPPS_CLINICAL_GROUPING_CHARS",
    "HIPPS_FUNCTIONAL_CHARS",
    "HIPPS_ADMISSION_CHARS",
    "HIPPS_POSITION_5",
    "EPISODE_WINDOW_DAYS",
    "EPISODE_END_OFFSET_DAYS",
    "RECERT_DUE_DAYS_BEFORE_END",
    "EPISODE_EXPIRE_GRACE_DAYS",
    "VISIT_MINUTE_MIN",
    "VISIT_MINUTE_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
