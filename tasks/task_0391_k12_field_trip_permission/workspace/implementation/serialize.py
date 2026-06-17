"""Serialize internal records into API output objects.

Derived/computed fields are recomputed live at read time so a GET always
reflects current state (PRD §2.5).
"""
from db import db
import calc


def _strip(record):
    """Copy a record, removing internal bookkeeping keys."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def student_out(s):
    return _strip(s)


def guardian_out(g):
    return _strip(g)


def vehicle_out(v):
    out = _strip(v)
    out["seats_reserved"] = calc.vehicle_seats_reserved(v["id"])
    return out


def pool_out(p):
    out = _strip(p)
    granted = calc.pool_granted_cents(p["id"])
    out["granted_cents"] = granted
    out["remaining_cents"] = p["total_cents"] - granted
    return out


def field_trip_out(t):
    out = _strip(t)
    out["signed_count"] = t["signed_count"]
    out["confirmed_count"] = t["confirmed_count"]
    out["required_chaperones"] = calc.required_chaperones(t)
    out["collected_fees_cents"] = calc.trip_collected_fees(t["id"])
    out["per_student_final_fee_cents"] = t["per_student_final_fee_cents"]
    return out


def slip_out(s):
    out = _strip(s)
    out["scholarship_award_cents"] = calc.slip_scholarship_award(s["id"])
    out["fee_due_cents"] = s["fee_due_cents"]
    out["net_paid_cents"] = calc.slip_net_paid(s["id"])
    return out


def grant_out(g):
    return _strip(g)


def chaperone_out(c):
    return _strip(c)


def booking_out(b):
    return _strip(b)


def approval_out(a):
    return _strip(a)


def emergency_contact_out(e):
    return _strip(e)


def fee_transaction_out(f):
    return _strip(f)


def attendance_out(a):
    return _strip(a)
