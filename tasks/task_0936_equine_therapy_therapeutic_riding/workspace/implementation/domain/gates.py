"""Rungs 14-18: the five ordered global write gates (PRD §2.8).

They are called in this order and each pre-empts every gate below it as well as
every ordinary rung that follows:

    14  incident hold        ERR_INCIDENT_HOLD_ACTIVE            (409)
    15  finalized period     ERR_REPORT_FINALIZED                (409)
    16  horse operational    ERR_HORSE_ON_HOLD                   (409)
    17  instructor cert      ERR_INSTRUCTOR_CERT_LAPSED          (409)
    18  physician release    ERR_RELEASE_MISSING / _EXPIRED      (422)
"""

from core import timeutil as T
from core.errors import fail
from core.store import db

from . import derive

LIVE_INCIDENT_STATUSES = ("OPEN", "UNDER_REVIEW")


def _incident_live(incident_id):
    incident = db["incidents"].get(incident_id) if incident_id else None
    return incident is not None and incident["status"] in LIVE_INCIDENT_STATUSES


# ------------------------------------------------------------------ gate 1
def gate_incident_hold(rider=None, horse=None, volunteer=None, instructors=()):
    if rider is not None and _incident_live(rider.get("medical_hold_incident_id")):
        fail("ERR_INCIDENT_HOLD_ACTIVE", "The rider is held by a live incident.")
    if horse is not None and horse["status"] == "REST_HOLD" \
            and horse.get("hold_reason") == "INCIDENT_REST_HOLD" \
            and _incident_live(horse.get("_hold_incident_id")):
        fail("ERR_INCIDENT_HOLD_ACTIVE", "The horse is held by a live incident.")
    if volunteer is not None and derive.volunteer_status(volunteer) == "SUSPENDED" \
            and _incident_live(volunteer.get("_suspension_incident_id")):
        fail("ERR_INCIDENT_HOLD_ACTIVE", "The volunteer is suspended by a live incident.")
    for instructor in instructors:
        if instructor is None:
            continue
        if derive.certification_status(instructor) == "SUSPENDED" \
                and _incident_live(instructor.get("_suspension_incident_id")):
            fail("ERR_INCIDENT_HOLD_ACTIVE",
                 "The instructor is suspended by a live incident.")


# ------------------------------------------------------------------ gate 2
def finalized_report_covering(on_date):
    for report in db["period_reports"].values():
        if report["status"] != "FINALIZED":
            continue
        start = T.parse_date(report["period_start"])
        end = T.parse_date(report["period_end"])
        if start <= on_date <= end:
            return report
    return None


def finalized_report_overlapping(period_start, period_end):
    for report in db["period_reports"].values():
        if report["status"] != "FINALIZED":
            continue
        start = T.parse_date(report["period_start"])
        end = T.parse_date(report["period_end"])
        if period_start <= end and start <= period_end:
            return report
    return None


def gate_finalized_period_for_session(session_date):
    if finalized_report_covering(session_date) is not None:
        fail("ERR_REPORT_FINALIZED",
             "A finalized period report already covers that session date.")


# ------------------------------------------------------------------ gate 3
def gate_horse_hold(horse):
    if horse["status"] != "AVAILABLE":
        fail("ERR_HORSE_ON_HOLD", "The horse is on a %s." % horse["status"])


# ------------------------------------------------------------------ gate 4
def gate_instructor_certification(instructors, allowed):
    """Evaluated on the instructor of record and, when named, the supervisor."""
    for instructor in instructors:
        if instructor is None:
            continue
        status = derive.certification_status(instructor)
        if status not in allowed:
            fail("ERR_INSTRUCTOR_CERT_LAPSED",
                 "Instructor certification is %s." % status)


# ------------------------------------------------------------------ gate 5
def gate_medical_release(rider):
    release = derive.latest_release(rider["id"])
    if release is None:
        fail("ERR_RELEASE_MISSING", "The rider has no physician release.")
    if derive.release_status(release) != "ACTIVE":
        fail("ERR_RELEASE_EXPIRED", "The rider's most recent release is not active.")
    return release
