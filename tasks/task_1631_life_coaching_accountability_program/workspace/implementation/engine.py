"""Cascades, waitlist promotion, overlap checks, and the date-advance sweep
evaluated against the logical clock (PRD §2.5, §2.9, §2.10; SCAFFOLD §1.2).

Derived enrollment counts (sessions_consumed / sessions_remaining / paid_cents
/ refunded_cents) and Client.engagement_score are computed at read time, so
cascades only need to perform the stored-field mutations and version bumps the
state machine declares.
"""
from datetime import timedelta

import calc
from db import store
from serializers import touch


# ------------------------------------------------------------------ membership

def memberships_of_cohort(cohort_id):
    return [m for m in store.memberships.values() if m["cohort_id"] == cohort_id]


def active_member_count(cohort_id):
    return sum(1 for m in memberships_of_cohort(cohort_id)
               if m["member_status"] == "ACTIVE")


def promote_waitlist_if_needed(cohort):
    """WAITLISTED -> ACTIVE: exactly one promotion when an ACTIVE member leaves
    and capacity is free; earliest joined_at, tie-break created_at (then a
    stable insertion counter). Only while OPEN or IN_PROGRESS (SCAFFOLD §1.2).
    """
    if cohort["cohort_status"] not in ("OPEN", "IN_PROGRESS"):
        return
    if active_member_count(cohort["id"]) >= cohort["capacity"]:
        return
    waitlisted = [m for m in memberships_of_cohort(cohort["id"])
                  if m["member_status"] == "WAITLISTED"]
    if not waitlisted:
        return
    waitlisted.sort(key=lambda m: (m["joined_at"], m["created_at"], m["_created_sort"]))
    waitlisted[0]["member_status"] = "ACTIVE"


def remove_membership(m):
    """ACTIVE/WAITLISTED -> REMOVED, then fire waitlist promotion (PRD §3.7)."""
    m["member_status"] = "REMOVED"
    cohort = store.cohorts.get(m["cohort_id"])
    if cohort is not None:
        promote_waitlist_if_needed(cohort)


def remove_enrollment_memberships(enrollment_id):
    """Cascade shared by enrollment cancel / refund approve / auto-completion:
    ACTIVE memberships of this enrollment -> REMOVED with promotion (PRD §3.5,
    §3.9, §3.7)."""
    for m in store.memberships.values():
        if m["enrollment_id"] == enrollment_id and m["member_status"] == "ACTIVE":
            remove_membership(m)


# -------------------------------------------------------------------- sessions

def cancel_scheduled_sessions_of_enrollment(enrollment_id):
    for s in calc.sessions_of(enrollment_id):
        if s["session_status"] == "SCHEDULED":
            s["session_status"] = "CANCELLED"
            touch(s)


def cancel_scheduled_sessions_of_coach(coach_id):
    """Coach revoke / ethics-suspend cascade (depth 1+2): each SCHEDULED session
    -> CANCELLED (session version +1); each cancelled session's enrollment
    recomputes with its version advancing (PRD §3.1)."""
    for s in store.sessions.values():
        if s["coach_id"] == coach_id and s["session_status"] == "SCHEDULED":
            s["session_status"] = "CANCELLED"
            touch(s)
            en = store.enrollments.get(s["enrollment_id"])
            if en is not None:
                touch(en)  # sessions_consumed / sessions_remaining recomputed


def session_intervals_collide(a_start, a_duration, b_start, b_duration):
    """Half-open, buffer-inclusive: [start, start + duration + 15min).
    Touching intervals (end == start) do NOT intersect (PRD §2.9)."""
    a_end = a_start + timedelta(minutes=a_duration + calc.BUFFER_MINUTES)
    b_end = b_start + timedelta(minutes=b_duration + calc.BUFFER_MINUTES)
    return a_start < b_end and b_start < a_end


def session_overlap(coach_id, start, duration, exclude_session_id=None):
    for s in store.sessions.values():
        if s["coach_id"] != coach_id or s["session_status"] != "SCHEDULED":
            continue
        if exclude_session_id is not None and s["id"] == exclude_session_id:
            continue
        if session_intervals_collide(start, duration,
                                     s["scheduled_start"], s["duration_minutes"]):
            return True
    return False


def discovery_call_overlap(coach_id, start, duration, exclude_call_id=None):
    """Closed intervals, NO buffer: [start, start + duration]; touching
    endpoints DO collide (PRD §2.9) — deliberately different from sessions."""
    a_end = start + timedelta(minutes=duration)
    for d in store.discovery_calls.values():
        if d["coach_id"] != coach_id or d["call_status"] != "SCHEDULED":
            continue
        if exclude_call_id is not None and d["id"] == exclude_call_id:
            continue
        b_end = d["scheduled_start"] + timedelta(minutes=d["duration_minutes"])
        if start <= b_end and d["scheduled_start"] <= a_end:
            return True
    return False


# --------------------------------------------------------- enrollment bubble-up

def check_enrollment_completion(enrollment):
    """System transition: when sessions_consumed reaches sessions_total on a
    Session terminal transition, an ACTIVE enrollment bubbles to COMPLETED;
    its OPEN goals stay OPEN (no auto-achieve); its ACTIVE cohort memberships
    -> REMOVED as community access ends (PRD §3.4)."""
    if enrollment["lifecycle_status"] != "ACTIVE":
        return
    if calc.sessions_consumed(enrollment["id"]) == enrollment["sessions_total"]:
        enrollment["lifecycle_status"] = "COMPLETED"
        touch(enrollment)
        remove_enrollment_memberships(enrollment["id"])


# -------------------------------------------------------------- date-advance sweep

def sweep_date_advance_transitions():
    """Re-evaluate every date-advance transition against the logical clock
    (PRD §2.5): coach credential expiry, installment delinquency -> default,
    cohort OPEN -> IN_PROGRESS -> COMPLETED, session forfeiture. A single
    clock set may legitimately fire chained transitions in one sweep."""
    now = store.clock
    today_d = now.date()

    # Coach: VERIFIED -> EXPIRED once current UTC date reaches credential_expires_on
    # (credential current only on days strictly before that date; PRD §2.7/§3.1).
    # No session cascade on expiry (PRD §3.1).
    for c in store.coaches.values():
        if (c["credential_status"] == "VERIFIED"
                and c["credential_expires_on"] <= today_d):
            c["credential_status"] = "EXPIRED"
            touch(c)

    # Enrollment payment dimension: CURRENT -> DELINQUENT when any PENDING
    # installment's due_on falls behind the current UTC date (PRD §3.3).
    for e in store.enrollments.values():
        if e["payment_status"] != "CURRENT":
            continue
        overdue = [i for i in store.installments.values()
                   if i["enrollment_id"] == e["id"]
                   and i["installment_status"] == "PENDING"
                   and i["due_on"] is not None
                   and i["due_on"] < today_d]
        if overdue:
            for i in overdue:
                i["installment_status"] = "LATE"
            e["payment_status"] = "DELINQUENT"
            touch(e)

    # DELINQUENT -> DEFAULTED after GRACE_DAYS (14) consecutive days delinquent:
    # measured from the earliest still-overdue (LATE) installment's due_on.
    for e in store.enrollments.values():
        if e["payment_status"] != "DELINQUENT":
            continue
        lates = [i for i in store.installments.values()
                 if i["enrollment_id"] == e["id"]
                 and i["installment_status"] == "LATE"
                 and i["due_on"] is not None]
        if lates and (today_d - min(i["due_on"] for i in lates)).days >= calc.GRACE_DAYS:
            e["payment_status"] = "DEFAULTED"
            touch(e)

    # Cohort window progression (dates, closed window end):
    # OPEN -> IN_PROGRESS at window_start; IN_PROGRESS -> COMPLETED past window_end,
    # at which point remaining WAITLISTED memberships -> REMOVED (PRD §3.7).
    for c in store.cohorts.values():
        if c["cohort_status"] == "OPEN" and today_d >= c["window_start"]:
            c["cohort_status"] = "IN_PROGRESS"
            touch(c)
        if c["cohort_status"] == "IN_PROGRESS" and today_d > c["window_end"]:
            c["cohort_status"] = "COMPLETED"
            touch(c)
            for m in memberships_of_cohort(c["id"]):
                if m["member_status"] == "WAITLISTED":
                    m["member_status"] = "REMOVED"

    # Session forfeiture: a session still SCHEDULED when the program window
    # closes -> FORFEITED (reduces sessions_remaining without consuming credit;
    # PRD §3.4). No enrollment version bump is declared for this transition.
    for s in store.sessions.values():
        if s["session_status"] != "SCHEDULED":
            continue
        e = store.enrollments.get(s["enrollment_id"])
        if e is None or e["activated_at"] is None:
            continue
        window_close = e["activated_at"] + timedelta(days=store.tiers[e["program_tier_id"]]["duration_days"])
        if now >= window_close:
            s["session_status"] = "FORFEITED"
            touch(s)
