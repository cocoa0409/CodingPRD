"""PointOfDiversion (headgate) endpoints."""
from flask import Blueprint

import calc
import db
import derive
import middleware
import response
import serialize
import validate
from routes import common

bp = Blueprint("points_of_diversion", __name__)

POD_STATUSES = ("PROPOSED", "AUTHORIZED", "RETIRED")


@bp.route("/water-rights/<rid>/points-of-diversion", methods=["POST"])
def create_pod(rid):
    middleware.authenticate((middleware.ROLE_ANALYST, middleware.ROLE_ADJUDICATOR))
    right = common.get_right(rid)

    body = validate.get_body()
    legal_description = validate.req_str(body, "legal_description", 1, 120)
    stream_reach_code = validate.req_str(body, "stream_reach_code", 1, 24)
    max_rate = validate.req_decimal(body, "max_rate_cfs", gt=0)
    miles = validate.req_decimal(body, "stream_miles_from_headwater", gte=0)

    row = db.base_row()
    row.update({
        "water_right_id": right["id"],
        "legal_description": legal_description,
        "stream_reach_code": stream_reach_code,
        "max_rate_cfs": calc.q3(max_rate),
        "stream_miles_from_headwater": calc.q2(miles),
        "status": "PROPOSED",
    })
    db.points_of_diversion[row["id"]] = row
    return response.object_response(serialize.point_of_diversion(row), 201)


@bp.route("/water-rights/<rid>/points-of-diversion", methods=["GET"])
def list_pods(rid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    right = common.get_right(rid)
    middleware.require_owner(caller, right["claimant_id"])

    limit, offset = validate.pagination()
    status = validate.query_enum("status", POD_STATUSES)

    rows = [
        p
        for p in derive.pods_for_right(right["id"])
        if status is None or p["status"] == status
    ]
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.point_of_diversion, limit, offset)


@bp.route("/points-of-diversion/<pid>", methods=["GET"])
def get_pod(pid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    pod = common.get_pod(pid)
    middleware.require_owner(caller, common.pod_owner(pod))
    return response.object_response(serialize.point_of_diversion(pod))
