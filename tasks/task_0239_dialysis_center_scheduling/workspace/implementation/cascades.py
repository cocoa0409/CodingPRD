"""Cascade side-effects shared across state machines (PRD §3.4, §3.5, §3.6)."""
from db import db


def cancel_session_transport(session):
    """Cancel any REQUESTED/CONFIRMED transport trip on a session; reverse a
    CONFIRMED trip's fare from the patient's account_balance_cents.
    """
    patient = db.patients.get(session["patient_id"])
    for trip in db.transport_trips.values():
        if trip["session_id"] != session["id"]:
            continue
        if trip["status"] in ("REQUESTED", "CONFIRMED"):
            was_confirmed = trip["status"] == "CONFIRMED"
            trip["status"] = "CANCELLED"
            db.touch(trip)
            if was_confirmed and patient is not None:
                patient["account_balance_cents"] -= trip["fare_cents"]
                db.touch(patient)


def cancel_booked_session(session):
    """Transition a BOOKED session -> CANCELLED and cascade its transport."""
    session["clinical_status"] = "CANCELLED"
    db.touch(session)
    cancel_session_transport(session)


def revoke_order_cascade(order):
    """Three-hop cascade: order revoke -> session cancel -> transport cancel -> fare reversal.

    Applies to every TreatmentSession authorized by this order in clinical_status
    BOOKED. Cancellation cascades to each such session's REQUESTED/CONFIRMED
    transport trips (CONFIRMED fares reversed via cancel_session_transport).
    """
    for session in db.sessions.values():
        if session.get("order_id") == order["id"] and session["clinical_status"] == "BOOKED":
            cancel_booked_session(session)


def release_slot_cascade(slot):
    """Releasing a standing slot cancels every BOOKED session generated from it."""
    for session in db.sessions.values():
        if session.get("standing_slot_id") == slot["id"] and session["clinical_status"] == "BOOKED":
            cancel_booked_session(session)
