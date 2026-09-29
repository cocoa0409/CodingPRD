"""Pure calculations (PRD 2.9 precision rules).

Every rounding in this module is ROUND_HALF_UP over Decimal values built from
str() so that binary float artefacts never shift a midpoint.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# rounding helper
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimals; returns a Decimal."""
    exp = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and hand back a JSON-friendly float."""
    return float(rhu(value, places))


def whole(value):
    """Round half up to a whole number and hand back an int."""
    return int(rhu(value, 0))


# --------------------------------------------------------------------------
# lethality_danger_score
# --------------------------------------------------------------------------

WEAPON_POINTS = 25
STRANGULATION_POINTS = 20
SEPARATION_POINTS = 15
THREATS_TO_KILL_POINTS = 18
STALKING_POINTS_PER_EVENT = 2
STALKING_CAP = 7
CORROBORATION_POINTS = 6
BOTH_COFACTOR_MULTIPLIER = Decimal("1.25")
ONE_COFACTOR_MULTIPLIER = Decimal("1.10")
NO_COFACTOR_MULTIPLIER = Decimal("1.00")
SCORE_CEILING = Decimal("100.0")
BAND_IMMINENT_MIN = Decimal("75.0")
BAND_ELEVATED_MIN = Decimal("50.0")
BAND_MODERATE_MIN = Decimal("25.0")

VARIANT_INTAKE = "INTAKE_SNAPSHOT"
VARIANT_CORROBORATED = "CORROBORATED_REVIEW"


def risk_band_of(score):
    s = dec(score)
    if s >= BAND_IMMINENT_MIN:
        return "IMMINENT"
    if s >= BAND_ELEVATED_MIN:
        return "ELEVATED"
    if s >= BAND_MODERATE_MIN:
        return "MODERATE"
    return "LOW"


def lethality_danger_score(weapon_access, strangulation_history, separation_recent,
                           threats_to_kill, stalking_frequency_per_week,
                           corroborate_with_history, corroborating_fact_count):
    """Return (variant_applied, fact_count, base_subtotal, multiplier, score, band)."""
    base_points = (
        (WEAPON_POINTS if weapon_access else 0)
        + (STRANGULATION_POINTS if strangulation_history else 0)
        + (SEPARATION_POINTS if separation_recent else 0)
        + (THREATS_TO_KILL_POINTS if threats_to_kill else 0)
        + STALKING_POINTS_PER_EVENT * min(stalking_frequency_per_week, STALKING_CAP)
    )
    if corroborate_with_history:
        variant = VARIANT_CORROBORATED
        facts = corroborating_fact_count
        bonus = CORROBORATION_POINTS * facts
    else:
        variant = VARIANT_INTAKE
        facts = 0
        bonus = 0
    base_subtotal = dec(base_points + bonus)

    if weapon_access and strangulation_history:
        multiplier = BOTH_COFACTOR_MULTIPLIER
    elif weapon_access or strangulation_history:
        multiplier = ONE_COFACTOR_MULTIPLIER
    else:
        multiplier = NO_COFACTOR_MULTIPLIER

    scored = rhu(base_subtotal * multiplier, 1)
    if scored > SCORE_CEILING:
        scored = SCORE_CEILING
    return (variant, facts, float(rhu(base_subtotal, 1)), float(multiplier),
            float(scored), risk_band_of(scored))


# --------------------------------------------------------------------------
# unit_bed_ledger thresholds
# --------------------------------------------------------------------------

def near_capacity_threshold(total_bed_capacity):
    """ceil(0.20 * total) in integer arithmetic."""
    return (total_bed_capacity * 20 + 99) // 100


def capacity_posture_of(available_beds, total_bed_capacity):
    if available_beds <= 0:
        return "FULL"
    if available_beds <= near_capacity_threshold(total_bed_capacity):
        return "NEAR_CAPACITY"
    return "OPEN"


def unit_status_of(reserved_beds, occupied_beds):
    if occupied_beds > 0:
        return "OCCUPIED"
    if reserved_beds > 0:
        return "HOLD"
    return "AVAILABLE"


# --------------------------------------------------------------------------
# safety_plan_coverage_score
# --------------------------------------------------------------------------

COMPONENT_TYPES = ("RELOCATION", "COMMUNICATION", "TECHNOLOGY", "WORKPLACE_NOTIFICATION")

BASE_WEIGHT = {
    "RELOCATION": 30,
    "COMMUNICATION": 25,
    "TECHNOLOGY": 25,
    "WORKPLACE_NOTIFICATION": 20,
}
IMMINENT_UPLIFT = Decimal("1.2")
UPLIFTED_TYPES = ("RELOCATION", "TECHNOLOGY")
STATUS_FACTOR = {
    "IMPLEMENTED": Decimal("1.000"),
    "DRAFT": Decimal("0.350"),
    "REVIEW_REQUIRED": Decimal("0.175"),
    "BLOCKED": Decimal("0.000"),
}
SCORE_DIVISOR = Decimal(10)


def component_weight_effective(component_type, client_risk_band):
    base = dec(BASE_WEIGHT[component_type])
    if client_risk_band == "IMMINENT" and component_type in UPLIFTED_TYPES:
        return rhu(base * IMMINENT_UPLIFT, 2)
    return rhu(base, 2)


def component_subscore(weight_effective, status):
    factor = STATUS_FACTOR[status]
    return rhu(dec(weight_effective) * factor / SCORE_DIVISOR, 2)


def coverage_total(subscores):
    total = Decimal(0)
    for s in subscores:
        total += dec(s)
    return rhu(total, 2)


# --------------------------------------------------------------------------
# shelter_stay_cost
# --------------------------------------------------------------------------

WEEKEND_NIGHTS_PER_WEEK = 2
DAYS_PER_WEEK = 7
SURCHARGE_WEEKDAYS = (4, 5)  # Friday, Saturday


def per_night_base(nightly_rate_cents, child_supplement_cents, minor_children_count):
    return nightly_rate_cents + child_supplement_cents * minor_children_count


def projected_stay_cost(entry_date, planned_exit_date, nightly_rate_cents,
                        weekend_surcharge_cents, child_supplement_cents,
                        minor_children_count):
    nights = (planned_exit_date - entry_date).days
    if nights < 0:
        nights = 0
    base = per_night_base(nightly_rate_cents, child_supplement_cents, minor_children_count)
    weekend_projected = whole(dec(nights) * WEEKEND_NIGHTS_PER_WEEK / dec(DAYS_PER_WEEK))
    return nights * base + weekend_projected * weekend_surcharge_cents


def settled_stay_cost(entry_date, actual_exit_date, nightly_rate_cents,
                      weekend_surcharge_cents, child_supplement_cents,
                      minor_children_count):
    base = per_night_base(nightly_rate_cents, child_supplement_cents, minor_children_count)
    total = 0
    night = entry_date
    while night < actual_exit_date:
        total += base
        if night.weekday() in SURCHARGE_WEEKDAYS:
            total += weekend_surcharge_cents
        night = night + timedelta(days=1)
    return total


# --------------------------------------------------------------------------
# landlord_engagement_incentive
# --------------------------------------------------------------------------

TIER_PLATINUM_MIN = Decimal("60.0")
TIER_GOLD_MIN = Decimal("30.0")
TIER_SILVER_MIN = Decimal("10.0")
TIER_MULTIPLIER = {
    "PLATINUM": Decimal("1.50"),
    "GOLD": Decimal("1.25"),
    "SILVER": Decimal("1.10"),
    "BASE": Decimal("1.00"),
}
RAPID_REHOUSING_BONUS_CENTS = 15000


def engagement_score_of(units_committed, units_pledged):
    if not units_pledged:
        return Decimal("0.0")
    return rhu(dec(100) * dec(units_committed) / dec(units_pledged), 1)


def incentive_tier_of(engagement_score):
    s = dec(engagement_score)
    if s >= TIER_PLATINUM_MIN:
        return "PLATINUM"
    if s >= TIER_GOLD_MIN:
        return "GOLD"
    if s >= TIER_SILVER_MIN:
        return "SILVER"
    return "BASE"


def incentive_fee(base_incentive_cents, tier, program_type):
    fee = whole(dec(base_incentive_cents) * TIER_MULTIPLIER[tier])
    if program_type == "RAPID_REHOUSING":
        fee += RAPID_REHOUSING_BONUS_CENTS
    return fee


# --------------------------------------------------------------------------
# staff_caseload_and_trauma_index
# --------------------------------------------------------------------------

DISTRESS_POINTS = 6
HOURS_POINTS = Decimal("0.5")
DEBRIEF_FACTOR = Decimal("0.70")
FRESH_WINDOW_DAYS = 7
STALE_WINDOW_DAYS = 30
CASELOAD_POINTS = Decimal("2.5")
INDEX_CEILING = Decimal("100.0")
POSTURE_FROZEN_MIN = Decimal("70.0")
POSTURE_RESTRICTED_MIN = Decimal("40.0")


def contribution_points(distress_scale, exposure_hours, debrief_completed):
    raw = dec(distress_scale) * DISTRESS_POINTS + dec(exposure_hours) * HOURS_POINTS
    if debrief_completed:
        raw = raw * DEBRIEF_FACTOR
    return float(rhu(raw, 1))


def decay_factor(days_since):
    if days_since <= FRESH_WINDOW_DAYS:
        return Decimal("1.0")
    if days_since <= STALE_WINDOW_DAYS:
        return Decimal("0.6")
    return Decimal("0.0")


def trauma_index(decayed_terms, active_caseload_count):
    total = Decimal(0)
    for points, days_since in decayed_terms:
        total += dec(points) * decay_factor(days_since)
    total += CASELOAD_POINTS * dec(active_caseload_count)
    rounded = rhu(total, 1)
    if rounded > INDEX_CEILING:
        rounded = INDEX_CEILING
    return float(rounded)


def wellness_posture_of(index):
    i = dec(index)
    if i >= POSTURE_FROZEN_MIN:
        return "FROZEN"
    if i >= POSTURE_RESTRICTED_MIN:
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------
# disclosure_field_projection
# --------------------------------------------------------------------------

KEY_VOCABULARY = (
    "client_code",
    "legal_name",
    "household_size",
    "minor_children_count",
    "program_type",
    "entry_date",
    "planned_exit_date",
    "shelter_unit_label",
    "shelter_street_address",
    "hotline_call_transcript",
)

_ALLOWED = {
    "HMIS_EXPORT": ("client_code", "household_size", "minor_children_count",
                    "program_type", "entry_date"),
    "COURT_SUBPOENA": tuple(k for k in KEY_VOCABULARY
                            if k not in ("shelter_unit_label", "shelter_street_address")),
    "PARTNER_AGENCY": tuple(k for k in KEY_VOCABULARY if k != "hotline_call_transcript"),
    "MANDATED_REPORT": KEY_VOCABULARY,
}

DISCLOSURE_KINDS = ("PARTNER_AGENCY", "COURT_SUBPOENA", "HMIS_EXPORT", "MANDATED_REPORT")


def disclosure_field_projection(kind, requested_field_keys, decision):
    """Return (released, suppressed, target_status), both arrays in canonical order."""
    requested = set(requested_field_keys)
    ordered = [k for k in KEY_VOCABULARY if k in requested]
    if decision == "DENY":
        return [], ordered, "DENIED"
    allowed = set(_ALLOWED[kind])
    released = [k for k in ordered if k in allowed]
    suppressed = [k for k in ordered if k not in allowed]
    status = "RELEASED" if not suppressed else "PARTIALLY_RELEASED"
    return released, suppressed, status
