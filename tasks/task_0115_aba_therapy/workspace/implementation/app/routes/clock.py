"""Test-driver clock endpoint."""
from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import add_seconds
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.cascades import evaluate_time_gated_transitions
from ..services.lookups import get_clinic
from ..services.serialize import serialize_clinic
from ..store import get_lock, stamp_update


bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_auth("ClinicAdmin")
def clock_advance():
    body = get_json_body()
    clinic_id = require_field(body, "clinic_id")
    seconds_raw = require_field(body, "seconds")

    if not isinstance(seconds_raw, int) or isinstance(seconds_raw, bool) or seconds_raw <= 0:
        raise APIError("ERR_VALIDATION", "seconds must be a strictly positive integer")

    with get_lock():
        clinic = get_clinic(clinic_id)
        clinic["now_ts"] = add_seconds(clinic["now_ts"], seconds_raw)
        stamp_update(clinic, now=clinic["now_ts"])
        evaluate_time_gated_transitions(clinic_id)

    body_out, status = success_response(serialize_clinic(clinic))
    return jsonify(body_out), status
