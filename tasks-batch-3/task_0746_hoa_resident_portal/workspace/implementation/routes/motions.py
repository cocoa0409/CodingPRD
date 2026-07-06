"""Motion: create, get, cast ballot, close."""

from datetime import timedelta
from math import ceil

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now, get_now_iso
from entities import bump, new_motion, new_ballot
from errors import raise_error
from response import success
from utils import (paginate, parse_iso, require_enum, require_fields,
                   require_int, require_str, require_json)

bp = Blueprint("motions", __name__)


# ---------------- Create motion ---------------- #

@bp.route("/motions", methods=["POST"])
@require_role("BoardMember")
def create_motion():
    body = require_json(request)
    require_fields(body, "title", "description", "category",
                   "voting_window_start", "voting_window_end",
                   "eligible_voter_count", "quorum_pct")
    title = require_str(body, "title")
    description = require_str(body, "description", allow_empty=True)
    category = require_enum(body, "category", {"BUDGET", "POLICY", "ELECTION"})
    vws = require_str(body, "voting_window_start")
    vwe = require_str(body, "voting_window_end")
    eligible = require_int(body, "eligible_voter_count", minimum=1)
    quorum = require_int(body, "quorum_pct", minimum=1, maximum=100)

    vws_dt = parse_iso(vws)
    vwe_dt = parse_iso(vwe)

    # Priority 10 temporal check.
    if not (vws_dt < vwe_dt):
        raise_error("ERR_MOTION_WINDOW_CONFLICT", "voting_window_start must be strictly before voting_window_end")

    # Overlap with buffered windows of same-category OPEN motions.
    buffer_start = vws_dt - timedelta(hours=24)
    buffer_end = vwe_dt + timedelta(hours=24)
    for other in db.motions.values():
        if other["status"] != "OPEN":
            continue
        if other["category"] != category:
            continue
        o_start = parse_iso(other["voting_window_start"])
        o_end = parse_iso(other["voting_window_end"])
        # Overlap of [buffer_start, buffer_end] with [o_start, o_end].
        if o_start <= buffer_end and o_end >= buffer_start:
            raise_error("ERR_MOTION_WINDOW_CONFLICT", "voting window conflicts with another OPEN motion of the same category")

    now_iso = get_now_iso()
    row = new_motion(title, description, category, vws, vwe, eligible, quorum, now_iso)
    db.motions[row["id"]] = row
    return success(row, status=201)


# ---------------- Get motion ---------------- #

@bp.route("/motions/<mid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_motion(mid):
    m = db.motions.get(mid)
    if not m:
        raise_error("ERR_NOT_FOUND", "motion not found")
    return success(m)


# ---------------- Cast ballot ---------------- #

@bp.route("/motions/<mid>/ballots", methods=["POST"])
@require_role("Homeowner", "BoardMember")
def cast_ballot(mid):
    body = require_json(request)
    m = db.motions.get(mid)
    if not m:
        raise_error("ERR_NOT_FOUND", "motion not found")

    require_fields(body, "homeowner_id", "choice")
    hid = require_str(body, "homeowner_id")
    choice = require_enum(body, "choice", {"YES", "NO", "ABSTAIN"})

    home = db.homeowners.get(hid)
    if not home:
        raise_error("ERR_FK_NOT_FOUND", "homeowner_id does not resolve")

    if m["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "motion not OPEN")

    # Priority 12: ballot uniqueness.
    for b in db.ballots.values():
        if b["motion_id"] == mid and b["homeowner_id"] == hid:
            raise_error("ERR_BALLOT_DUPLICATE", "homeowner has already cast a ballot on this motion")

    now_iso = get_now_iso()
    row = new_ballot(mid, hid, choice, now_iso)
    db.ballots[row["id"]] = row

    if choice == "YES":
        m["yes_count"] += 1
        bump(m, now_iso)
    elif choice == "NO":
        m["no_count"] += 1
        bump(m, now_iso)
    # ABSTAIN: no counter increment, but ballot exists (for quorum arithmetic).

    return success(row, status=201)


# ---------------- List ballots on a motion ---------------- #

@bp.route("/motions/<mid>/ballots", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_motion_ballots(mid):
    if mid not in db.motions:
        raise_error("ERR_NOT_FOUND", "motion not found")
    items = [b for b in db.ballots.values() if b["motion_id"] == mid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


# ---------------- Close motion ---------------- #

@bp.route("/motions/<mid>/close", methods=["POST"])
@require_role("BoardMember")
def close_motion(mid):
    require_json(request)
    m = db.motions.get(mid)
    if not m:
        raise_error("ERR_NOT_FOUND", "motion not found")

    if m["status"] != "OPEN":
        raise_error("ERR_INVALID_STATE", "motion not OPEN")
    vwe = parse_iso(m["voting_window_end"])
    if get_now() < vwe:
        raise_error("ERR_INVALID_STATE", "voting window has not ended")

    ballots_cast = sum(1 for b in db.ballots.values() if b["motion_id"] == mid)
    quorum_ceiling = ceil(m["eligible_voter_count"] * m["quorum_pct"] / 100)

    if ballots_cast < quorum_ceiling:
        m["status"] = "QUORUM_FAILED"
    elif m["yes_count"] > m["no_count"]:
        m["status"] = "CLOSED_PASSED"
    else:
        m["status"] = "CLOSED_FAILED"
    bump(m, get_now_iso())
    return success(m)
