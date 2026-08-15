"""CharacterTrack endpoints: create/list under tour, list/get/patch flat."""

from flask import Blueprint, request

import db
from errors import (err, ERR_NOT_FOUND, ERR_PRINCIPAL_NOT_CONTRACTED,
                    ERR_PRINCIPAL_DOUBLE_BOOKED)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain
from util import (get_body, reject_unknown, require_present, as_int, as_str,
                  paginate)

bp = Blueprint("tracks", __name__)


def _validate_principal(tour_id, member_id, exclude_track_id=None,
                        existence_only=False):
    """Existence (p3): member resolves. Referential (p9): member CONTRACTED on
    the same tour, and principal of at most one track of the tour."""
    member = db.cast_members.get(member_id) if isinstance(member_id, str) else None
    if member is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    if existence_only:
        return
    if member["status"] != "CONTRACTED" or member["tour_id"] != tour_id:
        raise err(ERR_PRINCIPAL_NOT_CONTRACTED, 422,
                  "Principal must be a CONTRACTED member of the same tour")
    for t in domain.tracks_of_tour(tour_id):
        if t["id"] == exclude_track_id:
            continue
        if t.get("principal_member_id") == member_id:
            raise err(ERR_PRINCIPAL_DOUBLE_BOOKED, 422,
                      "Member is already principal of another track of this tour")


def _exposed(track):
    return (False if track["required_covers"] == 0
            else track["available_covers"] < track["required_covers"])


@bp.route("/tours/<tour_id>/tracks", methods=["POST"])
def create_track(tour_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    if db.tours.get(tour_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    body = get_body()
    # Existence of the body FK before shape when present.
    if body.get("principal_member_id") is not None:
        _validate_principal(tour_id, body["principal_member_id"],
                            existence_only=True)
    reject_unknown(body, {"track_name", "required_covers", "principal_member_id"})
    name = as_str(require_present(body, "track_name"), "track_name")
    required = as_int(require_present(body, "required_covers"), "required_covers", minv=0)
    principal = body.get("principal_member_id")
    if principal is not None:
        as_str(principal, "principal_member_id")
        _validate_principal(tour_id, principal)
    rec = db.new_record()
    rec.update({
        "tour_id": tour_id,
        "track_name": name,
        "required_covers": required,
        "principal_member_id": principal,
        "available_covers": 0,
        "exposed": required > 0,
    })
    db.tracks[rec["id"]] = rec
    return success(db.serialize("track", rec), 201)


@bp.route("/tours/<tour_id>/tracks", methods=["GET"])
def list_tracks_of_tour(tour_id):
    authenticate()
    if db.tours.get(tour_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    items = sorted(domain.tracks_of_tour(tour_id), key=lambda t: t["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("track", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/tracks", methods=["GET"])
def list_tracks():
    authenticate()
    items = list(db.tracks.values())
    tour_id = request.args.get("tour_id")
    principal = request.args.get("principal_member_id")
    if tour_id is not None:
        items = [t for t in items if t["tour_id"] == tour_id]
    if principal is not None:
        items = [t for t in items if t.get("principal_member_id") == principal]
    items.sort(key=lambda t: t["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("track", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/tracks/<track_id>", methods=["GET"])
def get_track(track_id):
    authenticate()
    track = db.tracks.get(track_id)
    if track is None:
        raise err(ERR_NOT_FOUND, 404, "Track not found")
    return success(db.serialize("track", track), 200)


@bp.route("/tracks/<track_id>", methods=["PATCH"])
def patch_track(track_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    track = db.tracks.get(track_id)
    if track is None:
        raise err(ERR_NOT_FOUND, 404, "Track not found")
    body = get_body()
    reject_unknown(body, {"principal_member_id"})
    member_id = as_str(require_present(body, "principal_member_id"),
                       "principal_member_id")
    _validate_principal(track["tour_id"], member_id, exclude_track_id=track_id)
    track["principal_member_id"] = member_id
    domain.recompute_track(track)  # exposed recomputes (a genuine mutation)
    return success(db.serialize("track", track), 200)
