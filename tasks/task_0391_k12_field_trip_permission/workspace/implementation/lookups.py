"""Existence lookups returning the record or raising the right *_NOT_FOUND.

Path identifiers are validated left to right; the first that fails to resolve
raises before any business rule (PRD §2.6).
"""
from db import db
from errors import err


def get_trip(trip_id):
    t = db.field_trips.get(trip_id)
    if t is None:
        raise err("ERR_TRIP_NOT_FOUND", "Field trip not found.")
    return t


def get_slip_on_trip(trip_id, slip_id):
    s = db.permission_slips.get(slip_id)
    if s is None or s["trip_id"] != trip_id:
        raise err("ERR_SLIP_NOT_FOUND", "Permission slip not found on this trip.")
    return s


def get_chaperone_on_trip(trip_id, chaperone_id):
    c = db.chaperones.get(chaperone_id)
    if c is None or c["trip_id"] != trip_id:
        raise err("ERR_CHAPERONE_NOT_FOUND", "Chaperone not found on this trip.")
    return c


def get_booking_on_trip(trip_id, booking_id):
    b = db.transport_bookings.get(booking_id)
    if b is None or b["trip_id"] != trip_id:
        raise err("ERR_BOOKING_NOT_FOUND", "Transport booking not found on this trip.")
    return b


def get_grant_on_slip(slip_id, grant_id):
    g = db.scholarship_grants.get(grant_id)
    if g is None or g["slip_id"] != slip_id:
        raise err("ERR_GRANT_NOT_FOUND", "Scholarship grant not found on this slip.")
    return g


def get_student(student_id):
    s = db.students.get(student_id)
    if s is None:
        raise err("ERR_STUDENT_NOT_FOUND", "Student not found.")
    return s


def get_guardian(guardian_id):
    g = db.guardians.get(guardian_id)
    if g is None:
        raise err("ERR_GUARDIAN_NOT_FOUND", "Guardian not found.")
    return g


def get_vehicle(vehicle_id):
    v = db.vehicles.get(vehicle_id)
    if v is None:
        raise err("ERR_VEHICLE_NOT_FOUND", "Vehicle not found.")
    return v


def get_pool(pool_id):
    p = db.scholarship_pools.get(pool_id)
    if p is None:
        raise err("ERR_POOL_NOT_FOUND", "Scholarship pool not found.")
    return p
