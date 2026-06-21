"""Segment endpoints + membership evaluation (§3.10)."""

from flask import Blueprint

import db
import lookup
import models
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("segments", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}
GIVING_STATES = {"NONE", "ENTRY", "MID", "MAJOR"}
LIFECYCLE_STATES = {"PROSPECT", "ACTIVE", "LAPSED", "REACTIVATED", "ARCHIVED"}


def _matching_donors(seg):
    """Donors satisfying the segment predicate, evaluated at read time."""
    min_lifetime = seg["min_lifetime_cents"]
    giving_in = seg["giving_status_in"]
    lifecycle_in = seg["lifecycle_status_in"]
    out = []
    for d in db.donors.values():
        if d["lifetime_hard_credit_cents"] < min_lifetime:
            continue
        if giving_in and d["giving_status"] not in giving_in:
            continue
        if lifecycle_in and d["lifecycle_status"] not in lifecycle_in:
            continue
        out.append(d)
    return out


@bp.post("/segments")
def create_segment():
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        body = util.get_json_body()
        name = util.req_string(body, "name", min_len=1, max_len=80)
        min_lifetime_cents = util.opt_int(body, "min_lifetime_cents", default=0, min_val=0)
        giving_status_in = util.opt_enum_array(body, "giving_status_in",
                                               GIVING_STATES, default=[])
        lifecycle_status_in = util.opt_enum_array(body, "lifecycle_status_in",
                                                  LIFECYCLE_STATES, default=[])

        s = models.new_record({
            "name": name,
            "min_lifetime_cents": min_lifetime_cents,
            "giving_status_in": giving_status_in,
            "lifecycle_status_in": lifecycle_status_in,
            "member_count": 0,
        }, common=True)
        db.segments[s["id"]] = s
        return response.object_response(models.serialize(s), status=201)


@bp.get("/segments/<sid>")
def get_segment(sid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        s = lookup.segment(sid)
        # member_count recomputed on read (not stored as a snapshot).
        s["member_count"] = len(_matching_donors(s))
        return response.object_response(models.serialize(s))


@bp.get("/segments/<sid>/members")
def list_segment_members(sid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        s = lookup.segment(sid)
        limit, offset = util.parse_pagination()
        matching = _matching_donors(s)
        s["member_count"] = len(matching)
        rows = util.sort_by_created(matching)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
