"""Domain thresholds and canonical test values from the PRD calculations."""

# ---------------------------------------------------------------------------
# Named constants used by the PRD calculations
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # Reclamation yield
    "LB_TO_KG": 0.45359237,
    "DEPOLYMERIZATION_YIELD": 0.82,
    "MAX_RECLAIM_CONTAMINATION_PCT": 12.0,
    # Extrusion / denier
    "DENIER_TOLERANCE_FRACTION": 0.03,
    "MIN_MELT_FLOW_INDEX": 12.0,
    "SPIN_YIELD": 0.965,
    # Face weight
    "SQ_IN_PER_SQ_YD": 1296,
    "MM_PER_INCH": 25.4,
    "CUT_PILE_ALLOWANCE_IN": 0.0600,
    "LOOP_PILE_ALLOWANCE_IN": 0.1200,
    "GRAMS_PER_YARD_PER_DENIER": 0.00010160,
    "GRAMS_PER_OZ": 28.349523,
    "FACE_WEIGHT_TOLERANCE_OZ": 1.60,
    "PILE_HEIGHT_SPEC_TOLERANCE_MM": 0.5,
    # Backing / delamination
    "SBR_COEFF_PER_PCT": 0.0500,
    "FILLER_PENALTY_PER_PCT": 0.0200,
    "REFERENCE_CURE_SECONDS": 120.0,
    "MIN_DELAMINATION_LBF": 2.50,
    "RECOAT_LIMIT": 1,
    # Shade banding
    "SHADE_BAND_A_MAX": 0.80,
    "SHADE_BAND_B_MAX": 1.50,
    "SHADE_BAND_C_MAX": 2.50,
    "MAX_REDYE_COUNT": 2,
    # Lab verdicts
    "WEAR_TARR_MIN": 3.0,
    "STAIN_AATCC175_MIN": 8.0,
    "FLAMMABILITY_CHAR_MAX_MM": 25.4,
    # Recycled content
    "NSF_140_MIN_RECYCLED_PCT": 25.00,
    # Backorder posture
    "STYLE_BACKORDER_ALERT_YARDS": 250,
    # Roll-good yardage
    "REMNANT_THRESHOLD_YARDS": 30.0,
    # Settlement
    "FREIGHT_ALLOWED_MIN_CENTS": 100000,
    "FREIGHT_MID_MIN_CENTS": 50000,
    "REMNANT_ORDER_CREDIT_PCT": 0.03,
    "REMNANT_LINE_DISCOUNT_PCT": 0.15,
}

FACE_FIBER_FRACTION = {
    "NYLON_66": 0.42,
    "NYLON_6": 0.40,
    "PET": 0.38,
    "POLYPROPYLENE": 0.35,
}

GAUGE_NEEDLES_PER_INCH = {
    "G_1_8": 8.0,
    "G_1_10": 10.0,
    "G_5_64": 12.8,
}

SECONDARY_BACKING_FACTOR = {
    "ACTION_BAC": 1.00,
    "WOVEN_POLYPROPYLENE": 0.95,
    "CUSHION": 1.10,
}

SHADE_BAND_PRICE_FACTOR = {
    "A": 1.00,
    "B": 0.97,
    "C": 0.90,
    "OUT": 0.00,
    "SOLUTION": 1.00,
}


# ---------------------------------------------------------------------------
# Canonical test values
#
# The logical clock starts at CLOCK_START_UTC on a fresh server and only ever
# moves forward, so the fixtures schedule their windows after that instant and
# advance the clock into each window before the call that requires it open.
# ---------------------------------------------------------------------------

CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# Canonical instants used by the fixtures. Each is at or after CLOCK_START_UTC and
# they are listed in the order the fixtures move the clock through them.
RUN_WINDOW_OPEN_UTC = "2026-08-05T08:00:00Z"
DYE_WINDOW_OPEN_UTC = "2026-08-06T08:00:00Z"
POST_PRODUCTION_UTC = "2026-08-07T08:00:00Z"

TEST_DEFAULTS = {
    # Accounts
    "CREDIT_LIMIT_CENTS": 100_000_000,
    # Polymer
    "RECEIVED_KG": 5000.0,
    "MELT_FLOW_INDEX": 18.0,
    # Fiber batch: 7200 * 9000 / (750 * 72) == 1200.0 denier, exactly on target
    "INPUT_KG": 4000.0,
    "DENIER_TARGET": 1200.0,
    "FILAMENT_COUNT": 72,
    "THROUGHPUT_G_PER_MIN": 7200.0,
    "SPIN_SPEED_M_PER_MIN": 750.0,
    # Style: G_1_10 CUT pile 8.0 mm, 3 plies, 10.0 stitches/in and 1200 denier
    # yield a face weight of 32.04 oz/sy, inside the tolerance around 32.00.
    "PILE_HEIGHT_MM": 8.0,
    "PATTERN_REPEAT_MM": 300.0,
    "PLIES": 3,
    "TARGET_FACE_WEIGHT_OZ": 32.00,
    "STITCH_RATE_PER_INCH": 10.0,
    "LIST_PRICE_CENTS_PER_YARD": 4275,
    # Machine
    "MIN_PILE_HEIGHT_MM": 4.0,
    "MAX_PILE_HEIGHT_MM": 14.0,
    "CHANGEOVER_MINUTES": 60,
    "NEEDLE_BAR_WIDTH_IN": 144.0,
    # Vessel
    "VESSEL_CAPACITY_KG": 2000.0,
    # Run window; the clock is moved to RUN_WINDOW_OPEN_UTC before load-setup
    "RUN_START_UTC": "2026-08-05T08:00:00Z",
    "RUN_END_UTC": "2026-08-05T16:00:00Z",
    "GREIGE_YARDS": 400.0,
    # Backing: sbr_pct is capped at 70 inclusive; base 0.05*70 - 0.02*20 = 3.10
    # lbf, comfortably above the 2.50 floor with a full cure at 150 C.
    "SBR_PCT": 70.0,
    "FILLER_LOAD_PCT": 20.0,
    "CURE_TEMP_C": 150,
    "CURE_SECONDS": 120,
    # Dye lot
    "DYE_START_UTC": "2026-08-06T08:00:00Z",
    "DYE_END_UTC": "2026-08-06T14:00:00Z",
    "LOT_KG": 400.0,
    "DYED_YARDS": 400.0,
    "TARGET_LAB_L": 55.00,
    "TARGET_LAB_A": 12.00,
    "TARGET_LAB_B": -8.00,
    # Roll good
    "WIDTH_FT": 12.0,
    "INITIAL_YARDS": 200.0,
    # Lab results that pass their verdict rule
    "WEAR_TARR_PASS_VALUE": 4.0,
    "STAIN_AATCC175_PASS_VALUE": 9.0,
    "FLAMMABILITY_PASS_VALUE": 18.0,
    # Certificate expiry, strictly after the startup clock
    "CERT_EXPIRES_AT_UTC": "2027-08-01T00:00:00Z",
    # Orders
    "REQUESTED_YARDS": 120.0,
}
