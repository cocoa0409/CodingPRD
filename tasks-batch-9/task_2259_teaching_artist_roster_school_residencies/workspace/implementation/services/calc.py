"""Every calculation rule of PRD 2.5 / 3.x, in one place."""
import math
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from enums import (
    BLOCKING_SESSION_STATUSES,
    CANCELLED_SESSION_STATUSES,
    OPEN_RESIDENCY_STATUSES,
    OPEN_SESSION_STATUSES,
    REQUIRED_SCREENING_TYPES,
    TIER_ORDER,
)
from errors import ApiError
from validators import minutes_of, parse_date

# --- constants ---------------------------------------------------------------
W_ARTISTIC = Decimal("0.40")
W_PEDAGOGICAL = Decimal("0.35")
W_CULTURAL = Decimal("0.25")
PORTFOLIO_ADVANCE_THRESHOLD = Decimal("3.50")
PORTFOLIO_MIN_REVIEWS = 2

DEMO_ATTEMPT_LIMIT = 2
DEMO_PASS_SCORE = Decimal("3.5")
ADAPTATION_ROUND_LIMIT = 3

MASTER_PROMOTION_DELIVERIES = 25
MASTER_PROMOTION_RELIABILITY_BPS = 9500

RELIABILITY_WINDOW = 4
RELIABILITY_PROBATION_FLOOR_BPS = 8000
RELIABILITY_MIN_TERMINAL = 4
PROGRAM_YEAR_START_MONTH = 7

DISCIPLINE_BASE_RATE_CENTS = {
    "VISUAL_ARTS": 11000,
    "DANCE": 12000,
    "MUSIC": 12500,
    "THEATER": 11500,
    "MEDIA_ARTS": 13000,
    "LITERARY_ARTS": 10500,
}
GRADE_BAND_MULTIPLIER = {
    "K_2": Decimal("1.00"),
    "G3_5": Decimal("1.05"),
    "G6_8": Decimal("1.10"),
    "G9_12": Decimal("1.15"),
}
ROSTER_TIER_MULTIPLIER = {
    "APPRENTICE": Decimal("0.90"),
    "TEACHING_ARTIST": Decimal("1.00"),
    "MASTER": Decimal("1.20"),
}
LEAD_ARTIST_PREMIUM_PCT = Decimal("0.10")
BILINGUAL_PREMIUM_CENTS = 1500
SUBSTITUTE_RATE_PCT = Decimal("0.85")
MIN_SESSION_FEE_CENTS = 9000
MAX_SESSION_FEE_CENTS = 19000
MIN_DELIVERY_FRACTION = Decimal("0.50")

MILEAGE_RATE_CENTS_PER_MILE = 67
FREE_MILEAGE_PER_SESSION = Decimal("10.0")
MATERIALS_CAP_CENTS_PER_SESSION = 2500

W_OBSERVATION = Decimal("0.50")
W_SURVEY = Decimal("0.30")
W_ARTIFACT = Decimal("0.20")
OBSERVATION_SCALE_MAX = Decimal("4")
SURVEY_SCALE_MAX = Decimal("5")

INDIRECT_BRACKET_LOW_MAX_CENTS = 500000
INDIRECT_BRACKET_MID_MAX_CENTS = 1500000
INDIRECT_RATE_LOW = Decimal("0.15")
INDIRECT_RATE_MID = Decimal("0.12")
INDIRECT_RATE_HIGH = Decimal("0.10")

TRAVEL_BUFFER_MINUTES = 45


# --- rounding ---------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimals."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def as_number(value, places):
    """Render a Decimal as a JSON number with the pinned precision."""
    if value is None:
        return None
    return float(rhu(value, places))


# --- collection helpers -----------------------------------------------------
def sessions_of_residency(residency_id):
    return [s for s in db.sessions.values() if s["residency_id"] == residency_id]


def residency_of(session):
    return db.residencies.get(session["residency_id"])


def school_of_residency(residency):
    return db.school_partners.get(residency["school_partner_id"])


def blackouts_of_school(school_id):
    return [b for b in db.calendar_blackouts.values() if b["school_partner_id"] == school_id]


def reviews_of_artist(artist_id):
    return db.ordered([r for r in db.portfolio_reviews.values()
                       if r["teaching_artist_id"] == artist_id])


def screenings_of_artist(artist_id):
    return db.ordered([s for s in db.background_screenings.values()
                       if s["teaching_artist_id"] == artist_id])


def evaluations_of_session(session_id):
    return db.ordered([e for e in db.evaluation_records.values()
                       if e["session_id"] == session_id])


def vouchers_of_residency(residency_id):
    return [v for v in db.payment_vouchers.values() if v["residency_id"] == residency_id]


# --- portfolio --------------------------------------------------------------
def portfolio_composite(review):
    total = (W_ARTISTIC * dec(review["artistic_quality_score"])
             + W_PEDAGOGICAL * dec(review["pedagogical_clarity_score"])
             + W_CULTURAL * dec(review["cultural_responsiveness_score"]))
    return rhu(total, 2)


def portfolio_recommendation(composite):
    return "ADVANCE" if composite >= PORTFOLIO_ADVANCE_THRESHOLD else "DECLINE"


def portfolio_rollup(artist_id):
    reviews = reviews_of_artist(artist_id)
    count = len(set(r["reviewer_user_id"] for r in reviews))
    if not reviews:
        return count, None
    mean = sum((portfolio_composite(r) for r in reviews), Decimal("0")) / dec(len(reviews))
    return count, rhu(mean, 2)


# --- screening / clearance --------------------------------------------------
def latest_screenings(artist_id):
    """Map screening_type -> the winning row (effective_on DESC, created_at ASC)."""
    winners = {}
    for row in screenings_of_artist(artist_id):
        current = winners.get(row["screening_type"])
        if current is None or row["effective_on"] > current["effective_on"]:
            winners[row["screening_type"]] = row
    return winners


def screening_superseded(screening):
    winners = latest_screenings(screening["teaching_artist_id"])
    winner = winners.get(screening["screening_type"])
    return winner is not None and winner["id"] != screening["id"]


def artist_clearance_window(artist):
    """(clearance_status, clearance_expires_on)."""
    if artist.get("_clearance_forced_none"):
        return "NONE", None
    winners = latest_screenings(artist["id"])
    expiries = []
    for required in REQUIRED_SCREENING_TYPES:
        row = winners.get(required)
        if row is None or row["outcome"] == "FAILED" or not row.get("expires_on"):
            return "NONE", None
        expiries.append(row["expires_on"])
    earliest = min(expiries)
    status = "CLEARED" if earliest >= clock.logical_date() else "EXPIRED"
    return status, earliest


def clearance_status(artist):
    return artist_clearance_window(artist)[0]


def clearance_expires_on(artist):
    return artist_clearance_window(artist)[1]


# --- artist counters --------------------------------------------------------
def lifetime_delivered_count(artist_id):
    return len([s for s in db.sessions.values()
                if s["assigned_artist_id"] == artist_id and s["status"] == "DELIVERED"])


def no_show_count(artist_id):
    total = 0
    for s in db.sessions.values():
        if s["status"] != "CANCELLED_ARTIST" or s.get("cancel_reason") != "ARTIST_NO_SHOW":
            continue
        if s["assigned_artist_id"] == artist_id or s["vacated_artist_id"] == artist_id:
            total += 1
    return total


def terminal_sessions(artist_id):
    rows = [s for s in db.sessions.values()
            if (s["assigned_artist_id"] == artist_id or s["vacated_artist_id"] == artist_id)
            and s["status"] in ("DELIVERED", "CANCELLED_ARTIST")]
    # session_date DESC, created_at DESC
    rows.sort(key=lambda s: s["_seq"], reverse=True)
    rows.sort(key=lambda s: s["session_date"], reverse=True)
    return rows


def _bps(rows):
    if not rows:
        return 0
    credited = len([s for s in rows if s["status"] == "DELIVERED"])
    return rhu_int(dec(10000) * dec(credited) / dec(len(rows)))


def program_year_bounds(day=None):
    day = day or clock.logical_now().date()
    if day.month >= PROGRAM_YEAR_START_MONTH:
        start = date(day.year, PROGRAM_YEAR_START_MONTH, 1)
        end = date(day.year + 1, PROGRAM_YEAR_START_MONTH, 1)
    else:
        start = date(day.year - 1, PROGRAM_YEAR_START_MONTH, 1)
        end = date(day.year, PROGRAM_YEAR_START_MONTH, 1)
    return start.isoformat(), (date.fromordinal(end.toordinal() - 1)).isoformat()


def artist_reliability(artist_id):
    """(reliability_bps_rolling, reliability_bps_program_year)."""
    ordered = terminal_sessions(artist_id)
    rolling = _bps(ordered[:RELIABILITY_WINDOW])
    start, end = program_year_bounds()
    in_year = [s for s in ordered if start <= s["session_date"] <= end]
    return rolling, _bps(in_year)


def recompute_reliability(artist):
    rolling, program_year = artist_reliability(artist["id"])
    artist["reliability_bps_rolling"] = rolling
    artist["reliability_bps_program_year"] = program_year


def min_tier(left, right):
    return left if TIER_ORDER[left] <= TIER_ORDER[right] else right


def artist_roster_tier(artist):
    if artist["roster_status"] == "PROBATION":
        return min_tier(artist["roster_tier_assigned"], "TEACHING_ARTIST")
    if (lifetime_delivered_count(artist["id"]) >= MASTER_PROMOTION_DELIVERIES
            and artist["reliability_bps_program_year"] >= MASTER_PROMOTION_RELIABILITY_BPS):
        return "MASTER"
    return artist["roster_tier_assigned"]


def recompute_tier(artist):
    artist["roster_tier_effective"] = artist_roster_tier(artist)


# --- session fee ------------------------------------------------------------
def session_fee(residency, artist, minutes, is_substitute=False, is_lead=False):
    base = dec(DISCIPLINE_BASE_RATE_CENTS[residency["discipline"]])
    graded = rhu(base * GRADE_BAND_MULTIPLIER[residency["grade_band"]])
    tier = artist["roster_tier_effective"] if artist else "TEACHING_ARTIST"
    tiered = rhu(graded * ROSTER_TIER_MULTIPLIER[tier])
    premium = rhu(tiered * LEAD_ARTIST_PREMIUM_PCT) if is_lead else Decimal("0")
    language = Decimal("0")
    if (artist
            and residency["instruction_language"] != "en"
            and residency["instruction_language"] in (artist.get("languages") or [])):
        language = dec(BILINGUAL_PREMIUM_CENTS)
    raw = tiered + premium + language
    typed = rhu(raw * (SUBSTITUTE_RATE_PCT if is_substitute else Decimal("1.00")))
    capped = min(dec(MAX_SESSION_FEE_CENTS), max(dec(MIN_SESSION_FEE_CENTS), typed))
    billed = dec(int(math.ceil(float(dec(minutes)) / 5.0)) * 5)
    proration = min(Decimal("1.00"), billed / dec(residency["session_length_minutes"]))
    return rhu_int(capped * proration)


def is_lead_session(residency, session):
    return (session.get("assigned_artist_id") is not None
            and session["assigned_artist_id"] == residency["lead_artist_id"])


def full_length_fee(residency, session, artist=None, is_substitute=None):
    """Projected fee for a full-length delivery of `session`."""
    if artist is None and session.get("assigned_artist_id"):
        artist = db.teaching_artists.get(session["assigned_artist_id"])
    if is_substitute is None:
        is_substitute = bool(session.get("is_substitute"))
    return session_fee(residency, artist, residency["session_length_minutes"],
                       is_substitute=is_substitute,
                       is_lead=is_lead_session(residency, session))


def session_reimbursement(travel_miles, materials_spend_cents):
    billable = max(Decimal("0.0"), dec(travel_miles) - FREE_MILEAGE_PER_SESSION)
    travel = rhu_int(billable * dec(MILEAGE_RATE_CENTS_PER_MILE))
    materials = min(int(materials_spend_cents), MATERIALS_CAP_CENTS_PER_SESSION)
    return travel, materials


def min_delivery_minutes(residency):
    return int(math.ceil(float(MIN_DELIVERY_FRACTION * dec(residency["session_length_minutes"]))))


# --- residency ledgers ------------------------------------------------------
def session_ledger(residency):
    rows = sessions_of_residency(residency["id"])
    open_count = len([s for s in rows if s["status"] in OPEN_SESSION_STATUSES])
    delivered = len([s for s in rows if s["status"] == "DELIVERED"])
    vacated = len([s for s in rows if s["status"] == "VACATED"])
    cancelled = [s for s in rows if s["status"] in CANCELLED_SESSION_STATUSES]
    credits = len([s for s in cancelled
                   if s["makeup_eligible"] and not s["makeup_consumed"]])
    forfeited = len([s for s in cancelled if not s["makeup_eligible"]])
    forfeited += residency.get("_forfeited_extra", 0)
    return {
        "sessions_unscheduled_count": residency.get("sessions_unscheduled_count", 0),
        "sessions_open_count": open_count,
        "sessions_delivered_count": delivered,
        "sessions_forfeited_count": forfeited,
        "makeup_credits_outstanding": credits,
        "vacated_session_count": vacated,
    }


def budget_ledger(residency):
    rows = sessions_of_residency(residency["id"])
    encumbered = sum(s.get("encumbered_cents") or 0 for s in rows)
    disbursed = sum(voucher_total(v)["total_cents"]
                    for v in vouchers_of_residency(residency["id"])
                    if v["status"] == "APPROVED")
    if not residency.get("_ledger_init"):
        available = 0
    else:
        available = residency["budget_cents"] - encumbered - disbursed
    return {
        "encumbered_cents": encumbered,
        "disbursed_cents": disbursed,
        "available_cents": available,
    }


def staffing_status(residency):
    if residency.get("lead_artist_id") is None:
        return "LEAD_VACANT"
    if session_ledger(residency)["vacated_session_count"] >= 1:
        return "AT_RISK"
    return "STAFFED"


def school_health(school):
    rows = [r for r in db.residencies.values()
            if r["school_partner_id"] == school["id"] and r["status"] in OPEN_RESIDENCY_STATUSES]
    if any(r["status"] == "SUSPENDED" for r in rows):
        health = "INTAKE_SUSPENDED"
    elif any(staffing_status(r) in ("AT_RISK", "LEAD_VACANT") for r in rows):
        health = "WATCH"
    else:
        health = "HEALTHY"
    return health, len(rows)


# --- cost outlook -----------------------------------------------------------
def earned_to_date_cents(residency):
    return sum((s.get("payable_cents") or 0)
               for s in sessions_of_residency(residency["id"])
               if s["status"] == "DELIVERED")


def lead_projection(residency):
    lead = db.teaching_artists.get(residency.get("lead_artist_id")) \
        if residency.get("lead_artist_id") else None
    if lead is None:
        return session_fee(residency, None, residency["session_length_minutes"],
                           is_substitute=False, is_lead=False)
    return session_fee(residency, lead, residency["session_length_minutes"],
                       is_substitute=False, is_lead=True)


def projected_fee(residency, session):
    artist = None
    if session.get("assigned_artist_id"):
        artist = db.teaching_artists.get(session["assigned_artist_id"])
    elif session["status"] == "VACATED" and residency.get("lead_artist_id"):
        artist = db.teaching_artists.get(residency["lead_artist_id"])
    return session_fee(residency, artist, residency["session_length_minutes"],
                       is_substitute=bool(session.get("is_substitute")),
                       is_lead=is_lead_session(residency, session))


def projected_cost_cents(residency):
    ledger = session_ledger(residency)
    total = earned_to_date_cents(residency)
    for session in sessions_of_residency(residency["id"]):
        if session["status"] in OPEN_SESSION_STATUSES:
            total += projected_fee(residency, session)
    remaining = ledger["sessions_unscheduled_count"] + ledger["makeup_credits_outstanding"]
    if remaining:
        total += remaining * lead_projection(residency)
    return total


# --- evaluation -------------------------------------------------------------
def rubric_composite(record):
    if record["evaluation_type"] != "OBSERVATION_RUBRIC":
        return None
    total = (dec(record["rubric_engagement_score"])
             + dec(record["rubric_craft_score"])
             + dec(record["rubric_standards_evidence_score"]))
    return rhu(total / dec(3), 2)


def evaluation_index(residency):
    delivered = [s for s in sessions_of_residency(residency["id"]) if s["status"] == "DELIVERED"]
    delivered_ids = set(s["id"] for s in delivered)
    records = [e for e in db.evaluation_records.values() if e["session_id"] in delivered_ids]

    observations = [rubric_composite(e) for e in records
                    if e["evaluation_type"] == "OBSERVATION_RUBRIC"]
    surveys = [dec(e["teacher_survey_score"]) for e in records
               if e["evaluation_type"] == "TEACHER_SURVEY"]
    samples = [e for e in records if e["evaluation_type"] == "STUDENT_WORK_SAMPLE"]

    components = []
    if observations:
        mean = rhu(sum(observations, Decimal("0")) / dec(len(observations)), 2)
        components.append((W_OBSERVATION, mean / OBSERVATION_SCALE_MAX))
    if surveys:
        mean = rhu(sum(surveys, Decimal("0")) / dec(len(surveys)), 2)
        components.append((W_SURVEY, mean / SURVEY_SCALE_MAX))
    if samples:
        headcount = sum((s.get("students_present_count") or 0) for s in delivered)
        if headcount > 0:
            artifacts = sum(dec(e["student_work_artifact_count"] or 0) for e in samples)
            rate = min(Decimal("1"), artifacts / dec(headcount))
            components.append((W_ARTIFACT, rate))
    if not components:
        return None
    weight_sum = sum((w for w, _ in components), Decimal("0"))
    value = sum(((w / weight_sum) * v for w, v in components), Decimal("0"))
    return rhu(dec(100) * value, 1)


# --- funder report ----------------------------------------------------------
def funder_report_metrics(report):
    scope = [db.residencies[rid] for rid in report["scope_residency_ids"]
             if rid in db.residencies]
    metrics = {
        "sessions_delivered_total": 0,
        "students_served": 0,
        "frl_students_reached": 0,
        "ell_students_reached": 0,
        "iep_students_reached": 0,
        "direct_cost_cents": 0,
        "indirect_cost_cents": 0,
        "total_spend_cents": 0,
        "cost_per_student_cents": 0,
    }
    start = report["period_start"]
    end = report["period_end"]
    basis = report["headcount_basis"]

    delivered_total = 0
    students_served = 0
    frl = ell = iep = 0
    for residency in scope:
        rows = [s for s in sessions_of_residency(residency["id"])
                if s["status"] == "DELIVERED" and start <= s["session_date"] <= end]
        delivered_total += len(rows)
        encounters = sum((s.get("students_present_count") or 0) for s in rows)
        if basis == "ENCOUNTERS":
            students_served += encounters
        if not rows:
            continue
        if basis == "UNDUPLICATED":
            served = residency["enrolled_student_count"]
            students_served += served
        else:
            served = encounters
        school = school_of_residency(residency)
        if school is not None:
            frl += rhu_int(dec(served) * dec(school["frl_pct"]))
            ell += rhu_int(dec(served) * dec(school["ell_pct"]))
            iep += rhu_int(dec(served) * dec(school["iep_pct"]))

    scope_ids = set(report["scope_residency_ids"])
    direct = sum(voucher_total(v)["total_cents"] for v in db.payment_vouchers.values()
                 if v["status"] == "APPROVED" and v["residency_id"] in scope_ids
                 and start <= v["period_end"] <= end)
    if direct < INDIRECT_BRACKET_LOW_MAX_CENTS:
        rate = INDIRECT_RATE_LOW
    elif direct < INDIRECT_BRACKET_MID_MAX_CENTS:
        rate = INDIRECT_RATE_MID
    else:
        rate = INDIRECT_RATE_HIGH
    indirect = rhu_int(dec(direct) * rate)
    total_spend = direct + indirect

    metrics["sessions_delivered_total"] = delivered_total
    metrics["students_served"] = students_served
    metrics["frl_students_reached"] = frl
    metrics["ell_students_reached"] = ell
    metrics["iep_students_reached"] = iep
    metrics["direct_cost_cents"] = direct
    metrics["indirect_cost_cents"] = indirect
    metrics["total_spend_cents"] = total_spend
    metrics["cost_per_student_cents"] = (
        0 if students_served == 0 else rhu_int(dec(total_spend) / dec(students_served)))
    return metrics


# --- voucher money ----------------------------------------------------------
def voucher_total(voucher):
    fee = travel = materials = 0
    for session_id in voucher["session_ids"]:
        session = db.sessions.get(session_id)
        if session is None:
            continue
        fee += session.get("fee_cents") or 0
        travel += session.get("travel_reimbursement_cents") or 0
        materials += session.get("materials_reimbursement_cents") or 0
    return {
        "session_fee_subtotal_cents": fee,
        "travel_reimbursement_cents": travel,
        "materials_reimbursement_cents": materials,
        "total_cents": fee + travel + materials,
    }


# --- interval arithmetic ----------------------------------------------------
def blackout_hit(school_id, session_date):
    for window in blackouts_of_school(school_id):
        if window["start_date"] <= session_date <= window["end_date"]:
            return True
    return False


def _interval(session):
    return minutes_of(session["start_time"]), minutes_of(session["end_time"])


def check_artist_intervals(residency, artist_id, session_date, start, end, exclude_id=None):
    """PRD 3.6 artist resource: overlap first, then the travel buffer."""
    others = []
    for other in db.sessions.values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in BLOCKING_SESSION_STATUSES:
            continue
        if other["session_date"] != session_date:
            continue
        if other["assigned_artist_id"] != artist_id:
            continue
        others.append(other)
    for other in others:
        o_start, o_end = _interval(other)
        if start < o_end and o_start < end:
            raise ApiError("ERR_ARTIST_SCHEDULE_CONFLICT",
                           "the artist already holds an overlapping session that day")
    for other in others:
        o_start, o_end = _interval(other)
        other_residency = residency_of(other)
        if other_residency is None:
            continue
        if other_residency["school_partner_id"] == residency["school_partner_id"]:
            continue
        gap = max(o_start - end, start - o_end)
        if gap < TRAVEL_BUFFER_MINUTES:
            raise ApiError("ERR_TRAVEL_BUFFER_VIOLATION",
                           "less than %d minutes between sessions at different schools"
                           % TRAVEL_BUFFER_MINUTES)


def check_school_capacity(residency, session_date, start, end, exclude_id=None):
    school = school_of_residency(residency)
    if school is None:
        return
    intervals = [(start, end)]
    for other in db.sessions.values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in BLOCKING_SESSION_STATUSES:
            continue
        if other["session_date"] != session_date:
            continue
        other_residency = residency_of(other)
        if other_residency is None:
            continue
        if other_residency["school_partner_id"] != residency["school_partner_id"]:
            continue
        intervals.append(_interval(other))
    boundaries = sorted(set([i[0] for i in intervals] + [i[1] for i in intervals]))
    for instant in boundaries:
        load = len([1 for lo, hi in intervals if lo <= instant < hi])
        if load > school["concurrent_session_capacity"]:
            raise ApiError("ERR_SCHOOL_CAPACITY_EXCEEDED",
                           "concurrent session load exceeds the school's capacity")


def capability_check(residency, artist):
    disciplines = [artist["primary_discipline"]] + list(artist.get("secondary_disciplines") or [])
    if residency["discipline"] not in disciplines:
        raise ApiError("ERR_DISCIPLINE_MISMATCH",
                       "the artist cannot teach %s" % residency["discipline"])
    if residency["grade_band"] not in (artist.get("grade_bands") or []):
        raise ApiError("ERR_GRADE_BAND_MISMATCH",
                       "the artist is not rostered for %s" % residency["grade_band"])
    if residency["instruction_language"] not in (artist.get("languages") or []):
        raise ApiError("ERR_LANGUAGE_CAPABILITY_MISSING",
                       "the artist does not deliver instruction in %s"
                       % residency["instruction_language"])


def date_in(day, start, end):
    return start <= day <= end


def parse_or_none(value):
    return parse_date(value)
