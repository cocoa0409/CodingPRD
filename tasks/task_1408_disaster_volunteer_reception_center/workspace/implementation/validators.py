"""Shared pipeline helpers: resource resolution, lifecycle/posture gates, safety."""

import db
import services as svc
from errors import (
    ERR_BACKGROUND_CHECK_LAPSED,
    ERR_CREDENTIAL_CLASS_INSUFFICIENT,
    ERR_HAZARD_CREDENTIAL_REQUIRED,
    ERR_INCIDENT_DEMOBILIZING,
    ERR_INCIDENT_NOT_ACTIVE,
    ERR_POSTURE_FROZEN,
    ERR_POSTURE_RESTRICTED,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SHIFT_CAPACITY_REACHED,
    ERR_SITE_WINDOW_MISMATCH,
    ERR_SKILL_MISMATCH,
    ERR_VOLUNTEER_NOT_READY,
    raise_error,
)


# --- Pipeline stage 3: existence ------------------------------------------------

def get_or_404(store, entity_name, record_id):
    rec = store.get(record_id)
    if rec is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, f"{entity_name} not found: {record_id}")
    return rec


def get_incident_or_404(record_id):
    return get_or_404(db.incidents, "Incident", record_id)


def get_volunteer_or_404(record_id):
    return get_or_404(db.volunteers, "Volunteer", record_id)


def get_credential_or_404(record_id):
    return get_or_404(db.credentials, "SkillCredential", record_id)


def get_background_check_or_404(record_id):
    return get_or_404(db.background_checks, "BackgroundCheck", record_id)


def get_clearance_or_404(record_id):
    return get_or_404(db.clearances, "Clearance", record_id)


def get_request_or_404(record_id):
    return get_or_404(db.support_requests, "SupportRequest", record_id)


def get_shift_or_404(record_id):
    return get_or_404(db.shifts, "SiteShift", record_id)


def get_assignment_or_404(record_id):
    return get_or_404(db.assignments, "DeploymentAssignment", record_id)


def get_trip_or_404(record_id):
    return get_or_404(db.trips, "TransportTrip", record_id)


def get_booking_or_404(record_id):
    return get_or_404(db.seat_bookings, "SeatBooking", record_id)


def get_ppe_or_404(record_id):
    return get_or_404(db.ppe_issuances, "PPEIssuance", record_id)


def get_hour_entry_or_404(record_id):
    return get_or_404(db.hour_entries, "HourEntry", record_id)


def get_risk_report_or_404(record_id):
    return get_or_404(db.risk_reports, "RiskReport", record_id)


def load_fk_string(body, field, store, entity_name):
    """Body reference resolution: missing/mistyped ids fall through to stage-4
    shape validation; present string ids are existence-checked now (stage 3)."""
    value = body.get(field)
    if isinstance(value, str) and value:
        get_or_404(store, entity_name, value)
    return value


# --- Pipeline stage 5: incident lifecycle gate ---------------------------------------

def incident_gate(incident, operation, demob_allowed=False):
    """Writes creating/modifying operational data require an ACTIVE incident.

    In DEMOBILIZATION only the whitelisted wind-down writes remain permitted
    (ERR_INCIDENT_DEMOBILIZING otherwise); ACTIVATION and CLOSED reject with
    ERR_INCIDENT_NOT_ACTIVE.
    """
    status = incident["lifecycle_status"]
    if status == "ACTIVE":
        return
    if status == "DEMOBILIZATION":
        if demob_allowed:
            return
        raise_error(
            ERR_INCIDENT_DEMOBILIZING,
            f"Incident is in DEMOBILIZATION; {operation} is not permitted during wind-down",
        )
    raise_error(
        ERR_INCIDENT_NOT_ACTIVE,
        f"Incident must be ACTIVE for {operation} (current lifecycle: {status})",
    )


# --- Pipeline stage 6: posture gate -----------------------------------------------------

def posture_gate(incident, allow_restricted=True):
    """Applies to assignment create/confirm, auto-match, check-in, trip depart.
    Only meaningful while the lifecycle is ACTIVE (guaranteed by stage 5)."""
    posture = incident["operational_posture"]
    if posture == "FROZEN":
        raise_error(ERR_POSTURE_FROZEN, "Incident operational posture is FROZEN")
    if posture == "RESTRICTED" and not allow_restricted:
        raise_error(ERR_POSTURE_RESTRICTED, "Incident operational posture is RESTRICTED; auto-match is blocked")


# --- Pipeline stage 9/11/12: assignment safety and coherence -------------------------------

def best_qualifying_class(volunteer_id, skill_code):
    best = None
    for c in db.credentials.values():
        if c["volunteer_id"] == volunteer_id and c["skill_code"] == skill_code and c["status"] == "VERIFIED":
            if best is None or svc.CLASS_RANK[c["credential_class"]] > svc.CLASS_RANK[best]:
                best = c["credential_class"]
    return best


def check_assignment_safety(volunteer, req, shift):
    """Readiness, skill match, class minimum, hazard gating, background freshness."""
    if volunteer["status"] != "READY":
        raise_error(ERR_VOLUNTEER_NOT_READY, f"Volunteer must be READY (current: {volunteer['status']})")
    best = best_qualifying_class(volunteer["id"], req["required_skill"])
    if best is None:
        raise_error(ERR_SKILL_MISMATCH, "Volunteer holds no VERIFIED credential matching the request's required_skill")
    if svc.CLASS_RANK[best] < svc.CLASS_RANK[req["min_credential_class"]]:
        raise_error(ERR_CREDENTIAL_CLASS_INSUFFICIENT, "Qualifying credential class is below the request's minimum")
    if shift["hazard_level"] == "RED" and best != "ADVANCED":
        raise_error(ERR_HAZARD_CREDENTIAL_REQUIRED, "RED-hazard shifts require an ADVANCED qualifying credential")
    if not svc.has_fresh_cleared_bg(volunteer["id"]):
        raise_error(ERR_BACKGROUND_CHECK_LAPSED, "Volunteer has no CLEARED unexpired BackgroundCheck")


def check_site_window(req, shift):
    """Shift site must match exactly and the shift window must be contained."""
    if shift["site_name"] != req["site_name"]:
        raise_error(ERR_SITE_WINDOW_MISMATCH, "Shift site_name differs from the request's site_name")
    if shift["start_at"] < req["window_start"] or shift["end_at"] > req["window_end"]:
        raise_error(ERR_SITE_WINDOW_MISMATCH, "Shift window is not contained in the request window")


def check_confirm_shift_state(shift):
    """Confirm requires OPEN_FOR_ROSTER; LOCKED maps to the capacity error."""
    if shift["status"] == "LOCKED":
        raise_error(ERR_SHIFT_CAPACITY_REACHED, "Shift roster is locked at capacity")
    if shift["status"] != "OPEN_FOR_ROSTER":
        from errors import ERR_INVALID_STATE
        raise_error(ERR_INVALID_STATE, f"Shift must be OPEN_FOR_ROSTER to confirm (current: {shift['status']})")
