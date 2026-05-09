"""Domain thresholds and computed lookups derived from PRD §2 and §3.

These constants exist only to keep tests pinned to PRD-stated numbers
(no magic literals). Each entry's docstring cites the PRD passage from
which the value is taken.
"""

# ──────────────────────────────────────────────────────────
# Provisional / final valuation constants — PRD §3.1
# ──────────────────────────────────────────────────────────

VALUATION = {
    # PRD §3.1: "treat the platform-supplied base price as a constant of one
    # million cents per vehicle for the purposes of this calculation"
    "BASE_PRICE_CENTS": 1_000_000,
    # PRD §3.1: "the reference mileage of two hundred thousand kilometres"
    "REFERENCE_MILEAGE_KM": 200_000,
    # PRD §3.1: "that ratio further multiplied by the mileage decay constant
    # of one half"
    "MILEAGE_DECAY": 0.5,
    # PRD §3.1: "per-accident penalty of eight hundred basis points"
    "ACCIDENT_PENALTY_BP": 800,
    # PRD §3.1: "extra major-accident penalty of one thousand two hundred
    # basis points"
    "MAJOR_ACCIDENT_EXTRA_BP": 1_200,
    # PRD §3.1: "per-maintenance penalty of fifty basis points"
    "MAINT_PENALTY_BP": 50,
    # PRD §3.1: "discrepancy penalty of fifteen percent"
    "DISCREPANCY_PENALTY": 0.15,
    # PRD §3.1: "discrepancy tolerance of five percent"
    "MILEAGE_DISCREPANCY_TOLERANCE": 0.05,
}


# Letter grade → numeric weight per PRD §3.1.
GRADE_VALUES = {"A": 1.0, "B": 0.9, "C": 0.8, "D": 0.6}


# Assessment-score weights per PRD §3.1.
ASSESSMENT_SCORE_WEIGHTS = {"GRADE": 0.5, "MILEAGE": 0.2, "HISTORY": 0.3}


# ──────────────────────────────────────────────────────────
# Listing / Bid / Reservation constants — PRD §3.2, §3.3, §3.4
# ──────────────────────────────────────────────────────────

LISTING = {
    # PRD §3.2: "the photo_urls array must contain at least 6 entries"
    "MIN_PHOTOS": 6,
}


BID_INCREMENT = {
    # PRD §3.3: "below the first-tier ceiling of fifty thousand currency
    # units (five million cents)"
    "TIER_1_CEILING": 5_000_000,
    # PRD §3.3: "below the second-tier ceiling of two hundred thousand
    # currency units (twenty million cents)"
    "TIER_2_CEILING": 20_000_000,
    # PRD §3.3: "the required increment is five hundred currency units
    # (fifty thousand cents)"
    "INCR_LOW": 50_000,
    # PRD §3.3: "the required increment is two thousand currency units
    # (two hundred thousand cents)"
    "INCR_MID": 200_000,
    # PRD §3.3: "the required increment is five thousand currency units
    # (five hundred thousand cents)"
    "INCR_HIGH": 500_000,
}


DEPOSIT = {
    # PRD §3.7: "must not exceed fifty million cents"
    "BUYER_DEPOSIT_LIMIT_CENTS": 50_000_000,
}


# ──────────────────────────────────────────────────────────
# Loan constants — PRD §3.6
# ──────────────────────────────────────────────────────────

LENDER_MIN_CREDIT = {
    # PRD §3.6: "LENDER_A requires at least 680, LENDER_B at least 640,
    # LENDER_C at least 600"
    "LENDER_A": 680,
    "LENDER_B": 640,
    "LENDER_C": 600,
}


LENDER_MIN_DOWN_BP = {
    # PRD §3.6: "LENDER_A requires at least 1500 basis points, LENDER_B at
    # least 2000 basis points, LENDER_C at least 2500 basis points"
    "LENDER_A": 1_500,
    "LENDER_B": 2_000,
    "LENDER_C": 2_500,
}


# Allowed term values per PRD §3.6.
ALLOWED_LOAN_TERMS = {12, 24, 36, 48, 60, 72}


# ──────────────────────────────────────────────────────────
# Warranty constants — PRD §3.8
# ──────────────────────────────────────────────────────────

WARRANTY_DURATION_MONTHS = {
    # PRD §3.8: "BASIC adds six months, STANDARD adds twelve months,
    # PREMIUM adds twenty-four months"
    "BASIC": 6,
    "STANDARD": 12,
    "PREMIUM": 24,
}


WARRANTY_COVERAGE_SCOPE = {
    # PRD §3.8: "BASIC covers [POWERTRAIN]"
    "BASIC": ["POWERTRAIN"],
    # PRD §3.8: "STANDARD covers [POWERTRAIN, ELECTRICAL, COOLING]"
    "STANDARD": ["POWERTRAIN", "ELECTRICAL", "COOLING"],
    # PRD §3.8: "PREMIUM covers [POWERTRAIN, ELECTRICAL, COOLING,
    # INFOTAINMENT, SUSPENSION, INTERIOR]"
    "PREMIUM": [
        "POWERTRAIN",
        "ELECTRICAL",
        "COOLING",
        "INFOTAINMENT",
        "SUSPENSION",
        "INTERIOR",
    ],
}


WARRANTY_PER_CLAIM_CAP_CENTS = {
    # PRD §3.8: "the per-claim cap of two hundred thousand cents for BASIC,
    # five hundred thousand cents for STANDARD, or one million five hundred
    # thousand cents for PREMIUM"
    "BASIC": 200_000,
    "STANDARD": 500_000,
    "PREMIUM": 1_500_000,
}


WARRANTY_TOTAL_CAP_CENTS = {
    # PRD §3.8: "the total cap is five hundred thousand cents for BASIC,
    # two million cents for STANDARD, and six million cents for PREMIUM"
    "BASIC": 500_000,
    "STANDARD": 2_000_000,
    "PREMIUM": 6_000_000,
}


# ──────────────────────────────────────────────────────────
# Dispute constants — PRD §3.9
# ──────────────────────────────────────────────────────────

DISPUTE = {
    # PRD §3.9: "round_count may not exceed the maximum mediation rounds
    # of three"
    "MAX_MEDIATION_ROUNDS": 3,
    # PRD §3.9: "ten percent if no third_party_report_url was filed"
    "PARTIAL_BASE_PCT_NO_3P": 0.10,
    # PRD §3.9: "thirty percent if one was"
    "PARTIAL_BASE_PCT_WITH_3P": 0.30,
    # PRD §3.9: "an additional ten percentage points are added to the base
    # if the latest AssessmentReport for the vehicle had its
    # mileage_discrepancy_flag set to true"
    "DISCREPANCY_BUMP": 0.10,
    # PRD §3.9: "the buyer pays the seller five percent of the order's
    # agreed_price_cents rounded half-up"
    "SELLER_COMPENSATION_PCT": 0.05,
}


# ──────────────────────────────────────────────────────────
# Transfer constants — PRD §3.7
# ──────────────────────────────────────────────────────────

TRANSFER = {
    # PRD §3.7: "the gap from now to appointment_at must be at most sixty days"
    "APPOINTMENT_MAX_DAYS": 60,
}


# Required document types per PRD §3.7.
TRANSFER_DOC_TYPES = [
    "ID_BUYER",
    "ID_SELLER",
    "TITLE",
    "REGISTRATION",
    "RELEASE_OF_LIEN",
    "EMISSIONS_CERT",
]


# ──────────────────────────────────────────────────────────
# Pagination — PRD §2.3
# ──────────────────────────────────────────────────────────

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}
