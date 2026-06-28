"""Cross-cutting domain helpers: existence lookups, lazy lapse evaluation,
list sorting/pagination.
"""
import clock
import db
from errors import err, ERR_NOT_FOUND


def get_or_404(collection, _id, label="resource"):
    if _id is None or _id not in collection:
        raise err(ERR_NOT_FOUND, "%s not found: %s" % (label, _id))
    return collection[_id]


def exists(collection, _id):
    return _id is not None and _id in collection


def sort_paginate(records, limit, offset):
    """Sort by created_at ascending (tie-break insertion seq), then paginate."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ----- lazy lapse evaluation (clock-driven state) -----

def refresh_standing_order(order):
    """An ACTIVE standing order whose expires_at has been reached/passed is
    treated as EXPIRED; lapse is evaluated when the order is used or read."""
    if order["status"] == "ACTIVE" and clock.now() >= order["expires_at"]:
        order["status"] = "EXPIRED"
    return order


def refresh_supply_lot(lot):
    """When the clock reaches/passes expires_at and the lot has no reserved
    units, it becomes EXPIRED; evaluated on read, list, and reservation."""
    if (lot["status"] == "AVAILABLE"
            and clock.now() >= lot["expires_at"]
            and lot["units_reserved"] == 0):
        lot["status"] = "EXPIRED"
    return lot


def recompute_open_adverse_event_count(patient_id):
    """open_adverse_event_count = count of this patient's adverse events whose
    status is REPORTED or UNDER_REVIEW."""
    count = 0
    for ae in db.adverse_events.values():
        appt = db.appointments.get(ae["appointment_id"])
        if appt is None:
            continue
        if appt["patient_id"] != patient_id:
            continue
        if ae["status"] in ("REPORTED", "UNDER_REVIEW"):
            count += 1
    patient = db.patients.get(patient_id)
    if patient is not None:
        patient["open_adverse_event_count"] = count
