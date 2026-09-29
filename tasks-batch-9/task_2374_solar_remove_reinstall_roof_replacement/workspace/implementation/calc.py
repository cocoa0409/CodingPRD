"""Deterministic calculations (PRD 3.6, 3.7, 3.8, 3.9).

Every monetary figure is an integer number of whole cents; all real-valued
arithmetic runs through decimal.Decimal so the pinned rounding placements are
reproduced exactly.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)


def D(value):
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = ONE if places == 0 else ONE.scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value))


# --------------------------------------------------------------------------
# deck_upgrade_cost (PRD 3.6)
# --------------------------------------------------------------------------
AREA_TIER_1_MAX_SQFT = D(100)
AREA_TIER_1_CENTS_PER_SQFT = D(950)
AREA_TIER_2_MAX_SQFT = D(300)
AREA_TIER_2_CENTS_PER_SQFT = D(780)
AREA_TIER_3_CENTS_PER_SQFT = D(640)
ATTACHMENT_UNIT_CENTS = D(4200)
FLASHING_SURCHARGE_MULT = D("1.25")
SEVERITY_MULT = {
    "LOW": D("1.00"),
    "MEDIUM": D("1.15"),
    "HIGH": D("1.40"),
    "CRITICAL": D("1.75"),
}
EMERGENCY_SEVERITY_BUMP = D("0.25")
CAP_CENTS = 2500000
FLOOR_BASE_CENTS = 50000


def deck_upgrade_cost(finding, posture):
    area = D(finding["affected_area_sqft"])

    tier1 = min(area, AREA_TIER_1_MAX_SQFT) * AREA_TIER_1_CENTS_PER_SQFT
    tier2 = max(Decimal(0), min(area, AREA_TIER_2_MAX_SQFT) - AREA_TIER_1_MAX_SQFT) \
        * AREA_TIER_2_CENTS_PER_SQFT
    tier3 = max(Decimal(0), area - AREA_TIER_2_MAX_SQFT) * AREA_TIER_3_CENTS_PER_SQFT
    area_cost = tier1 + tier2 + tier3

    surcharge = (
        FLASHING_SURCHARGE_MULT
        if finding["finding_type"] == "FLASHING_FAILURE"
        else D("1.00")
    )
    attachment_cost = D(finding["attachment_count_affected"]) * ATTACHMENT_UNIT_CENTS * surcharge

    severity = SEVERITY_MULT[finding["severity"]]
    if posture == "FROZEN":
        severity = severity + EMERGENCY_SEVERITY_BUMP

    raw = (area_cost + attachment_cost) * severity

    capped = min(cents(raw), CAP_CENTS)
    effective_floor = max(FLOOR_BASE_CENTS, cents(attachment_cost))
    return max(capped, effective_floor)


def requires_repermit(finding_type, severity):
    return severity in ("HIGH", "CRITICAL") and finding_type in (
        "SHEATHING_ROT",
        "STRUCTURAL_DEFLECTION",
    )


# --------------------------------------------------------------------------
# permit_fee (PRD 3.7)
# --------------------------------------------------------------------------
SCOPE_BASE = {
    "REINSTALL_ONLY": 18000,
    "STRUCTURAL_UPGRADE": 46000,
    "FULL_REPERMIT": 72000,
}
PER_KW_CENTS = D(850)
REVISION_SURCHARGE_CENTS = 9000


def permit_fee(permit, jurisdiction, project, revision_count_after):
    fee = SCOPE_BASE[permit["scope"]]
    fee += cents(D(project["system_dc_kw"]) * PER_KW_CENTS)
    if permit["expedited"]:
        fee += int(jurisdiction["expedite_fee_cents"])
    fee += int(revision_count_after) * REVISION_SURCHARGE_CENTS
    return fee


# --------------------------------------------------------------------------
# downtime_production_loss_credit (PRD 3.9)
# --------------------------------------------------------------------------
CREDIT_RATE_CENTS_PER_KWH = D(14)
OWNERSHIP_FACTOR = {
    "HOST_OWNED": D("0.00"),
    "LEASE": D("1.00"),
    "PPA": D("0.85"),
}
WEATHER_ABORTED_DAY_FACTOR = D("0.5")


def provisional_credit_cents(project):
    factor = OWNERSHIP_FACTOR[project["ownership_model"]]
    total = (
        D(project["baseline_daily_kwh"])
        * D(project["downtime_days_estimated"])
        * CREDIT_RATE_CENTS_PER_KWH
        * factor
    )
    return cents(total)


def downtime_dates(start_dt, end_dt):
    """Ordered ascending list of distinct UTC calendar dates, inclusive."""
    if start_dt is None or end_dt is None:
        return []
    first = start_dt.date()
    last = end_dt.date()
    if last < first:
        return []
    days = []
    cursor = first
    while cursor <= last:
        days.append(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def final_credit_cents(project, aborted_windows):
    """The chronological variant: round per calendar day, then sum."""
    factor = OWNERSHIP_FACTOR[project["ownership_model"]]
    total = 0
    for day in downtime_dates(project["deenergized_at"], project["reenergized_at"]):
        day_factor = D("1.0")
        for window in aborted_windows:
            if window["start_utc"].date() <= day <= window["end_utc"].date():
                day_factor = WEATHER_ABORTED_DAY_FACTOR
                break
        total += cents(
            D(project["baseline_daily_kwh"])
            * CREDIT_RATE_CENTS_PER_KWH
            * factor
            * day_factor
        )
    return total


# --------------------------------------------------------------------------
# replacement_match_classification (PRD 3.8)
# --------------------------------------------------------------------------
BASE_TOLERANCE_PCT = D("3.00")
WARRANTY_FILED_BONUS_PCT = D("1.00")
WAIVER_BONUS_PCT = D("2.00")


def classify_replacement(unit, offered_manufacturer, offered_model_code,
                         offered_rated_watts, waiver_ref, warranty_notice_snapshot,
                         ownership_model):
    """Steps 1 to 4 of the pinned classification order.

    Returns (watt_delta_pct, tolerance_pct, match_class, status_or_None).
    A None status means the request must be refused with
    ERR_MODEL_MISMATCH_NOT_WAIVED and no row persisted.
    """
    rated = D(unit["rated_watts"])
    watt_delta = round_half_up(((D(offered_rated_watts) - rated) / rated) * D(100), 2)

    tolerance = BASE_TOLERANCE_PCT
    if warranty_notice_snapshot == "FILED":
        tolerance = tolerance + WARRANTY_FILED_BONUS_PCT
    if waiver_ref is not None:
        tolerance = tolerance + WAIVER_BONUS_PCT
    tolerance = round_half_up(tolerance, 2)

    if (
        offered_manufacturer == unit["manufacturer"]
        and offered_model_code == unit["model_code"]
    ):
        match_class = "EXACT"
    elif offered_manufacturer == unit["manufacturer"] and abs(watt_delta) <= tolerance:
        match_class = "COMPATIBLE"
    else:
        match_class = "MISMATCHED"

    if match_class == "EXACT":
        status = "APPROVED"
    elif match_class == "COMPATIBLE" and ownership_model == "HOST_OWNED":
        status = "APPROVED"
    elif match_class == "COMPATIBLE":
        status = "PENDING_REVIEW"
    elif waiver_ref is not None:
        status = "PENDING_REVIEW"
    else:
        status = None

    return float(watt_delta), float(tolerance), match_class, status


# --------------------------------------------------------------------------
# circuit_watt_spread (PRD 3.8)
# --------------------------------------------------------------------------
MAX_CIRCUIT_WATT_SPREAD_PCT = D("3.00")


def circuit_watt_spread_pct(watt_values):
    if not watt_values:
        return D("0.00")
    smallest = D(min(watt_values))
    largest = D(max(watt_values))
    if smallest == 0:
        return D("0.00")
    return round_half_up(((largest - smallest) / smallest) * D(100), 2)


def watt_spread_exceeded(watt_values):
    return circuit_watt_spread_pct(watt_values) > MAX_CIRCUIT_WATT_SPREAD_PCT


# --------------------------------------------------------------------------
# unit_warranty_preservation (PRD 3.9)
# --------------------------------------------------------------------------
MFR_MAX_OFFROOF_DAYS = 30
CLIMATE_THRESHOLD_DAYS = 14
LENIENT_MAX_OFFROOF_DAYS = 14
STRICT_RISK_POINTS = 10
LENIENT_RISK_POINTS = 25


def unit_warranty_preservation(unit, storage_bin, off_roof_days):
    condition = unit["condition_grade"]
    if unit["warranty_variant"] == "MANUFACTURER_STRICT":
        climate = bool(storage_bin["climate_controlled"]) if storage_bin else False
        preserved = (
            off_roof_days <= MFR_MAX_OFFROOF_DAYS
            and (off_roof_days <= CLIMATE_THRESHOLD_DAYS or climate)
            and condition in ("SERVICEABLE", "REPLACED")
        )
        points = 0 if preserved else STRICT_RISK_POINTS
    else:
        preserved = (
            off_roof_days <= LENIENT_MAX_OFFROOF_DAYS and condition == "SERVICEABLE"
        )
        points = 0 if preserved else LENIENT_RISK_POINTS
    return preserved, points


# --------------------------------------------------------------------------
# crew_window_overlap (PRD 3.3)
# --------------------------------------------------------------------------
def crew_window_conflict(candidate_start, candidate_end, existing_start, existing_end,
                         buffer_minutes):
    buffer = timedelta(seconds=int(buffer_minutes) * 60)
    return (
        candidate_start < existing_end + buffer
        and existing_start < candidate_end + buffer
    )


WEATHER_ABORT_RESTRICT_THRESHOLD = 2
