"""Business logic: derived fields, state side effects, calculations, sweeps."""
import math
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import fmt_ts

NO_SHOW_GRACE = timedelta(minutes=15)
FACILITATOR_BUFFER = timedelta(minutes=30)
BASE_FEE_CENTS = 2500
STIPEND_RATE_PER_HOUR = Decimal("18.50")


# ---------- record factory / mutation ----------

def make_record(fields):
    now = db.now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = fmt_ts(now)
    rec["_created_dt"] = now
    rec["_seq"] = db.next_seq()
    return rec


def add_common(rec):
    """Standard system fields for primary resources."""
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = fmt_ts(db.now())
    rec["version"] = rec.get("version", 1) + 1


# ---------- enrollment counters / waitlist ----------

def active_enrollment_count(group_id):
    """Derived: enrollments of the group with seat_status RESERVED or CONFIRMED."""
    return sum(
        1 for e in db.enrollments.values()
        if e["group_id"] == group_id and e["seat_status"] in ("RESERVED", "CONFIRMED")
    )


def sync_group_count(group):
    group["active_enrollment_count"] = active_enrollment_count(group["id"])


def seat_counts(group_id):
    reserved = confirmed = 0
    for e in db.enrollments.values():
        if e["group_id"] != group_id:
            continue
        if e["seat_status"] == "RESERVED":
            reserved += 1
        elif e["seat_status"] == "CONFIRMED":
            confirmed += 1
    return reserved, confirmed


def renumber_waitlist(group_id):
    """Reassign 1-based waitlist positions: reserved_at ASC, created_at ASC
    (insertion seq breaks identical-timestamp ties deterministically)."""
    waitlisted = [
        e for e in db.enrollments.values()
        if e["group_id"] == group_id and e["seat_status"] == "WAITLISTED"
    ]
    waitlisted.sort(key=lambda e: (e["_reserved_dt"], e["_created_dt"], e["_seq"]))
    for i, e in enumerate(waitlisted):
        newpos = i + 1
        if e.get("waitlist_position") != newpos:
            e["waitlist_position"] = newpos
            touch(e)


def promote_waitlist(group):
    """Promote the head of the waitlist while capacity is available."""
    while True:
        count = active_enrollment_count(group["id"])
        if count >= group["base_capacity"]:
            break
        waitlisted = [
            e for e in db.enrollments.values()
            if e["group_id"] == group["id"] and e["seat_status"] == "WAITLISTED"
        ]
        if not waitlisted:
            break
        waitlisted.sort(key=lambda e: (e["_reserved_dt"], e["_created_dt"], e["_seq"]))
        promoted = waitlisted[0]
        promoted["seat_status"] = "RESERVED"
        promoted["waitlist_position"] = None
        touch(promoted)
    renumber_waitlist(group["id"])
    sync_group_count(group)


def release_seat(enrollment, group, new_status):
    """Shared side effects for RELEASED / CANCELLED transitions."""
    enrollment["seat_status"] = new_status
    touch(enrollment)
    promote_waitlist(group)
    touch(group)


def cancel_participant_enrollments(participant_id):
    """Cascade: all RESERVED/CONFIRMED enrollments of the participant -> CANCELLED."""
    affected_groups = set()
    for e in db.enrollments.values():
        if e["participant_id"] == participant_id and e["seat_status"] in ("RESERVED", "CONFIRMED"):
            e["seat_status"] = "CANCELLED"
            touch(e)
            affected_groups.add(e["group_id"])
    for gid in affected_groups:
        group = db.groups.get(gid)
        if group is None:
            continue
        promote_waitlist(group)
        touch(group)


# ---------- program posture ----------

def recompute_program(program, bump=True):
    crit = std = 0
    pid = program["id"]
    for inc in db.incidents.values():
        if inc["_program_id"] != pid or inc["status"] not in ("OPEN", "ACKNOWLEDGED"):
            continue
        if inc["severity"] == "CRITICAL":
            crit += 1
        else:
            std += 1
    program["active_critical_incident_count"] = crit
    program["active_standard_incident_count"] = std
    if crit > 0:
        program["posture"] = "LOCKDOWN"
    elif std > 0:
        program["posture"] = "CAUTION"
    else:
        program["posture"] = "OPEN"
    if bump:
        touch(program)


def scheduled_session_count(program_id):
    return sum(
        1 for s in db.sessions.values()
        if s["_program_id"] == program_id and s["status"] == "SCHEDULED"
    )


def sync_program_session_count(program):
    program["scheduled_session_count"] = scheduled_session_count(program["id"])


# ---------- facilitator level ----------

def recompute_facilitator_level(fac):
    """facilitator_level: pinned evaluation order — training points first
    (passing completions on ACTIVE courses), then supervision bonus
    (count of rating>=4 reviews, halved floor, capped at 2), then clamp 1..5."""
    points = 0
    for c in db.completions.values():
        if c["facilitator_id"] != fac["id"] or c["score"] < 70:
            continue
        course = db.courses.get(c["course_id"])
        if course is not None and course["status"] == "ACTIVE":
            points += course["level_weight"]
    high_reviews = sum(
        1 for r in db.reviews.values()
        if r["facilitator_id"] == fac["id"] and r["rating"] >= 4
    )
    bonus = min(2, high_reviews // 2)
    fac["level"] = min(5, max(1, 1 + points + bonus))
    touch(fac)


# ---------- capacity / conflict rules ----------

def effective_capacity(group, room):
    """session_capacity_formula (modality-aware, integer)."""
    base = group["base_capacity"]
    if group["modality"] == "VIRTUAL":
        return base
    if group["modality"] == "IN_PERSON":
        return min(base, room["physical_capacity"])
    # HYBRID: in-person seats are a sub-allocation; virtual takes remainder
    in_person = min(room["physical_capacity"], math.ceil(base * 0.5))
    virtual = base - in_person
    return in_person + virtual


def in_person_subcapacity(session, group):
    room = db.rooms.get(session.get("room_id") or "")
    if room is None:
        return 0
    return min(room["physical_capacity"], math.ceil(group["base_capacity"] * 0.5))


def room_conflict(session):
    """Half-open interval: conflict iff NOT (s.end <= new.start OR new.end <= s.start)."""
    room_id = session.get("room_id")
    if not room_id:
        return False
    for s in db.sessions.values():
        if s["id"] == session["id"] or s.get("room_id") != room_id:
            continue
        if s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if not (s["_end_dt"] <= session["_start_dt"] or session["_end_dt"] <= s["_start_dt"]):
            return True
    return False


def facilitator_conflict(session):
    """30-minute buffer on either side for the new session's primary facilitator,
    across sessions where they serve as primary or cofacilitator."""
    fid = session["primary_facilitator_id"]
    for s in db.sessions.values():
        if s["id"] == session["id"]:
            continue
        if s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if s["primary_facilitator_id"] != fid and s.get("cofacilitator_id") != fid:
            continue
        if not (s["_end_dt"] + FACILITATOR_BUFFER <= session["_start_dt"]
                or session["_end_dt"] + FACILITATOR_BUFFER <= s["_start_dt"]):
            return True
    return False


# ---------- money / score calculations ----------

def enrollment_fee_cents(participant):
    """Tiered pricing, multiplicative stacking, round half-up at final step only."""
    household = participant["household_size"]
    if household >= 4:
        t1 = Decimal("0.50")
    elif household >= 2:
        t1 = Decimal("0.25")
    else:
        t1 = Decimal("0.00")
    t2 = Decimal("0.10") if participant["attendance_streak"] >= 5 else Decimal("0.00")
    fee = Decimal(BASE_FEE_CENTS) * (1 - t1) * (1 - t2)
    return int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def capacity_score(fid):
    training_hours = 0
    for c in db.completions.values():
        if c["facilitator_id"] == fid and c["score"] >= 70:
            course = db.courses.get(c["course_id"])
            if course is not None:
                training_hours += course["credit_hours"]
    supervision_count = sum(
        1 for r in db.reviews.values()
        if r["facilitator_id"] == fid and r["rating"] >= 3
    )
    sessions_led = sum(
        1 for s in db.sessions.values()
        if s["primary_facilitator_id"] == fid
        and s["status"] in ("COMPLETED", "COMPLETED_WITH_INCIDENT")
    )
    sc, th, sl = Decimal(supervision_count), Decimal(training_hours), Decimal(sessions_led)
    two = Decimal("0.01")
    conservative = (Decimal("0.5") * sc + Decimal("0.3") * th + Decimal("0.2") * sl).quantize(two, rounding=ROUND_HALF_UP)
    accelerated = (Decimal("0.2") * sc + Decimal("0.5") * th + Decimal("0.3") * sl).quantize(two, rounding=ROUND_HALF_UP)
    return {
        "conservative": float(conservative),
        "accelerated": float(accelerated),
        "sessions_led": sessions_led,
    }


def stipend_cents(fid):
    """Round each per-course stipend half-up to cents first, then sum."""
    total = 0
    for c in db.completions.values():
        if c["facilitator_id"] != fid or c["score"] < 70:
            continue
        course = db.courses.get(c["course_id"])
        if course is None or course["status"] != "ACTIVE":
            continue
        multiplier = Decimal("1.0") + Decimal("0.25") * (course["level_weight"] - 1)
        per = (Decimal(course["credit_hours"]) * STIPEND_RATE_PER_HOUR * multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
        total += int((per * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def round4(numerator, denominator):
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------- clock-driven transitions ----------

def sweep_time_transitions():
    """Fire automatic transitions against the logical clock:
    Session SCHEDULED->IN_PROGRESS at start_at; Agreement SIGNED->EXPIRED once
    the clock passes expires_at; AttendanceRecord CHECKED_IN->NO_SHOW at
    end_at + 15 minutes."""
    now = db.now()

    for s in db.sessions.values():
        if s["status"] == "SCHEDULED" and now >= s["_start_dt"]:
            s["status"] = "IN_PROGRESS"
            touch(s)

    for a in db.agreements.values():
        if a["status"] == "SIGNED" and now > a["_expires_dt"]:
            a["status"] = "EXPIRED"
            p = db.participants.get(a["participant_id"])
            if p is not None and p.get("current_agreement_id") == a["id"]:
                p["current_agreement_id"] = None
                touch(p)

    for rec in db.attendance.values():
        if rec["status"] != "CHECKED_IN":
            continue
        s = db.sessions.get(rec["session_id"])
        if s is None:
            continue
        if now >= s["_end_dt"] + NO_SHOW_GRACE:
            rec["status"] = "NO_SHOW"
            touch(rec)
            p = db.participants.get(rec["participant_id"])
            if p is not None:
                p["attendance_streak"] = 0
                p["total_no_shows"] = p.get("total_no_shows", 0) + 1
                touch(p)
