"""Domain thresholds — numeric constants from PRD §3 and §2.

Names mirror PRD-prose terms. Tests should reference these by name rather
than re-typing numeric literals so that boundary tests stay in lockstep
with PRD prose.

Generic `NON_EXISTENT_UUID` is re-exported from the framework.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Triage scoring (PRD §3.2)
# ---------------------------------------------------------------------------
CHIEF_COMPLAINT_FACTOR = 10
VITAL_ANOMALY_FACTOR = 2
RISK_FACTOR = 3

# PRD §3.2: 'where DIABETES contributes 1, HYPERTENSION contributes 1,
# and IMMUNOCOMPROMISED contributes 2'
RISK_TABLE = {
    "DIABETES": 1,
    "HYPERTENSION": 1,
    "IMMUNOCOMPROMISED": 2,
}

# PRD §3.2 severity band thresholds (half-open ranges).
BAND_LOW_MAX_EXCLUSIVE = 30   # severity_score < 30 -> LOW
BAND_MID_MAX_EXCLUSIVE = 60   # 30 <= score < 60 -> MID
BAND_HIGH_MAX_EXCLUSIVE = 90  # 60 <= score < 90 -> HIGH
# severity_score >= 90 -> EMERGENCY

# ---------------------------------------------------------------------------
# Consultation fee (PRD §3.5)
# ---------------------------------------------------------------------------
TIER1_CAP_MIN = 10
TIER1_RATE_CENTS = 100
TIER2_RATE_CENTS = 200

# ---------------------------------------------------------------------------
# Insurance reimbursement (PRD §3.7)
# ---------------------------------------------------------------------------
DEDUCTIBLE_CENTS = 5000
TIER1_CAP_CENTS = 10000

# In-scope tier rates (PRD §3.7).
IN_SCOPE_TIER1_RATE = 0.70
IN_SCOPE_TIER2_RATE = 0.50

# Out-of-scope penalty rates (PRD §3.7).
OUT_OF_SCOPE_TIER1_RATE = 0.30
OUT_OF_SCOPE_TIER2_RATE = 0.20

ANNUAL_CAP_CENTS = 1_000_000

# Disease enumerations referenced by PRD §3.7 and §3.6. The PRD names these
# sets without listing every code; tests use concrete representative codes
# from the test-recipes in the difficulty-design index.
INSURANCE_IN_SCOPE_DISEASES = {"HYPERTENSION", "DIABETES", "ASTHMA"}
PRESCRIPTION_ALLOWED_DISEASES = {"HYPERTENSION", "DIABETES", "ASTHMA"}

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Reminder channels (PRD §3.8)
# ---------------------------------------------------------------------------
VALID_REMINDER_CHANNELS = {"SMS", "EMAIL", "APP_PUSH"}

# ---------------------------------------------------------------------------
# Common test inputs
# ---------------------------------------------------------------------------
DEFAULT_REGION_CODE = "REGION_A"
ALT_REGION_CODE = "REGION_B"
DEFAULT_HOSPITAL_ID = "hospital_central"
ALT_HOSPITAL_ID = "hospital_north"

DEFAULT_DEPARTMENT_CODE = "CARDIO"
ALT_DEPARTMENT_CODE = "DERM"

# Representative in-scope and out-of-scope disease codes.
IN_SCOPE_DISEASE = "HYPERTENSION"
OUT_OF_SCOPE_DISEASE = "DERMA_OUT_OF_SCOPE"

# Pharmacy / e-commerce target ids; tests assume implementations seed a
# minimal directory or accept any non-empty string and verify on dispatch.
DEFAULT_PHARMACY_ID = "pharmacy_1"
DEFAULT_ECOMMERCE_ID = "ecommerce_1"

# Default base_fee in yuan (PRD §3.5 talks about decimal yuan).
DEFAULT_DOCTOR_BASE_FEE = 30.00

__all__ = [
    "CHIEF_COMPLAINT_FACTOR",
    "VITAL_ANOMALY_FACTOR",
    "RISK_FACTOR",
    "RISK_TABLE",
    "BAND_LOW_MAX_EXCLUSIVE",
    "BAND_MID_MAX_EXCLUSIVE",
    "BAND_HIGH_MAX_EXCLUSIVE",
    "TIER1_CAP_MIN",
    "TIER1_RATE_CENTS",
    "TIER2_RATE_CENTS",
    "DEDUCTIBLE_CENTS",
    "TIER1_CAP_CENTS",
    "IN_SCOPE_TIER1_RATE",
    "IN_SCOPE_TIER2_RATE",
    "OUT_OF_SCOPE_TIER1_RATE",
    "OUT_OF_SCOPE_TIER2_RATE",
    "ANNUAL_CAP_CENTS",
    "INSURANCE_IN_SCOPE_DISEASES",
    "PRESCRIPTION_ALLOWED_DISEASES",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "VALID_REMINDER_CHANNELS",
    "DEFAULT_REGION_CODE",
    "ALT_REGION_CODE",
    "DEFAULT_HOSPITAL_ID",
    "ALT_HOSPITAL_ID",
    "DEFAULT_DEPARTMENT_CODE",
    "ALT_DEPARTMENT_CODE",
    "IN_SCOPE_DISEASE",
    "OUT_OF_SCOPE_DISEASE",
    "DEFAULT_PHARMACY_ID",
    "DEFAULT_ECOMMERCE_ID",
    "DEFAULT_DOCTOR_BASE_FEE",
]
