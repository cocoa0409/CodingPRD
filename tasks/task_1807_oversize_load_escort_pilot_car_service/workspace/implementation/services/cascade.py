"""Cross-entity gates, promotions, demotions, releases, and clock sweeps.

Every mutation routes through mutate.mark() so each affected resource gets
exactly one version bump + updated_at refresh per API operation.
"""

import db
from mutate import mark
from services import calc


# --- Lookup helpers --------------------------------------------------------------
def legs_of_job(job_id):
    return [l for l in db.legs.values() if l["job_id"] == job_id]


def permits_of_leg(leg_id):
    return [p for p in db.permits.values() if p["leg_id"] == leg_id]


def surveys_of_leg(leg_id):
    return [s for s in db.surveys.values() if s["leg_id"] == leg_id]


def assignments_of_leg(leg_id):
    return [a for a in db.assignments.values() if a["leg_id"] == leg_id]


def assignments_of_escort(escort_id):
    return [a for a in db.assignments.values() if a["escort_id"] == escort_id]


def delays_of_job(job_id):
    return [d for d in db.delay_events.values() if d["job_id"] == job_id]


def incidents_of_job(job_id):
    return [i for i in db.incidents.values() if i["job_id"] == job_id]


def invoices_of_job(job_id):
    return [i for i in db.invoices.values() if i["job_id"] == job_id]


def job_of_leg(leg):
    return db.jobs.get(leg["job_id"])


def leg_of_assignment(a):
    return db.legs.get(a["leg_id"])


def job_of_assignment(a):
    leg = leg_of_assignment(a)
    return job_of_leg(leg) if leg else None


# --- Clearance gates --------------------------------------------------------------
def leg_gates_satisfied(leg):
    has_permit = any(p["permit_status"] == "ISSUED" for p in permits_of_leg(leg["id"]))
    if not has_permit:
        return False
    if leg["requires_route_survey"] and leg["clearance_verdict"] != "PASS":
        return False
    if leg["requires_police_escort"] and not leg["police_confirmed"]:
        return False
    return True


def promote_leg(leg, from_states):
    """DETERMINED -> CLEARED (permit issue / police confirm) or
    DETERMINED|BLOCKED -> CLEARED (survey accept PASS)."""
    if leg["leg_status"] in from_states and leg_gates_satisfied(leg):
        leg["leg_status"] = "CLEARED"
        mark(leg)
        return True
    return False


def reevaluate_job_clearance(job):
    """BOOKED -> CLEARED the moment every leg satisfies all three gates."""
    if job["job_status"] != "BOOKED":
        return
    legs = legs_of_job(job["id"])
    if legs and all(leg_gates_satisfied(l) for l in legs):
        job["job_status"] = "CLEARED"
        mark(job)


def block_leg_and_demote(leg):
    """Survey FAIL / permit expiry: leg DETERMINED|CLEARED -> BLOCKED; job CLEARED|SCHEDULED -> BOOKED."""
    job = job_of_leg(leg)
    if leg["leg_status"] in ("DETERMINED", "CLEARED"):
        leg["leg_status"] = "BLOCKED"
        mark(leg)
    if job is not None and job["job_status"] in ("CLEARED", "SCHEDULED"):
        job["job_status"] = "BOOKED"
        mark(job)


def reevaluate_leg_and_job_gates(leg, promote_from=("DETERMINED",)):
    """After permit issue / police confirm / survey accept."""
    promote_leg(leg, promote_from)
    job = job_of_leg(leg)
    if job is not None:
        reevaluate_job_clearance(job)


# --- Assignment coverage / release --------------------------------------------------
def required_positions_covered(job):
    """Every required escort position on every leg covered by an ACCEPTED assignment."""
    for leg in legs_of_job(job["id"]):
        accepted = [
            a for a in assignments_of_leg(leg["id"]) if a["assignment_status"] == "ACCEPTED"
        ]
        front = sum(1 for a in accepted if a["position"] == "FRONT")
        rear = sum(1 for a in accepted if a["position"] == "REAR")
        if front < leg["required_front_escorts"] or rear < leg["required_rear_escorts"]:
            return False
    return True


def release_assignment(a, cause):
    """OFFERED/ACCEPTED (dispatcher) or cascade releases (job cancel also ACTIVE)."""
    was_counted = a["assignment_status"] in ("ACCEPTED", "ACTIVE")
    a["assignment_status"] = "RELEASED"
    a["released_at"] = db.now()
    a["release_cause"] = cause
    mark(a)
    # active_assignment_count is computed on read; nothing stored to adjust.
    if was_counted:
        job = job_of_assignment(a)
        if job is not None and job["job_status"] == "SCHEDULED":
            if not required_positions_covered(job):
                job["job_status"] = "CLEARED"
                mark(job)


# --- Escort suspension cascade --------------------------------------------------------
def suspend_escort_cascade(escort):
    """Escort -> SUSPENDED; ACCEPTED assignments released (ESCORT_SUSPENDED);
    SCHEDULED jobs losing a required position demote to CLEARED."""
    escort["escort_status"] = "SUSPENDED"
    mark(escort)
    for a in assignments_of_escort(escort["id"]):
        if a["assignment_status"] == "ACCEPTED":
            release_assignment(a, "ESCORT_SUSPENDED")


# --- Clock sweep ---------------------------------------------------------------------
def sweep_permit_expiry():
    """Every ISSUED permit with valid_until < now -> EXPIRED; leg CLEARED -> BLOCKED;
    job CLEARED/SCHEDULED -> BOOKED."""
    now = db.now()
    for p in list(db.permits.values()):
        if p["permit_status"] == "ISSUED" and now > p["valid_until"]:
            p["permit_status"] = "EXPIRED"
            mark(p)
            leg = db.legs.get(p["leg_id"])
            if leg is not None and leg["leg_status"] == "CLEARED":
                leg["leg_status"] = "BLOCKED"
                mark(leg)
                job = job_of_leg(leg)
                if job is not None and job["job_status"] in ("CLEARED", "SCHEDULED"):
                    job["job_status"] = "BOOKED"
                    mark(job)


# --- Selector (CALC-7) ------------------------------------------------------------------
def escort_window_free(escort, candidate_job):
    """CALC-8: no buffered conflict against the escort's ACCEPTED/ACTIVE assignments."""
    for a in assignments_of_escort(escort["id"]):
        if a["assignment_status"] not in ("ACCEPTED", "ACTIVE"):
            continue
        other_job = job_of_assignment(a)
        if other_job is None:
            continue
        if calc.windows_conflict(candidate_job, other_job):
            return False
    return True


def escort_eligible(escort, leg, job, position):
    if escort["escort_status"] != "ACTIVE":
        return False
    if leg["state_code"] not in escort["certified_state_codes"]:
        return False
    if position == "FRONT" and leg["requires_height_pole"]:
        if not escort["has_height_pole"]:
            return False
        if escort["height_pole_max_inches"] < job["height_inches"]:
            return False
    return escort_window_free(escort, job)


def select_escort(leg, job, position):
    """CALC-7: reliability_score DESC, created_at ASC (creation sequence as stable
    tiebreak for identical timestamps — id is never consulted)."""
    pool = [e for e in db.escorts.values() if escort_eligible(e, leg, job, position)]
    if not pool:
        return None
    pool.sort(key=lambda e: (-e["reliability_score"], e["created_at"], e["_seq"]))
    return pool[0]
