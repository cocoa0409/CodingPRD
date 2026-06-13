"""Biometric capture (PRD §3.5).

status is ACCEPTED when fingerprint_quality <= 3 AND a compliant photo was
captured; otherwise REJECTED.
"""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_REFERENCED_ENTITY_NOT_FOUND
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    optional_bool,
    order_by_created,
    paginate,
    parse_pagination,
    require_fields,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
)
from services.lookups import get_or_404

bp = Blueprint("biometrics", __name__)


@bp.route("/biometric-captures", methods=["POST"])
def create_biometric():
    require_auth(["EnrollmentOfficer"])
    body = get_body()
    require_fields(body, ["appointment_id", "fingerprint_quality"])
    appointment_id = require_str(body, "appointment_id")
    quality = require_int(body, "fingerprint_quality", minimum=1, maximum=5)
    photo = optional_bool(body, "photo_captured", default=False)

    appt = db.appointments.get(appointment_id)
    if appt is None:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 404, "appointment_id does not exist")

    status = "ACCEPTED" if (quality <= 3 and photo) else "REJECTED"
    rec = {
        "appointment_id": appointment_id,
        "application_id": appt.get("application_id"),
        "fingerprint_quality": quality,
        "photo_captured": photo,
        "status": status,
    }
    stamp_create(rec)
    db.biometric_captures[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/appointments/<aid>/biometric-captures", methods=["GET"])
def list_biometrics(aid):
    require_auth(["EnrollmentOfficer", "SchedulingAdmin"])
    get_or_404(db.appointments, aid, "Appointment")
    limit, offset = parse_pagination()
    items = [b for b in db.biometric_captures.values() if b.get("appointment_id") == aid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
