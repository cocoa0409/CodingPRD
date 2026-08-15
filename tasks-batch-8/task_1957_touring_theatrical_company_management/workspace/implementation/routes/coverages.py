"""CoverageAssignment endpoints: create/list under track or cast, release."""

from flask import Blueprint, request

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_DUPLICATE_RECORD,
                    ERR_PRINCIPAL_NOT_CONTRACTED, ERR_COVERAGE_ACTIVATED)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain
from util import (get_body, reject_unknown, require_present, as_int, as_str,
                  as_enum, paginate)

bp = Blueprint("coverages", __name__)

KINDS = ("UNDERSTUDY", "SWING")
COVERAGE_STATUSES = ("STANDBY", "ACTIVATED", "SUSPENDED", "RELEASED")


@bp.route("/tracks/<track_id>/coverages", methods=["POST"])
def create_coverage(track_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    track = db.tracks.get(track_id)
    if track is None:
        raise err(ERR_NOT_FOUND, 404, "Track not found")
    body = get_body()
    member = None
    if body.get("cast_member_id") is not None:
        member = (db.cast_members.get(body["cast_member_id"])
                  if isinstance(body["cast_member_id"], str) else None)
        if member is None:
            raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    reject_unknown(body, {"cast_member_id", "kind", "priority_rank"})
    member_id = as_str(require_present(body, "cast_member_id"), "cast_member_id")
    kind = as_enum(require_present(body, "kind"), "kind", KINDS)
    rank = as_int(require_present(body, "priority_rank"), "priority_rank", minv=1)
    if member is None:
        member = db.cast_members.get(member_id)
        if member is None:
            raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    # Uniqueness (priority 7): rank unique among non-RELEASED of track+kind.
    for c in domain.coverages_of_track(track_id):
        if c["status"] != "RELEASED" and c["kind"] == kind \
                and c["priority_rank"] == rank:
            raise err(ERR_DUPLICATE_RECORD, 422,
                      "priority_rank %s is already taken for this track and kind" % rank)
    # Referential (priority 9): covering member CONTRACTED on the same tour.
    if member["status"] != "CONTRACTED" or member["tour_id"] != track["tour_id"]:
        raise err(ERR_PRINCIPAL_NOT_CONTRACTED, 422,
                  "Covering member must be a CONTRACTED member of the same tour")
    rec = db.new_record()
    rec.update({
        "track_id": track_id,
        "cast_member_id": member_id,
        "kind": kind,
        "priority_rank": rank,
        "status": "STANDBY",
    })
    db.coverages[rec["id"]] = rec
    domain.recompute_track(track)
    return success(db.serialize("coverage", rec), 201)


@bp.route("/tracks/<track_id>/coverages", methods=["GET"])
def list_coverages_of_track(track_id):
    authenticate()
    if db.tracks.get(track_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Track not found")
    items = domain.coverages_of_track(track_id)
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("coverage", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/cast/<cast_id>/coverages", methods=["GET"])
def list_coverages_of_cast(cast_id):
    authenticate()
    if db.cast_members.get(cast_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    items = domain.coverages_of_member(cast_id)
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("coverage", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/coverages/<coverage_id>", methods=["PUT"])
def put_coverage(coverage_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    cov = db.coverages.get(coverage_id)
    if cov is None:
        raise err(ERR_NOT_FOUND, 404, "Coverage not found")
    body = get_body()
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", COVERAGE_STATUSES)
    # The endpoint releases a coverage; an ACTIVATED coverage cannot be
    # released while its injury is COVERED (ERR_COVERAGE_ACTIVATED).
    if target != "RELEASED" or cov["status"] != "STANDBY":
        raise err(ERR_COVERAGE_ACTIVATED, 409,
                  "Only a STANDBY coverage may be released")
    cov["status"] = "RELEASED"
    touch(cov)
    domain.recompute_track(db.tracks[cov["track_id"]])
    return success(db.serialize("coverage", cov), 200)
