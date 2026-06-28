"""Domain logic shared across routes: computed-field reconciliation, serialization,
cascades (waitlist promotion, withdraw side-effects), credit issuance.

Every behavior here traces to PRD Section 2.5 (counts/cascades), Section 3.2/3.5/3.6
(withdraw + promotion cascades), Section 3.8 (credit issuance), Section 3.10 (ledger).
"""
from datetime import timedelta

from clock import clock
from db import store, iso, common_fields_on_create, touch
from helpers import parse_datetime

MAKEUP_CREDIT_VALIDITY_DAYS = 60  # scaffold 1.3 makeup_credit_expiry


# ---------------------------------------------------------------------------
# Age — PRD 2.4 / 2.5: whole months elapsed from birthdate to current instant, floor.
# ---------------------------------------------------------------------------
def compute_age_months(birthdate_dt):
    now = clock.now()
    if now < birthdate_dt:
        return 0
    months = (now.year - birthdate_dt.year) * 12 + (now.month - birthdate_dt.month)
    # If the day-of-month (and time) of "now" hasn't reached the birthdate's, the
    # last month isn't complete — subtract one (floor of whole months elapsed).
    if (now.day, now.hour, now.minute, now.second, now.microsecond) < (
        birthdate_dt.day, birthdate_dt.hour, birthdate_dt.minute,
        birthdate_dt.second, birthdate_dt.microsecond):
        months -= 1
    return max(0, months)


# ---------------------------------------------------------------------------
# ClassSession counts — PRD 2.5: full recount, not a delta.
# ---------------------------------------------------------------------------
def reconcile_session_counts(session):
    sid = session["id"]
    enrolled = sum(1 for e in store.enrollments.values()
                   if e["class_session_id"] == sid and e["status"] == "ACTIVE")
    waitlisted = sum(1 for e in store.enrollments.values()
                     if e["class_session_id"] == sid and e["status"] == "WAITLISTED")
    session["enrolled_count"] = enrolled
    session["waitlist_count"] = waitlisted


# ---------------------------------------------------------------------------
# Parent ledger — PRD 2.5 / 3.10.
# outstanding_balance_cents = sum of total_cents over the parent's ISSUED invoices.
# account_standing = PAST_DUE if any ISSUED invoice has reached/passed its due_at.
# ---------------------------------------------------------------------------
def recompute_parent_ledger(parent):
    pid = parent["id"]
    issued = [inv for inv in store.invoices.values()
              if inv["parent_id"] == pid and inv["status"] == "ISSUED"]
    parent["outstanding_balance_cents"] = sum(inv["total_cents"] for inv in issued)
    now = clock.now()
    past_due = False
    for inv in issued:
        due = parse_datetime(inv["due_at"], "due_at")
        if now >= due:
            past_due = True
            break
    parent["account_standing"] = "PAST_DUE" if past_due else "CURRENT"


# ---------------------------------------------------------------------------
# MakeupCredit expiry — PRD 3.8 / scaffold makeup_credit_expiry.
# is_expired = current_utc >= expires_at (boundary instant counts as expired).
# Lazily reflects EXPIRED status on read/redeem.
# ---------------------------------------------------------------------------
def credit_is_expired(credit):
    expires = parse_datetime(credit["expires_at"], "expires_at")
    return clock.now() >= expires


def effective_credit_status(credit):
    """PRD 3.8: when the clock reaches/passes expires_at, the credit is treated
    as EXPIRED on the next read/redeem. Only ISSUED credits flip to EXPIRED;
    REDEEMED credits keep their status."""
    if credit["status"] == "ISSUED" and credit_is_expired(credit):
        return "EXPIRED"
    return credit["status"]


def issue_makeup_credit(student_id, origin_enrollment_id, reason):
    """PRD 3.8: a credit is issued automatically. expires_at = issued_at + 60 days."""
    now = clock.now()
    expires = now + timedelta(days=MAKEUP_CREDIT_VALIDITY_DAYS)
    credit = common_fields_on_create()
    credit.update({
        "student_id": student_id,
        "origin_enrollment_id": origin_enrollment_id,
        "reason": reason,
        "issued_at": iso(now),
        "expires_at": iso(expires),
        "status": "ISSUED",
    })
    store.makeup_credits[credit["id"]] = credit
    return credit


# ---------------------------------------------------------------------------
# Waitlist promotion cascade — PRD 2.5 / 3.2 / 3.6.
# When a seat frees in a session, promote the earliest WAITLISTED enrollment of
# that session (order by joined_at ASC, tie-break created_at ASC) to ACTIVE,
# re-incrementing enrolled_count and charging a fresh prorated tuition basis.
# ---------------------------------------------------------------------------
def promote_waitlist(session):
    """Promote one waitlisted enrollment if a seat is free. The promotion is a
    system action (not client-initiated): account standing is not gated, but
    capacity is. Re-reconciles counts and bumps session version per side-effects."""
    reconcile_session_counts(session)
    if session["enrolled_count"] >= session["capacity"]:
        return None
    sid = session["id"]
    waiting = [e for e in store.enrollments.values()
               if e["class_session_id"] == sid and e["status"] == "WAITLISTED"]
    if not waiting:
        return None
    waiting.sort(key=lambda e: (e["joined_at"], e["created_at"], e["_seq"]))
    promoted = waiting[0]
    promoted["status"] = "ACTIVE"
    # Fresh prorated charge basis: joined_at re-set to current instant.
    promoted["joined_at"] = iso(clock.now())
    promoted["is_prorated_first_cycle"] = _is_prorated_first_cycle(promoted)
    touch(promoted)
    reconcile_session_counts(session)
    touch(session)  # PRD 3.2: re-increments enrolled_count; version bumped.
    return promoted


def _is_prorated_first_cycle(enrollment):
    """PRD 3.6: marker set true when the activating join lands after a cycle
    boundary. Authoritative proration is the invoice formula; here we mark true
    when joined_at is not exactly at midnight (a mid-cycle join heuristic kept
    informational, per scaffold note)."""
    joined = parse_datetime(enrollment["joined_at"], "joined_at")
    return not (joined.hour == 0 and joined.minute == 0 and joined.second == 0
                and joined.microsecond == 0)


# ---------------------------------------------------------------------------
# Enrollment withdraw side-effects — PRD 3.6.
# ---------------------------------------------------------------------------
def withdraw_enrollment(enrollment):
    """Move an enrollment to WITHDRAWN and run its own seat/waitlist side effects.
    Used by direct withdraw and by every cascade (student withdraw, session close,
    level-transfer disruption). Caller is responsible for ownership/state checks."""
    prior = enrollment["status"]
    session = store.class_sessions.get(enrollment["class_session_id"])
    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)
    if session is None:
        return
    if prior == "ACTIVE":
        reconcile_session_counts(session)
        touch(session)  # version++ per PRD 3.6
        promote_waitlist(session)
    elif prior == "WAITLISTED":
        reconcile_session_counts(session)
        touch(session)
    else:  # PAUSED -> WITHDRAWN: no seat held; still bump version per PRD 3.6.
        reconcile_session_counts(session)
        touch(session)


# ---------------------------------------------------------------------------
# Serialization — produce the public JSON view of each entity.
# Computed fields are reconciled at read time where the PRD requires it.
# ---------------------------------------------------------------------------
def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def serialize_location(r):
    out = _common(r)
    out.update({"name": r["name"], "timezone": r["timezone"], "status": r["status"]})
    return out


def serialize_level(r):
    out = _common(r)
    out.update({
        "name": r["name"],
        "sequence_order": r["sequence_order"],
        "next_level_id": r["next_level_id"],
        "min_age_months": r["min_age_months"],
        "max_age_months": r["max_age_months"],
        "max_students_per_instructor": r["max_students_per_instructor"],
        "monthly_tuition_cents": r["monthly_tuition_cents"],
        "readiness_threshold": r["readiness_threshold"],
    })
    return out


def serialize_skill(r):
    out = _common(r)
    out.update({"level_id": r["level_id"], "name": r["name"], "weight": r["weight"]})
    return out


def serialize_instructor(r):
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "certified_level_ids": list(r["certified_level_ids"]),
        "status": r["status"],
    })
    return out


def serialize_parent(r):
    # PRD 3.2 / 2.5: reading a parent recomputes balance and standing.
    recompute_parent_ledger(r)
    out = _common(r)
    out.update({
        "full_name": r["full_name"],
        "email": r["email"],
        "account_standing": r["account_standing"],
        "outstanding_balance_cents": r["outstanding_balance_cents"],
    })
    return out


def serialize_student(r):
    out = _common(r)
    birthdate = parse_datetime(r["birthdate"], "birthdate")
    out.update({
        "parent_id": r["parent_id"],
        "full_name": r["full_name"],
        "birthdate": r["birthdate"],
        "current_level_id": r["current_level_id"],
        # PRD 2.4: age_months recomputed on read against the logical clock.
        "age_months": compute_age_months(birthdate),
        "status": r["status"],
    })
    return out


def serialize_class_session(r):
    # PRD: get/list reconciles enrolled_count/waitlist_count.
    reconcile_session_counts(r)
    out = _common(r)
    out.update({
        "location_id": r["location_id"],
        "level_id": r["level_id"],
        "instructor_id": r["instructor_id"],
        "lane_number": r["lane_number"],
        "day_of_week": r["day_of_week"],
        "start_minute": r["start_minute"],
        "end_minute": r["end_minute"],
        "capacity": r["capacity"],
        "enrolled_count": r["enrolled_count"],
        "waitlist_count": r["waitlist_count"],
        "status": r["status"],
    })
    return out


def serialize_enrollment(r):
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "class_session_id": r["class_session_id"],
        "joined_at": r["joined_at"],
        "tuition_basis_cents": r["tuition_basis_cents"],
        "is_prorated_first_cycle": r["is_prorated_first_cycle"],
        "status": r["status"],
    })
    return out


def serialize_invoice(r):
    out = _common(r)
    out.update({
        "parent_id": r["parent_id"],
        "cycle_start": r["cycle_start"],
        "cycle_end": r["cycle_end"],
        "variant": r["variant"],
        "line_items": [dict(li) for li in r["line_items"]],
        "subtotal_cents": r["subtotal_cents"],
        "discount_cents": r["discount_cents"],
        "total_cents": r["total_cents"],
        "due_at": r["due_at"],
        "status": r["status"],
    })
    return out


def serialize_makeup_credit(r):
    out = _common(r)
    out.update({
        "student_id": r["student_id"],
        "origin_enrollment_id": r["origin_enrollment_id"],
        "reason": r["reason"],
        "issued_at": r["issued_at"],
        "expires_at": r["expires_at"],
        # PRD 3.8: expiry re-evaluated against the clock on read.
        "status": effective_credit_status(r),
    })
    return out


def serialize_makeup_booking(r):
    out = _common(r)
    out.update({
        "makeup_credit_id": r["makeup_credit_id"],
        "student_id": r["student_id"],
        "target_class_session_id": r["target_class_session_id"],
        "occurrence_date": r["occurrence_date"],
        "occurrence_start_minute": r["occurrence_start_minute"],
        "occurrence_end_minute": r["occurrence_end_minute"],
        "status": r["status"],
    })
    return out


def serialize_assessment(r):
    out = _common(r)
    out.update({
        "enrollment_id": r["enrollment_id"],
        "student_id": r["student_id"],
        "assessed_level_id": r["assessed_level_id"],
        "skill_scores": [dict(s) for s in r["skill_scores"]],
        "mastered_count": r["mastered_count"],
        "weighted_score": r["weighted_score"],
        "strict_ready": r["strict_ready"],
        "holistic_ready": r["holistic_ready"],
        "status": r["status"],
    })
    return out
