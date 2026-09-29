"""Derivation cascades and hierarchical consistency (PRD 2.8, 3.8)."""

from datetime import timedelta

import db
from services import calc


def refresh_phase_status(phase):
    """Re-derive a phase's staffing_status unless it has been frozen.

    Returns True when the stored status actually changed (which is the phase
    state-machine transition that increments the phase's version).
    """
    new_status = calc.derived_phase_status(phase)
    if new_status is None or new_status == phase["staffing_status"]:
        return False
    phase["staffing_status"] = new_status
    db.mark(phase)
    return True


def bubble_engagement(engagement):
    """SCHEDULED -> SETUP when every phase of the engagement is NOT_STAFFED."""
    if engagement is None or engagement["status"] != "SCHEDULED":
        return False
    phases = calc.phases_of_engagement(engagement["id"])
    if not phases:
        return False
    if any(p["staffing_status"] != "NOT_STAFFED" for p in phases):
        return False
    engagement["status"] = "SETUP"
    db.mark(engagement)
    return True


def refresh_engagement_staffing(engagement):
    """Re-derive every phase of the engagement and bubble the engagement down."""
    if engagement is None:
        return
    for phase in calc.phases_of_engagement(engagement["id"]):
        refresh_phase_status(phase)
    bubble_engagement(engagement)


def release_assignment(assignment):
    """PROPOSED / CONFIRMED -> RELEASED, exactly reversing the footprint."""
    assignment["staffing_status"] = "RELEASED"
    if assignment["review_status"] in ("PENDING_REVIEW", "IN_REVIEW", "REWORK_REQUESTED"):
        assignment["review_status"] = "NOT_REQUIRED"
    db.mark(assignment)


def expire_waiver(waiver, reason):
    waiver["status"] = "EXPIRED"
    waiver["expiry_reason"] = reason
    db.mark(waiver)


def waivers_of(staff_id=None, engagement_id=None, status=None):
    rows = list(db.waivers.values())
    if staff_id is not None:
        rows = [w for w in rows if w["staff_member_id"] == staff_id]
    if engagement_id is not None:
        rows = [w for w in rows if w["engagement_id"] == engagement_id]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    return db.by_seq(rows)


# ---------------------------------------------------------------------------
# cascade client_block_release_relax_expire (depth 4)
# ---------------------------------------------------------------------------
def cascade_client_block(engagement):
    # hop 1 — release every pending booking of the engagement
    released_staff_ids = []
    for assignment in calc.assignments_of_engagement(engagement["id"], ("PROPOSED", "CONFIRMED")):
        release_assignment(assignment)
        if assignment["staff_member_id"] not in released_staff_ids:
            released_staff_ids.append(assignment["staff_member_id"])

    # hop 2 — the affected staff members' committed load / risk figures are
    # derived lazily, so the release itself is the recomputation.
    # hop 3 — withdraw the overtime relief those bookings justified
    for staff_id in released_staff_ids:
        staff = db.staff_members.get(staff_id)
        if staff is None:
            continue
        committed = calc.committed_hours_current_week(staff)
        if committed <= calc.D(staff["base_weekly_cap_hours"]):
            for waiver in waivers_of(
                staff_id=staff_id, engagement_id=engagement["id"], status="APPROVED"
            ):
                # hop 4 — the expiry drops the allowance from the effective cap
                expire_waiver(waiver, "ENGAGEMENT_BLOCKED")

    for phase in calc.phases_of_engagement(engagement["id"]):
        refresh_phase_status(phase)


# ---------------------------------------------------------------------------
# cascade restriction_release_downgrade (depth 3)
# ---------------------------------------------------------------------------
def cascade_restriction(restriction):
    client_id = restriction["client_id"]
    staff_id = restriction["staff_member_id"]
    window_start = restriction["effective_start_date"]
    window_end = restriction["effective_end_date"]

    released = 0
    affected_phase_ids = []
    affected_engagement_ids = []
    for assignment in calc.assignments_of_staff(staff_id, ("PROPOSED", "CONFIRMED")):
        phase = db.phases.get(assignment["engagement_phase_id"])
        if phase is None:
            continue
        engagement = db.engagements.get(phase["engagement_id"])
        if engagement is None or engagement["client_id"] != client_id:
            continue
        if not calc.ranges_intersect(
            window_start,
            window_end,
            assignment["start_date"],
            calc.last_worked_day(assignment),
        ):
            continue
        release_assignment(assignment)
        released += 1
        if phase["id"] not in affected_phase_ids:
            affected_phase_ids.append(phase["id"])
        if engagement["id"] not in affected_engagement_ids:
            affected_engagement_ids.append(engagement["id"])

    restriction["released_assignment_count"] = released

    # hop 2 — phase derivation
    for phase_id in affected_phase_ids:
        refresh_phase_status(db.phases[phase_id])
    # hop 3 — engagement reversion
    for engagement_id in affected_engagement_ids:
        bubble_engagement(db.engagements[engagement_id])

    # the restricted person's overtime relief on affected engagements is withdrawn
    for engagement_id in affected_engagement_ids:
        for waiver in waivers_of(staff_id=staff_id, engagement_id=engagement_id, status="APPROVED"):
            expire_waiver(waiver, "RESTRICTION_IMPOSED")


# ---------------------------------------------------------------------------
# reschedule apply
# ---------------------------------------------------------------------------
def apply_reschedule(plan, engagement):
    shift = timedelta(days=plan["shift_days"])
    added = calc.D(plan["added_hours"])
    target_phase_id = plan["target_phase_id"]

    phases = calc.phases_of_engagement(engagement["id"])
    for phase in phases:
        phase["window_start_date"] = phase["window_start_date"] + shift
        phase["window_end_date"] = phase["window_end_date"] + shift
        db.mark(phase)

    if added > 0 and target_phase_id is not None and target_phase_id in db.phases:
        target = db.phases[target_phase_id]
        target["expected_hours"] = calc.r2(calc.D(target["expected_hours"]) + added)
        db.mark(target)
        engagement["scope_change_count"] = engagement["scope_change_count"] + 1

    for phase in phases:
        for assignment in calc.assignments_of_phase(phase["id"], ("PROPOSED", "CONFIRMED")):
            fits = (
                phase["window_start_date"] <= assignment["start_date"]
                and calc.last_worked_day(assignment) <= phase["window_end_date"]
            )
            if not fits:
                release_assignment(assignment)

    for phase in phases:
        refresh_phase_status(phase)
    bubble_engagement(engagement)

    for other in db.by_seq(list(db.reschedule_plans.values())):
        if other["id"] == plan["id"]:
            continue
        if other["engagement_id"] != engagement["id"]:
            continue
        if other["status"] in ("DRAFT", "SIMULATED"):
            other["status"] = "SUPERSEDED"
            db.mark(other)
