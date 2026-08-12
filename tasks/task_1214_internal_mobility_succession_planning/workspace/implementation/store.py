"""In-memory data store, logical clock, constants, and domain calculations.

Task 1214 — Internal Mobility & Succession Planning.

Every recorded timestamp derives from the single logical clock (PRD §2.4);
the clock starts at exactly 2026-05-01T00:00:00Z and only moves through
POST /talent/_clock/set_current_utc. All scoring uses Decimal arithmetic
with ROUND_HALF_UP (PRD §2.6).
"""
import uuid
import random
import string
import threading
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 / PRD §2-§3)
# ---------------------------------------------------------------------------
ROLES = {"HRAdmin", "HRBusinessPartner", "TalentManager", "Manager", "Employee"}

DEMOGRAPHIC_GROUPS = {"GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "UNDISCLOSED"}
UNDERREPRESENTED_GROUPS = {"GROUP_C", "GROUP_D"}
PERFORMANCE_RATINGS = {"LOW", "SOLID", "STRONG", "EXCEPTIONAL"}
CRITICALITY_TIERS = {"TIER_1", "TIER_2", "TIER_3"}
ASSESSMENT_METHODS_ROLE = {"WEIGHTED", "COVERAGE"}
READINESS_RATINGS = {"READY_NOW", "READY_1_2", "READY_3_PLUS"}
SUSPENSION_REASONS = {"PERFORMANCE_CONCERN", "EMPLOYEE_REQUEST", "ORG_CHANGE"}
HOLD_REASONS = {"CRITICAL_PROJECT", "PERFORMANCE_PLAN", "RECENT_MOVE"}
CLOSED_REASONS = {"NO_VIABLE_CANDIDATE", "ORG_CHANGE"}
APPLICATION_STATUSES = {
    "PENDING_MANAGER_CONSENT", "MANAGER_HOLD", "CONSENT_GRANTED", "INTERVIEWING",
    "OFFER_EXTENDED", "OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN",
}
DECISIONS = {"ACCEPT", "DECLINE"}
REVIEW_OUTCOMES = {"RETAIN", "REMOVE"}
ASSESSMENT_CLOSE_OUTCOMES = {"MITIGATED", "DISMISSED"}
ACTION_TYPES = {"STAY_INTERVIEW", "COMP_REVIEW", "ROLE_REDESIGN", "RETENTION_BONUS"}
ASSESSMENT_METHODS_RISK = {"POINT_IN_TIME", "TREND"}
SCOPE_TYPES = {"DEPARTMENT", "HIPO_CYCLE"}

RATING_POINTS = {"LOW": 20, "SOLID": 50, "STRONG": 80, "EXCEPTIONAL": 100}
READINESS_WEIGHT = {"READY_NOW": Decimal("1.0"), "READY_1_2": Decimal("0.6"),
                    "READY_3_PLUS": Decimal("0.3")}
POSITION_DECAY = Decimal("0.9")
SLATE_MAX = 5
MAX_POSSIBLE = Decimal("4.0951")  # sum_{p=1..5} 1.0 * 0.9^(p-1)
READINESS_RANK = {"READY_NOW": 0, "READY_1_2": 1}

TREND_WEIGHTS = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
TENURE_RISK_MONTHS = 24
TENURE_RISK_DELTA = 15
HIPO_RISK_DELTA = 10
READY_NOW_RISK_DELTA = 20

TIER_WEIGHT = {"TIER_1": 3, "TIER_2": 2, "TIER_3": 1}

CONSENT_WINDOW_DAYS = 14
HOLD_DURATION_DAYS = 30
FILL_WINDOW_DAYS = 60
MAX_ACTIVE_HOLDS = 1

# Posture / risk bands (PRD §2.9, §3.8)
POSTURE_ADEQUATE_MIN = Decimal("40")
POSTURE_STRONG_MIN = Decimal("70")
RISK_MEDIUM_MIN = Decimal("30")
RISK_HIGH_MIN = Decimal("60")
RISK_CRITICAL_MIN = Decimal("85")

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store — starts empty on every boot; no seeding anywhere.
# ---------------------------------------------------------------------------
employees = {}
critical_roles = {}
successor_entries = {}
development_plans = {}
vacancies = {}
postings = {}
applications = {}
calibration_sessions = {}
calibration_entries = {}
hipo_cycles = {}
hipo_nominations = {}
retention_assessments = {}
diversity_snapshots = {}

logical_clock = DEFAULT_CLOCK

_seq_counter = 0
_seq_lock = threading.Lock()
# Global write lock: serializes requests so every mutation + cascade is atomic.
request_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    """Current logical-clock instant (aware datetime)."""
    return logical_clock


def now_iso():
    return iso(logical_clock)


def set_clock(dt):
    global logical_clock
    logical_clock = dt


def meta_timestamp():
    """Envelope timestamp — server-generated wall-clock instant (PRD §2.2)."""
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime; None if bad."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD); returns a date or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def months_between(hire, now):
    """Whole calendar months between a hire date and the logical-clock instant."""
    months = (now.year - hire.year) * 12 + (now.month - hire.month)
    if now.day < hire.day:
        months -= 1
    return months


# ---------------------------------------------------------------------------
# Common field helpers — every common_fields entity carries id / created_at /
# updated_at / version. version increments on every modification including
# cascade-originated ones (PRD §2.5). Within a single request each resource is
# touched at most once (per-request dirty set), then flushed by commit().
# ---------------------------------------------------------------------------
_dirty = set()


def mark(res):
    _dirty.add(res["id"])


def _find(res_id):
    for table in (employees, critical_roles, successor_entries, development_plans,
                  vacancies, postings, applications, calibration_sessions,
                  calibration_entries, hipo_cycles, hipo_nominations,
                  retention_assessments):
        if res_id in table:
            return table[res_id]
    return None


def commit():
    """Apply updated_at/version to every resource touched this request."""
    for res_id in _dirty:
        res = _find(res_id)
        if res is None or "version" not in res:
            continue
        res["updated_at"] = now_iso()
        res["version"] = res["version"] + 1
    _dirty.clear()


def reset_request_dirty():
    _dirty.clear()


def stamp_new(row):
    ts = now_iso()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def stamp_append_only(row):
    row["created_at"] = now_iso()
    row["_seq"] = next_seq()
    return row


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def rhu(value, places):
    """Round half-up to `places` decimal places; returns Decimal."""
    return Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def num(value):
    """Serialize a Decimal as a JSON number (float)."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Derived / computed lookups
# ---------------------------------------------------------------------------
def employee_active_hold_count(employee_id):
    return sum(1 for a in applications.values()
               if a["employee_id"] == employee_id and a["status"] == "MANAGER_HOLD")


def employee_is_high_potential(employee_id):
    return any(n["employee_id"] == employee_id and n["status"] in ("ACTIVE", "UNDER_REVIEW")
               for n in hipo_nominations.values())


def posting_application_count(posting_id):
    terminal = ("OFFER_ACCEPTED", "OFFER_DECLINED", "REJECTED", "WITHDRAWN")
    return sum(1 for a in applications.values()
               if a["posting_id"] == posting_id and a["status"] not in terminal)


def session_entry_count(session_id):
    return sum(1 for e in calibration_entries.values() if e["session_id"] == session_id)


def session_ratified_count(session_id):
    return sum(1 for e in calibration_entries.values()
               if e["session_id"] == session_id and e["status"] in ("RATIFIED", "APPLIED"))


def cycle_enrolled_count(cycle_id):
    return sum(1 for n in hipo_nominations.values()
               if n["cycle_id"] == cycle_id and n["status"] in ("ACTIVE", "UNDER_REVIEW"))


def plan_of_entry(entry_id):
    for p in development_plans.values():
        if p["successor_entry_id"] == entry_id:
            return p
    return None


def non_terminal_entries(role_id):
    return [e for e in successor_entries.values()
            if e["critical_role_id"] == role_id
            and e["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")]


def active_entries(role_id):
    return [e for e in successor_entries.values()
            if e["critical_role_id"] == role_id and e["status"] == "ACTIVE"]


# ---------------------------------------------------------------------------
# readiness_score (SCAFFOLD §1.3) — stored on the entry, recomputed at the
# triggers named by the spec: entry create, entry PATCH, plan create/PATCH,
# calibration finalize for the employee's ACTIVE/SUSPENDED entries.
# ---------------------------------------------------------------------------
def compute_readiness_score(entry):
    emp = employees[entry["employee_id"]]
    plan_pct = 0
    plan = plan_of_entry(entry["id"])
    if plan is not None and plan["status"] in ("ACTIVE", "COMPLETED"):
        plan_pct = plan["completion_pct"]
    score = Decimal("0.5") * RATING_POINTS[emp["performance_rating"]] + \
        Decimal("0.5") * plan_pct
    return rhu(score, 2)


def recompute_entry_score(entry):
    entry["readiness_score"] = compute_readiness_score(entry)
    mark(entry)


# ---------------------------------------------------------------------------
# bench_strength / bench_posture / posture_alert (SCAFFOLD §1.3, PRD §2.9)
# ---------------------------------------------------------------------------
def compute_bench_strength(role):
    entries = active_entries(role["id"])
    if role["assessment_method"] == "COVERAGE":
        ready = sum(1 for e in entries
                    if e["readiness_rating"] in ("READY_NOW", "READY_1_2"))
        return rhu(Decimal(ready) / SLATE_MAX * 100, 0)
    # WEIGHTED — pinned order: per-entry 3dp, then sum, then normalize 2dp.
    total = Decimal("0")
    for e in entries:
        raw = READINESS_WEIGHT[e["readiness_rating"]] \
            * (POSITION_DECAY ** (e["slate_position"] - 1)) \
            * (Decimal(e["readiness_score"]) / 100)
        total += rhu(raw, 3)
    if total == 0:
        return Decimal("0.00")
    return rhu(total / MAX_POSSIBLE * 100, 2)


def posture_of(strength):
    if strength == 0:
        return "EMPTY"
    if strength < POSTURE_ADEQUATE_MIN:
        return "THIN"
    if strength < POSTURE_STRONG_MIN:
        return "ADEQUATE"
    return "STRONG"


def spawn_bench_thin_assessments(role):
    """PRD §2.9: on a newly set posture_alert, one OPEN POINT_IN_TIME
    BENCH_THIN_AUTO assessment per remaining ACTIVE READY_NOW slate entry."""
    for e in active_entries(role["id"]):
        if e["readiness_rating"] != "READY_NOW":
            continue
        emp_id = e["employee_id"]
        a = stamp_new({
            "id": new_id(),
            "employee_id": emp_id,
            "assessment_method": "POINT_IN_TIME",
            "trigger_source": "BENCH_THIN_AUTO",
            "action_type": None,
            "action_deadline": None,
            "status": "OPEN",
        })
        score, level = compute_risk(emp_id, "POINT_IN_TIME")
        a["risk_score"] = score
        a["risk_level"] = level
        retention_assessments[a["id"]] = a


def recompute_role_bench(role):
    """Recompute bench_strength/bench_posture; maintain posture_alert; on a
    degradation that newly sets the alert, fire the §2.9 auto-assessment cascade."""
    old_posture = role["bench_posture"]
    strength = compute_bench_strength(role)
    new_posture = posture_of(strength)
    role["bench_strength"] = strength
    role["bench_posture"] = new_posture
    alert_newly_set = False
    if new_posture in ("THIN", "EMPTY") and old_posture in ("ADEQUATE", "STRONG"):
        role["posture_alert"] = True
        alert_newly_set = True
    elif new_posture in ("ADEQUATE", "STRONG") and old_posture in ("THIN", "EMPTY"):
        role["posture_alert"] = False
    mark(role)
    if alert_newly_set:
        spawn_bench_thin_assessments(role)


# ---------------------------------------------------------------------------
# retention_risk_score / risk_level (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def compute_risk(employee_id, method):
    emp = employees[employee_id]
    now = now_dt()
    if method == "TREND" and emp["rating_history"]:
        hist = list(reversed(emp["rating_history"]))[:3]  # latest first
        weights = TREND_WEIGHTS[:len(hist)]
        wsum = sum(weights)
        weighted = sum((w / wsum) * RATING_POINTS[h["rating"]]
                       for w, h in zip(weights, hist))
        weighted = rhu(weighted, 3)
        base = Decimal(100) - weighted
    else:
        base = Decimal(100 - RATING_POINTS[emp["performance_rating"]])
    hire = parse_date(emp["hire_date"])
    if months_between(hire, now) < TENURE_RISK_MONTHS:
        base += TENURE_RISK_DELTA
    if employee_is_high_potential(employee_id):
        base -= HIPO_RISK_DELTA
    if any(e["employee_id"] == employee_id and e["status"] == "ACTIVE"
           and e["readiness_rating"] == "READY_NOW"
           for e in successor_entries.values()):
        base += READY_NOW_RISK_DELTA
    score = rhu(max(Decimal(0), min(Decimal(100), base)), 1)
    return score, risk_level_of(score)


def risk_level_of(score):
    if score < RISK_MEDIUM_MIN:
        return "LOW"
    if score < RISK_HIGH_MIN:
        return "MEDIUM"
    if score < RISK_CRITICAL_MIN:
        return "HIGH"
    return "CRITICAL"


# ---------------------------------------------------------------------------
# slate_fill_selection (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def select_slate_fill(vacancy):
    pool = []
    for e in active_entries(vacancy["critical_role_id"]):
        if e["readiness_rating"] not in ("READY_NOW", "READY_1_2"):
            continue
        emp = employees.get(e["employee_id"])
        if emp is None or emp["employment_status"] != "ACTIVE":
            continue
        pool.append(e)
    pool.sort(key=lambda e: (READINESS_RANK[e["readiness_rating"]],
                             -e["readiness_score"],
                             e["slate_position"],
                             e["created_at"],
                             e["_seq"]))
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# Serializers — computed fields recomputed live from the store.
# ---------------------------------------------------------------------------
def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def ser_employee(e):
    d = _common(e)
    d.update({
        "employee_code": e["employee_code"],
        "full_name": e["full_name"],
        "department": e["department"],
        "job_level": e["job_level"],
        "hire_date": e["hire_date"],
        "demographic_group": e["demographic_group"],
        "performance_rating": e["performance_rating"],
        "rating_history": e["rating_history"],
        "current_manager_id": e["current_manager_id"],
        "employment_status": e["employment_status"],
        "is_high_potential": employee_is_high_potential(e["id"]),
        "active_hold_count": employee_active_hold_count(e["id"]),
    })
    return d


def ser_role(r):
    d = _common(r)
    d.update({
        "role_title": r["role_title"],
        "department": r["department"],
        "criticality_tier": r["criticality_tier"],
        "assessment_method": r["assessment_method"],
        "incumbent_employee_id": r["incumbent_employee_id"],
        "status": r["status"],
        "bench_strength": num(r["bench_strength"]),
        "bench_posture": r["bench_posture"],
        "posture_alert": r["posture_alert"],
    })
    return d


def ser_successor(e):
    d = _common(e)
    d.update({
        "critical_role_id": e["critical_role_id"],
        "employee_id": e["employee_id"],
        "readiness_rating": e["readiness_rating"],
        "slate_position": e["slate_position"],
        "readiness_score": num(e["readiness_score"]),
        "status": e["status"],
        "suspension_reason": e["suspension_reason"],
        "supersedes_entry_id": e["supersedes_entry_id"],
    })
    return d


def ser_plan(p):
    d = _common(p)
    d.update({
        "successor_entry_id": p["successor_entry_id"],
        "target_readiness": p["target_readiness"],
        "completion_pct": p["completion_pct"],
        "status": p["status"],
    })
    return d


def ser_vacancy(v):
    d = _common(v)
    d.update({
        "critical_role_id": v["critical_role_id"],
        "status": v["status"],
        "fill_deadline": iso(v["fill_deadline"]),
        "filled_by_employee_id": v["filled_by_employee_id"],
        "fill_source": v["fill_source"],
        "closed_reason": v["closed_reason"],
    })
    return d


def ser_posting(p):
    d = _common(p)
    d.update({
        "vacancy_id": p["vacancy_id"],
        "title": p["title"],
        "min_tenure_months": p["min_tenure_months"],
        "min_job_level": p["min_job_level"],
        "planned_open_date": p["planned_open_date"],
        "planned_close_date": p["planned_close_date"],
        "status": p["status"],
        "application_count": posting_application_count(p["id"]),
    })
    return d


def ser_application(a):
    d = _common(a)
    d.update({
        "posting_id": a["posting_id"],
        "employee_id": a["employee_id"],
        "submitted_at": iso(a["submitted_at"]),
        "consent_deadline": iso(a["consent_deadline"]),
        "status": a["status"],
        "hold_reason": a["hold_reason"],
        "hold_at": iso(a["hold_at"]),
        "hold_expires_at": iso(a["hold_expires_at"]),
    })
    return d


def ser_session(s):
    d = _common(s)
    d.update({
        "name": s["name"],
        "department_scope": s["department_scope"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "status": s["status"],
        "entry_count": session_entry_count(s["id"]),
        "ratified_count": session_ratified_count(s["id"]),
    })
    return d


def ser_cal_entry(e):
    d = _common(e)
    d.update({
        "session_id": e["session_id"],
        "employee_id": e["employee_id"],
        "proposed_rating": e["proposed_rating"],
        "proposed_by_manager_id": e["proposed_by_manager_id"],
        "calibrated_rating": e["calibrated_rating"],
        "challenge_count": e["challenge_count"],
        "status": e["status"],
    })
    return d


def ser_cycle(c):
    d = _common(c)
    d.update({
        "cycle_name": c["cycle_name"],
        "capacity": c["capacity"],
        "enrolled_count": cycle_enrolled_count(c["id"]),
        "status": c["status"],
    })
    return d


def ser_nomination(n):
    d = _common(n)
    d.update({
        "cycle_id": n["cycle_id"],
        "employee_id": n["employee_id"],
        "nominated_by_manager_id": n["nominated_by_manager_id"],
        "endorsed_by_id": n["endorsed_by_id"],
        "review_count": n["review_count"],
        "status": n["status"],
    })
    return d


def ser_assessment(a):
    d = _common(a)
    d.update({
        "employee_id": a["employee_id"],
        "assessment_method": a["assessment_method"],
        "trigger_source": a["trigger_source"],
        "risk_score": num(a["risk_score"]),
        "risk_level": a["risk_level"],
        "action_type": a["action_type"],
        "action_deadline": a["action_deadline"],
        "status": a["status"],
    })
    return d


def ser_snapshot(s):
    # Append-only record: id + created_at only (no updated_at / version).
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "scope_type": s["scope_type"],
        "scope_ref": s["scope_ref"],
        "total_subjects": s["total_subjects"],
        "underrepresented_count": s["underrepresented_count"],
        "diversity_index": num(s["diversity_index"]),
    }
