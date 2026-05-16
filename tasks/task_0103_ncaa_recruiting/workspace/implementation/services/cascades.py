"""Cascading side-effect helpers used by state-transition handlers.

These mutate multiple entities and call aggregate recomputes. Callers must hold
the global STORE lock.
"""

from core.clock import CLOCK
from core.models import mark_mutated
from core.store import STORE
from services.aggregates import (
    recompute_program_aggregates,
    recompute_program_compliance,
    recompute_athlete_nil_lifetime,
)


# --- Athlete ENROLLED -> TRANSFER_PORTAL cascade ----------------------------

def cascade_enter_portal(athlete: dict):
    """Athlete enters portal. Move active slots->RELEASED for current program, then clear current_program_id."""
    origin_program_id = athlete.get("current_program_id")
    # Step 1: release ACTIVE slots for current program
    for s in STORE.scholarship_slots.values():
        if s.get("athlete_id") != athlete["id"]:
            continue
        if s.get("program_id") != origin_program_id:
            continue
        if s.get("status") == "ACTIVE":
            s["status"] = "RELEASED"
            mark_mutated(s)
    # Step 2: athlete state + clear program
    athlete["status"] = "TRANSFER_PORTAL"
    athlete["current_program_id"] = None
    mark_mutated(athlete)
    # Step 3: aggregate recompute
    if origin_program_id:
        recompute_program_aggregates(origin_program_id)
    return origin_program_id


# --- Athlete COMMITTED -> ENROLLED cascade ----------------------------------

def cascade_enroll(athlete: dict):
    """Athlete enrolls. Activate matching SIGNED slots; check roster cap; recompute program aggregates.

    Pre-checks roster_cap: count current ENROLLED + 1 (for this athlete) must be <= cap.
    Raises ERR_ROSTER_CAP_EXCEEDED if cap would be exceeded.
    """
    from core.errors import raise_error

    pid = athlete["current_program_id"]
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found for enrollment")
    # Roster cap check: count currently-ENROLLED at program then +1
    current_count = sum(
        1 for a in STORE.athletes.values()
        if a.get("status") == "ENROLLED" and a.get("current_program_id") == pid
    )
    if current_count + 1 > int(prog["roster_cap_count"]):
        raise_error("ERR_ROSTER_CAP_EXCEEDED", "Roster cap would be exceeded")

    # Activate signed slots
    now_iso = CLOCK.now_iso()
    for s in STORE.scholarship_slots.values():
        if s.get("athlete_id") != athlete["id"]:
            continue
        if s.get("program_id") != pid:
            continue
        if s.get("status") == "SIGNED":
            s["status"] = "ACTIVE"
            s["activated_at"] = now_iso
            mark_mutated(s)
    # Init years_of_eligibility_remaining if null
    if athlete.get("years_of_eligibility_remaining") is None:
        athlete["years_of_eligibility_remaining"] = 4
    athlete["status"] = "ENROLLED"
    mark_mutated(athlete)
    recompute_program_aggregates(pid)


# --- Violation SUSTAINED cascade --------------------------------------------

def cascade_violation_sustained(violation: dict):
    """When a violation reaches SUSTAINED outcome:

    - Recompute penalty_points (caller does this; we just refresh program aggregates).
    - If LEVEL_I or LEVEL_II AND related_athlete_id set: flip athlete amateur_status & ENROLLED->INELIGIBLE (LEVEL_I only).
    - Suspend approved deals (only when athlete flips to INELIGIBLE).
    - Recompute program penalty/compliance posture.
    """
    pid = violation["program_id"]
    related_aid = violation.get("related_athlete_id")
    severity = violation.get("severity")

    # Mark outcome SUSTAINED.
    violation["outcome"] = "SUSTAINED"
    mark_mutated(violation)

    # Athlete cascade only if related_athlete_id is set
    suspended_deal_ids = []
    prev_amateur_status = None
    prev_status = None
    if related_aid:
        a = STORE.athletes.get(related_aid)
        if a is not None:
            prev_amateur_status = a.get("amateur_status")
            prev_status = a.get("status")
            athlete_changed = False
            # LEVEL_I: athlete -> INELIGIBLE and amateur_status FORFEITED; deals suspend.
            # LEVEL_II: amateur_status AT_RISK; deals not auto-suspended (athlete remains ENROLLED).
            if severity == "LEVEL_I":
                # PRD §3.7 cascade only fires on LEVEL_I with related_athlete_id.
                a["amateur_status"] = "FORFEITED"
                if a.get("status") == "ENROLLED":
                    a["status"] = "INELIGIBLE"
                athlete_changed = True
                # Suspend all APPROVED deals for the athlete.
                for d in STORE.nil_deals.values():
                    if d.get("athlete_id") != related_aid:
                        continue
                    if d.get("status") == "APPROVED":
                        d["status"] = "SUSPENDED"
                        mark_mutated(d)
                        suspended_deal_ids.append(d["id"])
            elif severity == "LEVEL_II":
                # LEVEL_II also updates amateur_status to AT_RISK per state machine note.
                if a.get("amateur_status") != "AT_RISK":
                    a["amateur_status"] = "AT_RISK"
                    athlete_changed = True
            if athlete_changed:
                mark_mutated(a)
                # Recompute lifetime if any deal got suspended
                if suspended_deal_ids:
                    recompute_athlete_nil_lifetime(related_aid)
                # Recompute program aggregates because athlete may have left ENROLLED.
                cur_pid = a.get("current_program_id")
                if cur_pid:
                    recompute_program_aggregates(cur_pid)

    # Track suspension info for later overturn cascade
    STORE.violation_athlete_suspensions[violation["id"]] = {
        "athlete_id": related_aid,
        "suspended_deal_ids": suspended_deal_ids,
        "prev_amateur_status": prev_amateur_status,
        "prev_status": prev_status,
        "severity": severity,
    }

    # Recompute program compliance posture
    recompute_program_compliance(pid)


# --- Violation OVERTURNED cascade -------------------------------------------

def cascade_violation_overturned(violation: dict):
    """When a SUSTAINED violation later flips to CLEARED (OVERTURNED):

    - Restore the athlete if the original cascade caused INELIGIBLE.
    - Restore SUSPENDED deals that were suspended by this violation back to APPROVED.
    - Recompute program penalty/compliance.
    """
    pid = violation["program_id"]
    violation["outcome"] = "CLEARED"
    mark_mutated(violation)

    info = STORE.violation_athlete_suspensions.pop(violation["id"], None)
    if info:
        aid = info.get("athlete_id")
        suspended_ids = info.get("suspended_deal_ids", [])
        severity = info.get("severity")
        if aid:
            a = STORE.athletes.get(aid)
            if a is not None:
                # Restore amateur_status and ENROLLED if originally flipped.
                if severity == "LEVEL_I":
                    a["amateur_status"] = "AMATEUR"
                    if a.get("status") == "INELIGIBLE":
                        a["status"] = "ENROLLED"
                    mark_mutated(a)
                    cur_pid = a.get("current_program_id")
                    if cur_pid:
                        recompute_program_aggregates(cur_pid)
                elif severity == "LEVEL_II":
                    a["amateur_status"] = "AMATEUR"
                    mark_mutated(a)
                # Restore deals
                for did in suspended_ids:
                    d = STORE.nil_deals.get(did)
                    if d is not None and d.get("status") == "SUSPENDED":
                        d["status"] = "APPROVED"
                        mark_mutated(d)
                if suspended_ids:
                    recompute_athlete_nil_lifetime(aid)

    recompute_program_compliance(pid)


# --- Violation DISMISSED ---------------------------------------------------

def cascade_violation_dismissed(violation: dict):
    """INVESTIGATING -> DISMISSED: outcome becomes CLEARED. No cascades."""
    violation["outcome"] = "CLEARED"
    mark_mutated(violation)
    recompute_program_compliance(violation["program_id"])
