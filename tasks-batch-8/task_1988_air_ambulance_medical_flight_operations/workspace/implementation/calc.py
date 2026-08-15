"""Calculation rules C1-C8 (SCAFFOLD §1.3 / PRD §2.5, §3)."""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from core import db, now_dt, parse_dt

# ---------------------------------------------------------------------------
# C2 — patient acuity score
# ---------------------------------------------------------------------------

TRIAGE_W = {"cardio": Decimal("0.30"), "resp": Decimal("0.30"),
            "neuro": Decimal("0.20"), "interv": Decimal("0.20")}
ACCEPTANCE_W = {"cardio": Decimal("0.25"), "resp": Decimal("0.35"),
                "neuro": Decimal("0.25"), "interv": Decimal("0.15")}
DETERIORATION_BONUS = Decimal("2.0")
DETERIORATION_WINDOW_MIN = 120
TIER_CCT_MIN = Decimal("7.0")
TIER_ALS_MIN = Decimal("4.0")


def _weighted(weights, cardio, resp, neuro, interv):
    raw = (weights["cardio"] * cardio + weights["resp"] * resp
           + weights["neuro"] * neuro + weights["interv"] * interv)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def triage_score(cardio, resp, neuro, interv):
    """C2 triage variant: reported subscales, no deterioration bonus."""
    return _weighted(TRIAGE_W, cardio, resp, neuro, interv)


def acceptance_score(cardio, resp, neuro, interv, onset_dt, scoring_dt):
    """C2 acceptance variant: verified/updated subscales; bonus added AFTER
    rounding the weighted sum, when (scoring - onset) < 120 minutes strictly."""
    score = _weighted(ACCEPTANCE_W, cardio, resp, neuro, interv)
    if (scoring_dt - onset_dt) < timedelta(minutes=DETERIORATION_WINDOW_MIN):
        score = score + DETERIORATION_BONUS
    return score


def tier_of(acceptance):
    if acceptance >= TIER_CCT_MIN:
        return "CCT"
    if acceptance >= TIER_ALS_MIN:
        return "ALS"
    return "BLS"


def score_json(dec):
    """2dp Decimal -> JSON number."""
    return float(dec)


# ---------------------------------------------------------------------------
# C3 — weather minimums decision
# ---------------------------------------------------------------------------

BASE_CEIL = {("ROTOR_WING", "DAY"): 500, ("ROTOR_WING", "NIGHT"): 800,
             ("FIXED_WING", "DAY"): 800, ("FIXED_WING", "NIGHT"): 1200}
BASE_VIS = {("ROTOR_WING", "DAY"): Decimal("1.0"), ("ROTOR_WING", "NIGHT"): Decimal("3.0"),
            ("FIXED_WING", "DAY"): Decimal("2.0"), ("FIXED_WING", "NIGHT"): Decimal("3.0")}
MOUNTAIN_CEIL_BONUS = 500
XWIND_MAX = {"ROTOR_WING": 25, "FIXED_WING": 30}
MARGINAL_XWIND_PAD = 5
MARGINAL_VIS_PAD = Decimal("0.5")
ASSESSMENT_TTL_MIN = 60


def weather_decision(aircraft_class, ceiling_ft, visibility_sm, wind_kt,
                     precip, day_night, terrain):
    req_ceil = BASE_CEIL[(aircraft_class, day_night)]
    if terrain == "MOUNTAINOUS":
        req_ceil += MOUNTAIN_CEIL_BONUS
    req_vis = BASE_VIS[(aircraft_class, day_night)]
    xwind = XWIND_MAX[aircraft_class]
    vis = Decimal(str(visibility_sm))

    # NO_GO: any violation (wind/ceiling/visibility tests are strict)
    if precip == "ICE" or wind_kt > xwind or ceiling_ft < req_ceil or vis < req_vis:
        return "NO_GO"
    # MARGINAL: strictly-below / strictly-above tests; exact boundaries pass to GO
    marginal_ceil = req_ceil * Decimal("1.2")
    if (precip == "HEAVY" or Decimal(ceiling_ft) < marginal_ceil
            or vis < req_vis + MARGINAL_VIS_PAD or wind_kt > xwind - MARGINAL_XWIND_PAD):
        return "MARGINAL"
    return "GO"


def newest_assessment(mission_id):
    """Newest by created_at DESC; ties broken by server receipt sequence, never id."""
    cands = [a for a in db.weather_assessments.values() if a["mission_id"] == mission_id]
    if not cands:
        return None
    return max(cands, key=lambda a: (a["_created_dt"], a["_seq"]))


def assessment_fresh(assessment):
    """Fresh iff logical now <= assessed_at + 60 min (exactly 60 min still fresh)."""
    assessed = assessment.get("_assessed_dt") or parse_dt(assessment["assessed_at"])
    return now_dt() <= assessed + timedelta(minutes=ASSESSMENT_TTL_MIN)


# ---------------------------------------------------------------------------
# C1 / C4 / C7 — mission transport charge (pinned per-line rounding)
# ---------------------------------------------------------------------------

BASE_LIFTOFF = {"ROTOR_WING": 1800000, "FIXED_WING": 950000}
PER_MILE = {"ROTOR_WING": 16000, "FIXED_WING": 4500}
FUEL_PCT = 7
ACUITY_FEE = {"BLS": 0, "ALS": 120000, "CCT": 350000}
LOGISTICS_THRESHOLD = 2500000
LOGISTICS_PCT = 4
GROUND_LEG_FLAT = 45000
PROVISIONAL_MILE_FACTOR = Decimal("1.15")


def _round_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_miles(estimated_loaded_miles):
    """ceil(estimated * 1.15) to whole miles."""
    prod = Decimal(str(estimated_loaded_miles)) * PROVISIONAL_MILE_FACTOR
    return int(prod.quantize(Decimal("1"), rounding=ROUND_CEILING))


def charge_lines(aircraft_class, acuity_tier, miles, ground_leg_count):
    """Pinned order: mileage -> fuel -> subtotal -> logistics tier on the
    PRE-LOGISTICS subtotal -> logistics line -> ground line -> total.
    Every line rounds half-up to whole cents BEFORE summation (C4/C7)."""
    miles_dec = Decimal(str(miles))
    base_line = BASE_LIFTOFF[aircraft_class]
    mileage_line = _round_cents(miles_dec * PER_MILE[aircraft_class])
    fuel_line = _round_cents(Decimal(mileage_line) * FUEL_PCT / 100)
    acuity_line = ACUITY_FEE[acuity_tier]
    subtotal = base_line + mileage_line + fuel_line + acuity_line
    if subtotal >= LOGISTICS_THRESHOLD:
        logistics_line = _round_cents(Decimal(subtotal) * LOGISTICS_PCT / 100)
    else:
        logistics_line = 0
    ground_line = GROUND_LEG_FLAT * ground_leg_count
    total = subtotal + logistics_line + ground_line
    return {
        "base_line_cents": base_line,
        "mileage_line_cents": mileage_line,
        "fuel_line_cents": fuel_line,
        "acuity_line_cents": acuity_line,
        "logistics_line_cents": logistics_line,
        "ground_line_cents": ground_line,
        "total_cents": total,
    }


def count_ground_legs(mission_id, provisional):
    legs = [l for l in db.ground_legs.values() if l["mission_id"] == mission_id]
    if provisional:
        included = {"SCHEDULED", "ENROUTE", "AT_BEDSIDE", "COMPLETED"}
    else:
        included = {"COMPLETED"}
    return sum(1 for l in legs if l["status"] in included)


# ---------------------------------------------------------------------------
# C5 — crew duty / fatigue window (rolling 24h gate, whole minutes)
# ---------------------------------------------------------------------------

MAX_DUTY_MIN = 840
REST_MIN_MIN = 600
ROLLING_WINDOW_H = 24


def _shift_window(shift):
    start = shift["_planned_start"]
    end = shift["_planned_end"]
    return start, end


def _shift_effective_end(shift):
    """Later of planned and actual end (actual only exists once CLOSED)."""
    end = shift["_planned_end"]
    actual = shift.get("_actual_end")
    if actual is not None and actual > end:
        return actual
    return end


def _overlap_minutes(a_start, a_end, b_start, b_end):
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if hi <= lo:
        return 0
    return int((hi - lo).total_seconds() // 60)


def member_shifts(crew_member_id):
    """Shifts of the member, planned_start ASC, ties by creation order."""
    shifts = [s for s in db.crew_shifts.values() if s["crew_member_id"] == crew_member_id]
    shifts.sort(key=lambda s: (s["_planned_start"], s["_created_dt"], s["_seq"]))
    return shifts


def duty_projection_exceeded(crew_member_id, cand_start, cand_end, cand_minutes):
    """Window W = [cand_end - 24h, cand_end]; sum the full planned minutes of
    every member shift (OPEN or CLOSED) that intersects W, plus the candidate's
    planned_minutes; > 840 fails (== 840 passes).

    PRD §3.1: "Sum the minutes of all of the member's shifts, OPEN or CLOSED,
    that intersect the window ... and add the candidate's own planned_minutes.
    A projection of 840 minutes (fourteen hours) or less passes; 841 or more is
    rejected." The PRD's 841 boundary must be reachable: under
    intersection-clamping the 600-minute rest rule would structurally cap the
    projection at 840, making the ERR_DUTY_LIMIT_EXCEEDED branch dead code, so
    the shift's whole minutes are what the window sums."""
    w_start = cand_end - timedelta(hours=ROLLING_WINDOW_H)
    projected = cand_minutes
    for s in member_shifts(crew_member_id):
        s_start, s_end = _shift_window(s)
        if s_start < cand_end and w_start < s_end:
            projected += s["planned_minutes"]
    return projected > MAX_DUTY_MIN


def insufficient_rest(crew_member_id, cand_start):
    """Require >= 600 min since the member's latest prior shift end (later of
    planned/actual), considering only shifts ending at or before cand_start."""
    latest_end = None
    for s in member_shifts(crew_member_id):
        e = _shift_effective_end(s)
        if e <= cand_start and (latest_end is None or e > latest_end):
            latest_end = e
    if latest_end is None:
        return False
    gap_min = int((cand_start - latest_end).total_seconds() // 60)
    return gap_min < REST_MIN_MIN


def shift_overlaps(crew_member_id, cand_start, cand_end):
    """Positive-minute intersection with any existing shift of the member;
    zero-length end-to-start touching is not an overlap."""
    for s in member_shifts(crew_member_id):
        s_start, s_end = _shift_window(s)
        if s_start < cand_end and cand_start < s_end:
            return True
    return False


def duty_minutes_calendar_day(crew_member_id):
    """C5 calendar_day reporting variant: minutes of the member's shifts
    (OPEN or CLOSED) falling on the UTC calendar date of logical now."""
    day = now_dt().date()
    day_start = now_dt().replace(year=day.year, month=day.month, day=day.day,
                                 hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    total = 0
    for s in member_shifts(crew_member_id):
        s_start, s_end = _shift_window(s)
        total += _overlap_minutes(s_start, s_end, day_start, day_end)
    return total


# ---------------------------------------------------------------------------
# C8 — QA deficiency cascade tally
# ---------------------------------------------------------------------------

REMEDIATION_THRESHOLD = 15
WINDOW_DAYS = 90


def deficiency_points_90d(crew_member_id):
    """Sum of FLAGGED-review deficiency_points whose review instant lies in
    [logical now - 90 days, logical now], processed in review creation order."""
    lo = now_dt() - timedelta(days=WINDOW_DAYS)
    events = [e for e in db.qa_review_events
              if e["author_crew_id"] == crew_member_id and lo <= e["created_dt"] <= now_dt()]
    events.sort(key=lambda e: (e["created_dt"], e["seq"]))
    return sum(e["points"] for e in events)


# ---------------------------------------------------------------------------
# Capability ranks
# ---------------------------------------------------------------------------

CONFIG_RANK = {"BLS_CAPABLE": 1, "ALS_CAPABLE": 2, "CCT_CAPABLE": 3}
TIER_RANK = {"BLS": 1, "ALS": 2, "CCT": 3}
