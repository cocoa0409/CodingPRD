"""Condition admissibility, instructor tier, and effective load (PRD §3.2, §3.3)."""

from core import numbers as N
from core.constants import (
    BACKRIDER_WEIGHT_LB,
    INSTRUCTOR_TIER_ORDINAL,
    MAX_HORSE_LOAD_FRACTION,
)
from core.store import db

from . import derive

TIER_BY_ORDINAL = {value: key for key, value in INSTRUCTOR_TIER_ORDINAL.items()}


def find_policy(condition_code, activity_type):
    """The ConditionPolicy row governing one (code, activity) pair."""
    found = None
    for policy in db["condition_policies"].values():
        if (policy["condition_code"] == condition_code
                and policy["activity_type"] == activity_type):
            if found is None or (policy["created_at"].dt, policy["_seq"]) > (
                    found["created_at"].dt, found["_seq"]):
                found = policy
    return found


class PrecautionResult:
    __slots__ = ("tier", "error", "code")

    def __init__(self, tier, error=None, code=None):
        self.tier = tier
        self.error = error
        self.code = code


def evaluate_precaution(rider, activity_type):
    """Walk the rider's condition codes against this activity.

    A missing policy row stops the walk; a CONTRAINDICATION short-circuits at the
    worst possible outcome; an uncleared PRECAUTION raises the running worst tier.
    Physician clearance NEVER lifts a contraindication.
    """
    release = derive.active_release(rider["id"])
    cleared = set(release["cleared_condition_codes"]) if release else set()
    worst = "CLEAR"
    for code in rider.get("condition_codes") or []:
        policy = find_policy(code, activity_type)
        if policy is None:
            return PrecautionResult(worst, "ERR_CONDITION_POLICY_MISSING", code)
        if policy["tier"] == "CONTRAINDICATION":
            return PrecautionResult("CONTRAINDICATION", "ERR_CONDITION_CONTRAINDICATED", code)
        if policy["tier"] == "PRECAUTION" and code not in cleared:
            worst = "PRECAUTION"
    if worst == "PRECAUTION":
        return PrecautionResult("PRECAUTION", "ERR_PRECAUTION_NOT_CLEARED")
    return PrecautionResult("CLEAR")


def required_instructor_tier(rider, activity_type):
    """Highest min_instructor_tier over the rider's PRECAUTION rows, floored at
    REGISTERED.  Rows whose code the release CLEARED still contribute: clearing
    removes the participation bar, not the instructor-tier requirement."""
    ordinal = INSTRUCTOR_TIER_ORDINAL["REGISTERED"]
    for code in rider.get("condition_codes") or []:
        policy = find_policy(code, activity_type)
        if policy is None or policy["tier"] != "PRECAUTION":
            continue
        ordinal = max(ordinal, INSTRUCTOR_TIER_ORDINAL[policy["min_instructor_tier"]])
    return TIER_BY_ORDINAL[ordinal]


def effective_instructor(session):
    """The supervisor when one is named, else the instructor of record."""
    supervisor_id = session.get("supervising_instructor_id")
    if supervisor_id:
        return db["instructors"].get(supervisor_id)
    return db["instructors"].get(session["instructor_id"])


def session_instructors(session):
    """Instructor of record plus the supervising instructor when one is named."""
    rows = []
    of_record = db["instructors"].get(session["instructor_id"])
    if of_record is not None:
        rows.append(of_record)
    supervisor_id = session.get("supervising_instructor_id")
    if supervisor_id:
        supervisor = db["instructors"].get(supervisor_id)
        if supervisor is not None:
            rows.append(supervisor)
    return rows


def max_load_lb(body_weight_lb):
    return N.round2(N.dec(body_weight_lb) * N.dec(MAX_HORSE_LOAD_FRACTION))


def effective_load_lb(rider, horse, variant="current_declared"):
    """rider weight (per variant) + tack + backrider, rounded half-up to 2dp."""
    if variant == "at_assessment":
        assessment = derive.recorded_assessment(rider["id"])
        base = assessment["rider_weight_lb"] if assessment else rider["weight_lb"]
    else:
        base = rider["weight_lb"]
    backrider = N.dec(BACKRIDER_WEIGHT_LB) if rider.get("backriding_required") else N.dec(0)
    total = N.dec(base) + N.dec(horse["tack_weight_lb"]) + backrider
    return N.round2(total)
