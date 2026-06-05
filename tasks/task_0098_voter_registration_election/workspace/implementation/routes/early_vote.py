"""EarlyVoteCheckIn endpoints (PRD §3.7)."""

from flask import Blueprint, g, request

import db
from errors import APIError, not_found
import errors as E
from middleware import require_roles
from response import ok_object, ok_array
from services import serialize
from services.common import (
    get_json_body, require_fields, paginate, parse_iso, clock_now,
)

bp = Blueprint("early_vote", __name__)


@bp.route("/early-vote-checkins", methods=["POST"])
def create_checkin():
    require_roles("PollWorker")
    body = get_json_body()
    require_fields(body, "registration_id")
    reg = db.registrations.get(body["registration_id"])
    if reg is None:
        raise not_found("Registration not found.")

    # State (priority 11): registration must be ACTIVE.
    if reg["status"] != "ACTIVE":
        raise APIError(E.ERR_REGISTRATION_NOT_ACTIVE,
                       "Registration is not ACTIVE.", 409)

    # Temporal window (priority 6): [early_voting_start, early_voting_end).
    election = db.elections.get(reg["election_id"])
    now = clock_now()
    if now < parse_iso(election["early_voting_start"]) or \
            now >= parse_iso(election["early_voting_end"]):
        raise APIError(E.ERR_WINDOW_CLOSED,
                       "Outside the early-voting window.", 422)

    # Double-vote guard (priority 14).
    if reg.get("early_voted_at") is not None:
        raise APIError(E.ERR_ALREADY_VOTED, "Voter already checked in.", 409)
    for b in db.ballots.values():
        if (b["registration_id"] == reg["id"]
                and b["request_status"] in ("ISSUED", "RETURNED", "ACCEPTED")):
            raise APIError(E.ERR_ALREADY_VOTED,
                           "Voter has an in-flight absentee ballot.", 409)

    instant = db.current_utc_iso()
    row = {
        "registration_id": reg["id"],
        "precinct_id": reg.get("precinct_id"),
        "checked_in_at": instant,
    }
    db.stamp_create_light(row)
    db.early_vote_checkins[row["id"]] = row

    # Stamp the registration's early_voted_at (recompute turnout reads off this).
    reg["early_voted_at"] = instant
    db.stamp_update(reg)
    return ok_object(serialize.checkin_view(row), 201)


@bp.route("/early-vote-checkins/<cid>", methods=["GET"])
def get_checkin(cid):
    require_roles("ElectionAdmin", "Canvasser", "PollWorker")
    c = db.early_vote_checkins.get(cid)
    if c is None:
        raise not_found("Early-vote check-in not found.")
    return ok_object(serialize.checkin_view(c))


@bp.route("/early-vote-checkins", methods=["GET"])
def list_checkins():
    require_roles("ElectionAdmin", "Canvasser", "PollWorker")
    reg_id = request.args.get("registration_id")
    precinct_id = request.args.get("precinct_id")
    rows = list(db.early_vote_checkins.values())
    if reg_id is not None:
        rows = [r for r in rows if r["registration_id"] == reg_id]
    if precinct_id is not None:
        rows = [r for r in rows if r.get("precinct_id") == precinct_id]
    page, limit, offset, total, has_more = paginate(rows)
    return ok_array([serialize.checkin_view(r) for r in page],
                    limit=limit, offset=offset, total_count=total, has_more=has_more)
