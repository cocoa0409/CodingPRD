"""Client routes (PRD 3.1)."""

from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body
from response import object_response
from services import common, serialize, ownership

bp = Blueprint("clients", __name__)


@bp.route("/staffing/clients", methods=["POST"])
def create_client():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()

    name = common.require_str(body, "name")
    credit_limit_cents = common.require_int(body, "credit_limit_cents")
    # conversion_fee_pct optional; defaults to 0.20; must be > 0 and <= 1.
    if "conversion_fee_pct" in body and body["conversion_fee_pct"] is not None:
        pct = common.require_number(body, "conversion_fee_pct")
        if not (pct > 0 and pct <= 1):
            raise ApiError(errors.ERR_VALIDATION, 422, "conversion_fee_pct must be in (0, 1].")
    else:
        pct = 0.20

    rec = common.init_mutable({
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "conversion_fee_pct": pct,
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
        "open_exposure_cents": 0,
    })
    db.clients[rec["id"]] = rec
    return object_response(serialize.client(rec), 201)


@bp.route("/staffing/clients/<cid>", methods=["GET"])
def get_client(cid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    rec = common.get_or_404(db.clients, cid, errors.ERR_CLIENT_NOT_FOUND)
    if role == "Client":
        ownership.client_owns(user_id, rec["id"])
    return object_response(serialize.client(rec), 200)


@bp.route("/staffing/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    rec = common.get_or_404(db.clients, cid, errors.ERR_CLIENT_NOT_FOUND)
    # PRD 3.1: status ACTIVE -> SUSPENDED. (No explicit guard error is named;
    # suspending an already-suspended client simply re-asserts SUSPENDED.)
    rec["status"] = "SUSPENDED"
    common.touch(rec)
    return object_response(serialize.client(rec), 200)
