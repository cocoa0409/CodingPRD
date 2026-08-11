"""The ordered admissibility checks a session write runs (PRD §2.7 rungs 14-32).

`run_checks` walks the ladder in ascending rung number and either raises the
first failing rung's error or returns None.  `first_failure` runs exactly the
same walk without raising, which is what GET /sessions/{id}/eligibility reports
through `blocking_gate`.
"""

from core.constants import INSTRUCTOR_TIER_ORDINAL
from core.errors import ApiError, fail
from core.store import clock, db

from . import derive, gates, policy


def instructor_gate_check(session_or_ids, allowed, at=None):
    for instructor in session_or_ids:
        if instructor is None:
            continue
        status = derive.certification_status(instructor, at)
        if status not in allowed:
            fail("ERR_INSTRUCTOR_CERT_LAPSED",
                 "Instructor certification is %s." % status)


def release_gate_check(rider, at=None):
    release = derive.latest_release(rider["id"])
    if release is None:
        fail("ERR_RELEASE_MISSING", "The rider has no physician release.")
    if derive.release_status(release, at) != "ACTIVE":
        fail("ERR_RELEASE_EXPIRED", "The rider's most recent release is not active.")
    return release


def rider_state_checks(rider, activity_type):
    """Rungs 20-24 - shared by session creation and session confirmation."""
    if rider["status"] != "ACTIVE":                                   # rung 20
        fail("ERR_RIDER_NOT_ACTIVE", "The rider is %s." % rider["status"])
    status = derive.assessment_status(rider)                          # rung 21
    if status in ("OVERDUE", "NEVER_ASSESSED"):
        fail("ERR_REASSESSMENT_OVERDUE", "The rider's assessment is %s." % status)
    result = policy.evaluate_precaution(rider, activity_type)         # rungs 22-24
    if result.error is not None:
        fail(result.error, "Condition evaluation failed for %r." % result.code)
    return result


def supervision_pairing(instructor, supervisor):
    """Rung 25 - scoped to session creation."""
    trainee = instructor["certification_level"] == "IN_TRAINING"
    if trainee:
        if supervisor is None:
            fail("ERR_SUPERVISOR_REQUIRED",
                 "An IN_TRAINING instructor of record requires a supervisor.")
        if INSTRUCTOR_TIER_ORDINAL[supervisor["certification_level"]] <= \
                INSTRUCTOR_TIER_ORDINAL[instructor["certification_level"]]:
            fail("ERR_SUPERVISOR_REQUIRED",
                 "The supervisor's tier must be strictly greater than the trainee's.")
    elif supervisor is not None:
        fail("ERR_SUPERVISOR_REQUIRED",
             "A supervising instructor may only accompany an IN_TRAINING instructor.")


def instructor_tier_check(rider, activity_type, effective):
    """Rung 26."""
    required = policy.required_instructor_tier(rider, activity_type)
    if INSTRUCTOR_TIER_ORDINAL[effective["certification_level"]] < \
            INSTRUCTOR_TIER_ORDINAL[required]:
        fail("ERR_INSTRUCTOR_TIER_INSUFFICIENT",
             "The effective instructor is below the required tier %s." % required)


def load_check(rider, horse):
    """Rung 27 - equality passes."""
    load = policy.effective_load_lb(rider, horse)
    if load > horse["max_load_lb"]:
        fail("ERR_HORSE_LOAD_EXCEEDED",
             "Effective load %s exceeds the horse's ceiling %s."
             % (load, horse["max_load_lb"]))


def eligibility_walk(session, weight_variant, instant):
    """The same ordered walk, reported rather than raised."""
    rider = db["riders"].get(session["rider_id"])
    horse = db["horses"].get(session["horse_id"])
    instructors = policy.session_instructors(session)
    try:
        gates.gate_incident_hold(rider=rider, horse=horse, instructors=instructors)
        gates.gate_horse_hold(horse)
        instructor_gate_check(instructors, ("CURRENT",), instant)
        release_gate_check(rider, instant)
        rider_state_checks(rider, session["activity_type"])
        effective = policy.effective_instructor(session)
        instructor_tier_check(rider, session["activity_type"], effective)
        load = policy.effective_load_lb(rider, horse, weight_variant)
        if load > horse["max_load_lb"]:
            fail("ERR_HORSE_LOAD_EXCEEDED", "Effective load exceeds the ceiling.")
        if not derive.crew_satisfied(session):
            fail("ERR_CREW_INCOMPLETE", "The crew requirement is not satisfied.")
    except ApiError as exc:
        return exc.error_id
    return None
