"""Core business logic: counters, calculations, cascades, promotion selector.

Every function operates on the in-memory db module. All state-machine side
effects from the scaffold live here so route handlers stay thin.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
import util

BREAK_EVERY = 4
BREAK_EXTRA_MINUTES = 15
RUN_LENGTH_MINUTES = 45
BREAK_ALLOWANCE_PER_RUN = 10
BILL_UNIT_MINUTES = 15
MAX_OFFERS = 2

NON_TERMINAL_REQUEST_STATUSES = {"REQUESTED", "ASSIGNED", "CONFIRMED"}


def _q2(value):
    """Round to exactly 2 decimal places, half-up."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity lookups (404 helpers)
# ---------------------------------------------------------------------------

def get_window_or_404(wid):
    w = db.windows.get(wid)
    if w is None:
        raise errors.not_found("window not found")
    return w


def get_teacher_or_404(tid):
    t = db.teachers.get(tid)
    if t is None:
        raise errors.not_found("teacher not found")
    return t


def get_family_or_404(fid):
    f = db.families.get(fid)
    if f is None:
        raise errors.not_found("family not found")
    return f


def get_student_or_404(sid):
    s = db.students.get(sid)
    if s is None:
        raise errors.not_found("student not found")
    return s


def get_link_or_404(lid):
    l = db.links.get(lid)
    if l is None:
        raise errors.not_found("teacher link not found")
    return l


def get_slot_or_404(sid):
    s = db.slots.get(sid)
    if s is None:
        raise errors.not_found("slot not found")
    return s


def get_booking_or_404(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise errors.not_found("booking not found")
    return b


def get_interpreter_or_404(iid):
    i = db.interpreters.get(iid)
    if i is None:
        raise errors.not_found("interpreter not found")
    return i


def get_request_or_404(rid):
    r = db.interpreter_requests.get(rid)
    if r is None:
        raise errors.not_found("interpreter request not found")
    return r


def get_entry_or_404(eid):
    e = db.waitlist_entries.get(eid)
    if e is None:
        raise errors.not_found("waitlist entry not found")
    return e


def get_attendance_or_404(aid):
    a = db.attendance_records.get(aid)
    if a is None:
        raise errors.not_found("attendance record not found")
    return a


def get_outreach_or_404(oid):
    o = db.outreach_tasks.get(oid)
    if o is None:
        raise errors.not_found("outreach task not found")
    return o


# ---------------------------------------------------------------------------
# Window computed counters
# ---------------------------------------------------------------------------

def slots_total_count(window_id):
    return sum(1 for s in db.slots.values()
               if s["window_id"] == window_id and s["status"] != "RETIRED")


def slots_count(window_id, status):
    return sum(1 for s in db.slots.values()
               if s["window_id"] == window_id and s["status"] == status)


def bookings_confirmed_count(window_id):
    return sum(1 for b in db.bookings.values()
               if b["window_id"] == window_id and b["status"] == "CONFIRMED")


def waitlist_waiting_count(window_id):
    return sum(1 for e in db.waitlist_entries.values()
               if e["window_id"] == window_id and e["status"] == "WAITING")


# ---------------------------------------------------------------------------
# Family computed fields
# ---------------------------------------------------------------------------

def _family_attendance_records(family_id):
    recs = []
    for a in db.attendance_records.values():
        b = db.bookings.get(a["booking_id"])
        if b is not None and b["family_id"] == family_id:
            recs.append(a)
    return recs


def family_lifetime_no_show_count(family_id):
    return sum(1 for a in _family_attendance_records(family_id) if a["outcome"] == "NO_SHOW")


def family_strike_count(family_id):
    f = db.families.get(family_id)
    cleared = f["strikes_cleared_total"] if f else 0
    return max(0, family_lifetime_no_show_count(family_id) - cleared)


def family_risk_strict(family_id):
    return _q2(1.0 * family_lifetime_no_show_count(family_id))


def family_risk_score(family_id):
    recs = _family_attendance_records(family_id)
    total = 0.0
    for a in recs:
        if a["outcome"] == "NO_SHOW":
            total += 1.0
        elif a["outcome"] == "LATE":
            total += 0.5
        elif a["outcome"] == "EXCUSED":
            total += 0.25
    return _q2(total)


# ---------------------------------------------------------------------------
# Sibling compactness score
# ---------------------------------------------------------------------------

def compactness_score(family_id, window_id):
    candidates = []
    for b in db.bookings.values():
        if b["family_id"] != family_id or b["window_id"] != window_id:
            continue
        if b["status"] not in ("CONFIRMED", "COMPLETED", "NO_SHOW"):
            continue
        slot = db.slots.get(b["slot_id"])
        if slot is None:
            continue
        candidates.append((slot, b))
    if len(candidates) < 2:
        return _q2(0)
    candidates.sort(key=lambda pair: util.parse_dt(pair[0]["start_at"]))
    score = 0
    for i in range(len(candidates) - 1):
        slot1, b1 = candidates[i]
        slot2, b2 = candidates[i + 1]
        gap = util.minutes_between(util.parse_dt(slot1["end_at"]),
                                   util.parse_dt(slot2["start_at"]))
        if gap <= 15:
            tier = 1
        elif gap <= 45:
            tier = 3
        else:
            tier = 8
        if b1["channel"] != b2["channel"]:
            tier *= 2
        score += tier
    return _q2(score)


# ---------------------------------------------------------------------------
# Interpreter committed minutes + capacity + pay
# ---------------------------------------------------------------------------

def interpreter_committed_minutes(interpreter_id):
    """Sum of assigned_minutes over ASSIGNED|CONFIRMED requests whose window
    is not COMPLETED or ARCHIVED."""
    total = 0
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interpreter_id:
            continue
        if r["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        w = db.windows.get(r["window_id"])
        if w is not None and w["status"] in ("COMPLETED", "ARCHIVED"):
            continue
        total += r["assigned_minutes"]
    return total


def _request_interval(req):
    booking = db.bookings.get(req["booking_id"])
    if booking is None:
        return None
    slot = db.slots.get(booking["slot_id"])
    if slot is None:
        return None
    return (util.parse_dt(slot["start_at"]), util.parse_dt(slot["end_at"]))


def committed_in_window(interpreter_id, window_id):
    total = 0
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interpreter_id:
            continue
        if r["window_id"] != window_id:
            continue
        if r["status"] in ("ASSIGNED", "CONFIRMED"):
            total += r["assigned_minutes"]
    return total


def interpreter_capacity(interpreter_id, window_id):
    """Returns (committed_in_window, break_allowance, capacity, headroom)."""
    interp = db.interpreters[interpreter_id]
    committed = committed_in_window(interpreter_id, window_id)
    allowance = BREAK_ALLOWANCE_PER_RUN * (committed // RUN_LENGTH_MINUTES)
    capacity = max(0, interp["base_minutes_per_window"] - allowance)
    headroom = capacity - committed
    return committed, allowance, capacity, headroom


def interpreter_pay_estimate(interpreter_id, window_id):
    total = 0
    interp = db.interpreters[interpreter_id]
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interpreter_id:
            continue
        if r["window_id"] != window_id:
            continue
        if r["status"] != "CONFIRMED":
            continue
        units = util.ceil_div_minutes(r["assigned_minutes"], BILL_UNIT_MINUTES)
        pay = Decimal(units * BILL_UNIT_MINUTES * interp["hourly_rate_cents"]) / Decimal(60)
        pay = pay.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(pay)
    return total


def interpreter_overlap_conflict(interpreter_id, cand_start, cand_end, exclude_request_id=None):
    """Half-open interval overlap against ASSIGNED|CONFIRMED assignments."""
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interpreter_id:
            continue
        if r["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        if exclude_request_id is not None and r["id"] == exclude_request_id:
            continue
        interval = _request_interval(r)
        if interval is None:
            continue
        s, e = interval
        if cand_start < e and s < cand_end:
            return True
    return False


def interpreter_fatigue_ok(interpreter_id, cand_start, cand_end, max_consecutive):
    """Longest zero-gap run including the candidate must be <= max_consecutive."""
    intervals = [(cand_start, cand_end, cand_start, -1)]
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interpreter_id:
            continue
        if r["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        w = db.windows.get(r["window_id"])
        if w is not None and w["status"] == "ARCHIVED":
            continue
        interval = _request_interval(r)
        if interval is None:
            continue
        s, e = interval
        intervals.append((s, e, util.parse_dt(r["created_at"]), 0))
    intervals.sort(key=lambda iv: (iv[0], iv[2], iv[3]))
    max_run = 0.0
    cur_run = 0.0
    prev_end = None
    for s, e, _ca, _seq in intervals:
        length = util.minutes_between(s, e)
        if prev_end is not None and s == prev_end:
            cur_run += length
        else:
            cur_run = length
        if cur_run > max_run:
            max_run = cur_run
        prev_end = e
    return max_run <= max_consecutive


# ---------------------------------------------------------------------------
# Booking validation battery (shared by create / reschedule / claim / selector)
# ---------------------------------------------------------------------------

def find_link(student_id, teacher_id):
    for l in db.links.values():
        if l["student_id"] == student_id and l["teacher_id"] == teacher_id:
            return l
    return None


def teacher_daily_confirmed_count(teacher_id, window_id, day_label):
    count = 0
    for b in db.bookings.values():
        if b["teacher_id"] != teacher_id or b["window_id"] != window_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        slot = db.slots.get(b["slot_id"])
        if slot is not None and slot["day_label"] == day_label:
            count += 1
    return count


def family_confirmed_count(family_id, window_id):
    return sum(1 for b in db.bookings.values()
               if b["family_id"] == family_id
               and b["window_id"] == window_id
               and b["status"] == "CONFIRMED")


def required_gap_minutes(channel_a, channel_b, window):
    if channel_a == "VIRTUAL" and channel_b == "VIRTUAL":
        return 0
    if channel_a == "IN_PERSON" and channel_b == "IN_PERSON":
        return window["buffer_minutes"]
    return window["travel_minutes"]


def family_gap_conflict(family_id, window_id, cand_slot, cand_channel, exclude_booking_id=None):
    """Check the candidate (slot, channel) against every non-terminal family
    booking in the window. Returns True when a conflict exists."""
    c_start = util.parse_dt(cand_slot["start_at"])
    c_end = util.parse_dt(cand_slot["end_at"])
    window = db.windows[window_id]
    for b in db.bookings.values():
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["family_id"] != family_id or b["window_id"] != window_id:
            continue
        if b["status"] not in ("CONFIRMED", "COMPLETED", "NO_SHOW"):
            continue
        b_slot = db.slots.get(b["slot_id"])
        if b_slot is None:
            continue
        b_start = util.parse_dt(b_slot["start_at"])
        b_end = util.parse_dt(b_slot["end_at"])
        gap_after_b = required_gap_minutes(b["channel"], cand_channel, window)
        gap_after_c = required_gap_minutes(cand_channel, b["channel"], window)
        ok = (c_start >= b_end + timedelta(minutes=gap_after_b)) or \
             (b_start >= c_end + timedelta(minutes=gap_after_c))
        if not ok:
            return True
    return False


def channel_compatible(slot, teacher, channel):
    if slot["channel_allowed"] == "IN_PERSON" and channel != "IN_PERSON":
        return False
    if slot["channel_allowed"] == "VIRTUAL" and channel != "VIRTUAL":
        return False
    if channel == "IN_PERSON" and not teacher["supports_in_person"]:
        return False
    if channel == "VIRTUAL" and not teacher["supports_virtual"]:
        return False
    return True


def validate_booking(window, slot, student, channel, family, teacher,
                     exclude_booking_id=None, raise_errors=True):
    """Run the booking validation battery (PRD §3.4). When raise_errors is
    False, returns False instead of raising (used by the promotion selector).

    Assumes window-state, OCC, auth, and existence checks already done.
    Order per §2.7: entity-state (8) -> temporal gap (10) -> uniqueness (11)
    -> referential (12) -> capacity (13).
    """
    def fail(err):
        if raise_errors:
            raise err
        return False

    # --- tier 8: entity state ---
    if slot["status"] != "OPEN":
        return fail(errors.slot_not_available())
    if teacher["status"] != "ACTIVE":
        return fail(errors.teacher_inactive())
    if student["enrollment_status"] != "ENROLLED":
        return fail(errors.student_not_bookable())

    # --- tier 10: family gap rule ---
    if family_gap_conflict(family["id"], window["id"], slot, channel,
                           exclude_booking_id=exclude_booking_id):
        return fail(errors.family_schedule_conflict())

    # --- tier 11: uniqueness + channel ---
    for b in db.bookings.values():
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["window_id"] != window["id"] or b["status"] != "CONFIRMED":
            continue
        if b["student_id"] == student["id"] and b["teacher_id"] == teacher["id"]:
            return fail(errors.duplicate_booking())
        if window["format"] == "ELEMENTARY" and b["student_id"] == student["id"]:
            return fail(errors.duplicate_booking())
    if not channel_compatible(slot, teacher, channel):
        return fail(errors.channel_not_allowed())

    # --- tier 12: referential link ---
    link = find_link(student["id"], teacher["id"])
    if link is None:
        return fail(errors.teacher_not_linked())
    # ELEMENTARY requires the homeroom link: an explicit is_homeroom=false
    # marking fails; an omitted flag (null) does not.
    if window["format"] == "ELEMENTARY" and link["is_homeroom"] is False:
        return fail(errors.teacher_not_linked())

    # --- tier 13: capacity ---
    effective_cap = window["teacher_daily_conf_cap"]
    if teacher["daily_conf_cap_override"] is not None:
        effective_cap = min(effective_cap, teacher["daily_conf_cap_override"])
    if teacher_daily_confirmed_count(teacher["id"], window["id"], slot["day_label"]) >= effective_cap:
        return fail(errors.teacher_day_full())
    if family_confirmed_count(family["id"], window["id"]) >= window["family_conf_cap"]:
        return fail(errors.family_limit_reached())

    return True


# ---------------------------------------------------------------------------
# Booking / interpreter request creation helpers
# ---------------------------------------------------------------------------

def create_interpreter_request(booking, language):
    slot = db.slots[booking["slot_id"]]
    req = {
        "id": util.new_id(),
        "booking_id": booking["id"],
        "window_id": booking["window_id"],
        "language": language,
        "channel_required": booking["channel"],
        "interpreter_id": None,
        "assigned_minutes": booking_window_slot_length(booking),
        "declined_interpreter_ids": [],
        "status": "REQUESTED",
        "created_at": util.now_iso(),
        "updated_at": util.now_iso(),
        "version": 1,
    }
    db.interpreter_requests[req["id"]] = req
    return req


def booking_window_slot_length(booking):
    slot = db.slots.get(booking["slot_id"])
    if slot is None:
        return 0
    return int(util.minutes_between(util.parse_dt(slot["start_at"]),
                                    util.parse_dt(slot["end_at"])))


def create_booking(window, slot, student, channel, booked_by_role, interpreter_language,
                   rescheduled_from_booking_id=None):
    family_id = student["family_id"]
    now = util.now_iso()
    booking = {
        "id": util.new_id(),
        "window_id": window["id"],
        "family_id": family_id,
        "student_id": student["id"],
        "teacher_id": slot["teacher_id"],
        "slot_id": slot["id"],
        "channel": channel,
        "interpreter_language": interpreter_language,
        "booked_by_role": booked_by_role,
        "status": "CONFIRMED",
        "cancel_reason": None,
        "rescheduled_from_booking_id": rescheduled_from_booking_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.bookings[booking["id"]] = booking
    slot["status"] = "BOOKED"
    slot["updated_at"] = util.now_iso()
    slot["version"] += 1
    if interpreter_language:
        create_interpreter_request(booking, interpreter_language)
    return booking


# ---------------------------------------------------------------------------
# Interpreter request cancellation helper
# ---------------------------------------------------------------------------

def cancel_open_requests_for_booking(booking):
    """Cancel REQUESTED|ASSIGNED|CONFIRMED requests on a booking. ASSIGNED ones
    release committed minutes (implicit through computed committed_minutes)."""
    for r in db.interpreter_requests.values():
        if r["booking_id"] != booking["id"]:
            continue
        if r["status"] in NON_TERMINAL_REQUEST_STATUSES:
            r["status"] = "CANCELLED"
            r["updated_at"] = util.now_iso()
            r["version"] += 1


# ---------------------------------------------------------------------------
# Waitlist priority score
# ---------------------------------------------------------------------------

def compute_priority_score(entry, include_wait_bonus=True):
    score = 100
    link = find_link(entry["student_id"], entry["teacher_id"])
    if link is not None and link["required_conference"]:
        score += 50
    student = db.students.get(entry["student_id"])
    if student is not None:
        siblings = [s for s in db.students.values()
                    if s["family_id"] == student["family_id"] and s["id"] != student["id"]]
        sibling_ids = {s["id"] for s in siblings}
        count = 0
        for b in db.bookings.values():
            if b["window_id"] != entry["window_id"] or b["status"] != "CONFIRMED":
                continue
            if b["student_id"] in sibling_ids:
                count += 1
        score += 15 * min(count, 2)
    strict = family_risk_strict(entry["family_id"])
    import math as _math
    score -= 10 * min(int(_math.floor(strict)), 5)
    if include_wait_bonus:
        # Patience term: 5 points per full 24h the entry has been waiting on
        # the logical clock, measured from the clock reading at entry creation
        # (created_at is a wall-clock timestamp and must not be compared
        # against the logical clock).
        created_clock = entry.get("created_clock") or entry["created_at"]
        created = util.parse_dt(created_clock)
        hours = (util.clock_dt() - created).total_seconds() / 3600.0
        if hours > 0:
            score += 5 * min(int(hours // 24), 4)
    if score < 0:
        score = 0
    return _q2(score)


def refresh_priority_scores(window_id=None):
    for e in db.waitlist_entries.values():
        if e["status"] != "WAITING":
            continue
        if window_id is not None and e["window_id"] != window_id:
            continue
        e["priority_score"] = compute_priority_score(e)
        e["updated_at"] = util.now_iso()


# ---------------------------------------------------------------------------
# Waitlist promotion selector
# ---------------------------------------------------------------------------

def _waitlist_pref_compatible(pref, channel_allowed):
    if pref == "EITHER":
        return True
    if pref == "IN_PERSON":
        return channel_allowed in ("IN_PERSON", "EITHER")
    if pref == "VIRTUAL":
        return channel_allowed in ("VIRTUAL", "EITHER")
    return False


def _offer_channel_for_entry(slot, entry):
    """Pick the channel used for selector precondition evaluation."""
    if slot["channel_allowed"] == "IN_PERSON":
        return "IN_PERSON"
    if slot["channel_allowed"] == "VIRTUAL":
        return "VIRTUAL"
    if entry["channel_pref"] in ("IN_PERSON", "VIRTUAL"):
        return entry["channel_pref"]
    return "IN_PERSON"


def run_promotion(slot):
    """Offer the OPEN slot to the best eligible WAITING entry. Mutates state
    when an offer is made (slot OPEN -> HELD, entry -> OFFERED)."""
    if slot["status"] != "OPEN":
        return
    window = db.windows.get(slot["window_id"])
    if window is None or window["status"] != "BOOKING_OPEN":
        return
    candidates = []
    for e in db.waitlist_entries.values():
        if e["status"] != "WAITING":
            continue
        if e["teacher_id"] != slot["teacher_id"] or e["window_id"] != slot["window_id"]:
            continue
        if slot["id"] in e["declined_slot_ids"]:
            continue
        if not _waitlist_pref_compatible(e["channel_pref"], slot["channel_allowed"]):
            continue
        candidates.append(e)
    candidates.sort(key=lambda e: (-e["priority_score"], e["created_at"], e["created_seq"]))
    teacher = db.teachers.get(slot["teacher_id"])
    for e in candidates:
        student = db.students.get(e["student_id"])
        family = db.families.get(e["family_id"])
        if student is None or family is None or teacher is None:
            continue
        channel = _offer_channel_for_entry(slot, e)
        if not validate_booking(window, slot, student, channel, family, teacher,
                                raise_errors=False):
            continue
        # Make the offer
        e["status"] = "OFFERED"
        e["offered_slot_id"] = slot["id"]
        expires = util.clock_dt() + timedelta(hours=window["waitlist_offer_ttl_hours"])
        e["offer_expires_at"] = util.format_dt(expires)
        e["offers_made_count"] += 1
        e["updated_at"] = util.now_iso()
        e["version"] += 1
        slot["status"] = "HELD"
        slot["updated_at"] = util.now_iso()
        slot["version"] += 1
        return


def open_slot_with_promotion(slot):
    """BOOKED/HELD -> OPEN, then run promotion when the window is BOOKING_OPEN."""
    slot["status"] = "OPEN"
    slot["updated_at"] = util.now_iso()
    slot["version"] += 1
    run_promotion(slot)


# ---------------------------------------------------------------------------
# Waitlist decline / expiry shared path
# ---------------------------------------------------------------------------

def release_offer(entry):
    """OFFERED -> WAITING (< 2 offers) or EXHAUSTED (== 2). Releases the HELD
    slot to OPEN and re-runs promotion."""
    slot = db.slots.get(entry["offered_slot_id"]) if entry["offered_slot_id"] else None
    if slot is not None and entry["offered_slot_id"] not in entry["declined_slot_ids"]:
        entry["declined_slot_ids"].append(entry["offered_slot_id"])
    entry["offered_slot_id"] = None
    entry["offer_expires_at"] = None
    if entry["offers_made_count"] < MAX_OFFERS:
        entry["status"] = "WAITING"
        entry["priority_score"] = compute_priority_score(entry)
    else:
        entry["status"] = "EXHAUSTED"
    entry["updated_at"] = util.now_iso()
    entry["version"] += 1
    if slot is not None and slot["status"] == "HELD":
        slot["status"] = "OPEN"
        slot["updated_at"] = util.now_iso()
        slot["version"] += 1
        run_promotion(slot)


def withdraw_entry(entry):
    """WAITING|OFFERED -> WITHDRAWN. An OFFERED entry releases its HELD slot."""
    slot = db.slots.get(entry["offered_slot_id"]) if entry["offered_slot_id"] else None
    was_offered = entry["status"] == "OFFERED"
    entry["status"] = "WITHDRAWN"
    entry["offered_slot_id"] = None
    entry["offer_expires_at"] = None
    entry["updated_at"] = util.now_iso()
    entry["version"] += 1
    if was_offered and slot is not None and slot["status"] == "HELD":
        slot["status"] = "OPEN"
        slot["updated_at"] = util.now_iso()
        slot["version"] += 1
        run_promotion(slot)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cancel_booking_cascade(booking, reason):
    """Cancel a CONFIRMED booking: slot frees with promotion, open interpreter
    requests cancel. Also sweeps requests the window lock already moved to
    UNFILLED — the booking was still live then, and the restriction/withdrawal
    cascade is the terminal word on its coverage."""
    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = reason
    booking["updated_at"] = util.now_iso()
    booking["version"] += 1
    slot = db.slots.get(booking["slot_id"])
    if slot is not None and slot["status"] == "BOOKED":
        open_slot_with_promotion(slot)
    cancel_open_requests_for_booking(booking)
    for r in db.interpreter_requests.values():
        if r["booking_id"] == booking["id"] and r["status"] == "UNFILLED":
            r["status"] = "CANCELLED"
            r["updated_at"] = util.now_iso()
            r["version"] += 1


def family_restriction_cascade(family):
    """Family -> RESTRICTED: cancel future bookings, withdraw entries. Any
    still-open LANGUAGE_ACCESS follow-up is superseded: the restriction itself
    becomes the family's front-office follow-up context."""
    family["status"] = "RESTRICTED"
    family["updated_at"] = util.now_iso()
    family["version"] += 1
    # Still-open LANGUAGE_ACCESS follow-ups tied to this family's cancelled
    # bookings are removed outright: restriction replaces them, and the front
    # office's queue for the family is the no-show follow-up work.
    doomed = [tid for tid, t in db.outreach_tasks.items()
              if t["family_id"] == family["id"] and t["kind"] == "LANGUAGE_ACCESS"
              and t["status"] in ("OPEN", "CONTACTED")]
    for tid in doomed:
        del db.outreach_tasks[tid]
    clock = util.clock_dt()
    for b in list(db.bookings.values()):
        if b["family_id"] != family["id"] or b["status"] != "CONFIRMED":
            continue
        slot = db.slots.get(b["slot_id"])
        if slot is None:
            continue
        if util.parse_dt(slot["start_at"]) > clock:
            cancel_booking_cascade(b, "FAMILY_RESTRICTED")
    for e in list(db.waitlist_entries.values()):
        if e["family_id"] == family["id"] and e["status"] in ("WAITING", "OFFERED"):
            withdraw_entry(e)


def student_withdrawal_cascade(student):
    """Student ENROLLED -> WITHDRAWN with the cancellation cascade."""
    student["enrollment_status"] = "WITHDRAWN"
    student["updated_at"] = util.now_iso()
    student["version"] += 1
    clock = util.clock_dt()
    for b in list(db.bookings.values()):
        if b["student_id"] != student["id"] or b["status"] != "CONFIRMED":
            continue
        slot = db.slots.get(b["slot_id"])
        if slot is None:
            continue
        if util.parse_dt(slot["start_at"]) > clock:
            cancel_booking_cascade(b, "STUDENT_WITHDRAWN")
    for e in list(db.waitlist_entries.values()):
        if e["student_id"] == student["id"] and e["status"] in ("WAITING", "OFFERED"):
            withdraw_entry(e)


def teacher_deactivation_cascade(teacher):
    """Teacher ACTIVE -> INACTIVE. Retire slots in PUBLISHED/BOOKING_OPEN
    windows; cancel CONFIRMED bookings there (slots RETIRE, never reopen)."""
    for slot in list(db.slots.values()):
        if slot["teacher_id"] != teacher["id"]:
            continue
        window = db.windows.get(slot["window_id"])
        if window is None or window["status"] not in ("PUBLISHED", "BOOKING_OPEN"):
            continue
        if slot["status"] in ("OPEN", "BLOCKED"):
            slot["status"] = "RETIRED"
            slot["updated_at"] = util.now_iso()
            slot["version"] += 1
    for b in list(db.bookings.values()):
        if b["teacher_id"] != teacher["id"] or b["status"] != "CONFIRMED":
            continue
        window = db.windows.get(b["window_id"])
        if window is None or window["status"] not in ("PUBLISHED", "BOOKING_OPEN"):
            continue
        b["status"] = "CANCELLED"
        b["cancel_reason"] = "TEACHER_INACTIVE"
        b["updated_at"] = util.now_iso()
        b["version"] += 1
        slot = db.slots.get(b["slot_id"])
        if slot is not None and slot["status"] == "BOOKED":
            slot["status"] = "RETIRED"
            slot["updated_at"] = util.now_iso()
            slot["version"] += 1
        cancel_open_requests_for_booking(b)
    for e in list(db.waitlist_entries.values()):
        if e["teacher_id"] != teacher["id"] or e["status"] not in ("WAITING", "OFFERED"):
            continue
        window = db.windows.get(e["window_id"])
        if window is None or window["status"] not in ("PUBLISHED", "BOOKING_OPEN"):
            continue
        slot = db.slots.get(e["offered_slot_id"]) if e["offered_slot_id"] else None
        was_offered = e["status"] == "OFFERED"
        e["status"] = "WITHDRAWN"
        e["offered_slot_id"] = None
        e["offer_expires_at"] = None
        e["updated_at"] = util.now_iso()
        e["version"] += 1
        if was_offered and slot is not None and slot["status"] == "HELD":
            slot["status"] = "RETIRED"
            slot["updated_at"] = util.now_iso()
            slot["version"] += 1


def interpreter_deactivation_cascade(interp):
    """ASSIGNED requests bounce back to REQUESTED; CONFIRMED are honored."""
    for r in db.interpreter_requests.values():
        if r["interpreter_id"] != interp["id"]:
            continue
        if r["status"] == "ASSIGNED":
            r["status"] = "REQUESTED"
            r["interpreter_id"] = None
            r["updated_at"] = util.now_iso()
            r["version"] += 1


def create_outreach_task(family_id, kind, booking_id=None, window_id=None, note=None):
    task = {
        "id": util.new_id(),
        "family_id": family_id,
        "window_id": window_id,
        "booking_id": booking_id,
        "kind": kind,
        "status": "OPEN",
        "attempts_count": 0,
        "note": note,
        "created_at": util.now_iso(),
        "updated_at": util.now_iso(),
        "version": 1,
    }
    db.outreach_tasks[task["id"]] = task
    return task


def record_attendance(booking, outcome, marked_by_role, marked_by_user_id, note=None):
    rec = {
        "id": util.new_id(),
        "booking_id": booking["id"],
        "outcome": outcome,
        "marked_by_role": marked_by_role,
        "marked_by_user_id": marked_by_user_id,
        "note": note,
        "created_at": util.now_iso(),
    }
    db.attendance_records[rec["id"]] = rec
    return rec


def mark_no_show(booking, marked_by_role, marked_by_user_id, note=None):
    """Full NO_SHOW transition: record, strike recompute, outreach task,
    threshold check and possible family restriction cascade."""
    booking["status"] = "NO_SHOW"
    booking["updated_at"] = util.now_iso()
    booking["version"] += 1
    record_attendance(booking, "NO_SHOW", marked_by_role, marked_by_user_id, note)
    family = db.families.get(booking["family_id"])
    if family is None:
        return
    create_outreach_task(family_id=family["id"], kind="NO_SHOW_FOLLOW_UP",
                         booking_id=booking["id"], window_id=booking["window_id"])
    window = db.windows.get(booking["window_id"])
    threshold = window["no_show_strike_threshold"] if window is not None else 3
    if family["status"] == "ACTIVE" and family_strike_count(family["id"]) >= threshold:
        family_restriction_cascade(family)


def window_lock_cascade(window):
    """BOOKING_OPEN -> LOCKED: unfill REQUESTED requests, expire waitlist.
    Each unfilled request opens a LANGUAGE_ACCESS outreach task (PRD 3.7)."""
    for r in db.interpreter_requests.values():
        if r["window_id"] != window["id"]:
            continue
        if r["status"] == "REQUESTED":
            r["status"] = "UNFILLED"
            r["updated_at"] = util.now_iso()
            r["version"] += 1
            booking = db.bookings.get(r["booking_id"])
            if booking is not None:
                create_outreach_task(family_id=booking["family_id"],
                                     kind="LANGUAGE_ACCESS",
                                     booking_id=booking["id"],
                                     window_id=window["id"])
    for e in list(db.waitlist_entries.values()):
        if e["window_id"] != window["id"]:
            continue
        if e["status"] in ("WAITING", "OFFERED"):
            slot = db.slots.get(e["offered_slot_id"]) if e["offered_slot_id"] else None
            was_offered = e["status"] == "OFFERED"
            e["status"] = "EXPIRED"
            e["offered_slot_id"] = None
            e["offer_expires_at"] = None
            e["updated_at"] = util.now_iso()
            e["version"] += 1
            if was_offered and slot is not None and slot["status"] == "HELD":
                slot["status"] = "OPEN"
                slot["updated_at"] = util.now_iso()
                slot["version"] += 1


def run_ops_sweeps(window):
    """Ops checkpoint: offer expiry, auto no-show, priority refresh."""
    window["ops_run_index"] += 1
    clock = util.clock_dt()
    # Sweep 1: expire OFFERED entries whose deadline is strictly before clock
    for e in list(db.waitlist_entries.values()):
        if e["window_id"] != window["id"]:
            continue
        if e["status"] == "OFFERED" and e["offer_expires_at"] is not None:
            if util.parse_dt(e["offer_expires_at"]) < clock:
                release_offer(e)
    # Sweep 2: auto no-show while IN_PROGRESS or COMPLETED
    if window["status"] in ("IN_PROGRESS", "COMPLETED"):
        grace = timedelta(hours=window["auto_no_show_grace_hours"])
        for b in list(db.bookings.values()):
            if b["window_id"] != window["id"] or b["status"] != "CONFIRMED":
                continue
            slot = db.slots.get(b["slot_id"])
            if slot is None:
                continue
            if util.parse_dt(slot["end_at"]) + grace <= clock:
                mark_no_show(b, "system", "system")
    # Sweep 3: refresh WAITING priority scores in this window
    refresh_priority_scores(window["id"])
