"""Domain thresholds and constants from the PRD.

Numeric values used in PRD calculations and timing rules, plus test
defaults that exercise them. PRD section refs are inline.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# GWP-100 table (PRD §3.5)
# "gwp_factor is the GWP-100 value for that gas (CO2 = 1, CH4 = 28,
#  N2O = 265, HFC = 1430, PFC = 7390, SF6 = 23500, NF3 = 16100)"
# ---------------------------------------------------------------------------
GWP_TABLE: dict = {
    "CO2": 1,
    "CH4": 28,
    "N2O": 265,
    "HFC": 1430,
    "PFC": 7390,
    "SF6": 23500,
    "NF3": 16100,
}


# ---------------------------------------------------------------------------
# Data-quality scores (PRD §3.5)
# "METER_READING scores 1.00, INVOICE scores 0.80, SUPPLIER_DATA scores
#  0.65, and ESTIMATION scores 0.40"
# ---------------------------------------------------------------------------
DATA_QUALITY_SCORES: dict = {
    "METER_READING": 1.00,
    "INVOICE": 0.80,
    "SUPPLIER_DATA": 0.65,
    "ESTIMATION": 0.40,
}


# ---------------------------------------------------------------------------
# Materiality bounds (PRD §3.1)
# "must lie between 0.0 and 5.0 percent inclusive with two decimal places"
# Default per PRD: 1.0 percent.
# ---------------------------------------------------------------------------
MATERIALITY_MIN_PCT = 0.0
MATERIALITY_MAX_PCT = 5.0
MATERIALITY_DEFAULT_PCT = 1.0


# ---------------------------------------------------------------------------
# Base-year bounds (PRD §3.1)
# "between 1990 and 2100 inclusive"
# ---------------------------------------------------------------------------
BASE_YEAR_MIN = 1990
BASE_YEAR_MAX = 2100


# ---------------------------------------------------------------------------
# Scope-3 category bounds (PRD §3.3)
# "the GHG-Protocol Scope-3 category number from 1 through 15 inclusive"
# ---------------------------------------------------------------------------
SCOPE3_CATEGORY_MIN = 1
SCOPE3_CATEGORY_MAX = 15


# ---------------------------------------------------------------------------
# Vintage year lower bound (PRD §3.6)
# "vintage_year between 1990 and the year of the parent reporting period's
#  end_date inclusive"
# ---------------------------------------------------------------------------
VINTAGE_YEAR_MIN = 1990


# ---------------------------------------------------------------------------
# Precision tolerances — used by pytest.approx and assertion helpers.
# PRD §2.6: per-record kg_co2e and report totals rounded HALF_UP to 4dp.
# ---------------------------------------------------------------------------
EMISSIONS_PRECISION_DP = 4
EMISSIONS_TOLERANCE = 1e-4

COMPLETENESS_PRECISION_DP = 2
COMPLETENESS_TOLERANCE = 1e-2


# ---------------------------------------------------------------------------
# Common test defaults — factories pull from here.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    "ORG_NAME": "Test Energy Corp",
    "FUNCTIONAL_CURRENCY": "USD",
    "BASE_YEAR": 2025,
    "MATERIALITY_PCT": 1.00,

    "FACILITY_NAME": "Test Facility A",
    "COUNTRY_CODE": "US",

    "REVENUE": 1_000_000.00,
    "HEADCOUNT": 100,
    "UNIT_OUTPUT": 1000.0000,

    "PERIOD_LABEL": "FY2025",
    "PERIOD_START": "2025-01-01T00:00:00.000Z",
    "PERIOD_END": "2026-01-01T00:00:00.000Z",

    "FACTOR_CODE": "GRID-US",
    "FACTOR_KG_PER_UNIT": 0.500000,
    "TRACEABILITY_URL": "https://factors.example.com/grid-us-2025.pdf",

    "SOURCE_CODE": "S-DIESEL-GEN-A",

    "PROJECT_NAME": "Test Reduction Project",

    "REGISTRY": "VCS",
    "RETIREMENT_CERT_URL": "https://retirements.example.com/cert-001.pdf",

    "RATIONALE": "Initial facility add for testing.",

    "DEFAULT_QUANTITY": 1000.0000,
}


__all__ = [
    "GWP_TABLE",
    "DATA_QUALITY_SCORES",
    "MATERIALITY_MIN_PCT",
    "MATERIALITY_MAX_PCT",
    "MATERIALITY_DEFAULT_PCT",
    "BASE_YEAR_MIN",
    "BASE_YEAR_MAX",
    "SCOPE3_CATEGORY_MIN",
    "SCOPE3_CATEGORY_MAX",
    "VINTAGE_YEAR_MIN",
    "EMISSIONS_PRECISION_DP",
    "EMISSIONS_TOLERANCE",
    "COMPLETENESS_PRECISION_DP",
    "COMPLETENESS_TOLERANCE",
    "TEST_DEFAULTS",
]
