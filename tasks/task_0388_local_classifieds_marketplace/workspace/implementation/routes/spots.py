"""SafeTradeSpot endpoints (PRD §3.6). Spots carry only id + created_at (§2.4)."""
from flask import Blueprint, request

import constants as C
from db import store
from errors import err
from listutil import paginate_and_respond
from middleware import auth_context, require_role, parse_pagination, get_json_body
from response import object_response
from serializers import spot_out, meetup_out
import validate as V

bp = Blueprint("spots", __name__)


def _find_spot(spot_id):
    s = store.safe_trade_spots.get(spot_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Safe-trade spot not found.")
    return s


@bp.route("/safe-trade-spots", methods=["POST"])
def create_spot():
    user_id, role = auth_context()
    require_role(role, {C.ROLE_PLATFORM_ADMIN})
    body = get_json_body()

    name = V.require_str(body, "name")
    is_police = V.require_bool(body, "is_police_verified", default=False)
    open_m = V.require_int(body, "open_minute_of_day", minimum=0)
    close_m = V.require_int(body, "close_minute_of_day", minimum=0)

    # 0 <= open < close <= 1440 (§3.6).
    if not (0 <= open_m < close_m <= 1440):
        raise err("ERR_INVALID_REQUEST", "Invalid operating window.")

    now = store.now()
    rec = {
        "id": store.new_id(),
        "name": name,
        "is_police_verified": is_police,
        "open_minute_of_day": open_m,
        "close_minute_of_day": close_m,
        "created_at": now,
        "_seq": store.next_seq(),
    }
    store.safe_trade_spots[rec["id"]] = rec
    return object_response(spot_out(rec), 201)


@bp.route("/safe-trade-spots", methods=["GET"])
def list_spots():
    auth_context(require_auth=False)
    limit, offset = parse_pagination(request.args)
    recs = list(store.safe_trade_spots.values())
    if "is_police_verified" in request.args:
        raw = request.args.get("is_police_verified")
        want = raw.lower() in ("true", "1")
        recs = [s for s in recs if s["is_police_verified"] == want]
    return paginate_and_respond(recs, limit, offset, spot_out)


@bp.route("/safe-trade-spots/<spot_id>", methods=["GET"])
def get_spot(spot_id):
    auth_context(require_auth=False)
    s = _find_spot(spot_id)
    return object_response(spot_out(s))


@bp.route("/safe-trade-spots/<spot_id>/meetups", methods=["GET"])
def list_spot_meetups(spot_id):
    user_id, role = auth_context()
    require_role(role, {C.ROLE_MEMBER, C.ROLE_MODERATOR, C.ROLE_PLATFORM_ADMIN})
    _find_spot(spot_id)
    limit, offset = parse_pagination(request.args)
    recs = [m for m in store.meetups.values() if m["spot_id"] == spot_id]
    status = request.args.get("status")
    if status is not None:
        recs = [m for m in recs if m["status"] == status]
    return paginate_and_respond(recs, limit, offset, meetup_out)
