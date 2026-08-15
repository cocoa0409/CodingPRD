import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc
CENT = Decimal("1")
PCT2 = Decimal("0.01")


def D(x):
    return Decimal(str(x))


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def add_years(dt, years):
    """Same month-day; Feb 29 -> Feb 28 on non-leap years."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# remaining_strength_pct (both variants, 2dp half-up, clamped 0..100)
# ---------------------------------------------------------------------------
REQUIRED_SHELL_IN = {
    "H1": Decimal("2.75"), "1": Decimal("2.50"), "2": Decimal("2.25"),
    "3": Decimal("2.00"), "4": Decimal("1.75"), "5": Decimal("1.50"),
}
SPECIES_FACTOR = {
    "SOUTHERN_PINE": Decimal("1.00"), "DOUGLAS_FIR": Decimal("0.95"),
    "WESTERN_RED_CEDAR": Decimal("0.90"), "LARCH": Decimal("1.02"),
}
DECAY_PENALTY_PER_INCH = Decimal("5.0")
MOISTURE_THRESHOLD = Decimal("30.0")
MOISTURE_MULT = Decimal("0.95")


def _clamp0100(v):
    return min(max(v, Decimal("0")), Decimal("100"))


def remaining_strength(pole, shell_thickness_in, sound_wood_pct,
                       decay_pocket_depth_in, moisture_pct):
    shell = D(shell_thickness_in)
    sound = D(sound_wood_pct)
    decay = D(decay_pocket_depth_in)
    moisture = D(moisture_pct)
    shell_ratio = shell / REQUIRED_SHELL_IN[pole["original_class"]]
    # CONSERVATIVE
    base = shell_ratio * 100 * (sound / 100) * SPECIES_FACTOR[pole["species"]]
    decay_penalty = decay * DECAY_PENALTY_PER_INCH
    moisture_mult = MOISTURE_MULT if moisture > MOISTURE_THRESHOLD else Decimal("1.00")
    cons = _clamp0100((base - decay_penalty) * moisture_mult)
    # STATISTICAL
    stat = _clamp0100(Decimal("0.6") * (shell_ratio * 100)
                      + Decimal("0.4") * sound
                      - Decimal("3.0") * decay)
    return (cons.quantize(PCT2, rounding=ROUND_HALF_UP),
            stat.quantize(PCT2, rounding=ROUND_HALF_UP))


SERVICEABLE_MIN = Decimal("60.00")
MONITOR_MIN = Decimal("45.00")
REJECT_ROUTINE_MIN = Decimal("30.00")


def classify(effective_rs_pct):
    r = effective_rs_pct
    if r >= SERVICEABLE_MIN:
        return "SERVICEABLE"
    if r >= MONITOR_MIN:
        return "MONITOR"
    if r >= REJECT_ROUTINE_MIN:
        return "REJECT_ROUTINE"
    return "REJECT_PRIORITY"


# ---------------------------------------------------------------------------
# inspection_sample_selection
# ---------------------------------------------------------------------------
FIELD_SEASON_DAYS = 120


def sample_size_for(pool_size, sample_pct):
    if pool_size > 0 and sample_pct > 0:
        return max(1, math.floor(pool_size * sample_pct / 100))
    return 0


# ---------------------------------------------------------------------------
# replacement_priority_score (integer; sum -> criticality floor -> cap)
# ---------------------------------------------------------------------------
DEFERRAL_STEP = 5
JOINT_USE_BONUS = 10
AGE_BONUS = 5
AGE_CUTOFF_YEAR = 1969
CRITICAL_FLOOR = 80
SCORE_CAP = 100


def priority_score(pole, deferral_count):
    rs = pole["current_remaining_strength_pct"]
    deficiency = Decimal("100") - (D(rs) if rs is not None else Decimal("50.00"))
    raw = deficiency + Decimal(DEFERRAL_STEP * deferral_count)
    if pole["joint_use"]:
        raw += Decimal(JOINT_USE_BONUS)
    try:
        install_year = int(str(pole["install_date"])[:4])
    except (ValueError, TypeError):
        install_year = 9999
    if install_year <= AGE_CUTOFF_YEAR:
        raw += Decimal(AGE_BONUS)
    if pole["gis_tag"] == "FEEDER_CRITICAL":
        raw = max(raw, Decimal(CRITICAL_FLOOR))
    raw = min(raw, Decimal(SCORE_CAP))
    return int(raw.quantize(CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# escalated_cost (integer cents, round half-up)
# ---------------------------------------------------------------------------
ESCALATION_RATE = Decimal("1.08")
DEFAULT_REPLACEMENT_COST_CENTS = 250000


def escalated_cost(estimated_cost_cents, deferral_count):
    v = Decimal(estimated_cost_cents) * (ESCALATION_RATE ** deferral_count)
    return int(v.quantize(CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# contractor_quality_score (LIFETIME and ROLLING variants, 2dp half-up)
# ---------------------------------------------------------------------------
ROLLING_WINDOW = 5
SUSPEND_THRESHOLD = Decimal("70.00")
BONUS_THRESHOLD = Decimal("90.00")


def quality_scores(crew):
    events = sorted(crew["qa_event_log"],
                    key=lambda e: (e["decided_at"], e["_seq"]))

    def ratio(evs):
        if not evs:
            return Decimal("100.00")
        passes = sum(1 for e in evs if e["decision"] == "PASS")
        return (Decimal(100 * passes) / Decimal(len(evs))).quantize(
            PCT2, rounding=ROUND_HALF_UP)

    return ratio(events), ratio(events[-ROLLING_WINDOW:])


# ---------------------------------------------------------------------------
# warranty_window
# ---------------------------------------------------------------------------
PRODUCT_WARRANTY_YEARS = {"CCA_WRAP": 10, "PENTA_GEL": 8, "COPPER_NAPHTHENATE": 5}


# ---------------------------------------------------------------------------
# production_billing_amount (per-line rounding pinned before summation)
# ---------------------------------------------------------------------------
BASE_RATE_CENTS = {"CCA_WRAP": 17500, "PENTA_GEL": 21000, "COPPER_NAPHTHENATE": 14500}
SPECIES_MULT = {
    "SOUTHERN_PINE": Decimal("1.00"), "DOUGLAS_FIR": Decimal("1.15"),
    "WESTERN_RED_CEDAR": Decimal("0.90"), "LARCH": Decimal("1.05"),
}
MOBILIZATION_CENTS = 40000
EARLY_BONUS_PCT = Decimal("0.05")
QA_FAIL_PENALTY_CENTS = 2500


def production_billing(crew, orders, poles_by_id, season_end):
    n = len(orders)
    subtotal = 0
    for o in orders:
        pole = poles_by_id[o["pole_id"]]
        line = (Decimal(BASE_RATE_CENTS[o["product_code"]])
                * SPECIES_MULT[pole["species"]]).quantize(CENT, rounding=ROUND_HALF_UP)
        mobilization = (Decimal(MOBILIZATION_CENTS) / Decimal(n)).quantize(
            CENT, rounding=ROUND_HALF_UP)
        subtotal += int(line) + int(mobilization)
    all_early = all(o["_verified_dt"] <= season_end for o in orders)
    lifetime = crew["quality_score_lifetime"]
    if all_early and lifetime >= BONUS_THRESHOLD:
        bonus = int((Decimal(subtotal) * EARLY_BONUS_PCT).quantize(
            CENT, rounding=ROUND_HALF_UP))
    else:
        bonus = 0
    penalty = sum(o["qa_fail_events"] for o in orders) * QA_FAIL_PENALTY_CENTS
    return max(0, subtotal + bonus - penalty)
