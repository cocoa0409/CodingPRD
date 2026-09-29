"""The seven calculation rules (PRD sections 2.7, 3.2, 3.5-3.9).

Every rounding operation is round-half-up; money is whole cents; nothing here
ever touches a float.
"""

import datetime
import math
from decimal import Decimal, ROUND_HALF_UP

UTC = datetime.timezone.utc

D0 = Decimal("0")
D2 = Decimal("0.01")

# --- parcel_risk_score -------------------------------------------------------
VEG_POINTS = {
    "IRRIGATED_LANDSCAPE": Decimal("15"),
    "GRASS": Decimal("40"),
    "BRUSH": Decimal("75"),
    "MIXED_CONIFER": Decimal("90"),
}
ROOF_POINTS = {
    "CLASS_A": Decimal("10"),
    "CLASS_B": Decimal("45"),
    "CLASS_C": Decimal("80"),
    "NONE": Decimal("100"),
}
ACCESS_POINTS = {
    "NONE": Decimal("0"),
    "GATED": Decimal("25"),
    "LOCKED_GATE": Decimal("60"),
    "DOG_ON_SITE": Decimal("40"),
}
HAZARD_MULT = {
    "MODERATE": Decimal("1.00"),
    "HIGH": Decimal("1.15"),
    "VERY_HIGH": Decimal("1.30"),
}
HARDENING_CREDIT_PER_ITEM = Decimal("4.00")
HARDENING_CREDIT_CAP = Decimal("20.00")

# --- zone_deficiency_assessment ---------------------------------------------
ZONE_BASE_FT = {"ZONE_0_EMBER": Decimal("5"), "ZONE_1": Decimal("30"), "ZONE_2": Decimal("100")}
ZONE_WEIGHT = {"ZONE_0_EMBER": Decimal("1.50"), "ZONE_1": Decimal("1.00"), "ZONE_2": Decimal("0.60")}
LADDER_FUEL_PENALTY = Decimal("8.00")
SEVERITY_MINOR_MAX_RATIO = Decimal("0.2500")
SEVERITY_MAJOR_MAX_RATIO = Decimal("0.6000")
ZONES = ("ZONE_0_EMBER", "ZONE_1", "ZONE_2")
SEVERITY_ORDER = ("NONE", "MINOR", "MAJOR", "CRITICAL")

# --- notice_compliance_deadline ---------------------------------------------
MAIL_SERVICE_DAYS = 5
SEVERITY_DAYS = {"MINOR": 60, "MAJOR": 30, "CRITICAL": 14}
VERY_HIGH_COMPRESSION = Decimal("0.75")
MIN_COMPLIANCE_DAYS = 7
EXTENSION_DAYS = 30
MAX_EXTENSIONS = 1

# --- abatement_cost_recovery ------------------------------------------------
DISPOSAL_RATE_PER_TON_CENTS = Decimal("9200")
ADMIN_OVERHEAD_PCT = Decimal("0.125")
SUBSIDY_TIER_LADDER = [Decimal("0.10"), Decimal("0.20"), Decimal("0.30")]
ABATEMENT_CAP_CENTS = 750000
BUCKET_ORDER = ("ADMIN_OVERHEAD", "MOBILIZATION", "DISPOSAL", "LABOR")

# --- cost_share_award -------------------------------------------------------
PER_PARCEL_CAP_CENTS = 250000
MATCH_BY_RISK_CLASS = {
    "EXTREME": Decimal("0.75"),
    "HIGH": Decimal("0.60"),
    "MODERATE": Decimal("0.45"),
    "LOW": Decimal("0.30"),
}
COST_SHARE_INVOICE_CAP_CENTS = 1000000

# --- inspection_priority_rank -----------------------------------------------
RISK_CLASS_ORDINAL = {"EXTREME": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1}
NEVER_INSPECTED_STALENESS_DAYS = 100000

# --- program_compliance_metrics ---------------------------------------------
COMMUNITY_CERTIFY_FLOOR_PCT = Decimal("75.00")
COMMUNITY_LAPSE_FLOOR_PCT = Decimal("60.00")
COMMUNITY_MIN_MEMBER_PARCELS = 3
ELIGIBLE_STATUSES = ("COMPLIANT", "NON_COMPLIANT", "ABATEMENT_PENDING")

MAX_ACCESS_DENIALS = 2
CERTIFICATE_VALID_DAYS = 90


def rhu(value, places=0):
    """Round half up to ``places`` decimals."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def end_of_day(moment, plus_days=0):
    """The calendar date reached by adding ``plus_days``, at 23:59:59 UTC."""
    target = (moment + datetime.timedelta(days=plus_days)).date()
    return datetime.datetime(
        target.year, target.month, target.day, 23, 59, 59, 0, tzinfo=UTC
    )


# ---------------------------------------------------------------------------
# parcel_risk_score
# ---------------------------------------------------------------------------
def risk_score(parcel, veg_points=None, hardening_credit=Decimal("0.00")):
    """Weighted subscores; the hardening credit is subtracted BEFORE the
    hazard multiplier is applied, and the clamp precedes the rounding."""
    slope_points = min(Decimal("100"), Decimal(parcel["slope_pct"]) * 2)
    if veg_points is None:
        veg_points = VEG_POINTS[parcel["vegetation_type"]]
    structure_points = ROOF_POINTS[parcel["roof_class"]]
    access_points = ACCESS_POINTS[parcel["access_constraint"]]
    subtotal = (
        Decimal("0.30") * slope_points
        + Decimal("0.30") * Decimal(veg_points)
        + Decimal("0.25") * structure_points
        + Decimal("0.15") * access_points
    )
    product = (subtotal - Decimal(hardening_credit)) * HAZARD_MULT[parcel["hazard_zone"]]
    return rhu(min(Decimal("100.00"), product), 2)


def risk_class(score):
    if score >= Decimal("75.00"):
        return "EXTREME"
    if score >= Decimal("55.00"):
        return "HIGH"
    if score >= Decimal("35.00"):
        return "MODERATE"
    return "LOW"


# ---------------------------------------------------------------------------
# zone_deficiency_assessment
# ---------------------------------------------------------------------------
def slope_factor(slope_pct):
    slope = Decimal(slope_pct)
    if slope < 20:
        return Decimal("1.00")
    if slope < 40:
        return Decimal("1.25")
    return Decimal("1.50")


def grade_zone(parcel, zone, measured_clearance_ft, ladder_fuel_present):
    required = rhu(ZONE_BASE_FT[zone] * slope_factor(parcel["slope_pct"]), 1)
    deficit = rhu(max(D0, required - Decimal(measured_clearance_ft)), 1)
    ratio = rhu(deficit / required, 4)
    if ratio == Decimal("0.0000"):
        severity = "NONE"
    elif ratio <= SEVERITY_MINOR_MAX_RATIO:
        severity = "MINOR"
    elif ratio <= SEVERITY_MAJOR_MAX_RATIO:
        severity = "MAJOR"
    else:
        severity = "CRITICAL"
    zone_points = min(Decimal("100.00"), rhu(ratio * 100 * ZONE_WEIGHT[zone], 2))
    penalty = LADDER_FUEL_PENALTY if ladder_fuel_present else Decimal("0.00")
    points = min(Decimal("100.00"), rhu(zone_points + penalty, 2))
    return {
        "required_clearance_ft": required,
        "deficit_ft": deficit,
        "deficit_ratio": ratio,
        "deficiency_severity": severity,
        "points": points,
    }


def rollup(zone_evaluations, hardening_findings):
    """Round per zone, then sum (summing the raw products is incorrect)."""
    total = sum((Decimal(z["points"]) for z in zone_evaluations), D0)
    measured_veg_points = min(Decimal("100.00"), rhu(total, 2))
    compliant = sum(1 for f in hardening_findings if f["status"] == "COMPLIANT")
    credit = min(HARDENING_CREDIT_CAP, HARDENING_CREDIT_PER_ITEM * compliant)
    worst = "NONE"
    for evaluation in zone_evaluations:
        if SEVERITY_ORDER.index(evaluation["deficiency_severity"]) > SEVERITY_ORDER.index(worst):
            worst = evaluation["deficiency_severity"]
    return measured_veg_points, rhu(credit, 2), worst


# ---------------------------------------------------------------------------
# notice_compliance_deadline
# ---------------------------------------------------------------------------
def notice_dates(issued_at, notice_method, severity, hazard_zone):
    if notice_method == "CERTIFIED_MAIL":
        delivered = issued_at + datetime.timedelta(days=MAIL_SERVICE_DAYS)
    else:
        delivered = issued_at
    base_days = SEVERITY_DAYS[severity]
    if hazard_zone == "VERY_HIGH":
        compressed = int(math.ceil(base_days * 0.75))
        compliance_days = max(MIN_COMPLIANCE_DAYS, compressed)
    else:
        compliance_days = base_days
    return delivered, compliance_days, end_of_day(delivered, compliance_days)


# ---------------------------------------------------------------------------
# abatement_cost_recovery
# ---------------------------------------------------------------------------
def subsidy_tier(pre_subsidy_total_cents):
    if pre_subsidy_total_cents < 100000:
        return Decimal("0.30")
    if pre_subsidy_total_cents < 300000:
        return Decimal("0.20")
    return Decimal("0.10")


def step_ladder(pct):
    """One position toward more generous, saturating at 0.30."""
    index = SUBSIDY_TIER_LADDER.index(pct)
    return SUBSIDY_TIER_LADDER[min(index + 1, len(SUBSIDY_TIER_LADDER) - 1)]


def cost_recovery(actual_crew_hours, green_waste_tons, hourly_rate_cents,
                  mobilization_fee_cents, voluntary):
    labor = cents(Decimal(actual_crew_hours) * Decimal(hourly_rate_cents))
    disposal = cents(Decimal(green_waste_tons) * DISPOSAL_RATE_PER_TON_CENTS)
    mobilization = int(mobilization_fee_cents)
    if voluntary:
        admin = 0
    else:
        admin = (
            cents(Decimal(labor) * ADMIN_OVERHEAD_PCT)
            + cents(Decimal(disposal) * ADMIN_OVERHEAD_PCT)
            + cents(Decimal(mobilization) * ADMIN_OVERHEAD_PCT)
        )
    pre_subsidy = labor + disposal + mobilization + admin
    pct = subsidy_tier(pre_subsidy)
    if voluntary:
        pct = step_ladder(pct)
    subsidy = cents(Decimal(pre_subsidy) * pct)
    return {
        "labor_line_cents": labor,
        "disposal_line_cents": disposal,
        "mobilization_line_cents": mobilization,
        "admin_overhead_cents": admin,
        "pre_subsidy_total_cents": pre_subsidy,
        "subsidy_pct": pct,
        "district_subsidy_cents": subsidy,
        "total_recoverable_cents": pre_subsidy - subsidy,
        "recovery_basis": "VOLUNTARY_PRECOMPLIANCE" if voluntary else "DISTRICT_CONTRACTED",
    }


def recoverable_allocation(order):
    """Pour total_recoverable_cents into the four buckets in order; the subsidy
    shortfall therefore lands entirely in the last bucket, LABOR."""
    caps = {
        "ADMIN_OVERHEAD": order["admin_overhead_cents"] or 0,
        "MOBILIZATION": order["mobilization_line_cents"] or 0,
        "DISPOSAL": order["disposal_line_cents"] or 0,
        "LABOR": order["labor_line_cents"] or 0,
    }
    remaining = order["total_recoverable_cents"] or 0
    filled = {}
    for bucket in BUCKET_ORDER:
        take = min(remaining, caps[bucket])
        filled[bucket] = take
        remaining -= take
    return filled


def allocate_payment(order, prior_payments, amount_cents):
    filled = recoverable_allocation(order)
    already = dict((bucket, 0) for bucket in BUCKET_ORDER)
    for payment in prior_payments:
        for bucket in BUCKET_ORDER:
            already[bucket] += payment["allocation"].get(bucket, 0)
    remaining = amount_cents
    allocation = {}
    for bucket in BUCKET_ORDER:
        take = min(remaining, filled[bucket] - already[bucket])
        if take < 0:
            take = 0
        allocation[bucket] = take
        remaining -= take
    return allocation


# ---------------------------------------------------------------------------
# cost_share_award
# ---------------------------------------------------------------------------
def bonus_tier(award_before_bonus_cents):
    if award_before_bonus_cents < 50000:
        return Decimal("0.15")
    if award_before_bonus_cents < 120000:
        return Decimal("0.10")
    return Decimal("0.05")


def cost_share_award(parcel, vendor_invoice_cents):
    eligible = min(int(vendor_invoice_cents), PER_PARCEL_CAP_CENTS)
    match = MATCH_BY_RISK_CLASS[parcel["risk_class"]]
    before = cents(Decimal(eligible) * match)
    pct = bonus_tier(before)
    bonus = cents(Decimal(before) * pct) if parcel["owner_hardship_flag"] else 0
    return {
        "award_before_bonus_cents": before,
        "bonus_pct": pct,
        "hardship_bonus_cents": bonus,
        "award_cents": before + bonus,
    }
