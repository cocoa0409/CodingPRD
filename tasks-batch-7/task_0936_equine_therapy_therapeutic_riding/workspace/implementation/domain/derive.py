"""Every derived status axis (PRD §2.11) plus the ledgers they read.

All of these are computed at read time against the logical clock; nothing here
is ever persisted, which is exactly what makes them non-monotone.
"""

from core import numbers as N
from core import timeutil as T
from core.constants import (
    CERT_GRACE_DAYS,
    REASSESSMENT_DUE_WARNING_DAYS,
)
from core.store import clock, db, all_rows


def _ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"].dt, r["_seq"]))


# ------------------------------------------------------------------ riders
def rider_releases(rider_id):
    return _ordered([r for r in db["medical_releases"].values()
                     if r["rider_id"] == rider_id])


def release_status(release, at=None):
    """REVOKED > SUPERSEDED > EXPIRED > ACTIVE, evaluated in that exact order."""
    instant = at if at is not None else clock.now()
    revoked = release.get("revoked_at")
    if revoked is not None and revoked.dt <= instant:
        return "REVOKED"
    superseded = release.get("superseded_at")
    if superseded is not None and superseded.dt <= instant:
        return "SUPERSEDED"
    if instant >= release["expires_at"].dt:
        return "EXPIRED"
    return "ACTIVE"


def latest_release(rider_id):
    """The rider's most recent release - most recent by created_at, newest first."""
    rows = rider_releases(rider_id)
    return rows[-1] if rows else None


def active_release(rider_id, at=None):
    """The most recent release whose derived status is ACTIVE, else None."""
    for release in reversed(rider_releases(rider_id)):
        if release_status(release, at) == "ACTIVE":
            return release
    return None


def rider_assessments(rider_id):
    return _ordered([a for a in db["assessments"].values()
                     if a["rider_id"] == rider_id])


def recorded_assessment(rider_id):
    for assessment in reversed(rider_assessments(rider_id)):
        if assessment["status"] == "RECORDED":
            return assessment
    return None


def assessment_status(rider):
    """NEVER_ASSESSED / OVERDUE / DUE / CURRENT at the logical clock."""
    if recorded_assessment(rider["id"]) is None:
        return "NEVER_ASSESSED"
    due = rider.get("assessment_next_due_at")
    if due is None:
        return "NEVER_ASSESSED"
    now = clock.now()
    if now >= due.dt:
        return "OVERDUE"
    if now >= T.plus_days(due.dt, -REASSESSMENT_DUE_WARNING_DAYS):
        return "DUE"
    return "CURRENT"


def goals_met_count(rider_id):
    return sum(1 for g in db["goals"].values()
               if g["rider_id"] == rider_id and g["status"] == "MET")


# -------------------------------------------------------------- volunteers
def age_years(date_of_birth, at_date=None):
    """Whole completed years between date_of_birth and the logical clock date."""
    born = T.parse_date(date_of_birth)
    today = at_date if at_date is not None else T.day_of(clock.now())
    years = today.year - born.year
    if (today.month, today.day) < (born.month, born.day):
        years -= 1
    return years


def volunteer_status(volunteer, at=None):
    """SUSPENDED > INACTIVE > ACTIVE, evaluated in that exact order."""
    instant = at if at is not None else clock.now()
    suspended_until = volunteer.get("suspended_until")
    if suspended_until is not None and instant < suspended_until.dt:
        return "SUSPENDED"
    due = volunteer.get("retraining_due_at")
    if due is not None and instant >= due.dt:
        return "INACTIVE"
    return "ACTIVE"


def qualification_status(qualification, at=None):
    """SUSPENDED > IN_TRAINING > EXPIRED > QUALIFIED, in that exact order."""
    instant = at if at is not None else clock.now()
    volunteer = db["volunteers"].get(qualification["volunteer_id"])
    if volunteer is not None and volunteer_status(volunteer, instant) == "SUSPENDED":
        return "SUSPENDED"
    if qualification.get("signed_off_on") is None:
        return "IN_TRAINING"
    expires = qualification.get("expires_at")
    if expires is not None and instant >= expires.dt:
        return "EXPIRED"
    return "QUALIFIED"


def volunteer_qualifications(volunteer_id):
    return _ordered([q for q in db["volunteer_qualifications"].values()
                     if q["volunteer_id"] == volunteer_id])


def open_assignment_count(volunteer_id):
    total = 0
    for assignment in db["crew_assignments"].values():
        if assignment["volunteer_id"] != volunteer_id:
            continue
        if assignment["status"] != "ASSIGNED":
            continue
        session = db["sessions"].get(assignment["session_id"])
        if session is not None and session["schedule_status"] in ("CREW_PENDING", "CONFIRMED"):
            total += 1
    return total


# ------------------------------------------------------------- instructors
def certification_status(instructor, at=None):
    """SUSPENDED > CURRENT > GRACE > LAPSED, evaluated in that exact order."""
    instant = at if at is not None else clock.now()
    suspended_until = instructor.get("suspended_until")
    if suspended_until is not None and instant < suspended_until.dt:
        return "SUSPENDED"
    expires = instructor["certification_expires_at"].dt
    if instant < expires:
        return "CURRENT"
    if instant < T.plus_days(expires, CERT_GRACE_DAYS):
        return "GRACE"
    return "LAPSED"


# ------------------------------------------------------------------ ledgers
def charge_allocations(charge_id):
    return _ordered([a for a in db["funding_allocations"].values()
                     if a["charge_id"] == charge_id])


def allocated_cents(charge_id):
    return sum(a["amount_cents"] for a in db["funding_allocations"].values()
               if a["charge_id"] == charge_id and a["status"] == "ALLOCATED")


def balance_due_cents(charge_id):
    total = 0
    for allocation in db["funding_allocations"].values():
        if allocation["charge_id"] != charge_id:
            continue
        if allocation["source_type"] != "PRIVATE_PAY":
            continue
        if allocation["status"] != "ALLOCATED":
            continue
        total += allocation["amount_cents"]
    return total


def charge_status(charge):
    if charge.get("reversed_at") is not None:
        return "REVERSED"
    if balance_due_cents(charge["id"]) == 0:
        return "FUNDED"
    return "PENDING"


def grant_allocated(grant_id):
    return sum(a["amount_cents"] for a in db["funding_allocations"].values()
               if a.get("grant_id") == grant_id and a["status"] == "ALLOCATED")


def grant_remaining(grant):
    return grant["awarded_amount_cents"] - grant_allocated(grant["id"])


def grant_status(grant):
    return "EXHAUSTED" if grant_remaining(grant) == 0 else "OPEN"


def award_used(award_id):
    return sum(a["amount_cents"] for a in db["funding_allocations"].values()
               if a.get("scholarship_award_id") == award_id and a["status"] == "ALLOCATED")


def award_status(award):
    if award.get("superseded_at") is not None:
        return "SUPERSEDED"
    if award_used(award["id"]) >= award["period_cap_cents"]:
        return "EXHAUSTED"
    return "ACTIVE"


def rider_awards(rider_id):
    return _ordered([a for a in db["scholarship_awards"].values()
                     if a["rider_id"] == rider_id])


# --------------------------------------------------------------- sessions
def session_assignments(session_id):
    return _ordered([a for a in db["crew_assignments"].values()
                     if a["session_id"] == session_id])


def crew_counts(session_id):
    sidewalkers = 0
    leaders = 0
    for assignment in db["crew_assignments"].values():
        if assignment["session_id"] != session_id or assignment["status"] != "ASSIGNED":
            continue
        if assignment["crew_role"] == "SIDEWALKER":
            sidewalkers += 1
        elif assignment["crew_role"] == "LEADER":
            leaders += 1
    return sidewalkers, leaders


def crew_satisfied(session):
    """Exact equality on BOTH limbs - over-assignment fails like under-assignment."""
    rider = db["riders"].get(session["rider_id"])
    if rider is None:
        return False
    required_sidewalkers = rider.get("required_sidewalker_count")
    requires_leader = rider.get("requires_leader")
    if required_sidewalkers is None or requires_leader is None:
        return False
    sidewalkers, leaders = crew_counts(session["id"])
    return (sidewalkers == required_sidewalkers
            and leaders == (1 if requires_leader else 0))


def session_service_hours(session):
    minutes = session.get("mounted_minutes")
    if minutes is None:
        return 0
    return N.minutes_to_hours(minutes)


def sessions_all():
    return all_rows("sessions")
