"""Catch crews: create, read, and crew schedule listing."""
from flask import Blueprint, request

import db
import utils
from errors import ApiError
from helpers import check_unique, get_or_404, need_int, need_str
from middleware import body, list_response, require_roles
from response import ok

bp = Blueprint("crews", __name__)

ADMIN = "IntegratorAdmin"
HAUL = "LivehaulScheduler"


@bp.route("/api/catch-crews", methods=["POST"])
@require_roles(HAUL)
def create_crew():
    b = body()
    crew_code = need_str(b, "crew_code")
    max_catches = need_int(b, "max_catches_per_day")
    if max_catches <= 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "max_catches_per_day must be positive.", 422
        )
    check_unique(db.catch_crews.values(), "crew_code", crew_code, "crew_code")
    rec = utils.make_record(
        {"crew_code": crew_code, "max_catches_per_day": max_catches}
    )
    db.catch_crews[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/catch-crews/<cid>", methods=["GET"])
@require_roles(ADMIN, HAUL)
def get_crew(cid):
    rec = get_or_404(db.catch_crews, cid, "CatchCrew")
    return ok(utils.pub(rec))


@bp.route("/api/catch-crews/<cid>/schedules", methods=["GET"])
@require_roles(ADMIN, HAUL)
def list_crew_schedules(cid):
    get_or_404(db.catch_crews, cid, "CatchCrew")
    rows = [s for s in db.catch_schedules.values() if s["crew_id"] == cid]
    return list_response(rows, {"catch_date": request.args.get("catch_date")})
