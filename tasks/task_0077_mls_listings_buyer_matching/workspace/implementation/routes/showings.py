"""ShowingAppointment request/confirm/cancel/complete/no-show + listings."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

from db import db, server_now
from errors import err
from helpers import body, get_or_404, require_str
from middleware import authenticate
from response import ok, created, ok_list, parse_pagination, paginate
from serializers import serialize_showing
from services.entities import make_showing
from services.state import touch

bp = Blueprint("showings", __name__)


def _parse_dt(s, field):
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", f"{field} must be an ISO 8601 string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_VALIDATION", f"{field} invalid ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.post("/lockboxes/<lbid>/showings")
def request_showing(lbid):
    role, uid = authenticate({"BuyerAgent"})
    lb = get_or_404(db.lockboxes, lbid)
    data = body()
    buyer_agent_id = require_str(data, "buyer_agent_id")
    buyer_id = require_str(data, "buyer_id")
    start_s = require_str(data, "start_at")
    end_s = require_str(data, "end_at")

    # FK existence
    get_or_404(db.agents, buyer_agent_id)
    get_or_404(db.buyers, buyer_id)

    # ownership: acting agent == buyer_agent_id
    if uid != buyer_agent_id:
        raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")

    start_dt = _parse_dt(start_s, "start_at")
    end_dt = _parse_dt(end_s, "end_at")
    if not (end_dt > start_dt):
        raise err("ERR_BAD_TIME_WINDOW", "end_at must be strictly after start_at")

    rec = make_showing(lbid, buyer_agent_id, buyer_id, start_s, end_s)
    return created(serialize_showing(rec))


@bp.get("/showings/<sid>")
def get_showing(sid):
    rec = get_or_404(db.showings, sid)
    return ok(serialize_showing(rec))


@bp.get("/lockboxes/<lbid>/showings")
def list_lockbox_showings(lbid):
    get_or_404(db.lockboxes, lbid)
    limit, offset = parse_pagination()
    rows = [s for s in db.showings.values() if s["lockbox_id"] == lbid]
    rows = _apply_showing_filters(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_showing(s) for s in page], total, limit, offset)


@bp.get("/showings")
def list_showings():
    limit, offset = parse_pagination()
    rows = list(db.showings.values())
    lockbox_id = request.args.get("lockbox_id")
    if lockbox_id:
        rows = [s for s in rows if s["lockbox_id"] == lockbox_id]
    rows = _apply_showing_filters(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_showing(s) for s in page], total, limit, offset)


def _apply_showing_filters(rows):
    buyer_agent_id = request.args.get("buyer_agent_id")
    buyer_id = request.args.get("buyer_id")
    status = request.args.get("status")
    if buyer_agent_id:
        rows = [s for s in rows if s["buyer_agent_id"] == buyer_agent_id]
    if buyer_id:
        rows = [s for s in rows if s["buyer_id"] == buyer_id]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return rows


def _listing_for_showing(showing):
    lb = db.lockboxes.get(showing["lockbox_id"])
    if not lb:
        return None
    return db.listings.get(lb["listing_id"])


@bp.post("/showings/<sid>/confirm")
def confirm_showing(sid):
    role, uid = authenticate({"ListingAgent"})
    showing = get_or_404(db.showings, sid)
    lb = db.lockboxes.get(showing["lockbox_id"])
    listing = db.listings.get(lb["listing_id"]) if lb else None
    if not listing or uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if showing["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Showing not REQUESTED")
    if lb["status"] != "INSTALLED":
        raise err("ERR_LOCKBOX_DISABLED", "Lockbox is disabled")

    # overlap check against other CONFIRMED showings on same lockbox
    buffer = timedelta(minutes=lb["turnaround_minutes"])
    cand_start = _parse_dt(showing["start_at"], "start_at")
    cand_end = _parse_dt(showing["end_at"], "end_at") + buffer
    for other in db.showings.values():
        if other["id"] == sid:
            continue
        if other["lockbox_id"] != showing["lockbox_id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        o_start = _parse_dt(other["start_at"], "start_at")
        o_end = _parse_dt(other["end_at"], "end_at") + buffer
        if cand_start < o_end and o_start < cand_end:
            raise err("ERR_SHOWING_CONFLICT", "Showing conflicts with another confirmed showing")

    showing["status"] = "CONFIRMED"
    touch(showing)
    return ok(serialize_showing(showing))


@bp.post("/showings/<sid>/cancel")
def cancel_showing(sid):
    role, uid = authenticate({"BuyerAgent"})
    showing = get_or_404(db.showings, sid)
    if uid != showing["buyer_agent_id"]:
        raise err("ERR_NOT_BUYER_AGENT", "Acting agent is not the buyer agent")
    if showing["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Showing cannot be cancelled from this state")
    showing["status"] = "CANCELLED"
    touch(showing)
    return ok(serialize_showing(showing))


@bp.post("/showings/<sid>/complete")
def complete_showing(sid):
    return _closeout(sid, "COMPLETED")


@bp.post("/showings/<sid>/no-show")
def no_show(sid):
    return _closeout(sid, "NO_SHOW")


def _closeout(sid, target):
    role, uid = authenticate({"ListingAgent"})
    showing = get_or_404(db.showings, sid)
    lb = db.lockboxes.get(showing["lockbox_id"])
    listing = db.listings.get(lb["listing_id"]) if lb else None
    if not listing or uid != listing["listing_agent_id"]:
        raise err("ERR_NOT_LISTING_AGENT", "Acting agent is not the listing agent")
    if showing["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Showing not CONFIRMED")
    end_dt = _parse_dt(showing["end_at"], "end_at")
    if server_now() < end_dt:
        raise err("ERR_SHOWING_NOT_OVER", "Showing window has not elapsed")
    showing["status"] = target
    touch(showing)
    return ok(serialize_showing(showing))
