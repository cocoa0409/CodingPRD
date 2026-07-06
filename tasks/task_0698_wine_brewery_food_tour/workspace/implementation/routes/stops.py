"""Stop (itinerary) endpoints (PRD §3.3)."""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from middleware import require_auth, resolve_reader
from records import new_record
from response import object_response, array_response

bp = Blueprint("stops", __name__)

READ_ROLES = {"Operator", "Guide", "PartnerVenue", "Anonymous"}


@bp.post("/stops")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["departure_id", "partner_venue_id", "sequence", "dwell_minutes"])
    departure_id = body["departure_id"]
    partner_venue_id = body["partner_venue_id"]
    if not isinstance(departure_id, str) or not isinstance(partner_venue_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "FK fields must be strings")

    # FK existence (priority 4)
    departure = db.departures.get(departure_id)
    if departure is None:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "departure_id references a non-existent departure")
    if partner_venue_id not in db.partner_venues:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "partner_venue_id references a non-existent venue")

    sequence = validate.require_int(body, "sequence")
    dwell_minutes = validate.require_int(body, "dwell_minutes")

    # range check (priority 7): dwell_minutes > 0
    if dwell_minutes <= 0:
        validate.out_of_range()

    # stop added to a SCHEDULED departure (PRD §3.3)
    if departure["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Stops can only be added to a SCHEDULED departure")

    # sequence unique within its departure (priority 10)
    for s in db.stops.values():
        if s["departure_id"] == departure_id and s["sequence"] == sequence:
            raise errors.err(errors.ERR_DUPLICATE_STOP_SEQUENCE,
                             "sequence already used in this departure")

    rec = new_record({
        "departure_id": departure_id,
        "partner_venue_id": partner_venue_id,
        "sequence": sequence,
        "dwell_minutes": dwell_minutes,
        "estimated_commission_cents": 0,
        "settled_commission_cents": 0,
        "status": "PLANNED",
    })
    db.stops[rec["id"]] = rec
    return object_response(serialize.stop(rec), status=201)


@bp.get("/stops")
def list_stops():
    resolve_reader(READ_ROLES)
    limit, offset = validate.parse_pagination()
    departure_id = request.args.get("departure_id")
    partner_venue_id = request.args.get("partner_venue_id")
    records = list(db.stops.values())
    if departure_id is not None:
        records = [r for r in records if r["departure_id"] == departure_id]
    if partner_venue_id is not None:
        records = [r for r in records if r["partner_venue_id"] == partner_venue_id]
    items, total = validate.paginate(records, limit, offset, serialize.stop)
    return array_response(items, limit, offset, total)


@bp.get("/stops/<sid>")
def get_stop(sid):
    resolve_reader(READ_ROLES)
    rec = db.stops.get(sid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Stop not found")
    return object_response(serialize.stop(rec), status=200)
