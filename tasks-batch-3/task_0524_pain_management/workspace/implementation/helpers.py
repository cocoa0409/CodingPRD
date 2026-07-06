from flask import request

import db
import errors


def paginate(items):
    """Apply limit/offset pagination. items must already be sorted.

    Returns (page_items, limit, offset, total_count).
    """
    total = len(items)
    limit = _int_param("limit", default=10, minimum=1, maximum=100)
    offset = _int_param("offset", default=0, minimum=0, maximum=None)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, f"invalid {name}")
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def get_clinic(clinic_id):
    c = db.clinics.get(clinic_id)
    if c is None:
        raise errors.ApiError(errors.ERR_CLINIC_NOT_FOUND, 404, "clinic not found")
    return c


def get_patient(clinic_id, patient_id):
    p = db.patients.get(patient_id)
    if p is None or p["clinic_id"] != clinic_id:
        raise errors.ApiError(errors.ERR_PATIENT_NOT_FOUND, 404, "patient not found")
    return p


def get_patient_flat(patient_id):
    p = db.patients.get(patient_id)
    if p is None:
        raise errors.ApiError(errors.ERR_PATIENT_NOT_FOUND, 404, "patient not found")
    return p
