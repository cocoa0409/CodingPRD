"""Logical clock endpoint (PRD 2.4): set current UTC + monotonic sweeps."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from services.core import touch
from util import CLOCK, parse_date
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    authorized(["ProgramAdmin"])
    body = get_body()
    to_iso8601 = body.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601.strip():
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 is required")
    try:
        new_dt = CLOCK.set(to_iso8601)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")

    new_date = new_dt.date()
    # Sweep 1: AVAILABLE lots whose expiry_date is strictly before the new clock
    # date -> EXPIRED (equal date stays AVAILABLE). Sweeps never reverse.
    lots_expired = 0
    for lot in db["lots"].values():
        if lot["status"] == "AVAILABLE" and lot["expiry_date"] is not None:
            if parse_date(lot["expiry_date"]) < new_date:
                lot["status"] = "EXPIRED"
                touch(lot)
                lots_expired += 1
    # Sweep 2: ACTIVE contracts whose term_end is strictly before the new clock
    # date -> EXPIRED (on term_end itself the contract stays ACTIVE).
    contracts_expired = 0
    for contract in db["contracts"].values():
        if contract["status"] == "ACTIVE" and parse_date(contract["term_end"]) < new_date:
            contract["status"] = "EXPIRED"
            touch(contract)
            contracts_expired += 1
    return success_object({
        "current_utc": CLOCK.now_iso(),
        "lots_expired": lots_expired,
        "contracts_expired": contracts_expired,
    })
