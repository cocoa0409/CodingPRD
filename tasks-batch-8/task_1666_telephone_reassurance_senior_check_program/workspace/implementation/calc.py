"""Calculation rules: acuity, capacity, reliability, coverage, selector,
promotion scoring, satisfaction, SLA, outcome reports."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now
import timeutil
from timeutil import parse_hm

TIER_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}

REACHED_FAMILY = {"REACHED_OK", "REACHED_CONCERN", "REFUSED"}
NOANS_FAMILY = {"NO_ANSWER", "BUSY", "WRONG_NUMBER"}
REQUIRED_MODULES = {"SAFETY_PROTOCOL", "LISTENING_SKILLS", "MANDATED_REPORTING"}
FREQ_REQUIRED = {"CRITICAL": 5, "HIGH": 3, "MODERATE": 2, "LOW": 1}
SLA_HOURS = {"URGENT": 24, "STANDARD": 72, "ROUTINE": 168}
TIER_CAP = {"GOLD": 12, "SILVER": 10, "BRONZE": 8, "PROBATION": 4}
TIER_RANK = {"GOLD": 3, "SILVER": 2, "BRONZE": 1, "PROBATION": 0}
OPEN_STAGES = {"STEP_1_RETRY", "STEP_2_CONTACT", "STEP_3_WELFARE"}


def tier_for_score(score):
    if score <= 29:
        return "LOW"
    if score <= 59:
        return "MODERATE"
    if score <= 84:
        return "HIGH"
    return "CRITICAL"


def compute_intake_acuity(p):
    score = 0
    score += {"AGE_65_74": 0, "AGE_75_84": 10, "AGE_85_PLUS": 20}[p["age_band"]]
    score += 25 if p["lives_alone"] else 0
    score += {"NONE": 0, "LIMITED": 10, "SEVERE": 20}[p["mobility"]]
    score += 20 if p["cognitive_concern"] else 0
    score += min(3, p["chronic_conditions_count"]) * 5
    score += 10 if p["recent_hospitalization"] else 0
    score += 5 if p["recent_bereavement"] else 0
    score = min(100, score)
    return score, tier_for_score(score)


def effective_tier(p):
    t, r = p.get("acuity_tier"), p.get("rolling_acuity_tier")
    if t is None:
        return r
    if r is None:
        return t
    return t if TIER_ORDER[t] >= TIER_ORDER[r] else r


def sole_program():
    if not store.programs:
        return None
    return sorted(store.programs.values(), key=lambda e: (e["created_at"], e["_seq"]))[0]


# ---------------- capacity ----------------

def occupied_slots():
    return sum(1 for p in store.participants.values()
               if p["status"] in ("ENROLLED", "SUSPENDED", "WELFARE_HOLD"))


def waiting_count():
    return sum(1 for e in store.waitlist.values() if e["status"] in ("WAITING", "OFFERED"))


def critical_waiting_count():
    n = 0
    for e in store.waitlist.values():
        if e["status"] == "WAITING":
            p = store.participants.get(e["participant_id"])
            if p and p.get("acuity_tier") == "CRITICAL":
                n += 1
    return n


def capacity_numbers(prog):
    occupied = occupied_slots()
    gross_free = prog["total_capacity"] - occupied
    reserved = min(prog["max_reserve_slots"], critical_waiting_count())
    return occupied, gross_free, reserved


def admit_ok(prog, tier):
    """effective_capacity admission rule for a single applicant."""
    _, gross_free, reserved = capacity_numbers(prog)
    if tier == "CRITICAL":
        return gross_free >= 1
    return gross_free - reserved >= 1


# ---------------- volunteer reliability / load ----------------

def reliability(v):
    """Returns (windowed, streak_adj, tier, max_concurrent)."""
    td = timeutil.today()
    lo = td - timedelta(days=28)
    pool = [a for a in store.assignments.values()
            if a.get("volunteer_id") == v["id"]
            and lo < a["scheduled_date"] <= td
            and a["status"] in ("COMPLETED", "UNREACHED", "EXPIRED")]
    if len(pool) < 10:
        return None, None, "SILVER", TIER_CAP["SILVER"]
    showed = sum(1 for a in pool if a["status"] in ("COMPLETED", "UNREACHED"))
    windowed = (Decimal(showed * 100) / Decimal(len(pool))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)
    ordered = sorted(pool, key=lambda a: (a["scheduled_date"],
                                          parse_hm(a["window_start"]),
                                          a["created_at"], a["_seq"]))
    streak = 0
    for a in reversed(ordered):
        if a["status"] == "EXPIRED":
            streak += 1
        else:
            break
    adj = windowed - Decimal(5 * streak)
    if adj < 0:
        adj = Decimal("0.0")
    adj = adj.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if windowed >= Decimal("95.0"):
        tier = "GOLD"
    elif windowed >= Decimal("80.0"):
        tier = "SILVER"
    elif windowed >= Decimal("60.0"):
        tier = "BRONZE"
    else:
        tier = "PROBATION"
    return float(windowed), float(adj), tier, TIER_CAP[tier]


def _buffer():
    prog = sole_program()
    return prog["doc_buffer_minutes"] if prog else 15


def weekly_minutes(v, week_key, buffer=None):
    if buffer is None:
        buffer = _buffer()
    total = 0
    for a in store.assignments.values():
        if a.get("volunteer_id") != v["id"]:
            continue
        if a["status"] not in ("SCHEDULED", "COMPLETED", "UNREACHED"):
            continue
        if timeutil.iso_week_key(a["scheduled_date"]) != week_key:
            continue
        total += (parse_hm(a["window_end"]) - parse_hm(a["window_start"])) + buffer
    return total


def current_week_minutes(v):
    return weekly_minutes(v, timeutil.iso_week_key(timeutil.today()))


def future_scheduled_count(v):
    td = timeutil.today()
    return sum(1 for a in store.assignments.values()
               if a.get("volunteer_id") == v["id"]
               and a["status"] == "SCHEDULED" and a["scheduled_date"] >= td)


def training_current(v):
    clock = now()
    for m in REQUIRED_MODULES:
        ok = any(r["volunteer_id"] == v["id"] and r["module"] == m
                 and clock <= r["valid_until"]
                 for r in store.training.values())
        if not ok:
            return False
    return True


def agreement_current(v, prog):
    clock = now()
    return any(a["volunteer_id"] == v["id"] and a["status"] == "ACTIVE"
               and a["policy_version"] == prog["current_policy_version"]
               and clock <= a["valid_until"]
               for a in store.agreements.values())


def training_status(rec):
    return "VALID" if now() <= rec["valid_until"] else "EXPIRED"


def has_conflict(v, date, ws_min, we_min, buffer, exclude_id=None):
    """Closed, buffer-inclusive interval overlap vs the volunteer's SCHEDULED
    assignments on that date."""
    for a in store.assignments.values():
        if a.get("volunteer_id") != v["id"] or a["id"] == exclude_id:
            continue
        if a["status"] != "SCHEDULED" or a["scheduled_date"] != date:
            continue
        a_ws = parse_hm(a["window_start"])
        a_we = parse_hm(a["window_end"]) + buffer
        if ws_min <= a_we and a_ws <= we_min + buffer:
            return True
    return False


def availability_contains(v, date, ws_min, we_min):
    """Half-open containment in a volunteer AvailabilityWindow effective on date."""
    wd = timeutil.weekday_of(date)
    for w in store.windows.values():
        if w["volunteer_id"] != v["id"] or w["weekday"] != wd:
            continue
        if w["effective_from"] > date:
            continue
        if w["effective_to"] is not None and date > w["effective_to"]:
            continue
        if parse_hm(w["window_start"]) <= ws_min and we_min <= parse_hm(w["window_end"]):
            return True
    return False


def schedule_contains(p, date, ws_min, we_min):
    wd = timeutil.weekday_of(date)
    for s in store.schedules.values():
        if s["participant_id"] != p["id"] or s["weekday"] != wd:
            continue
        if s["status"] != "ACTIVE":
            continue
        if parse_hm(s["window_start"]) <= ws_min and we_min <= parse_hm(s["window_end"]):
            return True
    return False


def language_ok(v, p):
    return p["primary_language"] == "en" or p["primary_language"] in v["languages"]


def load_ok(v, date, slot_min, prog):
    wk = timeutil.iso_week_key(date)
    return (weekly_minutes(v, wk, prog["doc_buffer_minutes"]) + slot_min
            + prog["doc_buffer_minutes"] <= v["max_weekly_minutes"])


def cap_ok(v):
    _, _, _, cap = reliability(v)
    return future_scheduled_count(v) < cap


def selector(p, date, ws_min, we_min, prog):
    """Deterministic volunteer selector; returns VolunteerCaller or None."""
    slot_min = we_min - ws_min
    pool = []
    for v in store.volunteers.values():
        if v["status"] != "ACTIVE":
            continue
        if not training_current(v):
            continue
        if not agreement_current(v, prog):
            continue
        if not availability_contains(v, date, ws_min, we_min):
            continue
        if not language_ok(v, p):
            continue
        if has_conflict(v, date, ws_min, we_min, prog["doc_buffer_minutes"]):
            continue
        if not load_ok(v, date, slot_min, prog):
            continue
        if not cap_ok(v):
            continue
        pool.append(v)
    if not pool:
        return None
    wk = timeutil.iso_week_key(date)

    def rank(v):
        _, _, tier, _ = reliability(v)
        return (weekly_minutes(v, wk, prog["doc_buffer_minutes"]),
                -TIER_RANK[tier], v["created_at"], v["_seq"])

    pool.sort(key=rank)
    return pool[0]


# ---------------- coverage ----------------

def recompute_coverage(p):
    tier = effective_tier(p)
    if tier is None:
        p["coverage_deficient"] = False
        return
    required = FREQ_REQUIRED[tier]
    schedules = [s for s in store.schedules.values()
                 if s["participant_id"] == p["id"] and s["status"] == "ACTIVE"]
    if len(schedules) < required:
        p["coverage_deficient"] = True
        return
    td = timeutil.today()
    week_key = timeutil.iso_week_key(td)
    for s in schedules:
        covered = False
        for offset in range(7):
            d = td + timedelta(days=offset)
            if timeutil.weekday_of(d) != s["weekday"]:
                continue
            for a in store.assignments.values():
                if a["participant_id"] != p["id"]:
                    continue
                if a["status"] == "SCHEDULED" and a["scheduled_date"] == d and d >= td:
                    covered = True
                    break
                if (a["status"] == "COMPLETED"
                        and timeutil.iso_week_key(a["scheduled_date"]) == week_key
                        and timeutil.weekday_of(a["scheduled_date"]) == s["weekday"]):
                    covered = True
                    break
            if covered:
                break
        if not covered:
            p["coverage_deficient"] = True
            return
    p["coverage_deficient"] = False


# ---------------- rolling acuity ----------------

def compute_rolling(p):
    if p.get("acuity_score") is None:
        return
    clock = now()
    lo = clock - timedelta(days=30)
    logs = []
    for a in store.assignments.values():
        if a["participant_id"] != p["id"]:
            continue
        for lg in store.logs.values():
            if lg["assignment_id"] == a["id"] and lo <= lg["called_at"] <= clock:
                logs.append(lg)
    concerns = sum(1 for lg in logs if lg["concern_flag"])
    noans = sum(1 for lg in logs if lg["outcome"] in NOANS_FAMILY)
    esc = sum(1 for e in store.escalations.values()
              if e["participant_id"] == p["id"] and lo <= e["opened_at"] <= clock)
    refs = sum(1 for r in store.referrals.values()
               if r["participant_id"] == p["id"] and r.get("submitted_at")
               and lo <= r["submitted_at"] <= clock)
    signal = min(100, concerns * 15 + noans * 10 + esc * 25 + refs * 10)
    rolling = (Decimal("0.7") * Decimal(p["acuity_score"])
               + Decimal("0.3") * Decimal(signal)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP)
    p["rolling_acuity_score"] = float(rolling)
    p["rolling_acuity_tier"] = tier_for_score(rolling)


# ---------------- surveys / satisfaction ----------------

def survey_mean(items):
    val = (Decimal(1 * items[0] + 2 * items[1] + 1 * items[2] + 1 * items[3]
                   + 2 * items[4]) / Decimal(7))
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def satisfaction_index(period_month):
    means = [Decimal(str(s["survey_mean"])) for s in store.surveys.values()
             if s["status"] == "SCORED" and s["period_month"] == period_month
             and s.get("survey_mean") is not None]
    if not means:
        return None
    idx = sum(means) / Decimal(len(means))
    return float(idx.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------- referrals SLA ----------------

def referral_overdue(r):
    return (r["status"] == "SUBMITTED" and r.get("sla_due_at") is not None
            and now() > r["sla_due_at"])


# ---------------- outcome report ----------------

def compute_report_metrics(prog, period_month, variant):
    y, m = timeutil.parse_month(period_month)
    first, nxt, start, end = timeutil.month_bounds(y, m)
    td = timeutil.today()
    assignments = list(store.assignments.values())

    def in_period_date(d):
        return first <= d < nxt

    def in_period_dt(dt):
        return dt is not None and start <= dt < end

    if variant == "provisional":
        sched = [a for a in assignments
                 if in_period_date(a["scheduled_date"]) and a["scheduled_date"] <= td]
        denominator = sum(1 for a in sched
                          if a["status"] in ("COMPLETED", "UNREACHED", "EXPIRED"))
        calls_scheduled = len(sched)
    else:
        sched = [a for a in assignments
                 if in_period_date(a["scheduled_date"]) and a["status"] != "CANCELLED"]
        calls_scheduled = len(sched)
        denominator = calls_scheduled

    calls_completed = sum(1 for a in assignments
                          if a["status"] == "COMPLETED" and in_period_date(a["scheduled_date"]))
    if denominator == 0:
        completion_rate = None
    else:
        completion_rate = float(
            (Decimal(calls_completed * 100) / Decimal(denominator)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP))

    escalations_opened = sum(1 for e in store.escalations.values()
                             if in_period_dt(e["opened_at"]))
    escalations_resolved = sum(
        1 for e in store.escalations.values()
        if e["stage"].startswith("RESOLVED_") and in_period_dt(e.get("_resolved_at")))
    referrals_submitted = sum(1 for r in store.referrals.values()
                              if in_period_dt(r.get("submitted_at")))

    reached_pids = set()
    for lg in store.logs.values():
        if lg["outcome"] in REACHED_FAMILY and in_period_dt(lg["called_at"]):
            a = store.assignments.get(lg["assignment_id"])
            if a:
                reached_pids.add(a["participant_id"])

    return {
        "calls_scheduled": calls_scheduled,
        "calls_completed": calls_completed,
        "completion_rate": completion_rate,
        "escalations_opened": escalations_opened,
        "escalations_resolved": escalations_resolved,
        "referrals_submitted": referrals_submitted,
        "unique_participants_reached": len(reached_pids),
        "satisfaction_index": satisfaction_index(period_month),
    }
