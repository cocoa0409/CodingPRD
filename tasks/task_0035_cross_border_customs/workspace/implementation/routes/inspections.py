"""Inspection appointment lifecycle endpoints (complete/cancel)."""

from flask import Blueprint

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_STATE_TRANSITION,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.serializers import serialize_inspection


bp = Blueprint("inspections", __name__)


@bp.route("/inspection_appointments/<appointment_id>/complete", methods=["POST"])
@require_roles("CustomsOfficer")
def complete_inspection(appointment_id):
    with LOCK:
        ap = DB.inspections.get(appointment_id)
        if ap is None:
            raise not_found("InspectionAppointment not found")
        if ap["status"] != "SCHEDULED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Complete only from SCHEDULED", 409)
        ap["status"] = "COMPLETED"
        return success_object(serialize_inspection(ap), status=200)


@bp.route("/inspection_appointments/<appointment_id>/cancel", methods=["POST"])
@require_roles("CustomsOfficer")
def cancel_inspection(appointment_id):
    with LOCK:
        ap = DB.inspections.get(appointment_id)
        if ap is None:
            raise not_found("InspectionAppointment not found")
        if ap["status"] != "SCHEDULED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Cancel only from SCHEDULED", 409)
        ap["status"] = "CANCELLED"
        return success_object(serialize_inspection(ap), status=200)
