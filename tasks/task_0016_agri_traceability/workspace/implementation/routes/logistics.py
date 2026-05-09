"""Logistics-leg + sensor-reading top-level endpoints."""

from flask import Blueprint, jsonify, request

from middleware import require_roles
from response import error_response, paginated, success
from services import logistics as svc


bp = Blueprint("logistics", __name__)


@bp.route("/logistics-legs/<leg_id>/depart", methods=["POST"])
@require_roles("LogisticsOperator")
def depart(leg_id):
    return success(svc.depart_leg(leg_id))


@bp.route("/logistics-legs/<leg_id>/acknowledge", methods=["POST"])
@require_roles("Distributor", "LogisticsOperator", "RegulatoryOfficer")
def acknowledge(leg_id):
    return success(svc.acknowledge_leg(leg_id))


@bp.route("/logistics-legs/<leg_id>/sensor-readings", methods=["POST"])
@require_roles("LogisticsOperator")
def create_reading(leg_id):
    data, replay = svc.create_sensor_reading(leg_id)
    if replay:
        # Idempotent replay: HTTP 200 returning the original row, surfaced
        # via response_type=object whose data carries the original record plus
        # an `error_id` marker per scaffold §1.6 ERR_IDEMPOTENT_REPLAY (200 OK).
        from response import _meta_base
        body = {
            "meta": _meta_base(),
            "response_type": "object",
            "data": dict(data),
        }
        body["data"]["error_id"] = "ERR_IDEMPOTENT_REPLAY"
        body["data"]["replay_outcome"] = "ERR_IDEMPOTENT_REPLAY"
        return jsonify(body), 200
    return success(data, status_code=201)


@bp.route("/logistics-legs/<leg_id>/sensor-readings", methods=["GET"])
@require_roles("LogisticsOperator", "RegulatoryOfficer")
def list_readings(leg_id):
    items, limit, offset, total = svc.list_readings(leg_id, request.args)
    return paginated(items, limit, offset, total)
