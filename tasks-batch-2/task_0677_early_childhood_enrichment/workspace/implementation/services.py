"""Business-logic services: lookups, ownership resolution, computed-field
reconciliation, state-machine cascades, and the waitlist engine.

Every mutation to a versioned entity goes through db.touch so updated_at/version
stay consistent. Computed fields are reconciled synchronously (PRD 2.6).
"""
from util import parse_instant
from db import db, stamp_create, touch
import calculations as calc


# ---------------------------------------------------------------------------
# Lookups (existence). Return the row or None; callers raise ERR_NOT_FOUND.
# ---------------------------------------------------------------------------
def get_family(fid):
    return db.families.get(fid)


def get_child(cid):
    return db.children.get(cid)


def get_membership(mid):
    return db.memberships.get(mid)


def get_program(pid):
    return db.programs.get(pid)


def get_room(rid):
    return db.rooms.get(rid)


def get_instructor(iid):
    return db.instructors.get(iid)


def get_session(sid):
    return db.sessions.get(sid)


def get_enrollment(eid):
    return db.enrollments.get(eid)


def get_credit(cid):
    return db.credits.get(cid)


def get_booking(bid):
    return db.bookings.get(bid)


def get_invoice(iid):
    return db.invoices.get(iid)


# ---------------------------------------------------------------------------
# Ownership resolution: resolve any resource back to its owning Family.id.
# ---------------------------------------------------------------------------
def owning_family_of_child(child_row):
    return child_row.get("family_id")


def owning_family_of_membership(m):
    return m.get("family_id")


def owning_family_of_enrollment(e):
    child_row = db.children.get(e.get("child_id"))
    return child_row.get("family_id") if child_row else None


def owning_family_of_credit(credit_row):
    m = db.memberships.get(credit_row.get("membership_id"))
    return m.get("family_id") if m else None


def owning_family_of_invoice(inv):
    m = db.memberships.get(inv.get("membership_id"))
    return m.get("family_id") if m else None


def owning_family_of_booking(b):
    return b.get("family_id")


# ---------------------------------------------------------------------------
# Computed-field reconciliation.
# ---------------------------------------------------------------------------
def reconcile_child_count(family_id):
    """Family.child_count = count of ENROLLED_ELIGIBLE children of the family."""
    fam = db.families.get(family_id)
    if not fam:
        return
    n = sum(
        1 for c in db.children.values()
        if c.get("family_id") == family_id and c.get("status") == "ENROLLED_ELIGIBLE"
    )
    fam["child_count"] = n


def reconcile_credit_balance(membership_id):
    """Membership.makeup_credit_balance = count of AVAILABLE credits."""
    m = db.memberships.get(membership_id)
    if not m:
        return
    n = sum(
        1 for cr in db.credits.values()
        if cr.get("membership_id") == membership_id and cr.get("status") == "AVAILABLE"
    )
    m["makeup_credit_balance"] = n


# ---------------------------------------------------------------------------
# Waitlist engine.
# ---------------------------------------------------------------------------
def _session_enrollments(session_id):
    return [e for e in db.enrollments.values() if e.get("session_id") == session_id]


def max_waitlist_seq(session_id):
    seqs = [
        e["waitlist_seq"] for e in _session_enrollments(session_id)
        if e.get("status") == "WAITLISTED" and e.get("waitlist_seq") is not None
    ]
    return max(seqs) if seqs else 0


def promote_next_waitlisted(session_row):
    """Promote the lowest-waitlist_seq WAITLISTED row (created_at ASC tie-break)
    while a seat is free. Each promotion increments enrolled_count and clears the
    promoted row's waitlist_seq. Returns the promoted enrollment row or None.

    Promotion does NOT itself bump the session version beyond what the caller's
    seat-freeing transition already does; the session row's version is bumped by
    the caller. The promoted enrollment row is touched (its own version bump).
    """
    if session_row.get("enrolled_count", 0) >= session_row.get("capacity", 0):
        return None
    waitlisted = [
        e for e in _session_enrollments(session_row["id"])
        if e.get("status") == "WAITLISTED"
    ]
    if not waitlisted:
        return None
    waitlisted.sort(key=lambda e: (e.get("waitlist_seq", 0), e.get("_seq", 0)))
    promoted = waitlisted[0]
    promoted["status"] = "ENROLLED"
    promoted["waitlist_seq"] = None
    touch(promoted)
    session_row["enrolled_count"] = session_row.get("enrolled_count", 0) + 1
    return promoted


# ---------------------------------------------------------------------------
# Enrollment cancellation primitive (used by direct cancel + every cascade).
# ---------------------------------------------------------------------------
def cancel_enrollment_row(enr, promote=True):
    """Transition an ENROLLED/WAITLISTED enrollment to CANCELLED.

    For a formerly-ENROLLED row, decrement the host session's enrolled_count and
    (when promote=True) promote the next waitlisted row, then bump the session
    version. For a WAITLISTED row, no seat count changes but the session version
    is still bumped. The enrollment row itself is touched.
    """
    was_enrolled = enr.get("status") == "ENROLLED"
    enr["status"] = "CANCELLED"
    enr["waitlist_seq"] = None
    touch(enr)
    session_row = db.sessions.get(enr.get("session_id"))
    if session_row is None:
        return
    if was_enrolled:
        session_row["enrolled_count"] = max(0, session_row.get("enrolled_count", 0) - 1)
        if promote:
            promote_next_waitlisted(session_row)
    touch(session_row)


# ---------------------------------------------------------------------------
# Membership-cancel cascade (PRD 3.2).
# ---------------------------------------------------------------------------
def cancel_membership_cascade(m, was_active):
    """Expire AVAILABLE credits, (if active) cancel enrollments billed to the
    membership, void the current OPEN invoice, then bump membership version.
    """
    # All AVAILABLE credits -> EXPIRED; balance reconciled to 0.
    for cr in db.credits.values():
        if cr.get("membership_id") == m["id"] and cr.get("status") == "AVAILABLE":
            cr["status"] = "EXPIRED"
    reconcile_credit_balance(m["id"])

    # From an ACTIVE membership, cancel its ENROLLED/WAITLISTED enrollments.
    if was_active:
        targets = [
            e for e in db.enrollments.values()
            if e.get("membership_id") == m["id"]
            and e.get("status") in ("ENROLLED", "WAITLISTED")
        ]
        # Stable order for deterministic waitlist promotion.
        targets.sort(key=lambda e: e.get("_seq", 0))
        for e in targets:
            cancel_enrollment_row(e, promote=True)

    # Void the current OPEN invoice(s) for this membership.
    for inv in db.invoices.values():
        if inv.get("membership_id") == m["id"] and inv.get("status") == "OPEN":
            inv["status"] = "VOID"
            touch(inv)

    m["status"] = "CANCELLED"
    touch(m)


# ---------------------------------------------------------------------------
# Session-cancel cascade (PRD 3.3, three-depth).
# ---------------------------------------------------------------------------
def cancel_session_cascade(session_row):
    """CANCELLED branch: EXCUSED attendance for ENROLLED RECURRING, mint one
    credit per excused record (bump membership balance+version), then cancel all
    ENROLLED/WAITLISTED enrollments and zero enrolled_count, bump session version.
    """
    program = db.programs.get(session_row.get("program_id"))
    issued_tuition = program.get("tuition_cents", 0) if program else 0
    ttl = calc.CREDIT_TTL_DAYS

    enrollments = _session_enrollments(session_row["id"])
    enrollments.sort(key=lambda e: e.get("_seq", 0))

    # depth-1 + depth-2 + depth-3: EXCUSED records and minted credits for
    # ENROLLED RECURRING enrollments only (TRIAL never earns a credit).
    for e in enrollments:
        if e.get("status") == "ENROLLED" and e.get("kind") == "RECURRING":
            att = stamp_create({
                "enrollment_id": e["id"],
                "session_id": session_row["id"],
                "outcome": "EXCUSED",
            }, versioned=False)
            db.attendance[att["id"]] = att

            from datetime import timedelta
            from clock import clock
            from util import iso_ms
            expires = iso_ms(clock.now() + timedelta(days=ttl))
            cr = stamp_create({
                "membership_id": e["membership_id"],
                "source_attendance_id": att["id"],
                "issued_tuition_cents": issued_tuition,
                "status": "AVAILABLE",
                "expires_at": expires,
            }, versioned=False)
            db.credits[cr["id"]] = cr
            # depth-3: bump membership balance + version.
            reconcile_credit_balance(e["membership_id"])
            m = db.memberships.get(e["membership_id"])
            if m:
                touch(m)

    # Independently: cancel every ENROLLED/WAITLISTED enrollment; enrolled_count -> 0.
    for e in enrollments:
        if e.get("status") in ("ENROLLED", "WAITLISTED"):
            e["status"] = "CANCELLED"
            e["waitlist_seq"] = None
            touch(e)
    session_row["enrolled_count"] = 0
    session_row["status"] = "CANCELLED"
    touch(session_row)


# ---------------------------------------------------------------------------
# Session-hold cascade (PRD 3.3, HELD branch).
# ---------------------------------------------------------------------------
def hold_session_cascade(session_row, attendance_map):
    """HELD branch: one AttendanceRecord per ENROLLED enrollment with the
    supplied outcome (PRESENT/ABSENT); enrollments omitted default to ABSENT. No
    credits minted. Bump session version. attendance_map is keyed by enrollment
    id -> outcome.
    """
    enrollments = _session_enrollments(session_row["id"])
    enrollments.sort(key=lambda e: e.get("_seq", 0))
    for e in enrollments:
        if e.get("status") != "ENROLLED":
            continue
        outcome = attendance_map.get(e["id"], "ABSENT")
        att = stamp_create({
            "enrollment_id": e["id"],
            "session_id": session_row["id"],
            "outcome": outcome,
        }, versioned=False)
        db.attendance[att["id"]] = att
    session_row["status"] = "HELD"
    touch(session_row)


# ---------------------------------------------------------------------------
# Child withdraw cascade (PRD 3.1).
# ---------------------------------------------------------------------------
def withdraw_child_cascade(child_row):
    """Set child WITHDRAWN, cancel its ENROLLED/WAITLISTED enrollments (promote
    waitlist for freed seats), reconcile family child_count.
    """
    targets = [
        e for e in db.enrollments.values()
        if e.get("child_id") == child_row["id"]
        and e.get("status") in ("ENROLLED", "WAITLISTED")
    ]
    targets.sort(key=lambda e: e.get("_seq", 0))
    for e in targets:
        cancel_enrollment_row(e, promote=True)
    child_row["status"] = "WITHDRAWN"
    touch(child_row)
    reconcile_child_count(child_row["family_id"])


# ---------------------------------------------------------------------------
# Child advancement cascade (PRD 3.1).
# ---------------------------------------------------------------------------
def advance_child_cascade(child_row, target_program):
    """Set current_level to target program level_index; demote off-level ENROLLED
    RECURRING enrollments to WAITLISTED, freeing seats and promoting waitlists.
    """
    new_level = target_program.get("level_index")
    child_row["current_level"] = new_level
    touch(child_row)

    targets = [
        e for e in db.enrollments.values()
        if e.get("child_id") == child_row["id"]
        and e.get("status") == "ENROLLED"
        and e.get("kind") == "RECURRING"
    ]
    targets.sort(key=lambda e: e.get("_seq", 0))
    for e in targets:
        session_row = db.sessions.get(e.get("session_id"))
        if session_row is None:
            continue
        program = db.programs.get(session_row.get("program_id"))
        if program is None:
            continue
        if program.get("level_index") == new_level:
            continue  # still on-level; keep the standing seat
        # Demote ENROLLED -> WAITLISTED.
        e["status"] = "WAITLISTED"
        e["waitlist_seq"] = max_waitlist_seq(session_row["id"]) + 1
        touch(e)
        session_row["enrolled_count"] = max(0, session_row.get("enrolled_count", 0) - 1)
        promote_next_waitlisted(session_row)
        touch(session_row)


# ---------------------------------------------------------------------------
# Scheduling overlap checks (PRD 2.10, 2.11).
# ---------------------------------------------------------------------------
def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Strict half-open overlap: [a_start,a_end) vs [b_start,b_end). Adjacency
    (a_end == b_start) does NOT overlap.
    """
    return a_start < b_end and b_start < a_end


def instructor_conflict(instructor_row, new_start, new_end, exclude_session_id=None):
    """True if the new session, expanded by buffer_minutes on each side, overlaps
    any other non-CANCELLED session of the same instructor.
    """
    from datetime import timedelta
    buf = timedelta(minutes=instructor_row.get("buffer_minutes", 15))
    exp_start = new_start - buf
    exp_end = new_end + buf
    for s in db.sessions.values():
        if s.get("instructor_id") != instructor_row["id"]:
            continue
        if s.get("status") == "CANCELLED":
            continue
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        s_start = parse_instant(s["start_at"])
        s_end = parse_instant(s["end_at"])
        if _intervals_overlap(exp_start, exp_end, s_start, s_end):
            return True
    return False


def room_conflict_for_session(room_row, new_start, new_end):
    """True if a session (exclusive room hold) strictly overlaps any non-CANCELLED
    session or non-CANCELLED BIRTHDAY_PARTY booking on the room.
    """
    for s in db.sessions.values():
        if s.get("room_id") != room_row["id"]:
            continue
        if s.get("status") == "CANCELLED":
            continue
        if _intervals_overlap(new_start, new_end, parse_instant(s["start_at"]), parse_instant(s["end_at"])):
            return True
    for b in db.bookings.values():
        if b.get("room_id") != room_row["id"]:
            continue
        if b.get("status") == "CANCELLED":
            continue
        if b.get("booking_type") != "BIRTHDAY_PARTY":
            continue
        if _intervals_overlap(new_start, new_end, parse_instant(b["start_at"]), parse_instant(b["end_at"])):
            return True
    return False


def room_conflict_for_booking(room_row, booking_type, new_start, new_end, head_count):
    """Room overlap rule for a facility booking (PRD 2.10 / 3.8).

    BIRTHDAY_PARTY holds the room exclusively: conflicts with any non-CANCELLED
    session or non-CANCELLED BIRTHDAY_PARTY that strictly overlaps.
    OPEN_GYM is shared: it conflicts only if the summed head_count of overlapping
    CONFIRMED OPEN_GYM bookings (including this one) exceeds physical_capacity, OR
    if it strictly overlaps a non-CANCELLED session or a BIRTHDAY_PARTY (those
    hold the room exclusively).
    """
    if booking_type == "BIRTHDAY_PARTY":
        return room_conflict_for_session(room_row, new_start, new_end)

    # OPEN_GYM: first, exclusive holders block it.
    for s in db.sessions.values():
        if s.get("room_id") != room_row["id"] or s.get("status") == "CANCELLED":
            continue
        if _intervals_overlap(new_start, new_end, parse_instant(s["start_at"]), parse_instant(s["end_at"])):
            return True
    for b in db.bookings.values():
        if b.get("room_id") != room_row["id"] or b.get("status") == "CANCELLED":
            continue
        if b.get("booking_type") == "BIRTHDAY_PARTY":
            if _intervals_overlap(new_start, new_end, parse_instant(b["start_at"]), parse_instant(b["end_at"])):
                return True

    # Shared capacity: sum head_count of overlapping CONFIRMED OPEN_GYM + this one.
    overlapping_sum = head_count
    for b in db.bookings.values():
        if b.get("room_id") != room_row["id"]:
            continue
        if b.get("status") != "CONFIRMED" or b.get("booking_type") != "OPEN_GYM":
            continue
        if _intervals_overlap(new_start, new_end, parse_instant(b["start_at"]), parse_instant(b["end_at"])):
            overlapping_sum += b.get("head_count", 1)
    return overlapping_sum > room_row.get("physical_capacity", 0)
