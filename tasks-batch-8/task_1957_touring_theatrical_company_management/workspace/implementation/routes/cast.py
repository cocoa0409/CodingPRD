"""CastMember endpoints: create/list under tour, get, status transitions."""

from flask import Blueprint, request

import db
from db import touch
from errors import (err, ERR_NOT_FOUND, ERR_CAST_INVALID_STATE,
                    ERR_COVERAGE_ACTIVATED)
from middleware import authenticate, require_roles
from response import success, success_list
from services import domain
from util import (get_body, reject_unknown, require_present, as_int, as_str,
                  as_enum, paginate)

bp = Blueprint("cast", __name__)

CONTRACT_TYPES = ("PRINCIPAL", "UNDERSTUDY", "SWING", "ENSEMBLE")
CAST_STATUSES = ("OFFERED", "CONTRACTED", "ON_LEAVE", "REPLACED", "RELEASED")


@bp.route("/tours/<tour_id>/cast", methods=["POST"])
def create_cast(tour_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    if db.tours.get(tour_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    body = get_body()
    reject_unknown(body, {"name", "contract_type", "weekly_salary_cents"})
    rec = db.new_record()
    rec.update({
        "tour_id": tour_id,
        "name": as_str(require_present(body, "name"), "name"),
        "contract_type": as_enum(require_present(body, "contract_type"),
                                 "contract_type", CONTRACT_TYPES),
        "weekly_salary_cents": as_int(require_present(body, "weekly_salary_cents"),
                                      "weekly_salary_cents", minv=1),
        "status": "OFFERED",
        "bump_shows_accrued": 0,
        "bump_pay_cents": 0,
    })
    db.cast_members[rec["id"]] = rec
    return success(db.serialize("cast_member", rec), 201)


@bp.route("/tours/<tour_id>/cast", methods=["GET"])
def list_cast(tour_id):
    authenticate()
    if db.tours.get(tour_id) is None:
        raise err(ERR_NOT_FOUND, 404, "Tour not found")
    items = [c for c in db.cast_members.values() if c["tour_id"] == tour_id]
    status = request.args.get("status")
    contract_type = request.args.get("contract_type")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if contract_type is not None:
        items = [c for c in items if c["contract_type"] == contract_type]
    items.sort(key=lambda c: c["_seq"])
    data, total, limit, offset = paginate(items, lambda r: db.serialize("cast_member", r))
    return success_list(data, total, limit, offset, 200)


@bp.route("/cast/<cast_id>", methods=["GET"])
def get_cast(cast_id):
    authenticate()
    member = db.cast_members.get(cast_id)
    if member is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    return success(db.serialize("cast_member", member), 200)


@bp.route("/cast/<cast_id>", methods=["PUT"])
def put_cast(cast_id):
    _, role = authenticate()
    require_roles(role, ("CompanyManager",))
    member = db.cast_members.get(cast_id)
    if member is None:
        raise err(ERR_NOT_FOUND, 404, "Cast member not found")
    body = get_body()
    reject_unknown(body, {"status"})
    target = as_enum(require_present(body, "status"), "status", CAST_STATUSES)
    cur = member["status"]

    if target == "CONTRACTED":
        if cur != "OFFERED":
            raise err(ERR_CAST_INVALID_STATE, 409,
                      "CONTRACTED is only reachable from OFFERED")
        member["status"] = "CONTRACTED"
        touch(member)
    elif target == "RELEASED":
        if cur not in ("OFFERED", "CONTRACTED", "ON_LEAVE"):
            raise err(ERR_CAST_INVALID_STATE, 409,
                      "RELEASED is only reachable from OFFERED/CONTRACTED/ON_LEAVE")
        # Blocked while any of the member's coverages is ACTIVATED.
        own = domain.coverages_of_member(cast_id)
        if any(c["status"] == "ACTIVATED" for c in own):
            raise err(ERR_COVERAGE_ACTIVATED, 409,
                      "Cannot release a member with an ACTIVATED coverage")
        member["status"] = "RELEASED"
        touch(member)
        # Cascade: the member's STANDBY/SUSPENDED coverages release with them.
        tracks_to_recompute = set()
        for c in own:
            if c["status"] in ("STANDBY", "SUSPENDED"):
                c["status"] = "RELEASED"
                touch(c)
                tracks_to_recompute.add(c["track_id"])
        for tid in tracks_to_recompute:
            domain.recompute_track(db.tracks[tid])
    else:
        raise err(ERR_CAST_INVALID_STATE, 409,
                  "No cast transition to %s" % target)
    return success(db.serialize("cast_member", member), 200)
