"""Logical clock control endpoint (PRD 2.5)."""

from flask import Blueprint

import validate
from auth import SA, require
from envelope import ok
from store import STORE

bp = Blueprint("routes_clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require(SA)
    data = validate.body()
    moment = validate.req_dt(data, "to_iso8601")
    STORE.now = moment
    for contract in STORE.ordered(STORE.payer_contracts):
        if contract["status"] != "ACTIVE":
            continue
        if contract["_term_end"] < moment:
            contract["status"] = "EXPIRED"
            STORE.touch(contract)
    return ok({})
