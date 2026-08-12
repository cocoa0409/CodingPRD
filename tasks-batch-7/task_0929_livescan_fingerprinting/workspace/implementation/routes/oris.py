from flask import Blueprint, request

import constants as C
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import body_row, path_row, unique_or_400
from store import db

bp = Blueprint("oris", __name__)


@bp.post("/livescan/oris")
def create_ori():
    data = V.body()
    # rung 4 -- body foreign keys resolve before body validity is examined
    agency = body_row("agencies", data.get("agency_id")) if data.get("agency_id") else None
    ori_code = V.req_string(data, "ori_code")
    authority = V.req_string(data, "statutory_authority")
    waiver = V.opt_bool(data, "fee_waiver_eligible", default=False)
    if agency is None:
        V.bad_request("agency_id is required")
    if len(ori_code) != 9:
        V.bad_request("ori_code must be exactly nine characters")
    unique_or_400("oris", "ori_code", ori_code)
    V.enum_value("statutory_authority", authority, C.STATUTORY_AUTHORITIES)

    profile = C.ORI_AUTHORITY_PROFILE[authority]
    row = db.create(
        "oris",
        {
            "agency_id": agency["id"],
            "ori_code": ori_code,
            "statutory_authority": authority,
            "destination_requirement": profile["destination_requirement"],
            "dissemination_tier": profile["dissemination_tier"],
            "retention_permitted": profile["retention_permitted"],
            "rapback_authority": profile["rapback_authority"],
            "authority_status": "ACTIVE",
            "fee_waiver_eligible": waiver,
            "tcn_consumed_count": 0,
            "tcn_released_count": 0,
        },
    )
    return object_response(serializers.ori(row), 201)


@bp.get("/livescan/oris/<id>")
def read_ori(id):
    return object_response(serializers.ori(path_row("oris", id)))


@bp.get("/livescan/oris")
def list_oris():
    rows = list(db.oris.values())
    agency_id = request.args.get("agency_id")
    authority_status = request.args.get("authority_status")
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if authority_status is not None:
        rows = [r for r in rows if r["authority_status"] == authority_status]
    return paginate(rows, serializers.ori)


@bp.post("/livescan/oris/<id>/authority-status")
def set_authority_status(id):
    ori = path_row("oris", id)
    data = V.body()
    to_status = V.req_string(data, "to_status")
    V.enum_value("to_status", to_status, C.AUTHORITY_STATUSES)

    # rung 10 -- ACTIVE -> SUSPENDED only from ACTIVE, SUSPENDED -> ACTIVE only
    # from SUSPENDED.  Friction point 2(b): an ORI whose current state does not
    # admit the transition answers ERR_RECORD_STATE_INVALID at HTTP 409.
    if ori["authority_status"] == to_status:
        raise ApiError("ERR_RECORD_STATE_INVALID", "ORI is already %s" % to_status)

    ori["authority_status"] = to_status
    db.touch(ori)
    return object_response(serializers.ori(ori))
