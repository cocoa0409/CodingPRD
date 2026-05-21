"""Domain thresholds — numeric constants from PRD calculations and rules.

Each constant traces to a verbatim PRD sentence.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "limit defaults to 10 when omitted; its minimum is 1 and its
# maximum is 100. offset defaults to 0 when omitted; its minimum is 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Registration-fee — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "if curb_weight_lbs is strictly less than 3000 pounds, the
# weight base is 65.00; if it is at least 3000 pounds and strictly less
# than 6000 pounds, the weight base is 110.00; if it is at least 6000
# pounds, the weight base is 185.00 — note that the heavy tier uses the
# inclusive boundary 6000, not strictly greater than 6000."
WEIGHT_BASE_LIGHT: float = 65.00
WEIGHT_BASE_MID: float = 110.00
WEIGHT_BASE_HEAVY: float = 185.00
WEIGHT_TIER_MID_MIN_LBS: int = 3000
WEIGHT_TIER_HEAVY_MIN_LBS: int = 6000

# PRD §3.7: "age factor is the larger of 0.50 and the value 1.00 minus
# 0.05 multiplied by the age in years"
AGE_FACTOR_STEP: float = 0.05
AGE_FACTOR_FLOOR: float = 0.50

# PRD §3.7: "The surcharge is 22.00 if Owner.is_resident is true,
# otherwise it is 55.00."
COUNTY_SURCHARGE: float = 22.00
NON_RESIDENT_SURCHARGE: float = 55.00


# ---------------------------------------------------------------------------
# Sales tax — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "the resident rate of 0.0725"
RATE_RESIDENT: float = 0.0725
# PRD §3.7: "the non-resident rate of 0.085"
RATE_NON_RESIDENT: float = 0.085


# ---------------------------------------------------------------------------
# Processing-fee tiers — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "when fee_subtotal is at most 200.00, the processing fee is a
# flat 8.00; when fee_subtotal is strictly greater than 200.00 and at most
# 1000.00, it is a flat 18.00; when fee_subtotal is strictly greater than
# 1000.00 and at most 5000.00, it is a flat 38.00; when fee_subtotal is
# strictly greater than 5000.00, the processing fee is two percent (0.02)
# of fee_subtotal."
TIER_1_MAX: float = 200.00
TIER_2_MAX: float = 1000.00
TIER_3_MAX: float = 5000.00
TIER_1_FEE: float = 8.00
TIER_2_FEE: float = 18.00
TIER_3_FEE: float = 38.00
TIER_4_RATE: float = 0.02


# ---------------------------------------------------------------------------
# REAL ID scoring — PRD §3.10
# ---------------------------------------------------------------------------
# PRD §3.10: "40 points for documents_proof_of_identity being true, 30
# points for documents_proof_of_residency being true, and 25 points for
# documents_proof_of_ssn being true"
ID_WEIGHT: int = 40
RES_WEIGHT: int = 30
SSN_WEIGHT: int = 25
# PRD §3.10: "an age bonus of 5 points is added if and only if the age
# is at least 18 and at most 80"
AGE_BONUS: int = 5
AGE_BONUS_MIN: int = 18
AGE_BONUS_MAX: int = 80
# PRD §3.10: "A revision penalty of 5 points is subtracted for every
# prior revision cycle"
REVISION_PENALTY_PER_CYCLE: int = 5
# PRD §3.10: "The approval threshold is at least 80.00."
APPROVAL_THRESHOLD: float = 80.00
# PRD §3.10: "Resubmission is permitted only while revision_count is
# strictly less than 3"
REVISION_LIMIT: int = 3
# PRD §3.10: "Owner.real_id_expires_at is set to the current time plus
# eight years"
REAL_ID_EXPIRY_YEARS: int = 8


# ---------------------------------------------------------------------------
# Emissions — PRD §3.5, §3.7
# ---------------------------------------------------------------------------
# PRD §3.5: "Recording PASSED stamps result_recorded_at, sets
# Vehicle.emissions_expires_at to the recorded time plus 730 days"
EMISSIONS_EXPIRY_DAYS: int = 730
# PRD §3.5: "the current time is at or after the inspection's
# scheduled_start minus 15 minutes (a 15-minute early-arrival grace
# window)"
EMISSIONS_EARLY_GRACE_MINUTES: int = 15
# PRD §3.5: "the new inspection's slot at the given station_id must not
# overlap any other non-cancelled inspection's half-open interval
# [start, end + 15 minutes)"
EMISSIONS_SLOT_BUFFER_MINUTES: int = 15


# ---------------------------------------------------------------------------
# Unpaid timeout — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "whose updated_at plus seven days is at or before the new
# clock instant, the system reverts the application from TAX_ASSESSED
# back to EMISSIONS_PASSED"
UNPAID_TIMEOUT_DAYS: int = 7


# ---------------------------------------------------------------------------
# REAL ID enforcement cutoff — PRD §3.8
# ---------------------------------------------------------------------------
# PRD §3.8: "the current time is strictly earlier than
# 2027-05-07T00:00:00Z (the federal REAL ID enforcement instant)"
REAL_ID_ENFORCEMENT_INSTANT_ISO: str = "2027-05-07T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Linked TransferApplication recency — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5 (PASSED follow-on): "and which was last updated within the
# last 30 days"
LINKED_APPLICATION_RECENCY_DAYS: int = 30


# ---------------------------------------------------------------------------
# Jurisdiction — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "the boolean is true if and only if the codes match" against
# "the jurisdiction code CA".
JURISDICTION_CODE: str = "CA"


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "vin_prefix": "1HGBH41JXMN",
    "make": "Acme",
    "model": "Sedan",
    "curb_weight_lbs": 2500,
    "model_year": 2026,
    "fuel_type": "GASOLINE",
    "owner_full_name": "Test Owner",
    "residency_state_resident": "CA",
    "residency_state_non_resident": "NV",
    "date_of_birth_adult": "1995-01-01",
    "declared_sale_price": 20000.00,
    "trade_in_value": 5000.00,
    "lienholder_name": "First National Bank",
    "principal_amount": 12000.00,
    "station_id": "STATION-A",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "WEIGHT_BASE_LIGHT",
    "WEIGHT_BASE_MID",
    "WEIGHT_BASE_HEAVY",
    "WEIGHT_TIER_MID_MIN_LBS",
    "WEIGHT_TIER_HEAVY_MIN_LBS",
    "AGE_FACTOR_STEP",
    "AGE_FACTOR_FLOOR",
    "COUNTY_SURCHARGE",
    "NON_RESIDENT_SURCHARGE",
    "RATE_RESIDENT",
    "RATE_NON_RESIDENT",
    "TIER_1_MAX",
    "TIER_2_MAX",
    "TIER_3_MAX",
    "TIER_1_FEE",
    "TIER_2_FEE",
    "TIER_3_FEE",
    "TIER_4_RATE",
    "ID_WEIGHT",
    "RES_WEIGHT",
    "SSN_WEIGHT",
    "AGE_BONUS",
    "AGE_BONUS_MIN",
    "AGE_BONUS_MAX",
    "REVISION_PENALTY_PER_CYCLE",
    "APPROVAL_THRESHOLD",
    "REVISION_LIMIT",
    "REAL_ID_EXPIRY_YEARS",
    "EMISSIONS_EXPIRY_DAYS",
    "EMISSIONS_EARLY_GRACE_MINUTES",
    "EMISSIONS_SLOT_BUFFER_MINUTES",
    "UNPAID_TIMEOUT_DAYS",
    "REAL_ID_ENFORCEMENT_INSTANT_ISO",
    "LINKED_APPLICATION_RECENCY_DAYS",
    "JURISDICTION_CODE",
    "TEST_DEFAULTS",
]
