"""Cross-entity reconciliation, derived-state transitions, and waitlist promotion.

Whenever a derived field is reconciled, that reconciliation is a mutation of the
affected resource (PRD §2.4): updated_at refreshed and version incremented.
"""

from db import db
from clock import parse_iso
from services.common import touch
from services import calc


# --------------------------------------------------------------------------
# Authorization reconciliation
# --------------------------------------------------------------------------
def reconcile_authorization(auth):
    """Recompute counts and apply auto EXHAUSTED<->ACTIVE transitions, bumping version.

    PRD §3.4: when a reservation drives available_visits to exactly 0 the auth
    auto-transitions ACTIVE -> EXHAUSTED; when a release lifts it back above 0 it
    auto-transitions EXHAUSTED -> ACTIVE.
    """
    calc.recompute_authorization_counts(auth)
    if auth["status"] == "ACTIVE" and auth["available_visits"] == 0:
        auth["status"] = "EXHAUSTED"
    elif auth["status"] == "EXHAUSTED" and auth["available_visits"] > 0:
        auth["status"] = "ACTIVE"
    touch(auth)


# --------------------------------------------------------------------------
# Child computed fields (active_appointment_count, coordination_program)
# --------------------------------------------------------------------------
def recompute_child(child):
    """Recompute the child's active_appointment_count and coordination_program."""
    count = sum(
        1
        for a in db.appointments.values()
        if a["child_id"] == child["id"] and a["status"] == "SCHEDULED"
    )
    # coordination_program derived from the single active CoordinationPlan.
    program = "NONE"
    for cp in db.coordination_plans.values():
        if cp["child_id"] != child["id"]:
            continue
        if cp["status"] == "ACTIVE":
            program = "EARLY_INTERVENTION" if cp["plan_type"] == "IFSP" else "SCHOOL"
            break
    changed = (
        child["active_appointment_count"] != count
        or child["coordination_program"] != program
    )
    child["active_appointment_count"] = count
    child["coordination_program"] = program
    if changed:
        touch(child)


# --------------------------------------------------------------------------
# Therapist caseload reconciliation (explicit +/- in callers; reader helper)
# --------------------------------------------------------------------------
def caseload_count(therapist_id):
    """Distinct children whose ACTIVE plan names this therapist as primary."""
    children = set()
    for plan in db.plans_of_care.values():
        if (
            plan["primary_therapist_id"] == therapist_id
            and plan["status"] == "ACTIVE"
        ):
            children.add(plan["child_id"])
    return len(children)


# --------------------------------------------------------------------------
# Goal latest_progress + MET/OPEN derivation; plan roll-up
# --------------------------------------------------------------------------
def reconcile_goal(goal):
    """Recompute latest_progress_pct and auto MET<->OPEN transitions (PRD §3.6)."""
    new_latest = calc.goal_latest_progress(goal)
    if goal["latest_progress_pct"] != new_latest:
        goal["latest_progress_pct"] = new_latest
        # Auto-transition only for non-terminal-ish states (OPEN/MET cycle).
        if goal["status"] in ("OPEN", "MET"):
            if new_latest >= goal["target_pct"]:
                goal["status"] = "MET"
            else:
                goal["status"] = "OPEN"
        touch(goal)
    else:
        # latest unchanged but a status flip could still be warranted (e.g. weight
        # only matters for roll-up). Keep status consistent for OPEN/MET.
        if goal["status"] in ("OPEN", "MET"):
            target_state = "MET" if new_latest >= goal["target_pct"] else "OPEN"
            if goal["status"] != target_state:
                goal["status"] = target_state
                touch(goal)


def reconcile_plan_progress(plan):
    """Recompute the plan's overall_progress_pct forward-looking (PRD §2.8)."""
    new_value = calc.overall_progress_pct(plan["id"])
    if plan["overall_progress_pct"] != new_value:
        plan["overall_progress_pct"] = new_value
        touch(plan)


def recompute_goal_count(plan):
    count = sum(1 for g in db.goals.values() if g["plan_of_care_id"] == plan["id"])
    if plan["goal_count"] != count:
        plan["goal_count"] = count
        touch(plan)


# --------------------------------------------------------------------------
# Clock-driven authorization expiry (PRD §2.11, §3.4)
# --------------------------------------------------------------------------
def expire_due_authorizations():
    """Transition ACTIVE authorizations to EXPIRED when clock reaches valid_until.

    Returns the list of newly-expired authorization ids.
    """
    now = db.clock.now()
    expired = []
    for auth in db.authorizations.values():
        if auth["status"] == "ACTIVE" and now >= parse_iso(auth["valid_until"]):
            auth["status"] = "EXPIRED"
            touch(auth)
            expired.append(auth["id"])
    return expired


# --------------------------------------------------------------------------
# Waitlist promotion (scaffold §1.3 waitlist_promotion; PRD §3.8)
# --------------------------------------------------------------------------
def child_has_eligible_authorization(child_id, discipline):
    """True iff the child has an ACTIVE, non-EXPIRED authorization for the
    discipline with available_visits >= 1.
    """
    for auth in db.authorizations.values():
        if auth["child_id"] != child_id:
            continue
        if auth["discipline"] != discipline:
            continue
        if auth["status"] != "ACTIVE":
            continue
        if auth["available_visits"] >= 1:
            return True
    return False


def run_waitlist_promotion(therapist_id, exclude_ids=None):
    """Offer the freed therapist slot to the top-ranked eligible WAITING entry.

    Candidate set: WaitlistEntry where therapist_id == freed therapist AND
    status == WAITING AND discipline == freed therapist's discipline.
    Eligibility: child ACTIVE AND child has an ACTIVE non-EXPIRED authorization
    for the discipline with available_visits >= 1.
    Ranking: priority_score DESC, then created_at ASC. No id tie-break.

    exclude_ids: entry ids to skip in this round. On a decline, the just-declined
    entry returns to WAITING; promotion re-runs and must offer the NEXT-highest
    eligible entry (PRD §3.8), so the declined entry is excluded from this round.
    """
    exclude_ids = exclude_ids or set()
    therapist = db.therapists.get(therapist_id)
    if therapist is None:
        return None
    discipline = therapist["discipline"]

    candidates = []
    for entry in db.waitlist_entries.values():
        if entry["therapist_id"] != therapist_id:
            continue
        if entry["id"] in exclude_ids:
            continue
        if entry["status"] != "WAITING":
            continue
        if entry["discipline"] != discipline:
            continue
        child = db.children.get(entry["child_id"])
        if child is None or child["status"] != "ACTIVE":
            continue
        if not child_has_eligible_authorization(entry["child_id"], discipline):
            continue
        candidates.append(entry)

    if not candidates:
        return None

    # priority_score DESC, created_at ASC. created_at is the final discriminator.
    candidates.sort(key=lambda e: (-e["priority_score"], e["created_at"]))
    winner = candidates[0]
    winner["status"] = "OFFERED"
    touch(winner)
    return winner
