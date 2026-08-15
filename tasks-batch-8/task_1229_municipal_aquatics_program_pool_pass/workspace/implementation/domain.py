"""Business logic: calculations, state transitions, cascades, clock re-evaluation.

Implements SCAFFOLD §1.2 state machines, §1.3 calculations, and PRD §3 workflows.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import store

# --- calculation constants (SCAFFOLD §1.3) ---------------------------------
CHILD_MULTIPLIER = Decimal("0.60")
SENIOR_MULTIPLIER = Decimal("0.75")
EARLY_BIRD_DISCOUNT_PCT = Decimal("0.10")  # PRD names the window, not the rate
EARLY_BIRD_DAYS = 7

RENTAL_BASE_PER_HOUR_CENTS = 15000
NON_RESIDENT_RENTAL_MULTIPLIER = Decimal("1.50")
INCLUDED_PARTY_SIZE = 25
EXTRA_PERSON_CENTS = 300
OVERTIME_PER_15MIN_CENTS = 5000

BATHERS_PER_ADDITIONAL_GUARD = 25

FC_MIN, FC_MAX = 1.0, 5.0
PH_MIN, PH_MAX = 7.2, 7.8
CC_WARN = 0.4

FULL_REFUND_ELAPSED_MIN = 60
PRO_RATA_FRACTION = Decimal("0.50")

CANCEL_FEE_FRACTION = Decimal("0.25")
CANCEL_FEE_WINDOW_HOURS = 72

BAN_DAYS_PER_MAJOR = 30

CLOSED_STATUSES = {"CLOSED_CHEMISTRY", "CLOSED_WEATHER", "CLOSED_STAFFING", "CLOSED_SEASON"}
REOPENABLE_STATUSES = {"CLOSED_CHEMISTRY", "CLOSED_WEATHER", "CLOSED_STAFFING"}


# ---------------------------------------------------------------------------
# Facility derived fields
# ---------------------------------------------------------------------------
def recompute_required_lifeguards(fac):
    """SCAFFOLD calc bather_load_staffing_requirement (incl. RESTRICTED +1 margin)."""
    count = fac["current_bather_count"]
    if count == 0:
        required = 0
    elif count <= 50:
        required = 2
    else:
        excess = count - 50
        required = 2 + -(-excess // BATHERS_PER_ADDITIONAL_GUARD)  # ceil
    if fac["operational_status"] == "RESTRICTED":
        required += 1
    fac["required_lifeguard_count"] = required


def change_bather_count(fac, delta):
    fac["current_bather_count"] += delta
    recompute_required_lifeguards(fac)
    store.touch(fac)


def scheduled_guard_count(facility_id, window_start, window_end):
    """Shifts in SCHEDULED or COVERED overlapping [window_start, window_end)."""
    n = 0
    for s in store.shifts.values():
        if s["facility_id"] != facility_id:
            continue
        if s["status"] not in ("SCHEDULED", "COVERED"):
            continue
        if s["_shift_start"] < window_end and s["_shift_end"] > window_start:
            n += 1
    return n


def evaluate_staffing_closure(fac):
    """CLOSED_STAFFING when a shift change leaves coverage below requirement."""
    if fac["operational_status"] not in ("OPEN", "RESTRICTED"):
        return
    if fac["current_bather_count"] <= 0:
        return
    now = store.now()
    covered = scheduled_guard_count(fac["id"], now, now + timedelta(hours=1))
    if covered < fac["required_lifeguard_count"]:
        apply_closure(fac, "STAFFING_SHORTAGE", now)


# ---------------------------------------------------------------------------
# Chemistry
# ---------------------------------------------------------------------------
def classify_chemistry(fc, ph, cc):
    if fc < FC_MIN or fc > FC_MAX or ph < PH_MIN or ph > PH_MAX:
        return "OUT_OF_RANGE"
    if cc > CC_WARN:
        return "WARNING"
    return "IN_RANGE"


# ---------------------------------------------------------------------------
# Closure cascades (SCAFFOLD §1.2 Facility transitions, PRD §3.3/§3.4)
# ---------------------------------------------------------------------------
def _cancel_overlapping_allocations(fac, window_start):
    for a in store.lane_allocations.values():
        if a["facility_id"] != fac["id"] or a["status"] != "RESERVED":
            continue
        if a["_end"] > window_start:  # overlap with open-ended closure window
            a["status"] = "CANCELLED"
            store.touch(a)


def _force_complete_rentals(fac):
    for r in store.rentals.values():
        if r["facility_id"] == fac["id"] and r["status"] == "CHECKED_IN":
            r["status"] = "COMPLETED"
            r["final_price_cents"] = r["quoted_price_cents"]  # overtime waived
            store.touch(r)


def _exit_admissions(fac, now):
    for adm in store.admissions.values():
        if adm["facility_id"] == fac["id"] and adm["status"] == "ENTERED":
            adm["status"] = "EXITED"
            adm["exited_at"] = store.iso(now)
            store.touch(adm)


def _rain_check_admissions(fac, closure_start, now):
    """ENTERED -> RAIN_CHECKED with rain-check refund policy. Returns issuance."""
    issuance = "FULL_REFUND"
    for adm in store.admissions.values():
        if adm["facility_id"] != fac["id"] or adm["status"] != "ENTERED":
            continue
        entered = store.parse_datetime(adm["entered_at"]) if adm.get("entered_at") else now
        elapsed_min = int((closure_start - entered).total_seconds() // 60)
        charge = adm["charge_cents"]
        if elapsed_min <= FULL_REFUND_ELAPSED_MIN:
            refund = charge  # FULL_REFUND
        else:
            issuance = "PRO_RATA_CREDIT"
            refund = round_half_up_cents(Decimal(charge) * PRO_RATA_FRACTION)
        # cash refund is not persisted; season-pass admissions have charge 0
        adm["_rain_check_refund_cents"] = refund
        adm["status"] = "RAIN_CHECKED"
        store.touch(adm)
    return issuance


def _cancel_approved_rentals_in_window(fac, window_start):
    for r in store.rentals.values():
        if r["facility_id"] != fac["id"] or r["status"] != "APPROVED":
            continue
        if r["_start"] >= window_start:  # start falls inside the closure window
            r["status"] = "CANCELLED"  # full refund
            store.touch(r)


def apply_closure(fac, reason, started_at):
    """Transition facility into a CLOSED_* posture and run the full cascade."""
    target = {
        "WEATHER": "CLOSED_WEATHER",
        "CHEMISTRY": "CLOSED_CHEMISTRY",
        "STAFFING_SHORTAGE": "CLOSED_STAFFING",
        "SEASON_END": "CLOSED_SEASON",
    }[reason]
    now = store.now()
    issuance = "NONE"
    if reason == "WEATHER":
        issuance = _rain_check_admissions(fac, started_at, now)
        _cancel_overlapping_allocations(fac, started_at)
        _force_complete_rentals(fac)
        _cancel_approved_rentals_in_window(fac, started_at)
        fac["current_bather_count"] = 0
    elif reason == "CHEMISTRY":
        _cancel_overlapping_allocations(fac, started_at)
        _force_complete_rentals(fac)
        _exit_admissions(fac, now)
        fac["current_bather_count"] = 0
    elif reason == "STAFFING_SHORTAGE":
        _exit_admissions(fac, now)
        _cancel_overlapping_allocations(fac, started_at)
        # admissions are out; rentals (if any) keep their bather share
        fac["current_bather_count"] = sum(
            r["party_size"] for r in store.rentals.values()
            if r["facility_id"] == fac["id"] and r["status"] == "CHECKED_IN")
    elif reason == "SEASON_END":
        cancel_future_sessions(fac, now)

    fac["operational_status"] = target
    recompute_required_lifeguards(fac)
    store.touch(fac)

    event = store.base_fields()
    event.update({
        "facility_id": fac["id"],
        "closure_reason": reason,
        "started_at": store.iso(started_at),
        "ended_at": None,
        "rain_check_issuance": issuance,
        "status": "ACTIVE",
        "_seq": store.next_seq(),
    })
    store.closures[event["id"]] = event
    return event


def cancel_future_sessions(fac, now):
    """Season-end cascade: cancel sessions that have not started.

    DRAFT sessions never ran; SCHEDULED sessions whose start was reached while
    the facility was closed never moved to IN_PROGRESS and are cancelled too.
    Sessions already completed by the clock are terminal and untouched.
    """
    for s in list(store.lesson_sessions.values()):
        if s["facility_id"] != fac["id"]:
            continue
        if s["status"] == "DRAFT":
            cancel_session(s)
        elif s["status"] == "SCHEDULED":
            # SCHEDULED at rollover means it never entered IN_PROGRESS
            cancel_session(s)


def cancel_session(session):
    session["status"] = "CANCELLED"
    store.touch(session)
    for a in store.lane_allocations.values():
        if a.get("owning_lesson_session_id") == session["id"] and a["status"] == "RESERVED":
            a["status"] = "CANCELLED"
            store.touch(a)
    for e in store.enrollments.values():
        if e["lesson_session_id"] == session["id"] and e["status"] in ("ENROLLED", "WAITLISTED"):
            e["status"] = "DROPPED"
            e["waitlist_position"] = None
            store.touch(e)
    renumber_waitlist(session["id"])
    refresh_enrolled_count(session)


def refresh_enrolled_count(session):
    n = sum(1 for e in store.enrollments.values()
            if e["lesson_session_id"] == session["id"] and e["status"] == "ENROLLED")
    if session["enrolled_count"] != n:
        session["enrolled_count"] = n
        store.touch(session)


def renumber_waitlist(session_id):
    waiting = [e for e in store.enrollments.values()
               if e["lesson_session_id"] == session_id and e["status"] == "WAITLISTED"]
    waiting.sort(key=lambda e: (e.get("waitlist_position") or 1 << 30, e["_seq"]))
    for i, e in enumerate(waiting, start=1):
        if e["waitlist_position"] != i:
            e["waitlist_position"] = i
            store.touch(e)


# ---------------------------------------------------------------------------
# Lane capacity sweep (half-open intervals, "at every instant" semantics)
# ---------------------------------------------------------------------------
def max_reserved_lanes(facility_id, start, end, exclude_id=None):
    allocs = [a for a in store.lane_allocations.values()
              if a["facility_id"] == facility_id and a["status"] == "RESERVED"
              and a["id"] != exclude_id
              and a["_start"] < end and a["_end"] > start]
    if not allocs:
        return 0
    points = {start}
    for a in allocs:
        points.add(max(a["_start"], start))
        points.add(min(a["_end"], end))
    worst = 0
    for p in sorted(points):
        if p >= end:
            continue
        cur = sum(a["lane_count"] for a in allocs if a["_start"] <= p < a["_end"])
        worst = max(worst, cur)
    return worst


def any_reserved_overlap(facility_id, start, end):
    return max_reserved_lanes(facility_id, start, end) > 0


# ---------------------------------------------------------------------------
# Pricing (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def ceil_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_CEILING))


def round_half_up_cents(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def age_tier(holder, on_date):
    years = store.age_years(holder["_dob"], on_date)
    if years < 18:
        return "CHILD"
    if years >= 62:
        return "SENIOR"
    return "ADULT"


def find_current_season(facility_id, on_date):
    """PUBLISHED season covering on_date; falls back to the early-bird window."""
    early = None
    for s in store.seasons.values():
        if s["facility_id"] != facility_id or s["status"] != "PUBLISHED":
            continue
        if s["_start_date"] <= on_date <= s["_end_date"]:
            return s, False
        if s["_start_date"] - timedelta(days=EARLY_BIRD_DAYS) <= on_date < s["_start_date"]:
            early = s
    return (early, True) if early else (None, False)


def daily_admission_charge(season, holder, admission_date, is_early_bird):
    base = (season["resident_daily_price_cents"] if holder["residency_status"] == "RESIDENT"
            else season["non_resident_daily_price_cents"])
    amount = Decimal(base)
    if is_early_bird:
        amount = amount * (Decimal("1") - EARLY_BIRD_DISCOUNT_PCT)
    tier = age_tier(holder, admission_date)
    if tier == "CHILD":
        amount = amount * CHILD_MULTIPLIER
    elif tier == "SENIOR":
        amount = amount * SENIOR_MULTIPLIER
    return ceil_cents(amount)


def rental_quote(holder, party_size, start, end):
    import math
    seconds = (end - start).total_seconds()
    hours = math.ceil(seconds / 3600)  # partial hours round UP
    base_rate = RENTAL_BASE_PER_HOUR_CENTS * hours
    mult = Decimal("1.0") if holder["residency_status"] == "RESIDENT" else NON_RESIDENT_RENTAL_MULTIPLIER
    subtotal = round_half_up_cents(Decimal(base_rate) * mult)
    party_fee = max(0, party_size - INCLUDED_PARTY_SIZE) * EXTRA_PERSON_CENTS
    return subtotal + party_fee


def rental_overtime_cents(end, actual_exit):
    if actual_exit <= end:
        return 0
    over = (actual_exit - end).total_seconds()
    import math
    blocks = math.ceil(over / 900)
    return blocks * OVERTIME_PER_15MIN_CENTS


def rental_cancellation_fee(rental, now):
    """25% fee when an APPROVED rental is cancelled strictly inside 72h."""
    hours_to_start = (rental["_start"] - now).total_seconds() / 3600
    if hours_to_start < CANCEL_FEE_WINDOW_HOURS:
        return round_half_up_cents(Decimal(rental["quoted_price_cents"]) * CANCEL_FEE_FRACTION)
    return 0


# ---------------------------------------------------------------------------
# Ban activation (PRD §3.8)
# ---------------------------------------------------------------------------
def activate_ban(holder, now):
    holder["banned_until"] = store.iso(now + timedelta(days=BAN_DAYS_PER_MAJOR))
    store.touch(holder)
    for p in store.season_passes.values():
        if p["pass_holder_id"] == holder["id"] and p["status"] == "ACTIVE":
            p["status"] = "REVOKED"
            store.touch(p)
    for adm in store.admissions.values():
        if adm["pass_holder_id"] == holder["id"] and adm["status"] == "ISSUED":
            adm["status"] = "VOID"  # charge refunded in full
            store.touch(adm)


def is_banned(holder, now):
    bu = holder.get("banned_until")
    if not bu:
        return False
    dt = store.parse_datetime(bu)
    return dt is not None and dt > now  # strict inequality per PRD §2.6


# ---------------------------------------------------------------------------
# Clock-driven re-evaluation (PRD §2.6)
# ---------------------------------------------------------------------------
def cancel_future_shifts_for_guard(guard, now):
    affected = set()
    for s in store.shifts.values():
        if s["lifeguard_id"] == guard["id"] and s["status"] == "SCHEDULED" and s["_shift_start"] > now:
            s["status"] = "CANCELLED"
            store.touch(s)
            affected.add(s["facility_id"])
    return affected


def reevaluate_time_transitions():
    now = store.now()
    today = store.today()

    # lifeguard certification expiry
    affected_facilities = set()
    for g in list(store.lifeguards.values()):
        if g["cert_status"] == "ACTIVE" and now > g["_cert_expires_on"]:
            g["cert_status"] = "EXPIRED"
            store.touch(g)
            affected_facilities |= cancel_future_shifts_for_guard(g, now)

    # shift no-show detection (15 minute grace)
    for s in list(store.shifts.values()):
        if s["status"] == "SCHEDULED" and now > s["_shift_start"] + timedelta(minutes=15):
            s["status"] = "NO_SHOW"
            store.touch(s)
            affected_facilities.add(s["facility_id"])

    for fid in affected_facilities:
        fac = store.facilities.get(fid)
        if fac:
            evaluate_staffing_closure(fac)

    # lesson session start / completion
    for sess in list(store.lesson_sessions.values()):
        if sess["status"] == "SCHEDULED" and now >= sess["_start"]:
            fac = store.facilities.get(sess["facility_id"])
            if fac and fac["operational_status"] in ("OPEN", "RESTRICTED"):
                sess["status"] = "IN_PROGRESS"
                store.touch(sess)
        if sess["status"] == "IN_PROGRESS" and now >= sess["_end"]:
            sess["status"] = "COMPLETED"
            store.touch(sess)
            for a in store.lane_allocations.values():
                if a.get("owning_lesson_session_id") == sess["id"] and a["status"] == "RESERVED":
                    a["status"] = "RELEASED"
                    store.touch(a)
            for e in store.enrollments.values():
                if e["lesson_session_id"] == sess["id"] and e["status"] == "ENROLLED":
                    e["status"] = "COMPLETED"
                    store.touch(e)
            refresh_enrolled_count(sess)

    # season rollover
    for season in list(store.seasons.values()):
        if season["status"] == "PUBLISHED" and today > season["_end_date"]:
            close_season(season)


def close_season(season):
    season["status"] = "CLOSED"
    store.touch(season)
    now = store.now()
    today = store.today()
    # cascade: facility closes for the season when no future PUBLISHED season exists
    has_future = any(
        s["facility_id"] == season["facility_id"] and s["status"] == "PUBLISHED"
        and s["id"] != season["id"] and s["_end_date"] >= today
        for s in store.seasons.values()
    )
    fac = store.facilities.get(season["facility_id"])
    if fac and not has_future and fac["operational_status"] in ("OPEN", "RESTRICTED"):
        fac["operational_status"] = "CLOSED_SEASON"
        recompute_required_lifeguards(fac)
        store.touch(fac)
        cancel_future_sessions(fac, now)
