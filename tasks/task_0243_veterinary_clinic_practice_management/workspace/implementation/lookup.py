"""Entity existence lookups (PRD §2.8, §1.4 priority 3-4)."""
import db
import errors


def _get(collection, ident, err):
    if ident is None:
        return None
    rec = collection.get(ident)
    if rec is None:
        errors.raise_err(err, "Resource not found.")
    return rec


def household(hid):
    return _get(db.households, hid, errors.ERR_HOUSEHOLD_NOT_FOUND)


def owner(oid):
    return _get(db.owners, oid, errors.ERR_OWNER_NOT_FOUND)


def patient(pid):
    return _get(db.patients, pid, errors.ERR_PATIENT_NOT_FOUND)


def appointment(aid):
    return _get(db.appointments, aid, errors.ERR_APPOINTMENT_NOT_FOUND)


def estimate(eid):
    return _get(db.estimates, eid, errors.ERR_ESTIMATE_NOT_FOUND)


def surgery(sid):
    return _get(db.surgeries, sid, errors.ERR_SURGERY_NOT_FOUND)


def boarding(bid):
    return _get(db.boarding_stays, bid, errors.ERR_BOARDING_NOT_FOUND)


def prescription(rxid):
    return _get(db.prescriptions, rxid, errors.ERR_PRESCRIPTION_NOT_FOUND)


def vaccination(vid):
    return _get(db.vaccinations, vid, errors.ERR_VACCINATION_NOT_FOUND)


def lab_order(loid):
    return _get(db.lab_orders, loid, errors.ERR_LAB_ORDER_NOT_FOUND)


def invoice(invid):
    return _get(db.invoices, invid, errors.ERR_INVOICE_NOT_FOUND)


def operatory(oid):
    return _get(db.operatories, oid, errors.ERR_OPERATORY_NOT_FOUND)


def kennel(kid):
    return _get(db.kennels, kid, errors.ERR_KENNEL_NOT_FOUND)


def wellness_plan(wpid):
    # PRD §2.8 / §5 define no ERR_WELLNESS_PLAN_NOT_FOUND. A missing plan id on the
    # /wellness-plans/{wpid} path therefore returns a generic 404 (no catalogued
    # error_id exists to assert against). Resolved ambiguity: use a bare 404.
    rec = db.wellness_plans.get(wpid)
    if rec is None:
        raise errors.ApiError("ERR_WELLNESS_PLAN_NOT_FOUND", 404, "Wellness plan not found.")
    return rec
