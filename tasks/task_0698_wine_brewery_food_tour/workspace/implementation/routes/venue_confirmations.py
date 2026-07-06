"""VenueConfirmation endpoints and the cyclic confirmation loop (PRD §3.4)."""
from flask import Blueprint, request
import errors
import validate
import serialize
from db import db
from middleware import require_auth
from records import new_record, touch
from response import object_response, array_response

bp = Blueprint("venue_confirmations", __name__)

READ_ROLES = {"Operator", "PartnerVenue"}


def _require_owner(vc, user_id):
    """The acting PartnerVenue (X-User-ID) must own the confirmation
    (priority 9: ERR_NOT_RESOURCE_OWNER)."""
    if user_id != vc["partner_venue_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Acting venue does not own this confirmation")


@bp.post("/venue-confirmations")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["stop_id", "requested_headcount"])
    stop_id = body["stop_id"]
    if not isinstance(stop_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "stop_id must be a string")
    # FK existence (priority 4)
    stop = db.stops.get(stop_id)
    if stop is None:
        raise errors.err(errors.ERR_FK_NOT_FOUND, "stop_id references a non-existent stop")
    requested_headcount = validate.require_int(body, "requested_headcount")

    rec = new_record({
        "stop_id": stop_id,
        "partner_venue_id": stop["partner_venue_id"],  # copied from the Stop's venue
        "requested_headcount": requested_headcount,
        "revision_count": 0,
        "decline_note": None,
        "status": "REQUESTED",
    })
    db.venue_confirmations[rec["id"]] = rec
    return object_response(serialize.venue_confirmation(rec), status=201)


@bp.get("/venue-confirmations")
def list_confirmations():
    require_auth(READ_ROLES)
    limit, offset = validate.parse_pagination()
    stop_id = request.args.get("stop_id")
    partner_venue_id = request.args.get("partner_venue_id")
    status = request.args.get("status")
    records = list(db.venue_confirmations.values())
    if stop_id is not None:
        records = [r for r in records if r["stop_id"] == stop_id]
    if partner_venue_id is not None:
        records = [r for r in records if r["partner_venue_id"] == partner_venue_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, total = validate.paginate(records, limit, offset, serialize.venue_confirmation)
    return array_response(items, limit, offset, total)


@bp.get("/venue-confirmations/<vcid>")
def get_confirmation(vcid):
    require_auth(READ_ROLES)
    rec = db.venue_confirmations.get(vcid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Venue confirmation not found")
    return object_response(serialize.venue_confirmation(rec), status=200)


@bp.post("/venue-confirmations/<vcid>/confirm")
def confirm(vcid):
    user_id, _ = require_auth({"PartnerVenue"})
    rec = db.venue_confirmations.get(vcid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Venue confirmation not found")
    _require_owner(rec, user_id)
    if rec["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a REQUESTED confirmation can be confirmed")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return object_response(serialize.venue_confirmation(rec), status=200)


@bp.post("/venue-confirmations/<vcid>/request-changes")
def request_changes(vcid):
    user_id, _ = require_auth({"PartnerVenue"})
    rec = db.venue_confirmations.get(vcid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Venue confirmation not found")
    _require_owner(rec, user_id)
    if rec["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Only a REQUESTED confirmation can request changes")
    body = validate.get_json_body()
    validate.require_fields(body, ["decline_note"])
    decline_note = validate.require_str(body, "decline_note")
    rec["decline_note"] = decline_note
    rec["status"] = "CHANGES_REQUESTED"
    touch(rec)
    return object_response(serialize.venue_confirmation(rec), status=200)


@bp.post("/venue-confirmations/<vcid>/resubmit")
def resubmit(vcid):
    require_auth({"Operator"})
    rec = db.venue_confirmations.get(vcid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Venue confirmation not found")
    if rec["status"] != "CHANGES_REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Only a CHANGES_REQUESTED confirmation can be resubmitted")
    # revision limit: permitted only while revision_count < 3 (priority 19)
    if rec["revision_count"] >= 3:
        raise errors.err(errors.ERR_REVISION_LIMIT_REACHED, "Revision limit reached")
    body = validate.get_json_body()
    validate.require_fields(body, ["requested_headcount"])
    requested_headcount = validate.require_int(body, "requested_headcount")
    rec["requested_headcount"] = requested_headcount
    rec["revision_count"] += 1
    rec["status"] = "REQUESTED"
    touch(rec)
    return object_response(serialize.venue_confirmation(rec), status=200)


@bp.post("/venue-confirmations/<vcid>/decline")
def decline(vcid):
    user_id, _ = require_auth({"PartnerVenue"})
    rec = db.venue_confirmations.get(vcid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Venue confirmation not found")
    _require_owner(rec, user_id)
    if rec["status"] not in ("REQUESTED", "CHANGES_REQUESTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "This confirmation cannot be declined")
    body = validate.get_json_body()
    decline_note = validate.opt_str(body, "decline_note")
    if decline_note is not None:
        rec["decline_note"] = decline_note
    rec["status"] = "DECLINED"
    touch(rec)
    return object_response(serialize.venue_confirmation(rec), status=200)
