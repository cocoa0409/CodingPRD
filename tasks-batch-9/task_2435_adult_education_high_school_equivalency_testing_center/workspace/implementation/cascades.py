"""Compliance cascades: every chain runs to completion inside the request."""

from decimal import Decimal

import calc
from core import (
    by_created,
    clock,
    decrement_active_enrollment,
    fmt_clock,
    hours_out,
    q2,
    recompute_student_hours,
    recount_section_seats,
    store,
    touch,
)


# --------------------------------------------------------------------------
# money helpers
# --------------------------------------------------------------------------

def return_committed_cents(outcome):
    """Give a committed outcome line's cents back to its funding period."""
    if outcome["allocation_status"] != "COMMITTED":
        return
    amount = outcome["allocated_cents"]
    period = store.periods.get(outcome["funding_period_id"])
    outcome["allocation_status"] = "REVOKED"
    outcome["allocated_cents"] = 0
    if period is not None:
        period["committed_cents"] -= amount
        period["available_cents"] = period["total_cents"] - period["committed_cents"]
        touch(period)


def rescind_outcome(outcome, reason):
    outcome["status"] = "RESCINDED"
    outcome["rescission_reason"] = reason
    return_committed_cents(outcome)
    touch(outcome)


def refund_registration(registration, session, terminal_status):
    """Release a live seat and hand the voucher cents back to the learner."""
    refund = registration["voucher_applied_cents"]
    fee_due = registration["fee_due_cents"]
    registration["registration_status"] = terminal_status
    registration["refunded_cents"] = refund
    touch(registration)

    if session is not None and session["seats_taken"] > 0:
        session["seats_taken"] -= 1

    student = store.students.get(registration["student_id"])
    if student is not None:
        student["voucher_balance_cents"] += refund
        student["voucher_spent_cents"] -= refund
        student["exam_fee_owed_cents"] -= fee_due
        touch(student)


def live_registrations(session_id):
    return by_created([
        r for r in store.registrations.values()
        if r["exam_session_id"] == session_id
        and r["registration_status"] == "REGISTERED"
    ])


# --------------------------------------------------------------------------
# exam-session cancellation
# --------------------------------------------------------------------------

def cancel_session(session, reason):
    session["status"] = "CANCELLED"
    session["cancel_reason"] = reason
    proctor_id = session.get("proctor_id")
    if proctor_id:
        proctor = store.proctors.get(proctor_id)
        if proctor is not None and proctor["assigned_session_count"] > 0:
            proctor["assigned_session_count"] -= 1
            touch(proctor)
    for registration in live_registrations(session["id"]):
        refund_registration(registration, session, "CANCELLED_BY_CENTER")
    touch(session)


# --------------------------------------------------------------------------
# centre suspension
# --------------------------------------------------------------------------

def suspend_center(center, reason):
    center["authorization_status"] = "SUSPENDED"
    center["suspended_reason"] = reason
    center["allowed_subtests"] = []
    center["max_sessions_per_week"] = 0

    # link 1: ACTIVE rooms -> OUT_OF_SERVICE
    rooms = by_created([
        r for r in store.rooms.values()
        if r["testing_center_id"] == center["id"] and r["status"] == "ACTIVE"
    ])
    room_ids = set()
    for room in rooms:
        room["status"] = "OUT_OF_SERVICE"
        room_ids.add(room["id"])
        touch(room)

    # links 2-4: DRAFT|SCHEDULED sessions in those rooms are cancelled
    sessions = by_created([
        s for s in store.sessions.values()
        if s["testing_room_id"] in room_ids
        and s["status"] in ("DRAFT", "SCHEDULED")
    ])
    for session in sessions:
        cancel_session(session, "CENTER_SUSPENDED")

    touch(center)


# --------------------------------------------------------------------------
# section closure
# --------------------------------------------------------------------------

def close_section(section):
    section["status"] = "CLOSED"
    enrollments = by_created([
        e for e in store.enrollments.values()
        if e["class_section_id"] == section["id"] and e["status"] == "ACTIVE"
    ])
    for enrollment in enrollments:
        if enrollment["_posted_hours"] >= calc.MIN_POST_TEST_HOURS:
            enrollment["status"] = "COMPLETED"
        else:
            enrollment["status"] = "WITHDRAWN"
            enrollment["withdrawn_at"] = fmt_clock(clock())
        enrollment["exit_reason"] = "SECTION_CLOSED"
        touch(enrollment)
        if section["seats_taken"] > 0:
            section["seats_taken"] -= 1
        student = store.students.get(enrollment["student_id"])
        if student is not None:
            decrement_active_enrollment(student)
    recount_section_seats(section)
    touch(section)


# --------------------------------------------------------------------------
# attendance void
# --------------------------------------------------------------------------

def void_attendance(entry, reason):
    enrollment = store.enrollments[entry["enrollment_id"]]
    student = store.students.get(enrollment["student_id"])

    entry["status"] = "VOIDED"
    entry["void_reason"] = reason
    touch(entry)

    # link 1: hour ledgers
    was_at_threshold = enrollment["_posted_hours"] >= calc.MIN_POST_TEST_HOURS
    enrollment["_posted_hours"] = q2(enrollment["_posted_hours"] - entry["_hours"])
    if enrollment["_posted_hours"] < 0:
        enrollment["_posted_hours"] = Decimal("0.00")
    enrollment["posted_hours"] = hours_out(enrollment["_posted_hours"])
    enrollment["post_test_eligible"] = calc.hours_gate_ok(enrollment)
    touch(enrollment)
    if student is not None:
        recompute_student_hours(student)
        touch(student)

    crossed_below = was_at_threshold and not calc.hours_gate_ok(enrollment)
    if not crossed_below:
        return

    # link 2: post-tests lose their hour basis
    events = by_created([
        e for e in store.test_events.values()
        if e.get("enrollment_id") == enrollment["id"]
        and e["purpose"] == "POST_TEST"
        and e["status"] in ("SCHEDULED", "SCORED")
    ])
    if not events:
        return
    for event in events:
        event["status"] = "INVALIDATED"
        event["invalidation_reason"] = "HOURS_WITHDRAWN"
        touch(event)

    # links 3-4: standing EFL_GAIN claims are re-tested under the audited reading
    if student is None:
        return
    outcomes = by_created([
        o for o in store.outcomes.values()
        if o["student_id"] == student["id"]
        and o["measure_type"] == "EFL_GAIN"
        and o["status"] in ("RECORDED", "CERTIFIED")
    ])
    for outcome in outcomes:
        period = store.periods.get(outcome["funding_period_id"])
        result = calc.msg_determination(student["id"], "LATEST_POST", period)
        if not result["msg_achieved"]:
            rescind_outcome(outcome, "POST_TEST_INVALIDATED")


# --------------------------------------------------------------------------
# proctor revocation
# --------------------------------------------------------------------------

def revoke_proctor(proctor):
    proctor["certification_status"] = "REVOKED"
    proctor["assigned_session_count"] = 0
    touch(proctor)

    # link 1: SCHEDULED sittings revert to DRAFT and lose their supervisor
    sessions = by_created([
        s for s in store.sessions.values()
        if s.get("proctor_id") == proctor["id"] and s["status"] == "SCHEDULED"
    ])
    reverted_ids = set(s["id"] for s in sessions)

    # link 2b snapshot must be taken before link 1 clears anything
    invalidated = by_created([
        r for r in store.registrations.values()
        if r.get("identity_verified_by_proctor_id") == proctor["id"]
        and r["registration_status"] == "SCORED"
    ])
    reset_identity = by_created([
        r for r in store.registrations.values()
        if r["exam_session_id"] in reverted_ids
        and r["identity_status"] == "VERIFIED"
    ])

    for session in sessions:
        session["status"] = "DRAFT"
        session["proctor_id"] = None
        touch(session)

    # link 2a: identity resets on the reverted sittings
    for registration in reset_identity:
        registration["identity_status"] = "UNVERIFIED"
        registration["identity_verified_by_proctor_id"] = None
        touch(registration)

    # link 2b: results witnessed by the revoked proctor stop counting
    invalidated_ids = set()
    for registration in invalidated:
        registration["registration_status"] = "RESULT_INVALIDATED"
        invalidated_ids.add(registration["id"])
        touch(registration)

    if not invalidated_ids:
        return

    # link 3: credentials resting on those results are voided
    credentials = by_created([
        c for c in store.credentials.values()
        if c["status"] == "ISSUED"
        and any(rid in invalidated_ids for rid in c.get("qualifying_registration_ids", []))
    ])
    voided_ids = set()
    for credential in credentials:
        credential["status"] = "VOIDED"
        credential["void_reason"] = "PROCTOR_REVOKED"
        voided_ids.add(credential["id"])
        touch(credential)
        holder = store.students.get(credential["student_id"])
        if holder is not None:
            holder["credential_status"] = "REVOKED"
            touch(holder)

    if not voided_ids:
        return

    # link 4a: queued transcript orders are held
    orders = by_created([
        o for o in store.transcripts.values()
        if o["status"] == "QUEUED" and o.get("credential_issuance_id") in voided_ids
    ])
    for order in orders:
        order["status"] = "HELD"
        order["hold_reason"] = "CREDENTIAL_VOIDED"
        touch(order)

    # link 4b + link 5: outcome claims are rescinded and their cents returned
    outcomes = by_created([
        o for o in store.outcomes.values()
        if o.get("credential_issuance_id") in voided_ids
        and o["status"] in ("RECORDED", "CERTIFIED")
    ])
    for outcome in outcomes:
        rescind_outcome(outcome, "CREDENTIAL_VOIDED")
