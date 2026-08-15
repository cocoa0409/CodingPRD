"""Domain thresholds and shared defaults — numeric constants from PRD §2.6-§2.7 and §3."""

# PRD §2.6: the logical clock starts at this exact instant before any set call.
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_STAMP = "2026-08-01T00:00:00.000Z"

# PRD §3.5: inclusive potency window for pct_of_claim.
CLAIM_MIN_PCT = 90.0
CLAIM_MAX_PCT = 110.0

# PRD §3.5: record-review yield tolerance (inclusive).
YIELD_TOLERANCE_PCT = 10.0

# PRD §3.1: allowed overage band on a formula line.
OVERAGE_PCT_MIN = 0.0
OVERAGE_PCT_MAX = 25.0

# Standard formula attributes used across scenarios.
FORMULA_DEFAULTS = {
    "name": "C500",
    "dosage_form": "TABLET",
    "allergen_class": "NONE",
    "min_order_qty": 1000,
    "batch_size_units": 10000,
    "shelf_life_months": 24,
    "overage_basis": "THEORETICAL",
}

# Standard formula line: 500 mg theoretical, 10% overage, 450 mg label claim.
LINE_DEFAULTS = {
    "theoretical_qty_mg_per_unit": 500,
    "overage_pct": 10,
    "is_label_claim_line": True,
    "label_claim_mg_per_unit": 450,
}

# Standard single price tier at the minimum order quantity.
TIER_DEFAULTS = [{"min_qty": 1000, "unit_price_cents": 120}]

# Common operational quantities.
LOT_QTY_RECEIVED = 10000000
CONSUMPTION_QTY = 5500000
ORDERED_QTY = 10000
ACTUAL_YIELD_UNITS = 9800
ACTUAL_BULK_MASS_G = 5390

# Standard non-overlapping production windows (half-open intervals, PRD §3.3).
WINDOW_DAY1 = ("2026-09-01T08:00:00Z", "2026-09-01T16:00:00Z")
WINDOW_DAY2 = ("2026-09-02T08:00:00Z", "2026-09-02T16:00:00Z")
WINDOW_DAY3 = ("2026-09-03T08:00:00Z", "2026-09-03T16:00:00Z")

# Default operator identities used in segregation-of-duties workflows (PRD §2.10).
DEFAULT_OPERATOR_ID = "op-1"
DEFAULT_CHEMIST_ID = "chem-1"
DEFAULT_QA_MANAGER_ID = "qm-1"
