"""Domain logic: derived fields, counters, calculations, cascades, sweeps."""
from datetime import timedelta, datetime

import db
from util import logical_now, touch

S = db.STORE

UNION_THRESHOLD = 3
WINDOW_DAYS = 365
STANDARD_DAY_HOURS = 8


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find(name, rid):
    return S[name].get(rid)


def children(name, field, rid):
    return [r for r in S[name].values() if r.get(field) == rid]


# ---------------------------------------------------------------------------
# Derived talent fields
# ---------------------------------------------------------------------------

def compute_is_minor(talent, now=None):
    """Age at the current logical clock < 18 (PRD 3.3)."""
    now = now or logical_now()
    dob = talent["date_of_birth"]
    age = now.year - dob.year - ((now.month, now.day) < (dob.month, dob.day))
    return age < 18


def submission_talent_id(submission):
    return submission["talent_id"]


# ---------------------------------------------------------------------------
# Denormalized counters (PRD 2.9) -- recomputed set-level, not incrementally
# ---------------------------------------------------------------------------

def recompute_active_breakdown_count(production, bump=True):
    count = sum(1 for b in S["breakdowns"].values()
                if b["production_id"] == production["id"]
                and b["status"] in ("RELEASED_AGENT_ONLY", "RELEASED_OPEN"))
    if production.get("active_breakdown_count") != count:
        production["active_breakdown_count"] = count
    if bump:
        touch(production)


def recompute_submission_count(breakdown, bump=True):
    count = sum(1 for s in S["submissions"].values()
                if s["breakdown_id"] == breakdown["id"] and s["status"] != "WITHDRAWN")
    if breakdown.get("submission_count") != count:
        breakdown["submission_count"] = count
    if bump:
        touch(breakdown)


def recompute_booked_count(session, bump=True):
    count = sum(1 for a in S["appointments"].values()
                if a["session_id"] == session["id"]
                and a["status"] == "CONFIRMED" and not a.get("_completed"))
    if session.get("booked_count") != count:
        session["booked_count"] = count
    if bump:
        touch(session)


def recompute_union_count(talent):
    """Rolling 365-day count of CONFIRMED union-covered bookings (PRD 3.9).
    Window is INCLUSIVE at both ends: [clock - 365d, clock]."""
    now = logical_now()
    window_start = now - timedelta(days=WINDOW_DAYS)
    count = 0
    for b in S["bookings"].values():
        if b["status"] != "CONFIRMED":
            continue
        sub = find("submissions", b["submission_id"])
        if not sub or sub["talent_id"] != talent["id"]:
            continue
        memo = find("deal_memos", b["deal_memo_id"])
        if not memo:
            continue
        if not (window_start <= memo["engagement_start"] <= now):
            continue
        bd = find("breakdowns", sub["breakdown_id"])
        role = find("roles", bd["role_id"]) if bd else None
        if role and role.get("is_union_covered"):
            count += 1
    changed = talent.get("union_engagement_count_365d") != count
    talent["union_engagement_count_365d"] = count
    if talent.get("union_status") == "NON_UNION" and count >= UNION_THRESHOLD:
        talent["union_status"] = "ELIGIBLE_PENDING"
        changed = True
    if changed:
        touch(talent)


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

def engagement_fee_proration(weekly_rate_cents, engagement_start, engagement_end, proration_mode):
    """daily = weekly // 5 (floor BEFORE multiply); span inclusive both ends;
    CALENDAR_SPAN counts all days, WORKDAY_SPAN counts Mon-Fri only."""
    daily_rate = weekly_rate_cents // 5
    start_d = engagement_start.date()
    end_d = engagement_end.date()
    days = 0
    d = start_d
    while d <= end_d:
        if proration_mode == "CALENDAR_SPAN" or d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return daily_rate * days


def cancellation_penalty_tier(booking, now=None):
    """guarantee * tier_pct / 100; days_out = whole days from clock date to
    engagement_start, clamped >= 0; tiers inclusive at lower bound."""
    now = now or logical_now()
    memo = find("deal_memos", booking["deal_memo_id"])
    offer = find("offers", memo["offer_id"]) if memo else None
    guarantee = offer["guarantee_cents"] if offer else 0
    days_out = (memo["engagement_start"].date() - now.date()).days
    if days_out < 0:
        days_out = 0
    if days_out >= 14:
        pct = 0
    elif days_out >= 7:
        pct = 25
    elif days_out >= 3:
        pct = 50
    else:
        pct = 100
    return (guarantee * pct) // 100


def appointment_conflicts(new_appt, talent_id):
    """Half-open intervals; only the NEW appointment's buffer extends its tail.
    Existing appointment's own buffer is ignored. Adjacency is not a conflict."""
    new_eff_end = new_appt["slot_end"] + timedelta(minutes=new_appt.get("buffer_minutes", 0))
    for a in S["appointments"].values():
        if a["id"] == new_appt["id"]:
            continue
        if a["status"] != "CONFIRMED" or a.get("_completed"):
            continue
        sub = find("submissions", a["submission_id"])
        if not sub or sub["talent_id"] != talent_id:
            continue
        if a["slot_start"] < new_eff_end and new_appt["slot_start"] < a["slot_end"]:
            return True
    return False


def hold_outranking_candidates(hold):
    """ACTIVE holds of the same talent with overlapping half-open windows."""
    cands = []
    for h in S["holds"].values():
        if h["id"] == hold["id"] or h["status"] != "ACTIVE":
            continue
        if h["talent_id"] != hold["talent_id"]:
            continue
        if h["window_start"] < hold["window_end"] and hold["window_start"] < h["window_end"]:
            cands.append(h)
    return cands


def hold_is_outranked(hold, candidates):
    """Blocked iff any candidate has strictly lower priority_rank, or equal
    rank with earlier created_at (ms precision; _seq breaks exact ties)."""
    for c in candidates:
        if c["priority_rank"] < hold["priority_rank"]:
            return True
        if c["priority_rank"] == hold["priority_rank"]:
            if (c["created_at"], c["_seq"]) < (hold["created_at"], hold["_seq"]):
                return True
    return False


def minor_hours_exceeded(permit, engagement_start, engagement_end):
    """8 requested hours per engagement day vs school/non-school caps.
    School day = Mon-Fri (holidays/hiatus not modelled)."""
    if permit is None:
        return False
    d = engagement_start.date()
    end_d = engagement_end.date()
    while d <= end_d:
        if d.weekday() < 5:
            cap = permit["max_daily_hours_school_day"]
        else:
            cap = permit["max_daily_hours_non_school_day"]
        if STANDARD_DAY_HOURS > cap:
            return True
        d += timedelta(days=1)
    return False


def permit_covers(talent_id, production_id, engagement_end):
    """A VERIFIED permit for (talent, production) with valid_until reaching at
    least the engagement's final day."""
    for p in S["permits"].values():
        if p["talent_id"] != talent_id or p["production_id"] != production_id:
            continue
        if p["status"] != "VERIFIED":
            continue
        if engagement_end is None or p["valid_until"] >= engagement_end:
            return p
    return None


# ---------------------------------------------------------------------------
# Cascades shared across endpoints
# ---------------------------------------------------------------------------

def release_active_holds_on_submission(submission_id, kinds=("ACTIVE",)):
    for h in S["holds"].values():
        if h["submission_id"] == submission_id and h["status"] in kinds:
            h["status"] = "RELEASED"
            touch(h)


def revert_submission_if_no_active_appointments(submission):
    """CALLBACK_INVITED -> UNDER_REVIEW when no PROPOSED/CONFIRMED (and not
    individually completed) appointment remains."""
    if submission["status"] != "CALLBACK_INVITED":
        return
    remaining = [a for a in S["appointments"].values()
                 if a["submission_id"] == submission["id"]
                 and a["status"] in ("PROPOSED", "CONFIRMED")
                 and not a.get("_completed")]
    if not remaining:
        submission["status"] = "UNDER_REVIEW"
        touch(submission)


def maybe_auto_taft_hartley(booking):
    """Auto-create a PENDING report when production is union-signatory, the
    role is union-covered, and the talent is NON_UNION."""
    sub = find("submissions", booking["submission_id"])
    bd = find("breakdowns", sub["breakdown_id"])
    role = find("roles", bd["role_id"])
    production = find("productions", bd["production_id"])
    talent = find("talents", sub["talent_id"])
    if not (production.get("union_signatory") and role.get("is_union_covered")
            and talent.get("union_status") == "NON_UNION"):
        return None
    from util import new_record
    deadline = booking["confirmed_at"] + timedelta(days=15)
    rep = new_record({
        "production_id": production["id"],
        "talent_id": talent["id"],
        "booking_id": booking["id"],
        "reason_code": "FIRST_EMPLOYMENT",
        "filing_deadline": deadline,
        "filed_at": None,
        "status": "PENDING",
    })
    S["taft_hartley_reports"][rep["id"]] = rep
    return rep


def waive_pending_reports_for_booking(booking_id):
    for rep in S["taft_hartley_reports"].values():
        if rep["booking_id"] == booking_id and rep["status"] == "PENDING":
            rep["status"] = "WAIVED"
            touch(rep)


def cancel_booking_record(booking, reason, compute_penalty):
    """Shared cancellation mechanics used by booking cancel, deal-memo void,
    and permit lapse/revoke cascades."""
    now = logical_now()
    booking["status"] = "CANCELLED"
    booking["cancelled_at"] = now
    booking["cancellation_reason"] = reason
    touch(booking)
    memo = find("deal_memos", booking["deal_memo_id"])
    if memo is not None:
        if compute_penalty:
            memo["cancellation_penalty_cents"] = cancellation_penalty_tier(booking, now)
            touch(memo)
        else:
            if memo.get("cancellation_penalty_cents") != 0:
                memo["cancellation_penalty_cents"] = 0
    waive_pending_reports_for_booking(booking["id"])
    sub = find("submissions", booking["submission_id"])
    if sub is not None:
        talent = find("talents", sub["talent_id"])
        if talent is not None:
            recompute_union_count(talent)
