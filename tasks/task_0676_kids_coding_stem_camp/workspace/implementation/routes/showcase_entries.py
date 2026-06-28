"""ShowcaseEntry routes & lifecycle (PRD §3.8).

Submit validation order (priorities): existence(4) -> program_match(6) ->
showcase_session_clash(10) -> entry_deadline_passed(11).
Accept order: existence(4) -> state(5) -> belt_too_low(12) ->
showcase_at_capacity(17) -> stale_showcase_version(18).
"""
from datetime import timedelta

from flask import Blueprint

import errors
from errors import err
from clock import clock
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, require_number, parse_pagination, parse_iso, invalid
from services import lookup
from routes.common import arg, paginate

bp = Blueprint("showcase_entries", __name__)

SHOWCASE_BUFFER_MINUTES = 120
NON_TERMINAL_ATTENDANCE = ("RESERVED", "CHECKED_IN")


@bp.route("/showcase-entries", methods=["POST"])
def create_entry():
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    body = get_body()
    showcase_id = body.get("showcase_id")
    showcase = lookup.require_showcase(showcase_id)
    member_id = body.get("member_id")
    member = lookup.require_member(member_id)
    # ownership
    lookup.check_owner(role, user_id, lookup.member_guardian_id(member))

    # program match (priority 6)
    if member["program_id"] != showcase["program_id"]:
        raise err(errors.ERR_PROGRAM_MISMATCH, "Member is not on the showcase's program.")

    # showcase-session clash (priority 10): closed buffered window around
    # showcase.starts_at must not contain the starts_at of any session the member
    # holds a non-terminal enrollment in.
    sc_start = parse_iso(showcase["starts_at"])
    buffer = timedelta(minutes=SHOWCASE_BUFFER_MINUTES)
    low = sc_start - buffer
    high = sc_start + buffer
    for e in db.enrollments.values():
        if e["member_id"] != member_id:
            continue
        if e["attendance_status"] not in NON_TERMINAL_ATTENDANCE:
            continue
        sess = db.sessions.get(e["session_id"])
        if sess is None:
            continue
        s_start = parse_iso(sess["starts_at"])
        if low <= s_start <= high:
            raise err(errors.ERR_SHOWCASE_SESSION_CLASH, "Showcase clashes with an enrolled session.")

    # entry deadline (priority 11): submit at or before entry_deadline_at (inclusive)
    deadline = parse_iso(showcase["entry_deadline_at"])
    if clock.now() > deadline:
        raise err(errors.ERR_ENTRY_DEADLINE_PASSED, "Entry deadline has passed.")

    rec = db.make({
        "showcase_id": showcase_id,
        "member_id": member_id,
        "score": None,
        "rank": None,
        "status": "SUBMITTED",
    })
    db.showcase_entries[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/showcase-entries/<rid>", methods=["GET"])
def get_entry(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_showcase_entry(rid)
    return success(out(rec))


@bp.route("/showcase-entries", methods=["GET"])
def list_entries():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    showcase_id = arg("showcase_id")
    member_id = arg("member_id")
    items = [e for e in db.showcase_entries.values()
             if (showcase_id is None or e["showcase_id"] == showcase_id)
             and (member_id is None or e["member_id"] == member_id)]
    return paginate(items, limit, offset)


@bp.route("/showcase-entries/<rid>/accept", methods=["POST"])
def accept_entry(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    entry = lookup.require_showcase_entry(rid)
    showcase = db.showcases[entry["showcase_id"]]
    body = get_body()
    # state (priority 5): entry SUBMITTED and showcase OPEN
    if entry["status"] != "SUBMITTED" or showcase["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Entry cannot be accepted from its current state.")
    # belt too low (priority 12)
    member = db.members[entry["member_id"]]
    current_belt = db.belt_levels[member["current_belt_level_id"]]
    if current_belt["rank"] < showcase["min_belt_rank"]:
        raise err(errors.ERR_BELT_TOO_LOW, "Member belt rank below minimum.")
    # capacity (priority 17)
    if showcase["accepted_entry_count"] + 1 > showcase["capacity"]:
        raise err(errors.ERR_SHOWCASE_AT_CAPACITY, "Showcase is at capacity.")
    # OCC (priority 18)
    expected = body.get("expected_showcase_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid("expected_showcase_version is required and must be an integer.")
    if expected != showcase["version"]:
        raise err(errors.ERR_STALE_SHOWCASE_VERSION, "Showcase version is stale.")

    entry["status"] = "ACCEPTED"
    db.touch(entry)
    showcase["accepted_entry_count"] += 1
    db.touch(showcase)
    return success(out(entry))


@bp.route("/showcase-entries/<rid>/reject", methods=["POST"])
def reject_entry(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    entry = lookup.require_showcase_entry(rid)
    showcase = db.showcases[entry["showcase_id"]]
    if entry["status"] != "SUBMITTED" or showcase["status"] not in ("OPEN", "JUDGING"):
        raise err(errors.ERR_INVALID_STATE, "Entry cannot be rejected from its current state.")
    entry["status"] = "REJECTED"
    db.touch(entry)
    return success(out(entry))


@bp.route("/showcase-entries/<rid>/score", methods=["POST"])
def score_entry(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    entry = lookup.require_showcase_entry(rid)
    showcase = db.showcases[entry["showcase_id"]]
    if entry["status"] != "ACCEPTED" or showcase["status"] != "JUDGING":
        raise err(errors.ERR_INVALID_STATE, "Entry cannot be scored from its current state.")
    body = get_body()
    score = require_number(body, "score", minimum=0, maximum=100)
    entry["status"] = "SCORED"
    entry["score"] = score
    db.touch(entry)
    return success(out(entry))


@bp.route("/showcase-entries/<rid>/withdraw", methods=["POST"])
def withdraw_entry(rid):
    user_id, role = get_auth()
    require_role(role, {"Guardian", "CenterAdmin"})
    entry = lookup.require_showcase_entry(rid)
    member = db.members[entry["member_id"]]
    lookup.check_owner(role, user_id, member["guardian_id"])
    showcase = db.showcases[entry["showcase_id"]]
    if entry["status"] != "ACCEPTED" or showcase["status"] not in ("OPEN", "JUDGING"):
        raise err(errors.ERR_INVALID_STATE, "Entry cannot be withdrawn from its current state.")
    entry["status"] = "WITHDRAWN"
    db.touch(entry)
    showcase["accepted_entry_count"] = max(0, showcase["accepted_entry_count"] - 1)
    db.touch(showcase)
    return success(out(entry))
