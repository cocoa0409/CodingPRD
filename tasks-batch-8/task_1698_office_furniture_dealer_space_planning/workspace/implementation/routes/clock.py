"""Logical clock routes (PRD 2.7): DealerAdmin-settable test-driving clock.

Setting the clock triggers the two automatic sweeps: ACTIVE contracts whose
effective_to is earlier than the new current UTC date -> EXPIRED; APPRAISED
lots whose appraised_at is more than 30 days before the new date -> EXPIRED.
"""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize
from services.core import touch
from services.pricing import appraisal_expired
from util import CLOCK, parse_instant, parse_date
from validate import body_dict

bp = Blueprint("clock", __name__)


def run_sweeps():
    today = CLOCK.today()
    for contract in db["pricing_contracts"].values():
        if contract["status"] != "ACTIVE":
            continue
        effective_to = parse_date(contract.get("effective_to"))
        if effective_to is not None and effective_to < today:
            contract["status"] = "EXPIRED"
            touch(contract)
    for lot in db["liquidation_lots"].values():
        if lot["status"] != "APPRAISED":
            continue
        if lot.get("appraised_at") and appraisal_expired(lot["appraised_at"], today):
            lot["status"] = "EXPIRED"
            touch(lot)


@bp.route("/api/_clock", methods=["GET"])
def read_clock():
    authorize(ALL_ROLES)
    return success_object({"current_utc": CLOCK.now_iso()})


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["DealerAdmin"])
    body = body_dict()
    target = parse_instant(body.get("to_iso8601"))
    if target is None:
        raise_error(ERR_INVALID_REQUEST, "field 'to_iso8601' is required and must be an ISO 8601 instant")
    if target < CLOCK.now():
        raise_error(ERR_INVALID_REQUEST, "the logical clock only advances; to_iso8601 precedes the current logical time")
    CLOCK.set(target)
    run_sweeps()
    return success_object({"current_utc": CLOCK.now_iso()})
