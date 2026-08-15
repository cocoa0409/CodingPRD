"""Grower endpoints (PRD §3.2)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_FARM_CODE
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq
from validate import get_body, req_str, opt_int

bp = Blueprint("growers", __name__)


@bp.route("/mill/growers", methods=["POST"])
def create_grower():
    authorized(["Merchandiser"])
    body = get_body()
    season_id = req_str(body, "season_id")
    farm_code = req_str(body, "farm_code")
    legal_name = req_str(body, "legal_name")
    advance = opt_int(body, "advance_issued_cents", default=0, non_negative=True)
    require_resource("seasons", season_id)
    for g in db["growers"].values():
        if g["season_id"] == season_id and g["farm_code"] == farm_code:
            raise_error(ERR_DUPLICATE_FARM_CODE,
                        f"farm_code {farm_code} already used in this season")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "farm_code": farm_code,
        "legal_name": legal_name,
        "advance_issued_cents": advance,
        "advance_outstanding_cents": advance,
        "cumulative_paid_cents": 0,
    }
    core.touch_new(rec)
    db["growers"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/growers", methods=["GET"])
def list_growers():
    return list_endpoint("growers", ["season_id", "farm_code"])


@bp.route("/mill/growers/<rid>", methods=["GET"])
def get_grower(rid):
    return get_endpoint("growers", rid)
