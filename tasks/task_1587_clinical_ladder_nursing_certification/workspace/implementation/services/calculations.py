"""Calculation rules from scaffold section 1.3, implemented verbatim.

Covers: tenure_years, calc_participation_window, calc_committee_score,
calc_reimbursement_cap, calc_certification_bonus, calc_maintenance_score,
calc_retention_risk. Budget commitment/forecast live in services/budget.py
to avoid circular imports.
"""

import calendar
from datetime import timedelta

from clock import clock
from db import db


LEVELS = ["CN_I", "CN_II", "CN_III", "CN_IV"]
TRACK_ORDER = {"NONE": 0, "BASIC": 1, "SPECIALTY": 2, "ADVANCED": 3}

QUORUM = 3
REVIEW_WINDOW_DAYS = 14
MAINTENANCE_THRESHOLD = 60
LOOKBACK_MONTHS = 24
NURSE_FY_REIMBURSEMENT_CAP_CENTS = 150000

BONUS_BASE = {"BASIC": 50000, "SPECIALTY": 100000, "ADVANCED": 175000}
TENURE_BONUS_CENTS = 25000
TENURE_BONUS_YEARS = 10

W_LEADERSHIP = 0.30
W_CLINICAL = 0.30
W_PROFDEV = 0.20
W_OUTCOMES = 0.20

DECAY_PER_YEAR = 10


def subtract_months(dt, months):
    """Same day-of-month N months back; clamps to last day when absent."""
    m = dt.month - months
    y = dt.year
    while m <= 0:
        m += 12
        y -= 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def subtract_years(dt, years):
    try:
        return dt.replace(year=dt.year - years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year - years, day=28)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def tenure_years(nurse):
    """floor((now - hire_date).days / 365.25); recomputed on every read."""
    now = clock.now()
    days = (now - nurse["hire_date"]).days
    if days < 0:
        return 0
    return int(days // 365.25)


def calc_participation_window(nurse_id, at=None):
    """Integer sum of VERIFIED event points in [now-24m, now) half-open."""
    now = at if at is not None else clock.now()
    window_start = subtract_months(now, LOOKBACK_MONTHS)
    total = 0
    for e in db.participation_events.values():
        if e["nurse_id"] != nurse_id:
            continue
        if e["status"] != "VERIFIED":
            continue
        if window_start <= e["occurred_on"] < now:
            total += e["points"]
    return total


def round_half_up_int(x):
    """Round half-up to integer. Works on float via exact decimal string."""
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(repr(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calc_committee_score(application_id):
    """Weighted committee score. Returns integer aggregate or None if quorum unmet.

    Per-reviewer weighted totals kept at full float precision; averaged; the
    average rounded half-up to integer exactly once at the final step.
    """
    scored = [a for a in db.review_assignments.values()
              if a["application_id"] == application_id and a["status"] == "SCORED"]
    if not scored:
        return None
    per_reviewer = []
    for a in scored:
        ds = a["dimension_scores"]
        total = (ds["leadership"] * W_LEADERSHIP
                 + ds["clinical_expertise"] * W_CLINICAL
                 + ds["professional_development"] * W_PROFDEV
                 + ds["outcomes"] * W_OUTCOMES)
        per_reviewer.append(total)
    avg = sum(per_reviewer) / len(per_reviewer)
    return round_half_up_int(avg)


def active_criterion_for(target_level, at=None):
    """The active LadderCriterion covering target_level at clock position, or None."""
    now = at if at is not None else clock.now()
    for c in db.ladder_criteria.values():
        if c["target_level"] != target_level:
            continue
        if c["effective_from"] <= now and (c["effective_until"] is None or now < c["effective_until"]):
            return c
    return None


def nurse_level_requirement_track(nurse):
    """required_certification_track of the active criterion for nurse.current_level; NONE for CN_I."""
    if nurse["current_level"] == "CN_I":
        return "NONE"
    c = active_criterion_for(nurse["current_level"])
    if c is None:
        return "NONE"
    return c["required_certification_track"]


def nurse_has_current_cert_at_or_above(nurse_id, track):
    for c in db.certifications.values():
        if c["nurse_id"] == nurse_id and c["status"] == "CURRENT":
            if TRACK_ORDER[c["track"]] >= TRACK_ORDER[track]:
                return True
    return False


def calc_reimbursement_cap(nurse_id, fiscal_year, claimed_amount_cents):
    """Remaining room under the per-nurse FY ceiling, capped by the claim."""
    already = 0
    for claim in db.reimbursement_claims.values():
        cert = db.certifications.get(claim["certification_id"])
        if cert is None or cert["nurse_id"] != nurse_id:
            continue
        if claim["fiscal_year"] != fiscal_year:
            continue
        if claim["status"] in ("APPROVED", "PAID"):
            already += claim["approved_amount_cents"] or 0
    remaining = NURSE_FY_REIMBURSEMENT_CAP_CENTS - already
    return max(0, min(claimed_amount_cents, remaining))


def calc_certification_bonus(cert, nurse):
    """Track-tiered one-time bonus: round(base*multiplier) half-up, then add tenure."""
    base = BONUS_BASE[cert["track"]]
    multiplier = 1.5 if cert["renewal_of_id"] is None else 1.0
    multiplied = round_half_up_int(base * multiplier)
    tb = TENURE_BONUS_CENTS if tenure_years(nurse) >= TENURE_BONUS_YEARS else 0
    return multiplied + tb


def calc_maintenance_score(nurse):
    """Composite 0..100 from participation (cap 40) + certification (40/20/0) + tenure (cap 20)."""
    live = calc_participation_window(nurse["id"])
    participation_component = min(40, live * 2)
    requirement = nurse_level_requirement_track(nurse)
    has_req = nurse_has_current_cert_at_or_above(nurse["id"], requirement)
    if has_req:
        certification_component = 40
    else:
        certification_component = 20 if nurse_has_current_cert_at_or_above(nurse["id"], "BASIC") else 0
    tenure_component = min(20, tenure_years(nurse) * 2)
    return participation_component + certification_component + tenure_component


def record_risk_event(nurse_id, kind, at=None):
    """Append to the risk event log; entries ordered by (occurred_at, created_at)."""
    now = at if at is not None else clock.now()
    db.risk_events.append({
        "nurse_id": nurse_id,
        "kind": kind,
        "occurred_at": now,
        "created_at": now,
        "seq": db.next_seq(),
    })


def last_advancement_date(nurse):
    """Most recent APPROVE decision on any of the nurse's applications; None if never."""
    latest = None
    for d in db.advancement_decisions.values():
        if d["outcome"] != "APPROVE":
            continue
        app = db.applications.get(d["application_id"])
        if app is None or app["nurse_id"] != nurse["id"]:
            continue
        if latest is None or d["decided_at"] > latest:
            latest = d["decided_at"]
    return latest


def calc_retention_risk(nurse):
    """Decay first, then event bumps, then clamp to [0, 100]."""
    now = clock.now()
    baseline = last_advancement_date(nurse) or nurse["hire_date"]
    days = (now - baseline).days
    years = days // 365 if days >= 0 else 0
    decayed_base = max(0, nurse["retention_risk_score"] - int(years) * DECAY_PER_YEAR)

    w24_start = subtract_months(now, 24)
    w12_start = subtract_months(now, 12)

    def count(kind, window_start):
        # Upper bound inclusive of the evaluation instant so the event whose
        # transition triggered this recompute counts toward its own bump.
        evts = [e for e in db.risk_events
                if e["nurse_id"] == nurse["id"] and e["kind"] == kind
                and window_start <= e["occurred_at"] <= now]
        evts.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["seq"]))
        return len(evts)

    demotions = count("demotion", w24_start)
    cert_lapses = count("certification_lapse", w24_start)
    denials = count("application_denial", w24_start)
    clawbacks = count("bonus_clawback", w24_start)
    verifications = count("participation_verified", w12_start)
    advancements = count("advancement", w24_start)

    bumps = (15 * demotions + 10 * cert_lapses + 8 * denials + 5 * clawbacks
             - 6 * verifications - 20 * advancements)
    score = decayed_base + bumps
    return max(0, min(100, score))


def recompute_risk(nurse_id):
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        return
    nurse["retention_risk_score"] = calc_retention_risk(nurse)
