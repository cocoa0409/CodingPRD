"""The state white lists of eligible surplus lines insurers (PRD 3.2)."""

from flask import Blueprint

import auth
import clock
import eligibility
import serialize
import validation
from envelope import created, ok
from errors import ApiError
from routes.common import arg, filtered, list_response
from store import db, touch

bp = Blueprint("eligibilities", __name__)


@bp.post("/carrier-eligibilities")
def create_eligibility():
    auth.require("StateRegulator")
    data = validation.body()
    # Rung 5: carrier_id is declared before state_program_id.
    carrier = auth.body_fk(data, "carrier_id", "carriers", "carrier")
    program = auth.body_fk(data, "state_program_id", "state_programs",
                           "state_program")
    validation.req_str(data, "carrier_id")
    validation.req_str(data, "state_program_id")
    listed_at, listed_raw = validation.req_datetime(data, "listed_on")

    if int(carrier.get("capital_surplus_cents") or 0) < \
            int(program.get("min_carrier_capital_surplus_cents") or 0):
        raise ApiError("ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM",
                       "The carrier's capital and surplus is below the state "
                       "minimum for listability.")

    if eligibility.window_conflict(carrier["id"], program["id"], listed_at):
        raise ApiError("ERR_ELIGIBILITY_WINDOW_CONFLICT",
                       "The listing window collides with an existing window on "
                       "this carrier and state.")

    rec = db.insert("carrier_eligibilities", {
        "carrier_id": carrier["id"],
        "state_program_id": program["id"],
        "listing_status": "WHITE_LISTED",
        "listed_on": listed_raw,
        "removed_on": None,
        "_listed_at": listed_at,
        "_removed_at": None,
    })
    return created(serialize.public(rec))


@bp.get("/carrier-eligibilities/<rec_id>")
def get_eligibility(rec_id):
    auth.require(auth.ANY)
    rec = auth.path_entity("carrier_eligibilities", "carrier_eligibility", rec_id)
    return ok(serialize.public(rec))


@bp.get("/carrier-eligibilities")
def list_eligibilities():
    auth.require(auth.ANY)
    rows = filtered(db.all("carrier_eligibilities"),
                    carrier_id=arg("carrier_id"),
                    state_program_id=arg("state_program_id"),
                    listing_status=arg("listing_status"))
    return list_response(rows)


@bp.post("/carrier-eligibilities/<rec_id>/remove")
def remove_eligibility(rec_id):
    auth.require("StateRegulator")
    rec = auth.path_entity("carrier_eligibilities", "carrier_eligibility", rec_id)
    data = validation.body()
    removed_at, removed_raw = validation.opt_datetime(data, "removed_on")
    if removed_at is not None:
        listed_at = rec.get("_listed_at")
        if listed_at is not None and removed_at < listed_at:
            validation.bad("removed_on may not precede listed_on.")

    if rec.get("listing_status") != "WHITE_LISTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a WHITE_LISTED entry may be removed.")

    if removed_at is None:
        removed_at = clock.now()
        removed_raw = clock.now_raw()

    rec["listing_status"] = "REMOVED"
    rec["removed_on"] = removed_raw
    rec["_removed_at"] = removed_at
    touch(rec)
    return ok(serialize.public(rec))
