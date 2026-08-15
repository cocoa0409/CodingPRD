from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_VALIDATION
from middleware import ALL_ROLES, auth_context, require_roles
from response import success
from serializers import society_view
from services import get_or_404, new_record
from validators import body_json, req_enum, req_str

bp = Blueprint("societies", __name__)

SOCIETY_TYPES = ["PRO", "MECHANICAL", "COLLECTION"]


@bp.route("/societies", methods=["POST"], strict_slashes=False)
def create_society():
    uid, role = auth_context()
    require_roles(role, ["PublisherAdmin"])
    body = body_json()
    name = req_str(body, "name")
    code = req_str(body, "code")
    society_type = req_enum(body, "society_type", SOCIETY_TYPES)
    territory_code = req_str(body, "territory_code")
    for existing in STORE["societies"].values():
        if existing["code"] == code:
            raise ApiError(ERR_VALIDATION, 422,
                           "society code must be unique")
    s = new_record()
    s.update({
        "name": name,
        "code": code,
        "society_type": society_type,
        "territory_code": territory_code,
    })
    STORE["societies"][s["id"]] = s
    return success(society_view(s), status=201)


@bp.route("/societies/<sid>", methods=["GET"], strict_slashes=False)
def get_society(sid):
    uid, role = auth_context()
    require_roles(role, ALL_ROLES)
    s = get_or_404("societies", sid, "society")
    return success(society_view(s))
