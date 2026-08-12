"""Business services: derived counters, cascades, staffing ratio, med windows,
billing calculations, discharge refund (SCAFFOLD §1.3, PRD §3)."""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from db import db
from errors import raise_err, ERR_RATE_NOT_FOUND, ERR_INVALID_STATE
from util import fmt_ts, now_ts, touch


# ---------------------------------------------------------------------------
# Home-local time helpers
# ---------------------------------------------------------------------------

def home_tz(home):
    return ZoneInfo(home["timezone"])


def local_midnight(home, d):
    tz = home_tz(home)
    return datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Derived counters (PRD §2.11) — each recompute is a home mutation
# ---------------------------------------------------------------------------

def recompute_home_counters(home):
    home["current_census"] = sum(
        1 for r in db.residents.values()
        if r["home_id"] == home["id"] and r["status"] == "ADMITTED")
    home["open_case_count"] = sum(
        1 for c in db.cases.values()
        if c["home_id"] == home["id"] and c["status"] in ("OPEN", "SUBSTANTIATED"))
    touch(home)


# ---------------------------------------------------------------------------
# Admission/bed compensation cascades
# ---------------------------------------------------------------------------

def find_pending_admission_for_bed(bed_id):
    for a in db.admissions.values():
        if a["bed_id"] == bed_id and a["status"] == "PENDING":
            return a
    return None


def reject_admission_system(admission):
    admission["status"] = "REJECTED"
    admission["decided_by"] = "system"
    admission["decided_at"] = now_ts()
    touch(admission)


def release_bed_hold(admission):
    """HELD -> AVAILABLE compensation for reject/cancel."""
    bed = db.beds.get(admission["bed_id"])
    if bed is not None and bed["status"] == "HELD":
        bed["status"] = "AVAILABLE"
        touch(bed)


def close_home_cascade(home):
    """Home closure: non-OUT_OF_SERVICE beds -> OUT_OF_SERVICE (HELD beds first
    force their linked PENDING admission -> REJECTED with bed-release
    suppressed); all SCHEDULED shifts -> CANCELLED without ratio revalidation."""
    for bed in db.beds.values():
        if bed["home_id"] != home["id"] or bed["status"] == "OUT_OF_SERVICE":
            continue
        if bed["status"] == "HELD":
            adm = find_pending_admission_for_bed(bed["id"])
            if adm is not None:
                reject_admission_system(adm)
        bed["status"] = "OUT_OF_SERVICE"
        touch(bed)
    for s in db.shifts.values():
        if s["home_id"] == home["id"] and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)


# ---------------------------------------------------------------------------
# Caregiver personal-capacity rules (SCAFFOLD caregiver_overlap_check)
# ---------------------------------------------------------------------------

def _trunc_minute(dt):
    return dt.replace(second=0, microsecond=0)


def caregiver_schedule_conflict(caregiver_id, new_start, new_end, exclude_shift_id=None):
    """Strict half-open overlap, plus >16 scheduled hours in any rolling
    24h window (minute granularity). Returns True on conflict."""
    existing = [s for s in db.shifts.values()
                if s["caregiver_id"] == caregiver_id
                and s["status"] == "SCHEDULED"
                and s["id"] != exclude_shift_id]
    for s in existing:
        if new_start < s["_end_dt"] and s["_start_dt"] < new_end:
            return True
    intervals = [(_trunc_minute(s["_start_dt"]), _trunc_minute(s["_end_dt"])) for s in existing]
    intervals.append((_trunc_minute(new_start), _trunc_minute(new_end)))
    cap_seconds = 16 * 3600
    breakpoints = set()
    for (s, e) in intervals:
        breakpoints.add(s)
        breakpoints.add(e)
        breakpoints.add(s - timedelta(hours=24))
        breakpoints.add(e - timedelta(hours=24))
    for t in breakpoints:
        w_end = t + timedelta(hours=24)
        total = 0.0
        for (s, e) in intervals:
            lo = max(s, t)
            hi = min(e, w_end)
            if lo < hi:
                total += (hi - lo).total_seconds()
        if total > cap_seconds:
            return True
    return False


# ---------------------------------------------------------------------------
# Staffing ratio (SCAFFOLD staffing_ratio)
# ---------------------------------------------------------------------------

def _segment_period(home, a, b):
    """OVERNIGHT if the segment overlaps 22:00-06:00 local at all, else DAY."""
    tz = home_tz(home)
    la = a.astimezone(tz)
    lb = b.astimezone(tz)
    days = {la.date(), lb.date(), la.date() - timedelta(days=1), la.date() + timedelta(days=1)}
    overnight = False
    for d in days:
        o_start = datetime(d.year, d.month, d.day, 22, 0, tzinfo=tz)
        o_end = o_start + timedelta(hours=8)  # next 06:00
        if la < o_end and o_start < lb:
            overnight = True
            break
    return "OVERNIGHT" if overnight else "DAY"


def _awake_qualified_count(covering):
    n = 0
    for s in covering:
        if s.get("overnight_mode") != "AWAKE":
            continue
        cg = db.caregivers.get(s["caregiver_id"])
        if cg is not None and cg.get("awake_overnight_qualified"):
            n += 1
    return n


def build_segments(home, shifts, win_start, win_end, include_uncovered=False):
    """Atomic half-open segments cut at every shift boundary plus the window
    edges, within [win_start, win_end). With include_uncovered, sub-segments
    of the window with zero covering shifts are emitted (non-compliant when
    census > 0); otherwise only covered spans produce segments."""
    pts = {win_start, win_end}
    for s in shifts:
        for t in (s["_start_dt"], s["_end_dt"]):
            if win_start < t < win_end:
                pts.add(t)
    pts = sorted(pts)
    segs = []
    census = home["current_census"]
    for a, b in zip(pts, pts[1:]):
        if a >= b:
            continue
        covering = [s for s in shifts if s["_start_dt"] <= a and s["_end_dt"] >= b]
        if not covering and not include_uncovered:
            continue  # gaps are not part of the union of shift intervals
        on_duty = len(covering)
        period = _segment_period(home, a, b)
        if period == "OVERNIGHT":
            req = math.ceil(census / 2) if census > 0 else 0
            awake_q = _awake_qualified_count(covering)
            compliant = (awake_q >= req) or (
                awake_q >= 1 and on_duty >= (math.ceil(census / 3) if census > 0 else 0))
        else:
            req = math.ceil(census / 4) if census > 0 else 0
            compliant = on_duty >= req
        segs.append({
            "start_at": fmt_ts(a),
            "end_at": fmt_ts(b),
            "period": period,
            "on_duty": on_duty,
            "required": req,
            "compliant": compliant,
        })
    return segs


def forward_staffing_ok(home, shifts, win_start, win_end):
    """Forward-window staffing validation for shift create/cancel: evaluates
    the affected shift's own window (clipped to [now, +inf)) against the
    post-change shift set; with census > 0 any under-covered sub-segment,
    including uncovered ones, makes the change NON_COMPLIANT."""
    census = home["current_census"]
    if census <= 0:
        return True
    clip = max(win_start, db.now())
    if win_end <= clip:
        return True
    segs = build_segments(home, shifts, clip, win_end, include_uncovered=True)
    return all(s["compliant"] for s in segs)


def scheduled_shifts(home_id, exclude_id=None, extra=None):
    out = [s for s in db.shifts.values()
           if s["home_id"] == home_id and s["status"] == "SCHEDULED" and s["id"] != exclude_id]
    if extra is not None:
        out.append(extra)
    return out


# ---------------------------------------------------------------------------
# Medication administration windows (SCAFFOLD med_admin_window)
# ---------------------------------------------------------------------------

def med_windows_for(home, order, around_dt):
    """All candidate windows [T-60, T+60) for the order's schedule_times on the
    local date of around_dt plus its neighbours (windows can straddle midnight)."""
    tz = home_tz(home)
    local = around_dt.astimezone(tz)
    days = [local.date() - timedelta(days=1), local.date(), local.date() + timedelta(days=1)]
    windows = []
    for d in days:
        for t in order["schedule_times"]:
            try:
                hh, mm = [int(x) for x in str(t).split(":")]
                start_local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
            except Exception:
                continue
            T = start_local.astimezone(timezone.utc)
            windows.append((T - timedelta(minutes=60), T + timedelta(minutes=60)))
    return windows


def med_window_ok(home, order, administered_at, outcome):
    """Returns (inside_any_window, is_duplicate). Duplicate = a prior
    GIVEN/SELF_ADMINISTERED log already exists in a containing window;
    REFUSED and HELD outcomes do not consume a window."""
    windows = med_windows_for(home, order, administered_at)
    containing = [(w0, w1) for (w0, w1) in windows if w0 <= administered_at < w1]
    if not containing:
        return False, False
    if outcome not in ("GIVEN", "SELF_ADMINISTERED"):
        return True, False
    dup = False
    for log in db.med_logs.values():
        if log["order_id"] != order["id"]:
            continue
        if log["outcome"] not in ("GIVEN", "SELF_ADMINISTERED"):
            continue
        la = log["_admin_dt"]
        for (w0, w1) in containing:
            if w0 <= la < w1:
                dup = True
                break
        if dup:
            break
    return True, dup


def caregiver_on_shift(home_id, caregiver_id, when):
    for s in db.shifts.values():
        if (s["caregiver_id"] == caregiver_id and s["home_id"] == home_id
                and s["status"] == "SCHEDULED"
                and s["_start_dt"] <= when < s["_end_dt"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Billing (SCAFFOLD invoice_window_*, medicaid_acuity_rate, late_fee)
# ---------------------------------------------------------------------------

def acuity_band(assessment):
    adl = assessment["adl_dependency_score"]
    nh = Decimal(str(assessment["nursing_hours_per_week"]))
    if adl <= 2 and nh < 5:
        return "LOW"
    if adl >= 5 or nh >= 15:
        return "HIGH"
    return "MEDIUM"


def latest_finalized_assessment(resident_id):
    cands = [a for a in db.assessments.values()
             if a["resident_id"] == resident_id and a["status"] == "FINALIZED"]
    if not cands:
        return None
    # Latest by assessed_at; tie-break earliest created_at.
    cands.sort(key=lambda a: (a["_assessed_dt"], -a["_seq"]))
    return cands[-1]


def find_rate_schedule(home_id, payer_type, day):
    for rs in db.rate_schedules.values():
        if rs["home_id"] != home_id or rs["payer_type"] != payer_type:
            continue
        if rs["_effective_from"] <= day and (rs["_effective_to"] is None or day < rs["_effective_to"]):
            return rs
    return None


def daily_rate_cents(schedule, payer_type, band, nursing_hours):
    rnb = schedule["room_and_board_daily_cents"]
    addon = {
        "LOW": schedule["care_low_daily_cents"],
        "MEDIUM": schedule["care_medium_daily_cents"],
        "HIGH": schedule["care_high_daily_cents"],
    }[band]
    if payer_type == "MEDICAID":
        nh = Decimal(str(nursing_hours))
        weekly = min(nh * Decimal(1500), Decimal(9000))
        nursing_component = int((weekly / Decimal(7)).quantize(Decimal("1"), rounding=ROUND_DOWN))
        daily = Decimal(rnb + addon + nursing_component)
    else:
        daily = Decimal(rnb + addon)
    return int(daily.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_invoice_lines(home, resident, period_start, period_end):
    """One line per occupied day in [period_start, period_end). Occupied:
    admitted_at <= day_end AND (discharged_at null OR discharged_at > day_start).
    Provisional vs final diverges naturally through discharged_at."""
    snap = resident["payer_type"]
    assessment = latest_finalized_assessment(resident["id"])
    if assessment is None:
        raise_err(ERR_INVALID_STATE, "resident has no FINALIZED assessment")
    band = acuity_band(assessment)
    nursing_hours = assessment["nursing_hours_per_week"]
    admitted = resident.get("_admitted_dt")
    discharged = resident.get("_discharged_dt")
    lines = []
    d = period_start
    while d < period_end:
        d_start = local_midnight(home, d)
        d_end = local_midnight(home, d + timedelta(days=1))
        occupied = (admitted is not None and admitted <= d_end
                    and (discharged is None or discharged > d_start))
        if occupied:
            sched = find_rate_schedule(home["id"], snap, d)
            if sched is None:
                raise_err(ERR_RATE_NOT_FOUND,
                          f"no rate schedule covers day {d.isoformat()}")
            price = daily_rate_cents(sched, snap, band, nursing_hours)
            lines.append({
                "day": d.isoformat(),
                "description": "room_and_board",
                "qty": 1,
                "unit_price_cents": price,
                "amount_cents": price,
            })
        d += timedelta(days=1)
    subtotal = sum(l["amount_cents"] for l in lines)
    return lines, subtotal


def compute_late_fee(home, subtotal_cents, due_date):
    """5% of subtotal, round_half_up, clamped [2500, 15000]; only when the
    home-local current date is strictly after due_date."""
    today = db.now().astimezone(home_tz(home)).date()
    if today > due_date:
        raw = (Decimal(subtotal_cents) * Decimal(5) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        return int(min(max(raw, Decimal(2500)), Decimal(15000)))
    return 0


def invoice_paid_cents(invoice_id):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["invoice_id"] == invoice_id)


# ---------------------------------------------------------------------------
# Discharge refund (SCAFFOLD discharge_refund — waterfall allocation)
# ---------------------------------------------------------------------------

def compute_discharge_refund(home, resident, discharged_dt):
    discharge_date = discharged_dt.astimezone(home_tz(home)).date()
    invoices = [i for i in db.invoices.values() if i["resident_id"] == resident["id"]]
    prepaid = 0
    for inv in invoices:
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "PAID"):
            continue
        paid = invoice_paid_cents(inv["id"])
        future_rnb = sum(
            l["amount_cents"] for l in inv["line_items"]
            if l.get("description") == "room_and_board"
            and parse_day(l.get("day")) is not None
            and parse_day(l["day"]) > discharge_date)
        prepaid += min(paid, future_rnb)
    outstanding = [i for i in invoices if i["status"] in ("ISSUED", "PARTIALLY_PAID")]
    outstanding.sort(key=lambda i: (i["period_start"], i["_seq"]))
    for inv in outstanding:
        if prepaid <= 0:
            break
        balance = inv["total_cents"] - invoice_paid_cents(inv["id"])
        take = min(prepaid, max(balance, 0))
        prepaid -= take
    return max(prepaid, 0)


def parse_day(s):
    from datetime import date
    try:
        return date.fromisoformat(s)
    except Exception:
        return None
