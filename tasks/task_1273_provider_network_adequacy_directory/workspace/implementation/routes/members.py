"""Member endpoints."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list

bp = Blueprint("members", __name__)

MEMBER_STATUSES = {"ENROLLED", "DISENROLLED"}


@bp.route("/network/members", methods=["POST"])
@require_roles("NetworkManager")
def create_member(user_id, role):
    body = helpers.get_body()
    region_id = helpers.req_str(body, "region_id")
    member_ref = helpers.req_str(body, "member_ref")
    full_name = helpers.req_str(body, "full_name")
    enrolled_on = helpers.req_str(body, "enrolled_on")
    helpers.parse_date(enrolled_on, "enrolled_on")
    if region_id not in db.regions:
        raise errors.err_region_not_found()
    for m in db.members.values():
        if m["member_ref"] == member_ref:
            raise errors.err_member_ref_duplicate()
    rec = {
        "region_id": region_id, "member_ref": member_ref, "full_name": full_name,
        "enrolled_on": enrolled_on, "status": "ENROLLED", "disenrolled_at": None,
    }
    helpers.stamp_new(rec)
    db.members[rec["id"]] = rec
    return success_object(helpers.ser_member(rec), 201)


@bp.route("/network/members", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_members(user_id, role):
    limit, offset = helpers.get_pagination()
    region_id = helpers.query_str("region_id")
    status = helpers.query_enum("status", MEMBER_STATUSES)
    items = list(db.members.values())
    if region_id is not None:
        items = [m for m in items if m["region_id"] == region_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = helpers.paginate(items, limit, offset)
    return success_list([helpers.ser_member(m) for m in page], limit, offset, total)


@bp.route("/network/members/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_member(user_id, role, mid):
    rec = db.members.get(mid)
    if rec is None:
        raise errors.err_member_not_found()
    return success_object(helpers.ser_member(rec))


@bp.route("/network/members/<mid>/disenroll", methods=["POST"])
@require_roles("NetworkManager")
def disenroll_member(user_id, role, mid):
    rec = db.members.get(mid)
    if rec is None:
        raise errors.err_member_not_found()
    if rec["status"] != "ENROLLED":
        raise errors.err_member_not_enrolled()
    rec["status"] = "DISENROLLED"
    rec["disenrolled_at"] = helpers.now_iso()
    helpers.touch(rec)
    return success_object(helpers.ser_member(rec))
