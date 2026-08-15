"""Airline registration plus airline-scoped reverse-reachability lists."""
from flask import Blueprint

import errors
import helpers
from db import store
from helpers import (authenticate, get_path, json_body, paginate, req_string,
                     req_enum, opt_bool, READ_ROLES, CARRIER_CLASSES, IATA_RE)
from response import success_object, success_list
from services import (ser_airline, ser_agreement, ser_comment, ser_activity,
                      ser_mii_vote, ser_pfc, ser_settlement_line, stamp, now_dt)
from util import new_id

bp = Blueprint("airlines", __name__)


def _get_airline(airline_id):
    return get_path(store.airlines, airline_id, "Airline")


@bp.post("/airport/airlines")
def create_airline():
    authenticate(("AirportFinance",))
    body = json_body()
    iata_code = req_string(body, "iata_code")
    legal_name = req_string(body, "legal_name")
    carrier_class = req_enum(body, "carrier_class", CARRIER_CLASSES)
    pfc_approved = opt_bool(body, "pfc_approved", default=False)
    if not IATA_RE.match(iata_code):
        raise errors.invalid_request("iata_code must be exactly two uppercase letters")
    if iata_code in store.airlines_by_iata:
        raise errors.invalid_request("iata_code must be unique")
    ts = stamp()
    airline = {
        "id": new_id(),
        "iata_code": iata_code,
        "legal_name": legal_name,
        "carrier_class": carrier_class,
        "pfc_approved": pfc_approved,
        "mii_eligible_weight_kg": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.airlines[airline["id"]] = airline
    store.airlines_by_iata[iata_code] = airline
    return success_object(ser_airline(airline), status=201)


@bp.get("/airport/airlines")
def list_airlines():
    authenticate(READ_ROLES)
    items = list(store.airlines.values())
    carrier_class = helpers.request.args.get("carrier_class")
    if carrier_class is not None:
        items = [a for a in items if a["carrier_class"] == carrier_class]
    pfc = helpers.request.args.get("pfc_approved")
    if pfc is not None:
        want = pfc.strip().lower() in ("true", "1", "yes")
        items = [a for a in items if a["pfc_approved"] == want]
    data, meta = paginate(items, ser_airline)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>")
def get_airline(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    return success_object(ser_airline(airline))


@bp.get("/airport/airlines/<airline_id>/agreements")
def list_airline_agreements(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [a for a in store.agreements.values() if a["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_agreement)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>/comments")
def list_airline_comments(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [c for c in store.comments.values() if c["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_comment)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>/activity_records")
def list_airline_activity(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [r for r in store.activity_records.values() if r["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_activity)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>/mii_votes")
def list_airline_votes(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [v for v in store.mii_votes.values() if v["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_mii_vote)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>/pfc_applications")
def list_airline_pfc(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [p for p in store.pfc_applications.values() if p["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_pfc)
    return success_list(data, meta)


@bp.get("/airport/airlines/<airline_id>/settlement_lines")
def list_airline_settlement_lines(airline_id):
    authenticate(READ_ROLES)
    airline = _get_airline(airline_id)
    items = [l for l in store.settlement_lines.values() if l["airline_id"] == airline["id"]]
    data, meta = paginate(items, ser_settlement_line)
    return success_list(data, meta)
