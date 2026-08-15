"""Developer endpoints (scaffold section 1.5)."""
from flask import Blueprint

from db import DB, new_id, next_seq, pub, sort_key, stamp_new
from errors import ApiError
from middleware import READ_ROLES, auth
from response import ok, ok_list
from util import body, pagination_args, req_enum, req_str

bp = Blueprint("developers", __name__)

DEVELOPER_TYPES = ("IPP", "UTILITY_SCALE", "COMMUNITY")


@bp.route("/interconnection/developers", methods=["POST"])
def create_developer():
    auth(["QueueAdministrator"])
    data = body()
    developer = {
        "id": new_id(),
        "_seq": next_seq(),
        "legal_name": req_str(data, "legal_name"),
        "contact_email": req_str(data, "contact_email"),
        "developer_type": req_enum(data, "developer_type", DEVELOPER_TYPES),
    }
    stamp_new(developer)
    DB["developers"][developer["id"]] = developer
    return ok(pub(developer), 201)


@bp.route("/interconnection/developers/<developer_id>", methods=["GET"])
def get_developer(developer_id):
    auth(READ_ROLES)
    developer = DB["developers"].get(developer_id)
    if developer is None:
        raise ApiError("ERR_DEVELOPER_NOT_FOUND", 404, "Developer id does not exist")
    return ok(pub(developer))


@bp.route("/interconnection/developers/<developer_id>/projects", methods=["GET"])
def list_developer_projects(developer_id):
    auth(READ_ROLES)
    developer = DB["developers"].get(developer_id)
    if developer is None:
        raise ApiError("ERR_DEVELOPER_NOT_FOUND", 404, "Developer id does not exist")
    limit, offset = pagination_args()
    items = sorted(
        (p for p in DB["projects"].values() if p["developer_id"] == developer_id),
        key=sort_key,
    )
    page = items[offset:offset + limit]
    return ok_list([pub(p) for p in page], len(items), limit, offset)
