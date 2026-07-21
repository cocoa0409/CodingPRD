"""Tracks — PRD §3.3."""

from flask import Blueprint, request

from db import db, common_fields, touch
from errors import ApiError
from middleware import auth, require_ownership
from response import created, ok, ok_list, paginate, read_pagination
from services import core
import validation as v

bp = Blueprint("tracks", __name__)


def plan_allows_content_id(artist_id):
    subscription = core.any_subscription(artist_id)
    if subscription is None:
        return False
    plan = db.subscription_plans.get(subscription["plan_id"])
    return bool(plan and plan["allows_content_id"])


def owned_track(user_id, role, track_id):
    track = db.tracks.get(track_id)
    if role == "Artist" and track is not None:
        require_ownership(user_id == core.artist_of_track(track))
    return core.find_track(track_id)


@bp.post("/api/releases/<release_id>/tracks")
def create_track(release_id):
    user_id, role = auth("Artist")
    data = v.body()
    title = v.req_string(data, "title")
    duration_seconds = v.req_int(data, "duration_seconds", minimum=1)
    track_number = v.req_int(data, "track_number", minimum=1)
    isrc, has_isrc = v.opt_string(data, "isrc")
    if has_isrc:
        v.check_isrc(isrc)
    explicit, has_explicit = v.opt_bool(data, "explicit", nullable=True)
    content_id_enabled, has_cid = v.opt_bool(data, "content_id_enabled")

    release = db.releases.get(release_id)
    if role == "Artist" and release is not None:
        require_ownership(user_id == release["artist_id"])
    release = core.find_release(release_id)

    if release["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Tracks may only be added to a DRAFT release.")

    siblings = core.tracks_of_release(release["id"])
    if any(t["track_number"] == track_number for t in siblings):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "track_number already used on this release.")
    if isrc is not None and any(t["isrc"] == isrc for t in db.tracks.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "isrc already in use.")

    wants_content_id = bool(content_id_enabled) if has_cid else False
    if wants_content_id and not plan_allows_content_id(release["artist_id"]):
        raise ApiError("ERR_CONTENT_ID_NOT_ENTITLED")

    row = common_fields()
    row.update({
        "release_id": release["id"],
        "title": title,
        "isrc": isrc if has_isrc else None,
        "duration_seconds": duration_seconds,
        "track_number": track_number,
        "explicit": explicit if has_explicit else None,
        "content_id_enabled": wants_content_id,
        "status": "PENDING",
        "locked_split_sheet_id": None,
    })
    db.tracks[row["id"]] = row
    return created(row)


@bp.get("/api/tracks/<track_id>")
def read_track(track_id):
    user_id, role = auth("Artist", "DistributionOps", "FinanceOps", "PlatformAdmin")
    return ok(owned_track(user_id, role, track_id))


@bp.get("/api/tracks")
def list_tracks():
    user_id, role = auth("Artist", "DistributionOps", "FinanceOps", "PlatformAdmin")
    limit, offset = read_pagination(request.args)
    rows = list(db.tracks.values())
    if role == "Artist":
        own = {r["id"] for r in db.releases.values() if r["artist_id"] == user_id}
        rows = [t for t in rows if t["release_id"] in own]
    release_id = request.args.get("release_id")
    if release_id is not None:
        rows = [t for t in rows if t["release_id"] == release_id]
    status = request.args.get("status")
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/api/tracks/<track_id>")
def update_track(track_id):
    user_id, role = auth("Artist")
    data = v.body()
    title, has_title = v.opt_string(data, "title", nullable=False)
    isrc, has_isrc = v.opt_string(data, "isrc")
    if has_isrc:
        v.check_isrc(isrc)
    explicit, has_explicit = v.opt_bool(data, "explicit", nullable=True)
    content_id_enabled, has_cid = v.opt_bool(data, "content_id_enabled")
    duration_seconds, has_duration = v.opt_int(data, "duration_seconds", minimum=1)

    track = owned_track(user_id, role, track_id)

    if has_isrc and isrc is not None:
        if any(t["isrc"] == isrc and t["id"] != track["id"] for t in db.tracks.values()):
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "isrc already in use.")

    if has_cid and content_id_enabled:
        if not plan_allows_content_id(core.artist_of_track(track)):
            raise ApiError("ERR_CONTENT_ID_NOT_ENTITLED")

    if has_title:
        track["title"] = title
    if has_isrc:
        track["isrc"] = isrc
    if has_explicit:
        track["explicit"] = explicit
    if has_cid:
        track["content_id_enabled"] = content_id_enabled
    if has_duration:
        track["duration_seconds"] = duration_seconds
    touch(track)
    return ok(track)
