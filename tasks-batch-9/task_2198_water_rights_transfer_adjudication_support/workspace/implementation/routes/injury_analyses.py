"""Injury analyses attached to a transfer application."""
from flask import Blueprint

import calc
import cascades
import db
import derive
import middleware
import response
import serialize
import validate
from errors import ApiError
from routes import common

bp = Blueprint("injury_analyses", __name__)

METHODS = ("INSTANTANEOUS_DEPLETION", "SEASONAL_AVERAGE")
ANALYSIS_STATUSES = ("DRAFT", "FINALIZED", "VOIDED")
ANALYSABLE_APP_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "PROTEST_PERIOD",
    "UNDER_PROTEST",
    "REVISION_REQUESTED",
    "READY_FOR_DECISION",
)


@bp.route("/transfer-applications/<aid>/injury-analyses", methods=["POST"])
def create_analysis(aid):
    caller = middleware.authenticate(
        (middleware.ROLE_ANALYST, middleware.ROLE_HEARING, middleware.ROLE_ADJUDICATOR)
    )
    app = common.get_app(aid)

    body = validate.get_body()
    method = validate.req_enum(body, "method", METHODS)
    pod_move_miles = validate.req_decimal(body, "pod_move_miles", gte=0)
    credit = validate.opt_decimal(
        body, "return_flow_credit_af", gte=0, default=calc.D("0.00")
    )

    if app["status"] not in ANALYSABLE_APP_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "An application in status %s can no longer be analysed." % app["status"],
        )

    cascades.void_draft_analyses(app)

    row = db.base_row()
    row.update({
        "transfer_application_id": app["id"],
        "method": method,
        "pod_move_miles": calc.q2(pod_move_miles),
        "return_flow_credit_af": calc.q2(credit),
        "offset_af": calc.D("0.00"),
        "gross_depletion_af": calc.D("0.00"),
        "net_injury_af": calc.D("0.00"),
        "status": "DRAFT",
        "prepared_by_user_id": caller.user_id,
    })
    db.injury_analyses[row["id"]] = row
    cascades.recompute_analysis(row, app, bump=False)

    right = db.water_rights.get(app["water_right_id"])
    if right is not None:
        derive.recompute_right(right)
        db.touch(right)
    return response.object_response(serialize.injury_analysis(row), 201)


@bp.route("/transfer-applications/<aid>/injury-analyses", methods=["GET"])
def list_analyses(aid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    app = common.get_app(aid)
    middleware.require_owner(caller, common.app_owner(app))

    limit, offset = validate.pagination()
    status = validate.query_enum("status", ANALYSIS_STATUSES)
    rows = [
        a
        for a in derive.analyses_for_app(app["id"])
        if status is None or a["status"] == status
    ]
    rows = common.sort_created_asc(rows)
    return common.emit(rows, serialize.injury_analysis, limit, offset)


@bp.route("/injury-analyses/<anid>", methods=["GET"])
def get_analysis(anid):
    caller = middleware.authenticate(middleware.ALL_ROLES)
    analysis = common.get_analysis(anid)
    middleware.require_owner(caller, common.analysis_owner(analysis))
    return response.object_response(serialize.injury_analysis(analysis))
