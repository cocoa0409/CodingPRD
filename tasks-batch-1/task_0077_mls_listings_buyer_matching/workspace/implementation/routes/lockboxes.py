"""Lockbox install/get/list/disable."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import body, get_or_404, require_int, require_str
from middleware import authenticate
from response import ok, created, ok_list, parse_pagination, paginate
from serializers import serialize_lockbox
from services.entities import make_lockbox
from services.state import touch, lockbox_showings

bp = Blueprint("lockboxes", __name__)


@bp.post("/listings/<lid>/lockboxes")
def install_lockbox(lid):
    role, uid = authenticate({"ListingAgent"})
    listing = get_or_404(db.listings, lid)
    data = body()
    serial_no = require_str(data, "serial_no")
    access_mode = data.get("access_mode", "APPOINTMENT_ONLY")
    if access_mode is None:
        access_mode = "APPOINTMENT_ONLY"
    if access_mode not in ("APPOINTMENT_ONLY", "OPEN_ACCESS"):
        raise err("ERR_VALIDATION", "invalid access_mode")
    turnaround = require_int(data, "turnaround_minutes", required=False, default=30, min_value=0)

    if uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")

    # serial_no unique among INSTALLED lockboxes
    for lb in db.lockboxes.values():
        if lb["serial_no"] == serial_no and lb["status"] == "INSTALLED":
            raise err("ERR_DUPLICATE", "serial_no already installed")

    rec = make_lockbox(lid, serial_no, access_mode, turnaround)
    return created(serialize_lockbox(rec))


@bp.get("/lockboxes/<lbid>")
def get_lockbox(lbid):
    rec = get_or_404(db.lockboxes, lbid)
    return ok(serialize_lockbox(rec))


@bp.get("/listings/<lid>/lockboxes")
def list_lockboxes(lid):
    get_or_404(db.listings, lid)
    limit, offset = parse_pagination()
    rows = [lb for lb in db.lockboxes.values() if lb["listing_id"] == lid]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_lockbox(lb) for lb in page], total, limit, offset)


@bp.post("/lockboxes/<lbid>/disable")
def disable_lockbox(lbid):
    role, uid = authenticate({"ListingAgent"})
    lb = get_or_404(db.lockboxes, lbid)
    listing = db.listings.get(lb["listing_id"])
    if not listing or uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if lb["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Lockbox not INSTALLED")
    # refuse if any CONFIRMED showing on this lockbox
    if any(s["status"] == "CONFIRMED" for s in lockbox_showings(lbid)):
        raise err("ERR_LOCKBOX_HAS_SHOWINGS", "Lockbox has confirmed showings")
    # cascade: REQUESTED -> CANCELLED
    for s in lockbox_showings(lbid):
        if s["status"] == "REQUESTED":
            s["status"] = "CANCELLED"
            touch(s)
    lb["status"] = "DISABLED"
    touch(lb)
    return ok(serialize_lockbox(lb))
