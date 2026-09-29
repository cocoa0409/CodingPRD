"""Shared route plumbing."""
from db import serialize
from errors import ApiError
from middleware import ROLES
from response import list_response, object_response, paginate
from services.risk import patient_age_years

ALL_ROLES = ROLES


def view(row):
    return serialize(row)


def view_patient(patient):
    data = serialize(patient)
    data["age_years"] = patient_age_years(patient)
    return data


def send(row, status=200, viewer=view):
    return object_response(viewer(row), status)


def send_list(rows, viewer=view):
    window, total, limit, offset = paginate(rows)
    return list_response([viewer(row) for row in window], total, limit, offset)


def scope_check(left_practice_id, right_practice_id):
    if left_practice_id != right_practice_id:
        raise ApiError("ERR_PRACTICE_SCOPE_MISMATCH")


def state_error():
    return ApiError("ERR_INVALID_STATE_TRANSITION")
