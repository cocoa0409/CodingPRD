"""PeerToPeerConference resolution."""

from flask import request as flask_request

from db import db, touch
from errors import ApiError, ERR_NOT_ASSIGNED_MD, ERR_P2P_NOT_RESOLVABLE
from middleware import ROLE_MD, authorize, get_or_404, json_body, req_enum
from response import ok, serialize
from . import make_blueprint

bp = make_blueprint("conferences")


@bp.route("/peer-to-peer-conferences/<cid>/resolve", methods=["POST"])
def resolve_conference(cid):
    authorize(ROLE_MD)
    conf = get_or_404(db.conferences, cid, "peer-to-peer conference")
    body = json_body()
    outcome = req_enum(body, "outcome", ("COMPLETED", "NO_SHOW"))
    if conf["status"] != "SCHEDULED":
        raise ApiError(
            ERR_P2P_NOT_RESOLVABLE,
            409,
            "resolve requires conference status SCHEDULED",
        )
    uid = flask_request.headers.get("X-User-ID")
    if uid != conf["md_user_id"]:
        raise ApiError(
            ERR_NOT_ASSIGNED_MD,
            403,
            "resolve caller is not the scheduling md_user_id",
        )
    conf["status"] = outcome
    touch(conf)
    return ok(serialize(conf))
