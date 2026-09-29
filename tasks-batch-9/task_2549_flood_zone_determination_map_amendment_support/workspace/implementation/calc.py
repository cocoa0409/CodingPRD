"""Pinned calculations (scaffold section 1.3 / PRD sections 2.7, 2.9, 3.x).

Every rounding step here is round-half-up.  Money is integer cents; feet are
Decimals carried at the scale the PRD pins for each figure.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import add_years, all_rows, db

# --- pinned constants ------------------------------------------------------
GEOCODE_BUFFER_FT = {
    "ROOFTOP": Decimal("0"),
    "PARCEL_CENTROID": Decimal("25"),
    "ZIP_CENTROID": Decimal("250"),
    "FAILED": Decimal("0"),
}
GEOCODE_CONFIDENCE_FLOOR = Decimal("0.60")

REGULAR_CAP_CENTS = {
    "SINGLE_FAMILY": 25000000,
    "TWO_TO_FOUR_FAMILY": 25000000,
    "OTHER_RESIDENTIAL": 50000000,
    "NON_RESIDENTIAL": 50000000,
}
EMERGENCY_CAP_CENTS = {
    "SINGLE_FAMILY": 3500000,
    "TWO_TO_FOUR_FAMILY": 3500000,
    "OTHER_RESIDENTIAL": 10000000,
    "NON_RESIDENTIAL": 10000000,
}

DATUM_OFFSET_FT = {
    "CA": Decimal("-2.44"),
    "FL": Decimal("-1.15"),
    "TX": Decimal("-0.87"),
    "NC": Decimal("-0.55"),
}

BASE_FEE_CENTS = {"LOMA": 0, "LOMR_F": 50000}
RESUBMISSION_FEE_CENTS = 12500
EXPEDITE_SURCHARGE_PCT = {
    "TIER_1": Decimal("0.00"),
    "TIER_2": Decimal("0.30"),
    "TIER_3": Decimal("0.45"),
}
MAX_RESUBMISSIONS = 2

NOTICE_RESPONSE_DAYS = {
    "MANDATORY_PURCHASE": 45,
    "FORCE_PLACEMENT_WARNING": 30,
    "RE_DETERMINATION": 30,
    "COVERAGE_UNAVAILABLE": 15,
}
NOTICE_COOLDOWN_DAYS = 5

APPEAL_PERIOD_DAYS = 90
LFD_WAITING_PERIOD_DAYS = 180
CERTIFICATE_VALIDITY_DAYS = 365
DISPUTE_DECISION_DAYS = 30
MAX_DISPUTE_ROUNDS = 2
DAYS_PER_YEAR = 365
MONTHS_PER_YEAR = 12

ONE_DP = Decimal("0.1")
TWO_DP = Decimal("0.01")


# --- rounding helpers ------------------------------------------------------
def round_half_up(value, places):
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount to a whole number of cents, half-up."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def dec(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


# --- community -------------------------------------------------------------
def coverage_availability(community):
    if community["cbrs_flag"]:
        return "UNAVAILABLE"
    status = community["participation_status"]
    if status in ("SUSPENDED", "NON_PARTICIPATING", "WITHDRAWN"):
        return "UNAVAILABLE"
    if status == "EMERGENCY":
        return "EMERGENCY_LIMITS_ONLY"
    if status == "PROBATION":
        return "FULL_WITH_SURCHARGE"
    return "FULL"


# --- property geocode ------------------------------------------------------
def geocode_status(method, score):
    if method != "FAILED" and dec(score) >= GEOCODE_CONFIDENCE_FLOOR:
        return "GEOCODED"
    return "UNRESOLVED"


def geocode_buffer_ft(method):
    return GEOCODE_BUFFER_FT[method]


# --- panel selection -------------------------------------------------------
def effective_panel(prop):
    """The single panel governing a property, or None."""
    now = db.now()
    candidates = [
        p
        for p in all_rows("map_panels")
        if p["community_id"] == prop["community_id"]
        and p["map_panel_number"] == prop["map_panel_number"]
        and p["revision_status"] == "EFFECTIVE"
        and p["effective_date"] <= now
    ]
    # all_rows already yields created_at ascending, so scanning with a strict
    # comparison ranks by effective_date DESC and tie-breaks created_at ASC.
    best = None
    for panel in candidates:
        if best is None or panel["effective_date"] > best["effective_date"]:
            best = panel
    return best


# --- structure classification ---------------------------------------------
def classify(structure, prop, panel, variant, prior=None):
    """Resolve position_class, zone_code, sfha_flag, BFE snapshot and freeboard."""
    buffer_ft = geocode_buffer_ft(prop["geocode_method"]) + dec(
        panel["horizontal_uncertainty_ft"]
    )
    effective_offset_ft = dec(structure["sfha_offset_ft"]) - dec(
        panel["sfha_boundary_shift_ft"]
    )

    if effective_offset_ft + buffer_ft < 0:
        position_class = "INSIDE"
    elif effective_offset_ft - buffer_ft > 0:
        position_class = "OUTSIDE"
    else:
        position_class = "INDETERMINATE"

    if position_class == "INSIDE":
        zone_code = panel["zone_code"]
        sfha_flag = True
    elif position_class == "OUTSIDE":
        zone_code = "X"
        sfha_flag = False
    elif variant == "life_of_loan_lenient" and prior is not None:
        # an ambiguous re-read never flips the borrower's obligation
        zone_code = prior["zone_code"]
        sfha_flag = prior["sfha_flag"]
    else:
        # origination_strict, and the lenient fallback when there is no prior
        zone_code = panel["zone_code"]
        sfha_flag = True

    base_flood_elevation_ft = panel["base_flood_elevation_ft"] if sfha_flag else None
    freeboard_ft = None
    lowest = structure.get("lowest_floor_elevation_ft")
    if lowest is not None and base_flood_elevation_ft is not None:
        freeboard_ft = round_half_up(dec(lowest) - dec(base_flood_elevation_ft), 1)

    return {
        "position_class": position_class,
        "zone_code": zone_code,
        "sfha_flag": sfha_flag,
        "base_flood_elevation_ft": base_flood_elevation_ft,
        "freeboard_ft": freeboard_ft,
    }


def mandatory_purchase_flag(sfha_flag, community):
    return bool(sfha_flag) and community["coverage_availability"] != "UNAVAILABLE"


# --- coverage --------------------------------------------------------------
def required_coverage_cents(determination, structure, folio, community):
    """Scaffold required_coverage_amount.

    The mandatory-purchase condition is re-derived here from the determination's
    sfha_flag and the community's *current* coverage_availability, which is why a
    participation change alone can move the required amount.
    """
    if determination is None or structure is None:
        return 0
    if not mandatory_purchase_flag(determination.get("sfha_flag"), community):
        return 0
    if community["coverage_availability"] == "EMERGENCY_LIMITS_ONLY":
        cap = EMERGENCY_CAP_CENTS[structure["occupancy_type"]]
    else:
        cap = REGULAR_CAP_CENTS[structure["occupancy_type"]]
    return min(folio["principal_balance_cents"], structure["replacement_cost_cents"], cap)


def uninsured_exposure_cents(folio, required):
    if folio["insurance_status"] == "FORCE_PLACED":
        return 0
    return max(0, required - folio["reported_coverage_cents"])


# --- compliance posture ----------------------------------------------------
def compliance_posture(folio, community, notices):
    now = db.now()
    if community["coverage_availability"] == "UNAVAILABLE":
        return "COVERAGE_UNAVAILABLE"
    if folio["insurance_status"] == "FORCE_PLACED":
        return "FORCE_PLACED"
    if folio["pending_redetermination_count"] > 0:
        return "REVIEW_PENDING"
    if (
        folio["required_coverage_cents"] == 0
        or folio["reported_coverage_cents"] >= folio["required_coverage_cents"]
    ):
        return "COMPLIANT"
    mandatory = [n for n in notices if n["notice_type"] == "MANDATORY_PURCHASE"]
    for notice in mandatory:
        if notice["status"] in ("SENT", "EXPIRED") and notice["response_deadline_at"] < now:
            return "FORCE_PLACE_ELIGIBLE"
    for notice in mandatory:
        if notice["status"] == "SENT" and notice["response_deadline_at"] >= now:
            return "NOTICE_PENDING"
    return "NOTICE_DUE"


# --- elevation certificate conversion -------------------------------------
def cert_conversion(raw_floor, raw_lag, datum, state_code, panel_bfe):
    offset = DATUM_OFFSET_FT[state_code] if datum == "NGVD29" else Decimal("0.00")
    converted_floor = round_half_up(dec(raw_floor) + offset, 1)
    converted_lag = round_half_up(dec(raw_lag) + offset, 1)
    if panel_bfe is None:
        freeboard = None
        lag_freeboard = None
    else:
        bfe = dec(panel_bfe)
        freeboard = round_half_up(converted_floor - bfe, 1)
        lag_freeboard = round_half_up(converted_lag - bfe, 1)
    return converted_floor, converted_lag, freeboard, lag_freeboard


# --- amendment fee ---------------------------------------------------------
def amendment_fee(request_type, resubmission_count, expedite_flag):
    base = BASE_FEE_CENTS[request_type] + RESUBMISSION_FEE_CENTS * resubmission_count
    if base <= 0:
        tier = "TIER_1"
    elif base <= 50000:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    surcharge = cents(EXPEDITE_SURCHARGE_PCT[tier] * base) if expedite_flag else 0
    return base, tier, surcharge, base + surcharge


# --- premium arithmetic ----------------------------------------------------
def rolled_anniversary(anniversary, anchor):
    anniv = anniversary
    while anniv <= anchor:
        anniv = add_years(anniv, 1)
    return anniv


def forward_looking_estimate_cents(annual_rate_cents, anniversary, anchor):
    anniv = rolled_anniversary(anniversary, anchor)
    whole_months = (
        (anniv.year - anchor.year) * MONTHS_PER_YEAR
        + (anniv.month - anchor.month)
        - (1 if anniv.day < anchor.day else 0)
    )
    whole_months = max(0, whole_months)
    return cents(Decimal(annual_rate_cents) * whole_months / Decimal(MONTHS_PER_YEAR))


def chronological_actual(annual_rate_cents, anniversary, anchor):
    anniv = rolled_anniversary(anniversary, anchor)
    days = (anniv - anchor).days
    premium = cents(Decimal(annual_rate_cents) * days / Decimal(DAYS_PER_YEAR))
    return premium, days


def earned_premium_cents(premium_cents, days_in_force, coverage_days):
    if coverage_days <= 0:
        return premium_cents
    if days_in_force >= coverage_days:
        return premium_cents
    return cents(Decimal(premium_cents) * days_in_force / Decimal(coverage_days))
