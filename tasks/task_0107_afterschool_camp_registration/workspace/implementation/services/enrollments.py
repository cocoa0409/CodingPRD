"""Enrollment business logic: age check, capacity, sibling discount,
scholarship allocation, snapshotting, cancellation cascades, waitlist promotion.

Implements:
  - calc: child_age_on_reference_date (PIN: chronological — re-uses original creation snapshot)
  - calc: sibling_discount (per-line round-half-up)
  - calc: scholarship_allocation (waterfall, specific→ANY, larger remaining first, earlier created_at)
  - calc: weekly_capacity_check (strict <)
  - state machines: PENDING_AUTH→{CONFIRMED|WAITLISTED}, WAITLISTED→CONFIRMED (system),
    PENDING_AUTH/WAITLISTED/CONFIRMED→CANCELLED, CONFIRMED→COMPLETED (system).
"""

from datetime import timedelta

from clock import clock, parse_iso_date
from config import (
    SCHOLARSHIP_KINDS,
    TIER_PCT,
    TIER_PCT_4_PLUS,
    DAYS_PER_YEAR,
)
from db import db, init_common_fields, now_iso_virtual, touch
from errors import APIError
from money import apply_pct
from services.projection import project_child_auth_statuses


# ---------- Age computation (calc: child_age_on_reference_date) ----------

def compute_age_on_reference_date(child_dob_iso, reference_date_iso):
    """floor((reference_date - dob) / 365.2425 days)"""
    dob = parse_iso_date(child_dob_iso)
    ref = parse_iso_date(reference_date_iso)
    delta_days = (ref - dob).days
    return int(delta_days // DAYS_PER_YEAR)


def assert_age_in_range(child, session):
    age = compute_age_on_reference_date(child["date_of_birth"], session["reference_date"])
    if not (session["age_min"] <= age <= session["age_max"]):
        raise APIError(
            "ERR_AGE_OUT_OF_RANGE",
            f"Child age {age} on reference_date is outside [{session['age_min']}, {session['age_max']}].",
        )


# ---------- Capacity counting ----------

def count_confirmed_in_week(session_id, week_index, exclude_id=None):
    return sum(
        1
        for e in db.enrollments.values()
        if e["session_id"] == session_id
        and e["week_index"] == week_index
        and e["status"] == "CONFIRMED"
        and e["id"] != exclude_id
    )


def max_waitlist_position(session_id, week_index):
    positions = [
        e.get("waitlist_position") or 0
        for e in db.enrollments.values()
        if e["session_id"] == session_id
        and e["week_index"] == week_index
        and e["status"] == "WAITLISTED"
    ]
    return max(positions) if positions else 0


# ---------- Sibling discount (calc: sibling_discount) ----------

def sibling_tier_pct(n):
    if n >= 4:
        return TIER_PCT_4_PLUS
    return TIER_PCT[n]


def family_confirmed_siblings_in_week(family_id, session_id, week_index, include_id=None):
    """Return the list of currently-CONFIRMED enrollments belonging to the given family,
    in the same (session_id, week_index). If include_id is supplied (and the row is currently
    PENDING_AUTH/WAITLISTED about to be confirmed), include it.
    """
    rows = []
    for e in db.enrollments.values():
        if e["session_id"] != session_id or e["week_index"] != week_index:
            continue
        child = db.children.get(e["child_id"])
        if not child or child["family_id"] != family_id:
            continue
        if e["status"] == "CONFIRMED":
            rows.append(e)
        elif include_id is not None and e["id"] == include_id:
            rows.append(e)
    return rows


def recompute_sibling_for_row(enrollment):
    """Recompute sibling_discount_cents + final_fee_cents for one CONFIRMED row,
    given the current family confirmed sibling count in its (session, week).
    Bumps version + updated_at.
    """
    child = db.children[enrollment["child_id"]]
    family_id = child["family_id"]
    siblings = family_confirmed_siblings_in_week(
        family_id, enrollment["session_id"], enrollment["week_index"]
    )
    n = len(siblings)
    pct = sibling_tier_pct(n)
    new_sibling_discount = apply_pct(enrollment["list_fee_cents"], pct)
    # final_fee = max(0, list - sibling - scholarship)
    new_final = max(
        0,
        enrollment["list_fee_cents"]
        - new_sibling_discount
        - enrollment["scholarship_discount_cents"],
    )
    changed = (
        enrollment["sibling_discount_cents"] != new_sibling_discount
        or enrollment["final_fee_cents"] != new_final
    )
    enrollment["sibling_discount_cents"] = new_sibling_discount
    enrollment["final_fee_cents"] = new_final
    if changed:
        touch(enrollment)


def recompute_sibling_for_family_week(family_id, session_id, week_index):
    """Recompute sibling_discount on every CONFIRMED enrollment of the family in this (session, week)."""
    rows = family_confirmed_siblings_in_week(family_id, session_id, week_index)
    for r in rows:
        recompute_sibling_for_row(r)


# ---------- Scholarship allocation (calc: scholarship_allocation) ----------

def _eligible_awards_for_family(family_id, session_kind):
    rows = []
    for a in db.scholarships.values():
        if a["family_id"] != family_id:
            continue
        if a["status"] != "ACTIVE":
            continue
        if a["granted_for_kind"] not in {session_kind, "ANY"}:
            continue
        remaining = a["total_credit_cents"] - a["consumed_credit_cents"]
        if remaining < 1:
            continue
        rows.append(a)
    return rows


def _order_awards(awards, session_kind):
    """Specific kind first, then larger remaining first, then earlier created_at."""
    def key(a):
        specific_first = 0 if a["granted_for_kind"] == session_kind else 1
        remaining = a["total_credit_cents"] - a["consumed_credit_cents"]
        return (specific_first, -remaining, a["created_at"])
    return sorted(awards, key=key)


def compute_scholarship_allocation(family_id, session_kind, net_payable_cents):
    """Return (scholarship_discount_cents, scholarship_award_id-or-None).

    Selects the FIRST award (by ordering) with remaining >= 1 cent, allocates min(remaining, net_payable).
    """
    if net_payable_cents <= 0:
        return 0, None
    awards = _eligible_awards_for_family(family_id, session_kind)
    if not awards:
        return 0, None
    ordered = _order_awards(awards, session_kind)
    for a in ordered:
        remaining = a["total_credit_cents"] - a["consumed_credit_cents"]
        if remaining >= 1:
            allocated = min(remaining, net_payable_cents)
            return allocated, a["id"]
    return 0, None


# ---------- Snapshot (run at confirm) ----------

def _run_confirm_snapshot(enrollment):
    """Compute and snapshot list_fee, sibling_discount, scholarship_discount, final_fee.
    Apply scholarship credit consumption and EXHAUSTED auto-transition.
    Then cascade sibling recompute on already-CONFIRMED siblings.
    """
    session = db.sessions[enrollment["session_id"]]
    child = db.children[enrollment["child_id"]]
    family_id = child["family_id"]

    # 1. list_fee
    enrollment["list_fee_cents"] = session["base_weekly_fee_cents"]

    # 2. sibling discount — N includes the about-to-be-confirmed row itself.
    siblings = family_confirmed_siblings_in_week(
        family_id, session["id"], enrollment["week_index"], include_id=enrollment["id"]
    )
    n_self = len(siblings)
    pct = sibling_tier_pct(n_self)
    enrollment["sibling_discount_cents"] = apply_pct(enrollment["list_fee_cents"], pct)

    # 3. scholarship allocation against net_payable = list - sibling
    net_payable = enrollment["list_fee_cents"] - enrollment["sibling_discount_cents"]
    sch_amt, award_id = compute_scholarship_allocation(family_id, session["kind"], net_payable)
    enrollment["scholarship_discount_cents"] = sch_amt
    enrollment["scholarship_award_id"] = award_id

    # 4. final fee
    enrollment["final_fee_cents"] = max(
        0,
        enrollment["list_fee_cents"]
        - enrollment["sibling_discount_cents"]
        - enrollment["scholarship_discount_cents"],
    )

    # Apply scholarship consumption + EXHAUSTED auto-transition
    if award_id is not None and sch_amt > 0:
        award = db.scholarships[award_id]
        new_consumed = award["consumed_credit_cents"] + sch_amt
        if new_consumed > award["total_credit_cents"]:
            # Concurrency overflow
            raise APIError("ERR_SCHOLARSHIP_EXHAUSTED")
        award["consumed_credit_cents"] = new_consumed
        if new_consumed == award["total_credit_cents"]:
            award["status"] = "EXHAUSTED"
        touch(award)

    # After this row is set CONFIRMED upstream, the cascade on already-CONFIRMED
    # siblings must run. We do that in the caller (after status flip).


def _cascade_sibling_recompute_excluding_self(enrollment):
    """For every OTHER CONFIRMED sibling in same (session, week_index), recompute their sibling_discount."""
    child = db.children[enrollment["child_id"]]
    family_id = child["family_id"]
    rows = family_confirmed_siblings_in_week(
        family_id, enrollment["session_id"], enrollment["week_index"]
    )
    for r in rows:
        if r["id"] == enrollment["id"]:
            continue
        recompute_sibling_for_row(r)


# ---------- Create Enrollment (PENDING_AUTH) ----------

def create_enrollment(child_id, session_id, week_index):
    """Validate, then create PENDING_AUTH row."""
    if child_id not in db.children:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Child not found.")
    if session_id not in db.sessions:
        raise APIError("ERR_RESOURCE_NOT_FOUND", "Session not found.")
    child = db.children[child_id]
    session = db.sessions[session_id]

    if not isinstance(week_index, int) or isinstance(week_index, bool):
        raise APIError("ERR_VALIDATION", "week_index must be an integer.")

    # PRD §2.9 ordering: age (ERR_AGE_OUT_OF_RANGE) BEFORE week-index
    # (ERR_INVALID_WEEK_INDEX) inside the domain-constraint band.
    assert_age_in_range(child, session)

    if week_index < 0 or week_index >= session["week_count"]:
        raise APIError("ERR_INVALID_WEEK_INDEX")

    # Duplicate enrollment (priority 14 — ERR_DUPLICATE_ENROLLMENT)
    for e in db.enrollments.values():
        if (
            e["child_id"] == child_id
            and e["session_id"] == session_id
            and e["week_index"] == week_index
            and e["status"] in {"PENDING_AUTH", "CONFIRMED", "WAITLISTED"}
        ):
            raise APIError("ERR_DUPLICATE_ENROLLMENT")

    row = init_common_fields(
        {
            "child_id": child_id,
            "session_id": session_id,
            "week_index": week_index,
            "status": "PENDING_AUTH",
            "list_fee_cents": 0,
            "sibling_discount_cents": 0,
            "scholarship_discount_cents": 0,
            "final_fee_cents": 0,
            "scholarship_award_id": None,
            "waitlist_position": None,
            "cancelled_at": None,
        }
    )
    db.enrollments[row["id"]] = row
    return row


# ---------- Confirm ----------

def confirm_enrollment(enrollment_id):
    """Per state machine: PENDING_AUTH → CONFIRMED or PENDING_AUTH → WAITLISTED.

    Validation order follows PRD §2.9: state (Session=OPEN), safety triad,
    age check, capacity (which decides CONFIRMED vs WAITLISTED).
    """
    e = db.enrollments[enrollment_id]

    if e["status"] != "PENDING_AUTH":
        raise APIError("ERR_INVALID_STATE")

    session = db.sessions[e["session_id"]]

    # Session must be OPEN — ERR_INVALID_STATE
    if session["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE", "Session is not OPEN.")

    child = db.children[e["child_id"]]

    # Re-project authorization statuses to be safe (no clock advance happened
    # but a revoke may have).
    project_child_auth_statuses(child, persist=False)

    # Safety triad (priorities 6, 7, 8)
    if child["medical_authorization_status"] != "ACTIVE":
        raise APIError("ERR_MEDICAL_AUTH_REQUIRED")
    if child["pickup_authorization_status"] != "ACTIVE":
        raise APIError("ERR_PICKUP_AUTH_REQUIRED")
    if child["emergency_contact_count"] < 1:
        raise APIError("ERR_EMERGENCY_CONTACT_REQUIRED")

    # Age check (priority 10) — chronological reading, against current session.reference_date
    assert_age_in_range(child, session)

    # Capacity gate (calc: weekly_capacity_check; strict <)
    confirmed_count = count_confirmed_in_week(session["id"], e["week_index"])
    if confirmed_count >= session["weekly_capacity"]:
        # Normal-path WAITLIST
        e["status"] = "WAITLISTED"
        e["waitlist_position"] = max_waitlist_position(session["id"], e["week_index"]) + 1
        touch(e)
        return e

    # Snapshot + confirm
    _run_confirm_snapshot(e)
    e["status"] = "CONFIRMED"
    e["waitlist_position"] = None
    touch(e)

    # Cascade sibling recompute on already-CONFIRMED siblings (other than self)
    _cascade_sibling_recompute_excluding_self(e)
    return e


# ---------- Cancellation ----------

def _renumber_waitlist(session_id, week_index):
    """Renumber WAITLISTED rows in (session, week_index) to be contiguous starting at 1
    ordered by current waitlist_position ascending (ties by created_at).
    """
    rows = [
        e
        for e in db.enrollments.values()
        if e["session_id"] == session_id
        and e["week_index"] == week_index
        and e["status"] == "WAITLISTED"
    ]
    rows.sort(key=lambda r: (r.get("waitlist_position") or 0, r["created_at"]))
    for i, r in enumerate(rows, start=1):
        if r.get("waitlist_position") != i:
            r["waitlist_position"] = i
            touch(r)


def _refund_scholarship_on_cancel(enrollment):
    """Refund the snapshotted scholarship credit. EXHAUSTED→ACTIVE if applicable."""
    if not enrollment.get("scholarship_award_id"):
        return
    if enrollment["scholarship_discount_cents"] <= 0:
        return
    award = db.scholarships.get(enrollment["scholarship_award_id"])
    if not award:
        return
    award["consumed_credit_cents"] -= enrollment["scholarship_discount_cents"]
    if award["consumed_credit_cents"] < 0:
        award["consumed_credit_cents"] = 0
    if award["status"] == "EXHAUSTED" and award["consumed_credit_cents"] < award["total_credit_cents"]:
        award["status"] = "ACTIVE"
    touch(award)


def _try_promote_waitlist(session_id, week_index):
    """After a CONFIRMED cancellation opens a seat, promote the lowest-positioned WAITLISTED
    row that re-passes all confirmation preconditions. Skip any that fail and continue.
    """
    while True:
        # Has capacity?
        session = db.sessions.get(session_id)
        if not session:
            return
        if count_confirmed_in_week(session_id, week_index) >= session["weekly_capacity"]:
            return
        candidates = [
            e
            for e in db.enrollments.values()
            if e["session_id"] == session_id
            and e["week_index"] == week_index
            and e["status"] == "WAITLISTED"
        ]
        if not candidates:
            return
        candidates.sort(key=lambda r: (r.get("waitlist_position") or 0, r["created_at"]))
        candidate = candidates[0]
        if not _try_confirm_waitlisted(candidate):
            # Failed re-check — that row stays WAITLISTED but skip it: we need
            # to mark it so we don't keep promoting it. Instead, move on by
            # treating the queue as drained when its head doesn't pass.
            # Spec: "if a waitlisted enrollment fails re-check (e.g., auth has expired)
            # it is skipped; promotion continues with the next waitlist entry".
            # To skip without dequeuing, we drop this candidate and try the next.
            candidates_left = candidates[1:]
            promoted = False
            for nxt in candidates_left:
                if _try_confirm_waitlisted(nxt):
                    promoted = True
                    break
            if not promoted:
                return
            # If we promoted, loop again to see if more seats are still open.
            continue
        # Successfully promoted; loop to see if more seats opened.


def _try_confirm_waitlisted(e):
    """Try to promote a WAITLISTED enrollment. Returns True if promoted to CONFIRMED, False if skipped."""
    if e["status"] != "WAITLISTED":
        return False
    session = db.sessions.get(e["session_id"])
    if not session or session["status"] != "OPEN":
        return False
    child = db.children.get(e["child_id"])
    if not child:
        return False
    project_child_auth_statuses(child, persist=False)
    if child["medical_authorization_status"] != "ACTIVE":
        return False
    if child["pickup_authorization_status"] != "ACTIVE":
        return False
    if child["emergency_contact_count"] < 1:
        return False
    # Age recheck — using chronological reading the same session.reference_date applies.
    age = compute_age_on_reference_date(child["date_of_birth"], session["reference_date"])
    if not (session["age_min"] <= age <= session["age_max"]):
        return False
    if count_confirmed_in_week(session["id"], e["week_index"]) >= session["weekly_capacity"]:
        return False
    try:
        _run_confirm_snapshot(e)
    except APIError:
        # Scholarship overflow or similar — treat as a failed re-check.
        return False
    e["status"] = "CONFIRMED"
    old_pos = e.get("waitlist_position")
    e["waitlist_position"] = None
    touch(e)
    # Renumber the remaining waitlist for that (session, week)
    if old_pos is not None:
        _renumber_waitlist(e["session_id"], e["week_index"])
    # Cascade sibling on other confirmed siblings
    _cascade_sibling_recompute_excluding_self(e)
    return True


def cancel_enrollment(enrollment_id):
    """Per state machine: PENDING_AUTH→CANCELLED, WAITLISTED→CANCELLED, or CONFIRMED→CANCELLED."""
    e = db.enrollments[enrollment_id]
    if e["status"] in {"CANCELLED", "COMPLETED"}:
        raise APIError("ERR_INVALID_STATE")

    if e["status"] == "PENDING_AUTH":
        e["status"] = "CANCELLED"
        e["cancelled_at"] = now_iso_virtual()
        touch(e)
        return e

    if e["status"] == "WAITLISTED":
        e["status"] = "CANCELLED"
        e["cancelled_at"] = now_iso_virtual()
        e["waitlist_position"] = None
        touch(e)
        _renumber_waitlist(e["session_id"], e["week_index"])
        return e

    if e["status"] == "CONFIRMED":
        session = db.sessions[e["session_id"]]
        if session["status"] != "OPEN":
            # Cannot cancel CONFIRMED after CLOSED
            raise APIError("ERR_INVALID_STATE")
        # Unwind: cancelled_at, refund scholarship, sibling recompute, attempt promotion
        e["status"] = "CANCELLED"
        e["cancelled_at"] = now_iso_virtual()
        touch(e)
        _refund_scholarship_on_cancel(e)
        child = db.children[e["child_id"]]
        recompute_sibling_for_family_week(child["family_id"], e["session_id"], e["week_index"])
        _try_promote_waitlist(e["session_id"], e["week_index"])
        return e

    raise APIError("ERR_INVALID_STATE")


# ---------- Provisional fee quote (calc variant: provisional_quote) ----------

def fee_quote(enrollment_id):
    """Provisional what-if quote using CURRENT pre-confirmation sibling count + award balances."""
    e = db.enrollments[enrollment_id]
    if e["status"] in {"CONFIRMED", "COMPLETED"}:
        # When the row is already snapshotted, the snapshot is what matters.
        return {
            "list_fee_cents": e["list_fee_cents"],
            "sibling_discount_cents": e["sibling_discount_cents"],
            "scholarship_discount_cents": e["scholarship_discount_cents"],
            "final_fee_cents": e["final_fee_cents"],
            "scholarship_award_id": e.get("scholarship_award_id"),
        }
    session = db.sessions[e["session_id"]]
    child = db.children[e["child_id"]]
    family_id = child["family_id"]
    list_fee = session["base_weekly_fee_cents"]
    # Pre-confirm sibling count: include the about-to-be-confirmed row
    siblings = family_confirmed_siblings_in_week(
        family_id, session["id"], e["week_index"], include_id=e["id"]
    )
    n = len(siblings)
    pct = sibling_tier_pct(n)
    sibling_discount = apply_pct(list_fee, pct)
    net_payable = list_fee - sibling_discount
    sch_amt, award_id = compute_scholarship_allocation(family_id, session["kind"], net_payable)
    final_fee = max(0, list_fee - sibling_discount - sch_amt)
    return {
        "list_fee_cents": list_fee,
        "sibling_discount_cents": sibling_discount,
        "scholarship_discount_cents": sch_amt,
        "final_fee_cents": final_fee,
        "scholarship_award_id": award_id,
    }


# ---------- Cascades from upstream state changes ----------

def cascade_session_cancel(session):
    """Session OPEN→CANCELLED: every non-terminal enrollment goes to CANCELLED."""
    affected_weeks_with_confirmed_loss = set()
    for e in list(db.enrollments.values()):
        if e["session_id"] != session["id"]:
            continue
        if e["status"] in {"CANCELLED", "COMPLETED"}:
            continue
        was_confirmed = e["status"] == "CONFIRMED"
        e["status"] = "CANCELLED"
        e["cancelled_at"] = now_iso_virtual()
        e["waitlist_position"] = None
        touch(e)
        if was_confirmed:
            _refund_scholarship_on_cancel(e)
            affected_weeks_with_confirmed_loss.add((e["session_id"], e["week_index"]))
    # Recompute siblings for affected weeks (no remaining CONFIRMED rows in cancelled session,
    # so this is largely a no-op — but keeps invariants if any odd case exists).
    for (sid, wi) in affected_weeks_with_confirmed_loss:
        # All confirmed in this (sid, wi) have just been cancelled, so nothing to recompute.
        pass


def cascade_session_close(session):
    """Session OPEN→CLOSED: CONFIRMED→COMPLETED, others non-terminal→CANCELLED."""
    for e in list(db.enrollments.values()):
        if e["session_id"] != session["id"]:
            continue
        if e["status"] == "CONFIRMED":
            e["status"] = "COMPLETED"
            touch(e)
        elif e["status"] in {"PENDING_AUTH", "WAITLISTED"}:
            e["status"] = "CANCELLED"
            e["cancelled_at"] = now_iso_virtual()
            e["waitlist_position"] = None
            touch(e)


def cascade_auth_revoke_on_child(child):
    """When an authorization is revoked and the child's medical_or pickup_authorization_status
    drops below ACTIVE, cancel every CONFIRMED enrollment in a future/current week.

    PRD §3.2: future/current means Session.week_start + 7*week_index > now.
    """
    now = clock.now()
    affected_weeks = []
    for e in list(db.enrollments.values()):
        if e["child_id"] != child["id"] or e["status"] != "CONFIRMED":
            continue
        session = db.sessions[e["session_id"]]
        week_start = parse_iso_date(session["week_start"])
        week_end_for_index = week_start + timedelta(days=7 * e["week_index"] + 7)
        # "future or current week (Session.week_start + 7*week_index > now)" — note PRD wording:
        # the week window is week_start + 7*week_index strictly after now means the week
        # has NOT yet ended (its end-of-week is in the future).
        week_end_dt = parse_iso_date(session["week_start"])
        # Use end-of-week comparison consistent with §3.2: week_start + 7*week_index*days > now
        # PRD literal: week_start + 7*week_index > now. Treat both as window-end checks.
        from datetime import datetime, timezone, time as dtime
        cmp_dt = datetime.combine(
            week_start + timedelta(days=7 * e["week_index"] + 7), dtime.min, tzinfo=timezone.utc
        )
        if cmp_dt > now:
            # cancel
            e["status"] = "CANCELLED"
            e["cancelled_at"] = now_iso_virtual()
            touch(e)
            _refund_scholarship_on_cancel(e)
            affected_weeks.append((e["session_id"], e["week_index"], child["family_id"]))
    for (sid, wi, fid) in affected_weeks:
        recompute_sibling_for_family_week(fid, sid, wi)
        _try_promote_waitlist(sid, wi)
