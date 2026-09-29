"""Markets."""
import re

from flask import Blueprint

import auth
import response
import store
import validate
from errors import ApiError
from store import db

from routes import common

bp = Blueprint("markets", __name__)

CODE_RE = re.compile(r"^[A-Z-]{3,12}$")
DISPLAY_MODES = ("TOTAL_UPFRONT", "EXCL_TAXES")
MARKET_STATUSES = ("ACTIVE", "CLOSED")


@bp.post("/markets")
def create_market():
    auth.authenticate(("PlatformAdmin",))
    data = validate.body()
    code = validate.str_req(data, "market_code")
    if not CODE_RE.match(code):
        raise ApiError("ERR_INVALID_REQUEST",
                       "market_code must be 3-12 uppercase letters or hyphens.")
    name = validate.str_req(data, "name")
    capacity = validate.int_req(data, "paid_slot_capacity", minimum=0)
    mode = validate.enum_req(data, "price_display_mode", DISPLAY_MODES)
    disclosure = validate.bool_opt(data, "ranking_disclosure_required", True)
    for row in db["markets"].values():
        if row["market_code"] == code:
            raise ApiError("ERR_MARKET_CODE_TAKEN")
    market = store.new_row("markets", {
        "market_code": code,
        "name": name,
        "paid_slot_capacity": capacity,
        "price_display_mode": mode,
        "ranking_disclosure_required": disclosure,
        "status": "ACTIVE",
    })
    return response.obj(market, 201)


@bp.get("/markets/<market_id>")
def read_market(market_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("markets", market_id), 200)


@bp.get("/markets")
def list_markets():
    auth.authenticate(auth.ALL_ROLES)
    status = validate.filter_enum("status", MARKET_STATUSES)
    rows = [r for r in db["markets"].values() if status is None or r["status"] == status]
    # newest first
    return common.paged(rows, reverse=True)
