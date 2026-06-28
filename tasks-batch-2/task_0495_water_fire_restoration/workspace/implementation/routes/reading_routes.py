from flask import Blueprint, request

from db import db
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from validate import pagination_params

bp = Blueprint("readings", __name__)


@bp.route("/restoration/readings/<reading_id>", methods=["GET"])
def get_reading(reading_id):
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    return object_response(get_or_404(db.readings, reading_id))


@bp.route("/restoration/readings", methods=["GET"])
def list_readings():
    auth(["Technician", "Dispatcher", "Adjuster", "PlatformAdmin"])
    chamber_id = request.args.get("chamber_id")
    job_id = request.args.get("job_id")
    limit, offset = pagination_params()

    items = list(db.readings.values())
    if chamber_id is not None:
        items = [r for r in items if r["chamber_id"] == chamber_id]
    if job_id is not None:
        items = [r for r in items if r["job_id"] == job_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
