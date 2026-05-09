"""Common lookup helpers that raise existence errors."""
import errors as E
from db import DATA


def get_student(student_id):
    s = DATA.students.get(student_id)
    if s is None:
        raise E.APIError(E.ERR_STUDENT_NOT_FOUND, 404)
    return s


def get_instructor(inst_id):
    i = DATA.instructors.get(inst_id)
    if i is None:
        raise E.APIError(E.ERR_INSTRUCTOR_NOT_FOUND, 404)
    return i


def get_vehicle(v_id):
    v = DATA.vehicles.get(v_id)
    if v is None:
        raise E.APIError(E.ERR_VEHICLE_NOT_FOUND, 404)
    return v


def get_package(pkg_id):
    p = DATA.course_packages.get(pkg_id)
    if p is None:
        raise E.APIError(E.ERR_PACKAGE_NOT_FOUND, 404)
    return p


def get_practice(p_id):
    p = DATA.practice_appointments.get(p_id)
    if p is None:
        raise E.APIError(E.ERR_PRACTICE_NOT_FOUND, 404)
    return p


def get_exam(e_id):
    e = DATA.exam_appointments.get(e_id)
    if e is None:
        raise E.APIError(E.ERR_EXAM_NOT_FOUND, 404)
    return e


def get_simulator(s_id):
    s = DATA.simulator_sessions.get(s_id)
    if s is None:
        raise E.APIError(E.ERR_SIMULATOR_NOT_FOUND, 404)
    return s


def get_complaint(c_id):
    c = DATA.complaints.get(c_id)
    if c is None:
        raise E.APIError(E.ERR_COMPLAINT_NOT_FOUND, 404)
    return c


def occ_check(record, body):
    """If body has 'version', compare; on mismatch raise ERR_STALE_DATA. Otherwise no-op."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    if body["version"] != record.get("version"):
        raise E.APIError(E.ERR_STALE_DATA, 409,
                         f"Stale version (expected {record.get('version')}, got {body['version']})")
