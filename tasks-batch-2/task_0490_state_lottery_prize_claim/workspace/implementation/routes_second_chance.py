"""SecondChanceDrawing + SecondChanceEntry endpoints (PRD 3.9)."""
from flask import Blueprint, request

from clock import clock
from db import db
from errors import err
from middleware import get_auth, require_roles
from models import (_stamp_create, serialize, touch, get_or_404,
                    parse_pagination, paginate, sort_by_created)
from response import success
from util import parse_iso8601
from validate import require_body, req_str, req_int

sc_bp = Blueprint("second_chance", __name__)

VIEW_ROLES = {"LotteryOfficer", "ClaimsClerk", "TerminalOperator"}


def _serialize_drawing(d):
    return serialize(d)


def _serialize_entry(e):
    return serialize(e)


# ---------------------------------------------------------------------------
# Drawings
# ---------------------------------------------------------------------------
@sc_bp.route("/second-chance-drawings", methods=["POST"])
def create_drawing():
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    body = require_body(request.get_json(silent=True))

    game_id = req_str(body, "game_id")
    entry_deadline_raw = body.get("entry_deadline")
    if entry_deadline_raw is None:
        raise err("ERR_INVALID_REQUEST", "entry_deadline is required")
    entry_deadline = parse_iso8601(entry_deadline_raw, "entry_deadline")
    prize_pool_cents = req_int(body, "prize_pool_cents", minimum=1)

    get_or_404(db.games, game_id, "game")

    drawing = {
        "game_id": game_id,
        "entry_deadline": entry_deadline,
        "prize_pool_cents": prize_pool_cents,
        "entry_count": 0,
        "winning_entry_id": None,
        "status": "OPEN",
    }
    _stamp_create(drawing)
    db.drawings[drawing["id"]] = drawing
    return success(_serialize_drawing(drawing), 201)


@sc_bp.route("/second-chance-drawings/<did>", methods=["GET"])
def get_drawing(did):
    _, role = get_auth()
    require_roles(role, VIEW_ROLES)
    drawing = get_or_404(db.drawings, did, "drawing")
    return success(_serialize_drawing(drawing), 200)


@sc_bp.route("/second-chance-drawings", methods=["GET"])
def list_drawings():
    _, role = get_auth()
    require_roles(role, VIEW_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.drawings.values())
    for key in ("game_id", "winning_entry_id", "status"):
        f = request.args.get(key)
        if f is not None:
            rows = [d for d in rows if d[key] == f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_drawing(d) for d in page], 200, pagination=meta)


def _entries_of(drawing_id):
    return [e for e in db.entries.values() if e["drawing_id"] == drawing_id]


@sc_bp.route("/second-chance-drawings/<did>/run", methods=["POST"])
def run_drawing(did):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    drawing = get_or_404(db.drawings, did, "drawing")
    body = require_body(request.get_json(silent=True))
    expected_version = req_int(body, "expected_drawing_version")

    # State gate (priority 4).
    if drawing["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "drawing not OPEN")
    # OCC (priority 5).
    if expected_version != drawing["version"]:
        raise err("ERR_STALE_VERSION", "drawing version stale")
    # Temporal: clock strictly past entry_deadline (priority 13).
    if not (clock.now > drawing["entry_deadline"]):
        raise err("ERR_DRAWING_NOT_CLOSED", "entry deadline not yet passed")
    # Non-empty pool (priority 14).
    if drawing["entry_count"] < 1:
        raise err("ERR_EMPTY_DRAWING_POOL", "no entries to draw")

    entries = _entries_of(did)
    # Winner: earliest entered_at, tie-break by created_at ASC (never id).
    winner = min(entries, key=lambda e: (e["entered_at"], e["created_at"], e["_seq"]))

    drawing["winning_entry_id"] = winner["id"]
    drawing["status"] = "DRAWN"
    touch(drawing)

    for e in entries:
        ticket = db.tickets.get(e["ticket_id"])
        if e["id"] == winner["id"]:
            e["outcome"] = "WON"
            if ticket is not None and ticket["second_chance_status"] == "ENTERED":
                ticket["second_chance_status"] = "DRAWN_WINNER"
                touch(ticket)
        else:
            e["outcome"] = "LOST"
            if ticket is not None and ticket["second_chance_status"] == "ENTERED":
                ticket["second_chance_status"] = "DRAWN_LOSER"
                touch(ticket)
        touch(e)

    return success(_serialize_drawing(drawing), 200)


@sc_bp.route("/second-chance-drawings/<did>/cancel", methods=["POST"])
def cancel_drawing(did):
    _, role = get_auth()
    require_roles(role, {"LotteryOfficer"})
    drawing = get_or_404(db.drawings, did, "drawing")
    if drawing["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "drawing not OPEN")
    drawing["status"] = "CANCELLED"
    touch(drawing)
    # Release every entry's ticket back to ELIGIBLE; outcomes stay PENDING.
    for e in _entries_of(did):
        ticket = db.tickets.get(e["ticket_id"])
        if ticket is not None and ticket["second_chance_status"] == "ENTERED":
            ticket["second_chance_status"] = "ELIGIBLE"
            touch(ticket)
    return success(_serialize_drawing(drawing), 200)


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
@sc_bp.route("/second-chance-entries", methods=["POST"])
def create_entry():
    _, role = get_auth()
    require_roles(role, {"TerminalOperator", "ClaimsClerk"})
    body = require_body(request.get_json(silent=True))

    drawing_id = req_str(body, "drawing_id")
    ticket_id = req_str(body, "ticket_id")

    # Existence left-to-right: drawing then ticket.
    drawing = get_or_404(db.drawings, drawing_id, "drawing")
    ticket = get_or_404(db.tickets, ticket_id, "ticket")

    # Eligibility (priority 12): ticket ELIGIBLE, drawing OPEN, clock <= deadline.
    if (ticket["second_chance_status"] != "ELIGIBLE"
            or drawing["status"] != "OPEN"
            or clock.now > drawing["entry_deadline"]):
        raise err("ERR_ENTRY_NOT_ELIGIBLE", "entry not eligible")

    entry = {
        "drawing_id": drawing_id,
        "ticket_id": ticket_id,
        "entered_at": clock.now,
        "outcome": "PENDING",
    }
    _stamp_create(entry)
    db.entries[entry["id"]] = entry

    # Ticket ELIGIBLE -> ENTERED; drawing entry_count++.
    ticket["second_chance_status"] = "ENTERED"
    touch(ticket)
    drawing["entry_count"] += 1
    touch(drawing)

    return success(_serialize_entry(entry), 201)


@sc_bp.route("/second-chance-entries/<eid>", methods=["GET"])
def get_entry(eid):
    _, role = get_auth()
    require_roles(role, VIEW_ROLES)
    entry = get_or_404(db.entries, eid, "entry")
    return success(_serialize_entry(entry), 200)


@sc_bp.route("/second-chance-entries", methods=["GET"])
def list_entries():
    _, role = get_auth()
    require_roles(role, VIEW_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.entries.values())
    for key in ("drawing_id", "ticket_id", "outcome"):
        f = request.args.get(key)
        if f is not None:
            rows = [e for e in rows if e[key] == f]
    rows = sort_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return success([_serialize_entry(e) for e in page], 200, pagination=meta)
