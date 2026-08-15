"""Bin endpoints (PRD §3.5, §2.9)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_BIN_CODE
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq, q2
from validate import get_body, req_str, req_num

bp = Blueprint("bins", __name__)


@bp.route("/mill/bins", methods=["POST"])
def create_bin():
    authorized(["MillAdmin"])
    body = get_body()
    season_id = req_str(body, "season_id")
    bin_code = req_str(body, "bin_code")
    capacity = req_num(body, "capacity_cwt", positive=True)
    require_resource("seasons", season_id)
    for b in db["bins"].values():
        if b["season_id"] == season_id and b["bin_code"] == bin_code:
            raise_error(ERR_DUPLICATE_BIN_CODE,
                        f"bin_code {bin_code} already used in this season")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "bin_code": bin_code,
        "capacity_cwt": q2(capacity),
        "variety_lock": None,
        "stock_cwt": q2(0),
        "reserved_cwt": q2(0),
        "available_cwt": q2(capacity),
        "status": "AVAILABLE",
    }
    core.touch_new(rec)
    db["bins"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/bins", methods=["GET"])
def list_bins():
    return list_endpoint("bins", ["season_id", "status", "variety_lock"])


@bp.route("/mill/bins/<rid>", methods=["GET"])
def get_bin(rid):
    return get_endpoint("bins", rid)
