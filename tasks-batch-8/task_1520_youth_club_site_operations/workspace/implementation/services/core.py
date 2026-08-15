"""Core domain services: entity resolution, day posture, staff compliance,
behavior points, and the sweep/cascade machinery."""

from datetime import datetime, timedelta, timezone

import db
from clock_util import CLOCK
from errors import not_found

MEAL_TYPES = ["BREAKFAST", "SNACK", "SUPPER"]
TIERS = ["FREE", "REDUCED", "PAID"]

POINTS_BY_CATEGORY = {"LEVEL_1": 1, "LEVEL_2": 3, "LEVEL_3": 8}
WATCH_THRESHOLD = 10
WINDOW_DAYS = 90


# ---------------------------------------------------------------------------
# Resolution helpers (pipeline stage 3)
# ---------------------------------------------------------------------------

def require(kind, rid):
    if not isinstance(rid, str) or not rid:
        raise not_found()
    rec = db.get(kind, rid)
    if rec is None:
        raise not_found()
    return rec


def resolve_fk(kind, value):
    if value is None or not isinstance(value, str):
        raise not_found()
    rec = db.get(kind, value)
    if rec is None:
        raise not_found()
    return rec


def _parse_dt(iso):
    s = iso[:-1] + "+00:00" if isinstance(iso, str) and iso.endswith("Z") else iso
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(s):
    y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    from datetime import date as date_cls
    return date_cls(y, m, d)


def day_end(dt_date):
    """End-of-day instant for a calendar date (used for approved_at <= day end)."""
    return datetime(dt_date.year, dt_date.month, dt_date.day, 23, 59, 59, 999999, tzinfo=timezone.utc)


def day_start(dt_date):
    return datetime(dt_date.year, dt_date.month, dt_date.day, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Staff compliance (PRD §3.1)
# ---------------------------------------------------------------------------

def compute_compliance(staff):
    """INCOMPLETE (any null) -> LAPSED (any expiry < now) -> EXPIRING (any within
    30 days) -> COMPLIANT."""
    now = CLOCK.now()
    bg = staff.get("background_check_expires_at")
    tr = staff.get("training_expires_at")
    if bg is None or tr is None:
        return "INCOMPLETE"
    bg_dt = _parse_dt(bg)
    tr_dt = _parse_dt(tr)
    if bg_dt < now or tr_dt < now:
        return "LAPSED"
    horizon = now + timedelta(days=30)
    if bg_dt <= horizon or tr_dt <= horizon:
        return "EXPIRING"
    return "COMPLIANT"


def lapse_cascade(staff, site_ids=None):
    """PRD §3.1: when a staff member is LAPSED, cancel their SCHEDULED and
    CHECKED_IN rotation assignments on club days dated today or later, and
    recompute each affected day's posture."""
    today = CLOCK.today()
    affected_days = set()
    for ra in db.find("rotations", staff_id=staff["id"]):
        if ra["status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        day = db.get("club_days", ra["club_day_id"])
        if day is None or day["date"] < today:
            continue
        ra["status"] = "CANCELLED"
        db.touch(ra)
        affected_days.add(day["id"])
    for day_id in affected_days:
        recompute_posture(db.get("club_days", day_id))


def staff_lapse_sweep(site_id):
    """Opening sweep leg two: any staff whose compliance is now LAPSED fires the
    lapse cascade."""
    for staff in db.find("staff", site_id=site_id):
        if compute_compliance(staff) == "LAPSED":
            lapse_cascade(staff)


# ---------------------------------------------------------------------------
# Behavior points and suspensions (PRD §3.8)
# ---------------------------------------------------------------------------

def recompute_behavior_points(member):
    """Rolling 90-day window [today-90, today] inclusive; ADJUDICATED incidents
    whose suspension is not RESCINDED count."""
    today = CLOCK.today()
    today_d = _parse_date(today)
    window_start = (today_d - timedelta(days=WINDOW_DAYS)).isoformat()
    total = 0
    for inc in db.find("incidents", member_id=member["id"]):
        if inc["adjudication_status"] != "ADJUDICATED":
            continue
        if inc["suspension_status"] == "RESCINDED":
            continue
        if window_start <= inc["incident_date"] <= today:
            total += inc["points"]
    member["behavior_points"] = total
    member["discipline_watch"] = total >= WATCH_THRESHOLD


def suspension_sweep(site_id, day_date):
    """Opening sweep leg one (PRD §3.4): IMPOSED suspensions whose start date has
    been reached become ACTIVE (member ACTIVE->SUSPENDED); ACTIVE suspensions
    whose full window [start, start+days) has elapsed become SERVED (member
    SUSPENDED->ACTIVE when no other ACTIVE suspension remains)."""
    site_members = {m["id"]: m for m in db.find("members", site_id=site_id)}
    # Activation first
    for inc in db.all_records("incidents"):
        member = site_members.get(inc["member_id"])
        if member is None:
            continue
        if inc["suspension_status"] != "IMPOSED":
            continue
        if day_date >= inc["suspension_start_date"]:
            inc["suspension_status"] = "ACTIVE"
            db.touch(inc)
            if member["status"] == "ACTIVE":
                member["status"] = "SUSPENDED"
                db.touch(member)
    # Serving second
    for inc in db.all_records("incidents"):
        member = site_members.get(inc["member_id"])
        if member is None:
            continue
        if inc["suspension_status"] != "ACTIVE":
            continue
        start = _parse_date(inc["suspension_start_date"])
        end = (start + timedelta(days=inc["suspension_days"])).isoformat()
        if day_date >= end:
            inc["suspension_status"] = "SERVED"
            db.touch(inc)
            maybe_reinstate_member(member)


def maybe_reinstate_member(member):
    """SUSPENDED -> ACTIVE when no other incident still holds an ACTIVE
    suspension for this member."""
    if member["status"] != "SUSPENDED":
        return
    for other in db.find("incidents", member_id=member["id"]):
        if other["suspension_status"] == "ACTIVE":
            return
    member["status"] = "ACTIVE"
    db.touch(member)


# ---------------------------------------------------------------------------
# Club-day posture (PRD §3.4)
# ---------------------------------------------------------------------------

def recompute_posture(day):
    """Evaluation order pinned: OVER_CAPACITY first, then RATIO_STRAINED, else
    NORMAL. The ratio leg always uses the site's standard_ratio."""
    site = db.get("sites", day["site_id"])
    staff_day = 0
    for ra in db.find("rotations", club_day_id=day["id"]):
        if ra["kind"] == "STAFF" and ra["status"] == "CHECKED_IN":
            staff_day += 1
    if day["present_count"] >= site["youth_capacity"]:
        day["posture"] = "OVER_CAPACITY"
    elif staff_day * site["standard_ratio"] < day["present_count"]:
        day["posture"] = "RATIO_STRAINED"
    else:
        day["posture"] = "NORMAL"


def zeroed_meal_counts():
    return {mt: {t: 0 for t in TIERS} for mt in MEAL_TYPES}


# ---------------------------------------------------------------------------
# Rotation helpers (PRD §3.6)
# ---------------------------------------------------------------------------

def effective_ratio(area, site):
    if area.get("ratio_override") is not None:
        return area["ratio_override"]
    if area["risk_tier"] == "ELEVATED":
        return site["elevated_ratio"]
    return site["standard_ratio"]


def checked_in_counts(club_day_id, area_id, block):
    youth = 0
    staff = 0
    for ra in db.find("rotations", club_day_id=club_day_id, area_id=area_id, block=block):
        if ra["status"] != "CHECKED_IN":
            continue
        if ra["kind"] == "YOUTH":
            youth += 1
        else:
            staff += 1
    return youth, staff


def ride_covers(member_id, day_date):
    """ACTIVE ride whose half-open window [start, end) covers day_date."""
    for ride in db.find("rides", member_id=member_id):
        if ride["status"] != "ACTIVE":
            continue
        if ride["effective_start_date"] <= day_date:
            end = ride.get("effective_end_date")
            if end is None or day_date < end:
                return ride
    return None
