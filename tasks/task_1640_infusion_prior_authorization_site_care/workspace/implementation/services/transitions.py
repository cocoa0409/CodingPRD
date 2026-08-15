"""Cross-aggregate cascades and clock-driven transitions (PRD 2.4, 2.10).

Every cascade step is an independent mutation: each touched resource gets its
own version += 1 and updated_at refresh.
"""
from datetime import timedelta

from db import db, touch
from services.calculations import compute_validity_window

MISSED_GRACE_MINUTES = 60
P2P_NO_SHOW_GRACE_MINUTES = 30


def approve_request(req, now):
    """DENIED/SUBMITTED -> APPROVED: fix the validity window from the decision
    date and copy requested_dose_mg into approved_dose_mg (PRD 3.4)."""
    from db import db as _db
    policy = _db["payer_policies"][req["policy_id"]]
    patient = _db["patients"][req["patient_id"]]
    valid_from, valid_to = compute_validity_window(policy, patient, now)
    req["status"] = "APPROVED"
    req["auth_valid_from"] = valid_from
    req["auth_valid_to"] = valid_to
    req["approved_dose_mg"] = req["requested_dose_mg"]
    touch(req, now)


def cascade_appeal_closed(appeal, closed_status, now):
    """Appeal closure cascade onto the parent AuthorizationRequest:
    CLOSED_OVERTURNED -> DENIED -> APPROVED (window recomputed from decision date);
    CLOSED_UPHELD -> DENIED -> DENIED_CLOSED."""
    req = db["authorization_requests"].get(appeal["authorization_request_id"])
    if req is None or req["status"] != "DENIED":
        return
    if closed_status == "CLOSED_OVERTURNED":
        approve_request(req, now)
    else:  # CLOSED_UPHELD
        req["status"] = "DENIED_CLOSED"
        touch(req, now)


def supersede_request(req, now):
    """APPROVED -> SUPERSEDED; cancel the request's future SCHEDULED/CONFIRMED
    appointments (chair occupation released). The ON_HOLD clearance stays ON_HOLD."""
    req["status"] = "SUPERSEDED"
    touch(req, now)
    for appt in db["appointments"].values():
        if (appt["authorization_request_id"] == req["id"]
                and appt["status"] in ("SCHEDULED", "CONFIRMED")
                and appt["scheduled_start"] > now):
            appt["status"] = "CANCELLED"
            touch(appt, now)


def run_clock_sweep(now):
    """Setting the logical clock synchronously applies every time-based transition
    whose trigger has fired (PRD 2.4)."""
    for req in db["authorization_requests"].values():
        if (req["status"] == "APPROVED" and req["auth_valid_to"] is not None
                and now > req["auth_valid_to"]):
            req["status"] = "EXPIRED"
            touch(req, now)
    for appt in db["appointments"].values():
        if appt["status"] == "CONFIRMED" and now >= appt["scheduled_end"]:
            appt["status"] = "COMPLETED"
            touch(appt, now)
        elif (appt["status"] == "SCHEDULED"
                and now > appt["scheduled_start"] + timedelta(minutes=MISSED_GRACE_MINUTES)):
            appt["status"] = "MISSED"
            touch(appt, now)
    for rev in db["peer_to_peer_reviews"].values():
        if (rev["status"] == "SCHEDULED"
                and now > rev["scheduled_end"] + timedelta(minutes=P2P_NO_SHOW_GRACE_MINUTES)):
            rev["status"] = "NO_SHOW"
            touch(rev, now)
