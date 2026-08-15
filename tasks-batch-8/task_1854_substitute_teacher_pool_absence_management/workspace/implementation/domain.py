"""Business logic: selector, cascades, calculations, reliability, payroll.

Every rule here is pinned to PRD.md section 3 and SCAFFOLD.yaml sections
1.2 (state machines), 1.3 (calculations) and 1.4 (validation pipeline).
"""

from datetime import timedelta
from decimal import Decimal

import db
from db import STORE, new_entity, touch, now, now_iso, public
from util import (
    parse_date, parse_datetime, weekday_count, is_next_workday,
    ranges_overlap, rhu, dec, midnight_utc, iso_week_bounds,
)

REQUIRED_CLEARANCE_TYPES = ("BACKGROUND_CHECK", "TEACHING_CREDENTIAL")

EVENT_DELTAS = {
    "COMPLETION": 1,
    "SUB_CANCEL_EARLY": -5,
    "SUB_CANCEL_LATE": -15,
    "NO_SHOW": -25,
    "FLAG_MINOR": -3,
    "FLAG_MAJOR": -10,
}

COMMITTED_STATUSES = ("ACCEPTED", "WORKED", "VERIFIED")  # budget reserve legs
LIVE_OFFER_STATUSES = ("OFFERED", "ACCEPTED")


# ---------------------------------------------------------------------------
# Navigation helpers
# ---------------------------------------------------------------------------

def absence_school(absence):
    return STORE.schools.get(absence["school_id"])


def absence_district(absence):
    school = absence_school(absence)
    return STORE.districts.get(school["district_id"]) if school else None


def assignment_absence(asg):
    return STORE.absences.get(asg["absence_id"])


def assignment_district(asg):
    absence = assignment_absence(asg)
    return absence_district(absence) if absence else None


def school_district(school):
    return STORE.districts.get(school["district_id"])


def budget_available(school):
    return (school["coverage_budget_total_cents"]
            - school["coverage_budget_committed_cents"]
            - school["coverage_budget_spent_cents"])


# ---------------------------------------------------------------------------
# Clearances: lazy expiry
# ---------------------------------------------------------------------------

def refresh_clearance(c):
    """Flip PENDING/VERIFIED -> EXPIRED once the clock date passes expires_on.
    Flip-only; cascade contexts (batch, activation, clock jump) handle the
    suspension consequence separately."""
    if c["status"] in ("PENDING", "VERIFIED"):
        exp = parse_date(c["expires_on"])
        if exp is not None and now().date() > exp:
            c["status"] = "EXPIRED"
            touch(c)
            return True
    return False


def required_clearances_valid(sub_id, through_date):
    """Both required clearances VERIFIED with expires_on >= through_date.
    Reads apply lazy flip-only expiry."""
    for ctype in REQUIRED_CLEARANCE_TYPES:
        ok = False
        for c in STORE.clearances.values():
            if c["substitute_id"] != sub_id or c["clearance_type"] != ctype:
                continue
            refresh_clearance(c)
            if c["status"] == "VERIFIED" and parse_date(c["expires_on"]) >= through_date:
                ok = True
                break
        if not ok:
            return False
    return True


def expire_clearances_with_cascade():
    """Clock-driven expiry (dispatch batch / forward clock jump): flip every
    stale clearance; when a required clearance of an ACTIVE substitute
    expires, suspend with the full cascade."""
    for c in sorted(STORE.clearances.values(), key=lambda x: x["_seq"]):
        if c["status"] in ("PENDING", "VERIFIED"):
            exp = parse_date(c["expires_on"])
            if exp is not None and now().date() > exp:
                c["status"] = "EXPIRED"
                touch(c)
                if c["clearance_type"] in REQUIRED_CLEARANCE_TYPES:
                    sub = STORE.substitutes.get(c["substitute_id"])
                    if sub is not None and sub["status"] == "ACTIVE":
                        suspend_substitute(sub)


# ---------------------------------------------------------------------------
# Reliability scores and suspension (PRD 2.10)
# ---------------------------------------------------------------------------

def _event_dt(ev):
    return parse_datetime(ev["occurred_at"])


def recompute_scores(sub, district=None):
    """Recompute lifetime/trailing scores and completion counters.
    Trailing window: occurred_at >= clock - district.reliability_window_days."""
    window = district["reliability_window_days"] if district else 90
    cutoff = now() - timedelta(days=window)
    lifetime = 100
    trailing = 100
    comp_lifetime = 0
    comp_trailing = 0
    for ev in sub["reliability_events"]:
        delta = ev["delta"]
        lifetime += delta
        in_window = _event_dt(ev) >= cutoff
        if in_window:
            trailing += delta
        if ev["event_type"] == "COMPLETION":
            comp_lifetime += 1
            if in_window:
                comp_trailing += 1
    sub["reliability_lifetime_score"] = max(0, min(100, lifetime))
    sub["reliability_trailing_score"] = max(0, min(100, trailing))
    sub["completions_lifetime"] = comp_lifetime
    sub["completions_trailing"] = comp_trailing


def refresh_substitute_scores(sub):
    """Lazy recompute on read: events age out of the trailing window as the
    clock advances. Uses the district context of the latest event (single-
    district deployments are exact); defaults to the 90-day window."""
    district = None
    if sub["reliability_events"]:
        last = sub["reliability_events"][-1]
        district = STORE.districts.get(last.get("_district_id"))
    elif len(STORE.districts) == 1:
        district = next(iter(STORE.districts.values()))
    recompute_scores(sub, district)


def append_event(sub, event_type, assignment_id=None, district=None):
    ev = {
        "event_type": event_type,
        "delta": EVENT_DELTAS[event_type],
        "occurred_at": now_iso(),
    }
    if assignment_id is not None:
        ev["assignment_id"] = assignment_id
    ev["_district_id"] = district["id"] if district else None
    sub["reliability_events"].append(ev)
    recompute_scores(sub, district)
    touch(sub)
    evaluate_suspension(sub, district)


def evaluate_suspension(sub, district):
    """ACTIVE substitute with trailing score STRICTLY below threshold and at
    least the minimum trailing completions is auto-suspended."""
    if district is None:
        return
    if (sub["status"] == "ACTIVE"
            and sub["reliability_trailing_score"] < district["suspension_score_threshold"]
            and sub["completions_trailing"] >= district["suspension_min_completions"]):
        suspend_substitute(sub)


def suspend_substitute(sub):
    """Full suspension cascade (PRD 3.2): OFFERED and ACCEPTED assignments
    are cancelled with SUSPENSION_CANCEL and no reliability penalty; their
    absences stay in / return to DISPATCHING and re-run the selector."""
    sub["status"] = "SUSPENDED"
    touch(sub)
    own = [a for a in sorted(STORE.assignments.values(), key=lambda x: x["_seq"])
           if a["substitute_id"] == sub["id"] and a["status"] in ("OFFERED", "ACCEPTED")]
    for asg in own:
        cancel_assignment(asg, "SUSPENSION_CANCEL", reliability_event=None)


# ---------------------------------------------------------------------------
# Premium pay (PRD 3.4) and final payout (PRD 3.5)
# ---------------------------------------------------------------------------

def premium_multiplier(absence, school, district):
    """lead_hours measured from the clock to midnight UTC of the first
    absence day (may be negative). Snapshot = min(1 + htf + notice, cap),
    exact to two decimal places by construction."""
    start_midnight = midnight_utc(parse_date(absence["start_date"]))
    lead = Decimal(str((start_midnight - now()).total_seconds())) / Decimal(3600)
    tier = school["hard_to_fill_tier"]
    if tier == "HIGH":
        htf = dec(district["htf_high_premium_pct"])
    elif tier == "MODERATE":
        htf = dec(district["htf_moderate_premium_pct"])
    else:
        htf = Decimal("0")
    if lead < dec(district["short_notice_hours"]):
        notice = dec(district["short_notice_premium_pct"])
    elif lead < dec(district["moderate_notice_hours"]):
        notice = dec(district["moderate_notice_premium_pct"])
    else:
        notice = Decimal("0")
    mult = Decimal("1") + htf + notice
    cap = dec(district["premium_cap_multiplier"])
    return min(mult, cap)


def provisional_pay(sub, scheduled_days, multiplier):
    """scheduled_days * round_half_up(base_daily_rate_cents * multiplier):
    one single rounding per assignment at offer time."""
    return scheduled_days * rhu(dec(sub["base_daily_rate_cents"]) * dec(multiplier))


def recompute_streaks(asg):
    """Full chronological recompute over the assignment's APPROVED
    timesheets: streak_index, per-day rounded day_pay_cents,
    worked_days_count, long_term_converted."""
    sub = STORE.substitutes[asg["substitute_id"]]
    district = assignment_district(asg)
    base = dec(sub["base_daily_rate_cents"])
    threshold = district["long_term_threshold_days"]
    lt_mult = dec(district["long_term_rate_multiplier"])
    prem_mult = dec(asg["premium_multiplier_snapshot"])
    sheets = sorted(
        (t for t in STORE.timesheets.values()
         if t["assignment_id"] == asg["id"] and t["status"] == "APPROVED"),
        key=lambda t: parse_date(t["work_date"]),
    )
    prev = None
    streak = 0
    converted = False
    for s in sheets:
        d = parse_date(s["work_date"])
        if prev is not None and is_next_workday(prev, d):
            streak += 1
        else:
            streak = 1
        mult = lt_mult if streak >= threshold else prem_mult
        day_pay = rhu(base * mult)
        if s.get("streak_index") != streak or s.get("day_pay_cents") != day_pay:
            s["streak_index"] = streak
            s["day_pay_cents"] = day_pay
            touch(s)
        if streak >= threshold:
            converted = True
        prev = d
    if asg["worked_days_count"] != len(sheets) or asg["long_term_converted"] != converted:
        asg["worked_days_count"] = len(sheets)
        asg["long_term_converted"] = converted
        touch(asg)


def compute_final_payout(asg):
    """Sum of per-day rounded day_pay_cents over APPROVED sheets
    (per-day-then-sum is authoritative)."""
    recompute_streaks(asg)
    return sum(
        t["day_pay_cents"] for t in STORE.timesheets.values()
        if t["assignment_id"] == asg["id"] and t["status"] == "APPROVED"
    )


# ---------------------------------------------------------------------------
# Absence day counters (conservation invariant, PRD 3.6)
# ---------------------------------------------------------------------------

def recompute_day_counters(absence, touch_absence=True):
    internal_dates = set()
    for c in STORE.coverages.values():
        if c["absence_id"] == absence["id"] and c["status"] in ("APPROVED", "WORKED", "COMPENSATED"):
            internal_dates.add(c["coverage_date"])
    absence["days_covered_internal"] = len(internal_dates)
    sub_days = 0
    for a in STORE.assignments.values():
        if a["absence_id"] == absence["id"] and a["status"] in ("VERIFIED", "PAID"):
            sub_days = a["worked_days_count"]
            break
    absence["days_covered_sub"] = sub_days
    absence["days_uncovered"] = (absence["total_days"]
                                 - absence["days_covered_internal"] - sub_days)
    if touch_absence:
        touch(absence)


# ---------------------------------------------------------------------------
# Dispatch selector (PRD 2.11) and offers (PRD 3.4)
# ---------------------------------------------------------------------------

def active_mark(school_id, substitute_id, mark_type):
    for m in STORE.marks.values():
        if (m["school_id"] == school_id and m["substitute_id"] == substitute_id
                and m["mark_type"] == mark_type and m["status"] == "ACTIVE"):
            return m
    return None


def has_qualification(sub_id, subject, grade_band):
    for q in STORE.qualifications.values():
        if (q["substitute_id"] == sub_id and q["subject"] == subject
                and q["grade_band"] == grade_band):
            return True
    return False


def substitute_assignments(sub_id, statuses):
    return [a for a in STORE.assignments.values()
            if a["substitute_id"] == sub_id and a["status"] in statuses]


def has_assignment_overlap(sub_id, start, end, exclude_assignment_id=None):
    """Any ACCEPTED/WORKED/VERIFIED assignment whose date range intersects
    [start, end]; adjacent ranges permitted."""
    for a in substitute_assignments(sub_id, COMMITTED_STATUSES):
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if ranges_overlap(parse_date(a["start_date"]), parse_date(a["end_date"]), start, end):
            return True
    return False


def existing_assignment_for(absence_id, sub_id, statuses):
    for a in STORE.assignments.values():
        if a["absence_id"] == absence_id and a["substitute_id"] == sub_id and a["status"] in statuses:
            return a
    return None


def selector_eligible(sub, absence, school, district):
    """The full eligibility filter of PRD 2.11."""
    if sub["status"] != "ACTIVE":
        return False
    if not has_qualification(sub["id"], absence["required_subject"], absence["required_grade_band"]):
        return False
    if not required_clearances_valid(sub["id"], parse_date(absence["end_date"])):
        return False
    if active_mark(absence["school_id"], sub["id"], "DO_NOT_RETURN"):
        return False
    if has_assignment_overlap(sub["id"], parse_date(absence["start_date"]), parse_date(absence["end_date"])):
        return False
    if existing_assignment_for(absence["id"], sub["id"], LIVE_OFFER_STATUSES):
        return False
    if existing_assignment_for(absence["id"], sub["id"], ("DECLINED", "EXPIRED")):
        return False  # no-re-offer rule
    return True


def rank_score(sub, absence, district):
    score = sub["reliability_trailing_score"]
    if active_mark(absence["school_id"], sub["id"], "PREFERRED"):
        score += district["preference_rank_boost"]
    return score


def run_selector(absence, exclude_ids=(), batch_counter=None):
    """Pick the single best eligible substitute and create an OFFERED
    assignment (AUTO_DISPATCH). Empty pool -> no offer, absence stays
    DISPATCHING. Returns the created assignment or None."""
    school = absence_school(absence)
    district = absence_district(absence)
    best = None
    for sub in sorted(STORE.substitutes.values(), key=lambda s: s["_seq"]):
        if sub["id"] in exclude_ids:
            continue
        refresh_substitute_scores(sub)
        if not selector_eligible(sub, absence, school, district):
            continue
        score = rank_score(sub, absence, district)
        key = (-score, sub["_seq"])  # rank DESC, tie -> earliest registered
        if best is None or key < best[0]:
            best = (key, sub)
    if best is None:
        return None
    asg = create_offer(absence, best[1], "AUTO_DISPATCH")
    if batch_counter is not None:
        batch_counter["created"] += 1
    return asg


def create_offer(absence, sub, source):
    """Offer-time snapshots: offered_at/expires_at from the logical clock,
    start/end dates, scheduled weekday count, premium snapshot, provisional
    pay with a single round-half-up."""
    school = absence_school(absence)
    district = absence_district(absence)
    seqs = [a["offer_sequence"] for a in STORE.assignments.values()
            if a["absence_id"] == absence["id"]]
    offer_sequence = (max(seqs) + 1) if seqs else 1
    scheduled = weekday_count(parse_date(absence["start_date"]), parse_date(absence["end_date"]))
    mult = premium_multiplier(absence, school, district)
    prov = provisional_pay(sub, scheduled, mult)
    offered_at = now()
    expires_at = offered_at + timedelta(minutes=district["offer_response_window_minutes"])
    return new_entity(STORE.assignments, {
        "absence_id": absence["id"],
        "substitute_id": sub["id"],
        "school_id": absence["school_id"],
        "offer_source": source,
        "offer_sequence": offer_sequence,
        "status": "OFFERED",
        "cancel_reason": None,
        "offered_at": db.iso(offered_at),
        "offer_expires_at": db.iso(expires_at),
        "start_date": absence["start_date"],
        "end_date": absence["end_date"],
        "scheduled_days": scheduled,
        "premium_multiplier_snapshot": float(mult),
        "provisional_pay_cents": prov,
        "worked_days_count": 0,
        "long_term_converted": False,
        "final_payout_cents": None,
        "payout_capped": False,
    })


def redispatch(absence, exclude_ids=(), batch_counter=None):
    """Re-run the selector for a DISPATCHING absence."""
    if absence["fill_status"] == "DISPATCHING":
        run_selector(absence, exclude_ids=exclude_ids, batch_counter=batch_counter)


# ---------------------------------------------------------------------------
# Assignment cancellation (PRD 3.5) and the DNR cascade (PRD 3.8)
# ---------------------------------------------------------------------------

def cancel_assignment(asg, reason, reliability_event=None, district=None,
                      exclude_from_redispatch=()):
    """Pinned cancel_reason by actor/cause; system cancels carry no
    reliability penalty. ACCEPTED cancels release the provisional reserve,
    reopen the absence ASSIGNED -> DISPATCHING and re-run the selector."""
    was_accepted = asg["status"] == "ACCEPTED"
    asg["status"] = "CANCELLED"
    asg["cancel_reason"] = reason
    touch(asg)
    absence = assignment_absence(asg)
    if was_accepted:
        school = STORE.schools[asg["school_id"]]
        school["coverage_budget_committed_cents"] -= asg["provisional_pay_cents"]
        touch(school)
        if reliability_event is not None:
            sub = STORE.substitutes[asg["substitute_id"]]
            append_event(sub, reliability_event, assignment_id=asg["id"], district=district)
        if absence["fill_status"] == "ASSIGNED":
            absence["fill_status"] = "DISPATCHING"
            touch(absence)
        redispatch(absence, exclude_ids=exclude_from_redispatch)


def dnr_cascade(school_id, sub_id):
    """Future-dated (end_date >= clock date) OFFERED and ACCEPTED assignments
    of the substitute at this school -> CANCELLED (DNR_CANCEL, no penalty);
    cancelled ACCEPTED absences reopen and re-run the selector (the marked
    substitute is now ineligible)."""
    today = now().date()
    targets = [a for a in sorted(STORE.assignments.values(), key=lambda x: x["_seq"])
               if a["school_id"] == school_id and a["substitute_id"] == sub_id
               and a["status"] in ("OFFERED", "ACCEPTED")
               and parse_date(a["end_date"]) >= today]
    for asg in targets:
        cancel_assignment(asg, "DNR_CANCEL", exclude_from_redispatch=(sub_id,))


# ---------------------------------------------------------------------------
# Dispatch batch (PRD 3.4)
# ---------------------------------------------------------------------------

def expire_offers(batch_counter=None):
    """Every offer whose expiry instant has been reached flips OFFERED ->
    EXPIRED, triggering the same re-dispatch cascade as a decline."""
    for asg in sorted(STORE.assignments.values(), key=lambda x: x["_seq"]):
        if asg["status"] != "OFFERED":
            continue
        if parse_datetime(asg["offer_expires_at"]) <= now():
            asg["status"] = "EXPIRED"
            touch(asg)
            if batch_counter is not None:
                batch_counter["expired"] += 1
            absence = assignment_absence(asg)
            redispatch(absence, batch_counter=batch_counter)


def run_dispatch_batch(district, run_date):
    """One batch = expire stale offers, pick-up, cutoff sweep, clearance
    expiry with suspension cascade. Pick-up runs before the cutoff sweep so
    an absence whose pool is empty is marked UNFILLED in the same run."""
    counter = {"considered": 0, "created": 0, "expired": 0, "unfilled": 0}
    considered_ids = set()
    expire_offers(counter)
    district_absences = sorted(
        (a for a in STORE.absences.values()
         if absence_district(a) and absence_district(a)["id"] == district["id"]),
        key=lambda a: a["_seq"])
    # Pick-up: eligible REPORTED / UNFILLED absences move to DISPATCHING and
    # run the selector; at most one offer per absence per batch.
    for absence in district_absences:
        if absence["fill_status"] not in ("REPORTED", "UNFILLED"):
            continue
        considered_ids.add(absence["id"])
        if absence["approval_status"] in ("PENDING", "REJECTED"):
            continue
        if parse_date(absence["end_date"]) < now().date():
            continue  # pick-up guard reads the clock date, not the run date
        if absence["days_covered_internal"] != 0:
            continue
        absence["fill_status"] = "DISPATCHING"
        touch(absence)
        run_selector(absence, batch_counter=counter)
    # Cutoff sweep: DISPATCHING, start_date <= run date, no committed
    # assignment, no live offer -> UNFILLED.
    for absence in district_absences:
        if absence["fill_status"] != "DISPATCHING":
            continue
        considered_ids.add(absence["id"])
        if parse_date(absence["start_date"]) > run_date:
            continue
        has_committed = any(
            a["absence_id"] == absence["id"] and a["status"] in COMMITTED_STATUSES
            for a in STORE.assignments.values())
        has_live = any(
            a["absence_id"] == absence["id"] and a["status"] == "OFFERED"
            for a in STORE.assignments.values())
        if not has_committed and not has_live:
            absence["fill_status"] = "UNFILLED"
            touch(absence)
            counter["unfilled"] += 1
    # Clearance expiry with suspension cascade.
    expire_clearances_with_cascade()
    counter["considered"] = len(considered_ids)
    return counter


def flip_stale_clearances():
    """Flip-only expiry (clock jumps, non-batch validations): stale
    PENDING/VERIFIED clearances become EXPIRED with no suspension cascade."""
    for c in sorted(STORE.clearances.values(), key=lambda x: x["_seq"]):
        refresh_clearance(c)


# ---------------------------------------------------------------------------
# Coverage capacity (PRD 3.6)
# ---------------------------------------------------------------------------

def coverage_capacity_ok(staff_member_id, coverage_date, extra_periods, district,
                         exclude_coverage_id=None):
    """Sum of periods over PROPOSED/APPROVED/WORKED/COMPENSATED coverages on
    the same date <= daily cap, and over the ISO week (Mon-Sun) <= weekly cap."""
    day_total = 0
    week_total = 0
    week_start, week_end = iso_week_bounds(coverage_date)
    for c in STORE.coverages.values():
        if c["staff_member_id"] != staff_member_id:
            continue
        if exclude_coverage_id and c["id"] == exclude_coverage_id:
            continue
        if c["status"] not in ("PROPOSED", "APPROVED", "WORKED", "COMPENSATED"):
            continue
        d = parse_date(c["coverage_date"])
        if d == coverage_date:
            day_total += c["periods"]
        if week_start <= d <= week_end:
            week_total += c["periods"]
    if day_total + extra_periods > district["daily_period_cap"]:
        return False
    if week_total + extra_periods > district["weekly_period_cap"]:
        return False
    return True


# ---------------------------------------------------------------------------
# Payroll waterfall (PRD 3.7)
# ---------------------------------------------------------------------------

def export_payroll_period(period):
    district_id = period["district_id"]
    p_start = parse_date(period["period_start"])
    p_end = parse_date(period["period_end"])

    def in_district(absence):
        d = absence_district(absence)
        return d is not None and d["id"] == district_id

    total_payout = 0
    paid_count = 0
    compensated_count = 0

    in_scope = sorted(
        (a for a in STORE.assignments.values()
         if a["status"] == "VERIFIED"
         and in_district(assignment_absence(a))
         and p_start <= parse_date(assignment_absence(a)["end_date"]) <= p_end),
        key=lambda a: (a["created_at"], a["_seq"]))
    for asg in in_scope:
        school = STORE.schools[asg["school_id"]]
        # 1. release the provisional reserve
        school["coverage_budget_committed_cents"] -= asg["provisional_pay_cents"]
        # 2. charge clamped to what remains available
        available = budget_available(school)
        charge = max(0, min(asg["final_payout_cents"], available))
        # 3. spend; final_payout stays uncapped, payout_capped records shortfall
        school["coverage_budget_spent_cents"] += charge
        touch(school)
        asg["payout_capped"] = charge < asg["final_payout_cents"]
        # 4. pay the assignment and export its approved timesheets
        asg["status"] = "PAID"
        touch(asg)
        for t in sorted(STORE.timesheets.values(), key=lambda x: x["_seq"]):
            if t["assignment_id"] == asg["id"] and t["status"] == "APPROVED":
                t["status"] = "EXPORTED"
                t["payroll_period_id"] = period["id"]
                touch(t)
        absence = assignment_absence(asg)
        if absence["fill_status"] == "COMPLETED":
            absence["fill_status"] = "CLOSED"
            touch(absence)
        total_payout += charge
        paid_count += 1

    coverages = sorted(
        (c for c in STORE.coverages.values()
         if c["status"] == "WORKED"
         and in_district(STORE.absences[c["absence_id"]])
         and p_start <= parse_date(c["coverage_date"]) <= p_end),
        key=lambda c: (c["created_at"], c["_seq"]))
    for cov in coverages:
        school = STORE.schools[cov["school_id"]]
        school["coverage_budget_spent_cents"] += cov["compensation_cents"]  # never capped
        touch(school)
        cov["status"] = "COMPENSATED"
        touch(cov)
        total_payout += cov["compensation_cents"]
        compensated_count += 1

    period["total_payout_cents"] = total_payout
    period["assignments_paid_count"] = paid_count
    period["coverages_compensated_count"] = compensated_count
    period["exported_at"] = now_iso()
    period["status"] = "EXPORTED"
    touch(period)
