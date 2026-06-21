"""Existence-lookup helpers shared across route modules."""
from common import parse_pagination, paginate, sorted_by_created
from errors import err
from response import success
from store import db


def get_owner(owner_id):
    o = db.owners.get(owner_id)
    if o is None:
        raise err("ERR_OWNER_NOT_FOUND", "Owner not found")
    return o


def get_dog(dog_id):
    d = db.dogs.get(dog_id)
    if d is None:
        raise err("ERR_DOG_NOT_FOUND", "Dog not found")
    return d


def get_trainer(trainer_id):
    t = db.trainers.get(trainer_id)
    if t is None:
        raise err("ERR_TRAINER_NOT_FOUND", "Trainer not found")
    return t


def get_series(series_id):
    s = db.class_series.get(series_id)
    if s is None:
        raise err("ERR_SERIES_NOT_FOUND", "ClassSeries not found")
    return s


def get_session(session_id):
    s = db.class_sessions.get(session_id)
    if s is None:
        raise err("ERR_SESSION_NOT_FOUND", "ClassSession not found")
    return s


def get_enrollment(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise err("ERR_ENROLLMENT_NOT_FOUND", "Enrollment not found")
    return e


def get_package(package_id):
    p = db.packages.get(package_id)
    if p is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Package not found")
    return p


def get_attendance(attendance_id):
    a = db.attendance_records.get(attendance_id)
    if a is None:
        raise err("ERR_ATTENDANCE_NOT_FOUND", "AttendanceRecord not found")
    return a


def get_makeup(makeup_id):
    m = db.makeup_bookings.get(makeup_id)
    if m is None:
        raise err("ERR_MAKEUP_NOT_FOUND", "MakeupBooking not found")
    return m


def get_redemption(red_id):
    r = db.package_redemptions.get(red_id)
    if r is None:
        raise err("ERR_PACKAGE_NOT_FOUND", "Redemption not found")
    return r


def get_certificate(cert_id):
    c = db.certificates.get(cert_id)
    if c is None:
        raise err("ERR_INVALID_REQUEST", "Certificate not found")
    return c


def list_response(rows, serialize_fn):
    limit, offset = parse_pagination()
    rows = sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    data = [serialize_fn(r) for r in page]
    return success(data, 200, pagination=meta)
