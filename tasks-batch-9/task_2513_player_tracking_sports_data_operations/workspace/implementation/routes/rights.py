"""Rights windows: allocation out of a finite pool, and revocation (PRD §3.7)."""

from flask import Blueprint

import db
from auth import authenticate
from calc import (HOLDER_TYPES, RIGHTS_CLASSES, SCOPE_MEMBERS,
                  window_allocated_minutes)
from db import audit_new, new_id, store, touch
from errors import ApiError
from lookups import (require_club, require_game, require_licensee,
                     require_rights_window)
from response import array_response, object_response
from services.billing import settle_and_terminate
from services.rights import has_rights_window_collision, recompute_game_ledger
from util import parse_dt, serialize, serialize_many, sorted_rows
from validation import (field, no_body, paginate, pagination, string_filter,
                        validate_body)

bp = Blueprint("rights", __name__)

WINDOW_SPEC = {
    "rights_class": field("enum", values=RIGHTS_CLASSES),
    "holder_type": field("enum", values=HOLDER_TYPES),
    "holder_id": field("string", required=False, default=None),
    "territory": field("string"),
    "window_start_utc": field("datetime"),
    "window_end_utc": field("datetime"),
    "max_latency_ms": field("integer", minimum=1),
    "allowed_scopes": field("array", min_items=1,
                            item=field("enum", values=SCOPE_MEMBERS)),
}


@bp.post("/games/<game_id>/rights-windows")
def create_rights_window(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    body = validate_body(WINDOW_SPEC)

    holder_type = body["holder_type"]
    holder_id = body["holder_id"]

    # rank 5: the holder reference is polymorphic and resolves against the
    # declared holder_type; a missing row is a 404 naming that type.
    if holder_id is not None:
        if holder_type == "CLUB":
            require_club(holder_id)
        elif holder_type == "LICENSEE":
            require_licensee(holder_id)

    start = parse_dt(body["window_start_utc"])
    end = parse_dt(body["window_end_utc"])

    # rank 25
    if not (end > start):
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS",
                       "window_end_utc must be strictly after window_start_utc.")

    # rank 28
    if has_rights_window_collision(game["id"], body["rights_class"],
                                   body["territory"], start, end):
        raise ApiError("ERR_RIGHTS_WINDOW_OVERLAP",
                       "A colliding active rights window already covers this "
                       "game, class and territory.")

    # rank 41
    if holder_type == "LEAGUE":
        if holder_id is not None:
            raise ApiError("ERR_RIGHTS_HOLDER_MISMATCH",
                           "A LEAGUE window must omit holder_id.")
    elif holder_type == "CLUB":
        if holder_id is None or holder_id not in (game["home_club_id"],
                                                  game["away_club_id"]):
            raise ApiError("ERR_RIGHTS_HOLDER_MISMATCH",
                           "A CLUB window must name a club playing in this game.")
    else:  # LICENSEE
        if holder_id is None:
            raise ApiError("ERR_RIGHTS_HOLDER_MISMATCH",
                           "A LICENSEE window must name a data licensee.")

    allocated = window_allocated_minutes(start, end)

    # rank 42: the two pools are disjoint, and equality is admitted.
    if body["rights_class"] == "LEAGUE_ARCHIVE":
        room = game["league_reserve_minutes"] - game["league_reserve_allocated_minutes"]
    else:
        room = game["remaining_allocatable_minutes"]
    if allocated > room:
        raise ApiError("ERR_ALLOCATION_POOL_EXHAUSTED",
                       "The candidate window's %d minute(s) do not fit the %d "
                       "minute(s) left in its pool." % (allocated, room))

    window = {
        "id": new_id(),
        "game_id": game["id"],
        "rights_class": body["rights_class"],
        "holder_type": holder_type,
        "holder_id": holder_id,
        "territory": body["territory"],
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "max_latency_ms": body["max_latency_ms"],
        "allowed_scopes": body["allowed_scopes"],
        "allocated_minutes": allocated,
        "status": "ACTIVE",
        "revoked_at_utc": None,
        "active_feed_session_count": 0,
    }
    audit_new(window)
    store.rights_windows[window["id"]] = window

    recompute_game_ledger(game)
    touch(game)
    return object_response(serialize(window), 201)


@bp.get("/games/<game_id>/rights-windows")
def list_rights_windows(game_id):
    authenticate("LeagueDataOps", "ClubDataOfficer", "Licensee")
    require_game(game_id)
    limit, offset = pagination()
    rights_class = string_filter("rights_class")
    status = string_filter("status")
    rows = db.rights_windows_of_game(game_id)
    if rights_class is not None:
        rows = [r for r in rows if r["rights_class"] == rights_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


@bp.post("/rights-windows/<window_id>/revoke")
def revoke_rights_window(window_id):
    authenticate("LeagueDataOps")
    window = require_rights_window(window_id)
    no_body()

    # rank 18
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_RIGHTS_WINDOW_REVOKED",
                       "The rights window is already revoked.")

    window["status"] = "REVOKED"
    window["revoked_at_utc"] = store.clock_raw

    # Link 1: every session held under the window is settled exactly as a
    # voluntary termination would settle it.  Link 2, caused by link 1, moves
    # each affected licensee's ledger (handled inside the settlement).
    for session in sorted_rows(db.sessions_of_window(window["id"])):
        if session["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        settle_and_terminate(session, touch_window=False)

    touch(window)

    # The window's minutes return to the pool they came from.
    game = store.games.get(window["game_id"])
    if game is not None:
        recompute_game_ledger(game)
        touch(game)

    return object_response(serialize(window))
