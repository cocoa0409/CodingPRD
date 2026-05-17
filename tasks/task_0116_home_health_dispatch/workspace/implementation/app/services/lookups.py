"""Static lookup tables — PRD §3 / SCAFFOLD §1.3."""
from decimal import Decimal


# Base 30-day PDGM rate (PRD §3.7).
BASE_30DAY_RATE = Decimal("2000.00")

# LUPA visit-count threshold (strict: count < threshold triggers LUPA).
LUPA_THRESHOLD = 5

# Per-visit LUPA rates by discipline (PRD §3.7).
LUPA_PER_VISIT_RATE = {
    "SN": Decimal("160.00"),
    "PT": Decimal("170.00"),
    "OT": Decimal("165.00"),
    "SLP": Decimal("175.00"),
    "HHA": Decimal("80.00"),
}

# Mileage tier rates (PRD §3.6).
TIER1_LIMIT_MILES = Decimal("30")
TIER2_LIMIT_MILES = Decimal("70")  # tier 2 covers (30..100], i.e. up to 70 additional miles
TIER1_RATE = Decimal("0.70")
TIER2_RATE = Decimal("0.55")
TIER3_RATE = Decimal("0.40")

# Case-mix weight table — keyed by (timing_category, clinical_grouping,
# functional_impairment_level, admission_source) -> weight (Decimal, 4 decimals).
CMW_TABLE: dict = {
    ("EARLY", "MMTA_OTHER", "LOW",    "COMMUNITY"):     Decimal("0.9000"),
    ("EARLY", "MMTA_OTHER", "MEDIUM", "COMMUNITY"):     Decimal("1.0000"),
    ("EARLY", "MMTA_OTHER", "HIGH",   "COMMUNITY"):     Decimal("1.1500"),
    ("EARLY", "MMTA_OTHER", "LOW",    "INSTITUTIONAL"): Decimal("1.0500"),
    ("EARLY", "MMTA_OTHER", "MEDIUM", "INSTITUTIONAL"): Decimal("1.1500"),
    ("EARLY", "MMTA_OTHER", "HIGH",   "INSTITUTIONAL"): Decimal("1.3000"),
    ("EARLY", "NEURO",      "LOW",    "COMMUNITY"):     Decimal("1.0000"),
    ("EARLY", "NEURO",      "MEDIUM", "COMMUNITY"):     Decimal("1.1500"),
    ("EARLY", "NEURO",      "HIGH",   "COMMUNITY"):     Decimal("1.3500"),
    ("EARLY", "NEURO",      "LOW",    "INSTITUTIONAL"): Decimal("1.2000"),
    ("EARLY", "NEURO",      "MEDIUM", "INSTITUTIONAL"): Decimal("1.3500"),
    ("EARLY", "NEURO",      "HIGH",   "INSTITUTIONAL"): Decimal("1.5000"),
    ("EARLY", "WOUND",      "MEDIUM", "COMMUNITY"):     Decimal("1.2000"),
    ("EARLY", "WOUND",      "HIGH",   "COMMUNITY"):     Decimal("1.4000"),
    ("EARLY", "MS_REHAB",   "MEDIUM", "COMMUNITY"):     Decimal("1.1000"),
    ("EARLY", "BEHAVIORAL", "MEDIUM", "COMMUNITY"):     Decimal("0.9500"),
    ("EARLY", "COMPLEX",    "HIGH",   "INSTITUTIONAL"): Decimal("1.6000"),
    ("LATE",  "MMTA_OTHER", "LOW",    "COMMUNITY"):     Decimal("0.8000"),
    ("LATE",  "MMTA_OTHER", "MEDIUM", "COMMUNITY"):     Decimal("0.9000"),
    ("LATE",  "MMTA_OTHER", "HIGH",   "COMMUNITY"):     Decimal("1.0500"),
    ("LATE",  "NEURO",      "MEDIUM", "COMMUNITY"):     Decimal("1.0500"),
    ("LATE",  "NEURO",      "HIGH",   "COMMUNITY"):     Decimal("1.2500"),
    ("LATE",  "WOUND",      "HIGH",   "COMMUNITY"):     Decimal("1.3000"),
}


# HIPPS code position 2: clinical_grouping -> letter (PRD §3.7).
CLINICAL_GROUPING_LETTER = {
    "MMTA_OTHER": "A",
    "NEURO":      "B",
    "WOUND":      "C",
    "MS_REHAB":   "D",
    "BEHAVIORAL": "E",
    "COMPLEX":    "F",
}

# HIPPS code position 3: functional_impairment_level -> letter (PRD §3.7).
FUNCTIONAL_LETTER = {
    "LOW":    "F",
    "MEDIUM": "G",
    "HIGH":   "H",
}

# HIPPS code position 4: admission_source -> letter (PRD §3.7).
ADMISSION_LETTER = {
    "COMMUNITY":     "J",
    "INSTITUTIONAL": "K",
}


# wage_index lookup keyed by ZIP code (5 digits). Patients whose ZIP isn't in
# the table fall back to DEFAULT_WAGE_INDEX. Sample-table values are kept simple
# so tests can reason about them deterministically.
DEFAULT_WAGE_INDEX = Decimal("1.0000")


def lookup_wage_index(zip_code: str) -> Decimal:
    """Compute wage_index from a 5-digit ZIP code.

    The CMS wage index is real-world per-CBSA; for the API surface we derive a
    deterministic Decimal from the numeric ZIP prefix in [0.80, 1.30] so each
    distinct ZIP maps to a stable index but the value isn't trivially 1.0.
    """
    if not isinstance(zip_code, str) or len(zip_code) != 5 or not zip_code.isdigit():
        # caller validates input; this is a defensive fallback.
        return DEFAULT_WAGE_INDEX
    # Map the integer ZIP into a 4-decimal value in [0.80, 1.30].
    n = int(zip_code)
    # 0..99999 -> 0..50 in steps of (50/99999), then /100 -> 0.00..0.50
    # final wage index = 0.80 + (n mod 5001) / 10000  (deterministic, 4dp)
    raw = Decimal(n % 5001) / Decimal(10000)
    wi = (Decimal("0.8000") + raw).quantize(Decimal("0.0001"))
    return wi
