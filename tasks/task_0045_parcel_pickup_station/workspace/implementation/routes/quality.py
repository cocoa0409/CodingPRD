"""Quality assessment routes."""
from flask import Blueprint, request
from response import ok_object
from middleware import require_roles, get_auth
from services.quality import (
    create_or_fetch_assessment, get_assessment, close_assessment,
)
from services.station import get_station
from services.serialize import quality_assessment as ser_qa


bp = Blueprint("quality", __name__)


@bp.post("/stations/<station_id>/quality-assessments")
@require_roles("Manager", "PlatformAdmin")
def post_assessment(station_id):
    body = request.get_json(silent=True, force=True) or {}
    qa, created = create_or_fetch_assessment(station_id, body)
    status = 201 if created else 200
    return ok_object(ser_qa(qa), status=status)


@bp.post("/stations/<station_id>/quality-assessments/<period_yyyymm>/close")
@require_roles("Manager")
def post_close_assessment(station_id, period_yyyymm):
    get_station(station_id)
    user_id, role = get_auth()
    qa = close_assessment(station_id, period_yyyymm, role, user_id)
    return ok_object(ser_qa(qa))


@bp.get("/stations/<station_id>/quality-assessments/<period_yyyymm>")
@require_roles("Manager", "PlatformAdmin")
def read_assessment(station_id, period_yyyymm):
    get_station(station_id)
    qa = get_assessment(station_id, period_yyyymm)
    return ok_object(ser_qa(qa))
