"""Operator utilities: the logical clock and the statutory compliance sweep (PRD §2.4)."""

from flask import Blueprint

import calc
import cascades
from auth import COMPLIANCE_OFFICER, context
from envelope import object_response
from errors import fail
from store import db, ordered, touch
from timeutil import fmt, parse_dt
from validation import body

bp = Blueprint("ops", __name__)

OPEN_PETITION_STATES = ("FILED", "HEARING_SCHEDULED", "CONTINUED")


@bp.post("/behavioral-health/_clock/set_current_utc")
def set_clock():
    context((COMPLIANCE_OFFICER,))
    data = body()
    if "to_iso8601" not in data or data["to_iso8601"] is None:
        fail("ERR_INVALID_REQUEST", "missing required field: to_iso8601")
    parsed = parse_dt(data["to_iso8601"])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    # Moving the clock changes no entity state whatsoever.
    db.current_utc = parsed
    return object_response({"current_utc": fmt(db.current_utc)})


def _hold_has_open_petition(hold_id):
    return any(
        p["hold_id"] == hold_id and p["status"] in OPEN_PETITION_STATES
        for p in db.petitions.values()
    )


def _sweep_holds(now):
    count = 0
    for hold in ordered(list(db.holds.values())):
        if hold["status"] != "ACTIVE":
            continue
        if hold["release_deadline_at"] is None or now < hold["release_deadline_at"]:
            continue
        if _hold_has_open_petition(hold["id"]):
            continue
        hold["status"] = "EXPIRED"
        hold["closure_reason"] = "STATUTORY_EXPIRY"
        touch(hold)
        cascades.close_hold_cascade(hold, "EXPIRY")
        count += 1
    return count


def _sweep_restraints(now):
    count = 0
    for episode in ordered(list(db.restraints.values())):
        status = episode["status"]
        if status == "ORDERED":
            deadline = episode["face_to_face_deadline_at"]
            if deadline is None or now <= deadline:
                continue
            released_at = deadline
            actual = 60
        elif status == "ACTIVE":
            authorized_until = episode["authorized_until_at"]
            if authorized_until is None or now < authorized_until:
                continue
            released_at = authorized_until
            actual = episode["ordered_duration_minutes"]
        else:
            continue

        cascades.finalize_episode(episode, released_at, actual, "EXPIRED_UNAUTHORIZED")
        admission = db.admissions.get(episode["admission_id"])
        if admission is not None:
            cascades.flag_rights_violation(admission)
            cascades.recompute_admission_staffing(admission)
        count += 1
    return count


def _sweep_discharge_requests(now):
    count = 0
    for request_row in ordered(list(db.discharge_requests.values())):
        if request_row["status"] != "PENDING":
            continue
        deadline = request_row["response_deadline_at"]
        if deadline is None or now <= deadline:
            continue
        request_row["status"] = "EXPIRED_UNANSWERED"
        touch(request_row)
        admission = db.admissions.get(request_row["admission_id"])
        if admission is not None:
            cascades.flag_rights_violation(admission)
            if admission["legal_status"] == "VOLUNTARY":
                cascades.advance_placement_on_grant(admission)
        count += 1
    return count


def _sweep_consents(now):
    count = 0
    for consent in ordered(list(db.medication_consents.values())):
        if consent["status"] != "ACTIVE":
            continue
        if consent["consent_basis"] != "EMERGENCY_OVERRIDE":
            continue
        expires_at = consent["expires_at"]
        if expires_at is None or now <= expires_at:
            continue
        consent["status"] = "EXPIRED"
        touch(consent)
        count += 1
    return count


@bp.post("/behavioral-health/_compliance/sweep")
def compliance_sweep():
    context((COMPLIANCE_OFFICER,))
    body()
    now = db.now()
    expired_hold_count = _sweep_holds(now)
    expired_restraint_count = _sweep_restraints(now)
    expired_discharge_request_count = _sweep_discharge_requests(now)
    expired_consent_count = _sweep_consents(now)
    return object_response(
        {
            "expired_hold_count": expired_hold_count,
            "expired_restraint_count": expired_restraint_count,
            "expired_discharge_request_count": expired_discharge_request_count,
            "expired_consent_count": expired_consent_count,
        }
    )


# calc is imported for its side-effect-free helpers used by the cascade layer.
_ = calc
