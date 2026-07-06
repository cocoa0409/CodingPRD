"""PartnerVenue endpoints (PRD §3.2)."""
from flask import Blueprint
import errors
import validate
import serialize
from db import db
from middleware import require_auth, resolve_reader
from records import new_record, touch
from response import object_response

bp = Blueprint("partner_venues", __name__)

READ_ROLES = {"Operator", "PartnerVenue", "Anonymous"}


@bp.post("/partner-venues")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["name", "kind", "commission_pct", "tasting_cost_per_guest_cents"])
    name = validate.require_str(body, "name")
    kind = body["kind"]
    if not isinstance(kind, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "kind must be a string")
    commission_pct = validate.require_number(body, "commission_pct")
    tasting_cost = validate.require_int(body, "tasting_cost_per_guest_cents")

    # enum check (priority 6)
    validate.check_enum(kind, validate.VENUE_KIND_VALUES, "kind")
    # range checks (priority 7)
    if not (0.0 <= float(commission_pct) <= 0.50):
        validate.out_of_range()
    if tasting_cost < 0:
        validate.out_of_range()

    rec = new_record({
        "name": name,
        "kind": kind,
        "commission_pct": commission_pct,
        "tasting_cost_per_guest_cents": tasting_cost,
        "status": "ACTIVE",
    })
    db.partner_venues[rec["id"]] = rec
    return object_response(serialize.partner_venue(rec), status=201)


@bp.get("/partner-venues/<pvid>")
def get_venue(pvid):
    resolve_reader(READ_ROLES)
    rec = db.partner_venues.get(pvid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Partner venue not found")
    return object_response(serialize.partner_venue(rec), status=200)


@bp.post("/partner-venues/<pvid>/set-status")
def set_status(pvid):
    require_auth({"Operator"})
    rec = db.partner_venues.get(pvid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Partner venue not found")
    body = validate.get_json_body()
    validate.require_fields(body, ["status"])
    status = body["status"]
    if not isinstance(status, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "status must be a string")
    validate.check_enum(status, validate.PARTNER_STATUS_VALUES, "status")
    rec["status"] = status
    touch(rec)
    return object_response(serialize.partner_venue(rec), status=200)
