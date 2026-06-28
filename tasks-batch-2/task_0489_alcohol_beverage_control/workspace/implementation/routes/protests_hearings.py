"""Protests and hearings: file/withdraw/schedule-hearing protests, render
hearings, plus the fetch and reverse-reachable child reads."""
from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS, get_caller, KNOWN_ROLES
from clock import clock, parse_iso
from db import db, new_id, common_fields, touch
from helpers import body, paginate, sort_created, out, out_list, get_or_404
import validate
from response import ok, created, listed

bp = Blueprint("protests_hearings", __name__)

GROUNDS = {"PUBLIC_NUISANCE", "OVER_CONCENTRATION", "ZONING", "MORAL_CHARACTER"}
HEARING_OUTCOMES = {"PROTEST_SUSTAINED", "PROTEST_OVERRULED"}

# Roles permitted to file a protest (everyone, including Anonymous/public).
PROTEST_FILE_ROLES = {
    "Director", "LicensingExaminer", "AdjudicationOfficer", "ZoningOfficer",
    "Investigator", "Applicant", "Anonymous",
}


# --- Protests ----------------------------------------------------------------
@bp.route("/protests", methods=["POST"])
def file_protest():
    # The public protest endpoint is the single anonymous-allowed write.
    caller = get_caller()
    if caller is not None and caller.role not in PROTEST_FILE_ROLES:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted")
    # caller is None => anonymous public party (allowed here).

    data = body()
    application_id = validate.require_str(data, "application_id")
    app = db.license_applications.get(application_id)
    if app is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Application not found")
    protester_name = validate.require_str(data, "protester_name")
    grounds = validate.require_enum(data, "grounds", GROUNDS)

    # priority 9: protest window must be open
    if app["status"] != "PROTEST_PERIOD" or clock.now() >= app["protest_period_ends_at"]:
        raise errors.err(errors.ERR_PROTEST_WINDOW_CLOSED, "Protest window closed")

    ent = {
        "id": new_id(), "application_id": application_id,
        "protester_name": protester_name, "grounds": grounds,
        "status": "FILED", "hearing_id": None,
    }
    ent.update(common_fields())
    db.protests[ent["id"]] = ent
    return created(out(ent))


@bp.route("/protests/<id>", methods=["GET"])
def get_protest(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.protests, id)
    return ok(out(ent))


@bp.route("/protests/<id>/schedule-hearing", methods=["POST"])
def schedule_hearing(id):
    require_auth(["AdjudicationOfficer"])
    protest = get_or_404(db.protests, id)
    if protest["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Protest not FILED")
    app = db.license_applications.get(protest["application_id"])
    if app is None or app["status"] != "PROTEST_PERIOD":
        raise errors.err(errors.ERR_INVALID_STATE, "Application not in PROTEST_PERIOD")

    data = body()
    room_code = validate.require_str(data, "room_code")
    starts_raw = validate.require(data, "starts_at")
    ends_raw = validate.require(data, "ends_at")
    try:
        starts_at = parse_iso(starts_raw)
        ends_at = parse_iso(ends_raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid hearing window")
    if not ends_at > starts_at:
        raise errors.err(errors.ERR_INVALID_REQUEST, "ends_at must be after starts_at")

    # priority 12: half-open room overlap. [a,b) overlaps [c,d) iff a < d and c < b.
    for h in db.hearings.values():
        if h["room_code"] != room_code:
            continue
        if starts_at < h["ends_at"] and h["starts_at"] < ends_at:
            raise errors.err(errors.ERR_HEARING_ROOM_CONFLICT, "Hearing room conflict")

    hearing = {
        "id": new_id(), "application_id": app["id"], "room_code": room_code,
        "starts_at": starts_at, "ends_at": ends_at, "outcome": "PENDING",
        "status": "PENDING", "officer_user_id": None,
    }
    hearing.update(common_fields())
    db.hearings[hearing["id"]] = hearing

    protest["status"] = "SCHEDULED"
    protest["hearing_id"] = hearing["id"]
    touch(protest)

    app["status"] = "PROTEST_HEARING"
    touch(app)
    return ok(out(protest))


@bp.route("/protests/<id>/withdraw", methods=["POST"])
def withdraw_protest(id):
    require_auth(["Director"])
    protest = get_or_404(db.protests, id)
    if protest["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Protest not FILED")
    protest["status"] = "WITHDRAWN"
    touch(protest)
    return ok(out(protest))


@bp.route("/protests/<id>/hearings", methods=["GET"])
def list_protest_hearings(id):
    require_auth(ALL_READERS)
    protest = get_or_404(db.protests, id)
    items = []
    if protest["hearing_id"] is not None:
        h = db.hearings.get(protest["hearing_id"])
        if h is not None:
            items.append(h)
    items = sort_created(items)
    window, limit, offset, total = paginate(items)
    return listed(out_list(window), limit, offset, total)


# --- Hearings ----------------------------------------------------------------
@bp.route("/hearings/<id>", methods=["GET"])
def get_hearing(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.hearings, id)
    return ok(out(ent))


@bp.route("/hearings/<id>/render", methods=["POST"])
def render_hearing(id):
    caller = require_auth(["AdjudicationOfficer"])
    hearing = get_or_404(db.hearings, id)
    if hearing["outcome"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Hearing already rendered")
    data = body()
    outcome = validate.require_enum(data, "outcome", HEARING_OUTCOMES)

    # may render only once the clock has reached starts_at
    if clock.now() < hearing["starts_at"]:
        raise errors.err(errors.ERR_INVALID_STATE, "Hearing not yet started")

    app = db.license_applications.get(hearing["application_id"])
    # find the scheduled protest for this hearing
    protest = None
    for p in db.protests.values():
        if p["hearing_id"] == hearing["id"]:
            protest = p
            break

    hearing["officer_user_id"] = caller.user_id
    hearing["outcome"] = outcome
    hearing["status"] = outcome

    if outcome == "PROTEST_OVERRULED":
        if protest is not None:
            protest["status"] = "OVERRULED"
            touch(protest)
        if app is not None:
            app["status"] = "PROTEST_PERIOD"
            touch(app)
    else:  # PROTEST_SUSTAINED
        if protest is not None:
            protest["status"] = "SUSTAINED"
            touch(protest)
        if app is not None:
            app["status"] = "DENIED"
            if app.get("quota_slot_held"):
                app["quota_slot_held"] = False
            touch(app)
    touch(hearing)
    return ok(out(hearing))
